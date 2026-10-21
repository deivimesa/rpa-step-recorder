"""Navegador predeterminado: detección y arranque con depuración remota.

La grabación web controla el navegador por el protocolo de depuración (CDP),
que solo hablan los navegadores basados en Chromium. Si el predeterminado es
uno de ellos (Chrome, Edge, Brave, Vivaldi...) se usa ese; si no (Firefox,
Opera...), se recurre a Edge, que viene con Windows, o a Chrome.

El navegador se abre con un perfil propio de la grabación: desde Chrome 136 la
depuración remota no se permite sobre el perfil habitual, y así tampoco se
toca la sesión normal del usuario. El perfil se conserva entre grabaciones,
de modo que los inicios de sesión hechos allí se recuerdan la próxima vez.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.core import paths

log = logging.getLogger("rpa.browser")

# Ejecutable -> (clave del perfil, nombre visible). Todos hablan CDP.
CHROMIUM = {
    "chrome.exe": ("chrome", "Google Chrome"),
    "msedge.exe": ("edge", "Microsoft Edge"),
    "brave.exe": ("brave", "Brave"),
    "vivaldi.exe": ("vivaldi", "Vivaldi"),
    "chromium.exe": ("chromium", "Chromium"),
}

_FALLBACKS = (
    ("msedge.exe", (r"%ProgramFiles(x86)%\Microsoft\Edge\Application", r"%ProgramFiles%\Microsoft\Edge\Application")),
    ("chrome.exe", (r"%ProgramFiles%\Google\Chrome\Application", r"%ProgramFiles(x86)%\Google\Chrome\Application",
                    r"%LOCALAPPDATA%\Google\Chrome\Application")),
)


class BrowserError(Exception):
    """No se pudo encontrar o abrir el navegador (mensaje apto para el usuario)."""


@dataclass
class BrowserInfo:
    exe: str          # ruta completa del ejecutable
    process: str      # nombre del ejecutable (chrome.exe), para los selectores UiPath
    key: str          # nombre corto para la carpeta del perfil
    name: str         # nombre visible ("Google Chrome")
    is_default: bool  # es el navegador predeterminado del usuario
    note: str = ""    # por qué no se usa el predeterminado, si aplica


# ── detección ───────────────────────────────────────────────


def _default_command() -> tuple[str, str]:
    """(ProgId, comando de apertura) del navegador predeterminado para https."""
    import winreg

    base = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https"
    prog_id = ""
    # Windows 11 reciente guarda la elección en UserChoiceLatest; antes, en UserChoice.
    for sub in (r"\UserChoiceLatest\ProgId", r"\UserChoiceLatest", r"\UserChoice"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + sub) as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0]
                if prog_id:
                    break
        except OSError:
            continue
    if not prog_id:
        return "", ""
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command") as key:
            return prog_id, winreg.QueryValueEx(key, "")[0]
    except OSError:
        return prog_id, ""


def _exe_from_command(command: str) -> str:
    command = os.path.expandvars(command.strip())
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    match = re.match(r"(.+?\.exe)\b", command, re.IGNORECASE)
    return match.group(1) if match else ""


def _friendly_name(exe: str, prog_id: str) -> str:
    stem = Path(exe).stem.lower() if exe else ""
    if "firefox" in stem or prog_id.lower().startswith("firefox"):
        return "Firefox"
    if "opera" in stem or prog_id.lower().startswith("opera") or stem == "launcher":
        return "Opera"
    return Path(exe).stem.capitalize() if exe else (prog_id or "desconocido")


def _fallback(note: str) -> BrowserInfo | None:
    for process, folders in _FALLBACKS:
        for folder in folders:
            exe = Path(os.path.expandvars(folder)) / process
            if exe.exists():
                key, name = CHROMIUM[process]
                return BrowserInfo(str(exe), process, key, name, False, note)
    return None


def pick() -> BrowserInfo:
    """El navegador con el que se graba: el predeterminado si es compatible."""
    if sys.platform != "win32":
        raise BrowserError("La grabación web del híbrido solo está disponible en Windows.")
    prog_id, command = _default_command()
    exe = _exe_from_command(command) if command else ""
    process = Path(exe).name.lower() if exe else ""
    if process in CHROMIUM and Path(exe).exists():
        key, name = CHROMIUM[process]
        return BrowserInfo(exe, process, key, name, True)
    current = _friendly_name(exe, prog_id)
    note = (f"Tu navegador predeterminado ({current}) no admite la grabación web; "
            "se usa {name}.") if exe or prog_id else "No se encontró el navegador predeterminado; se usa {name}."
    info = _fallback(note)
    if info is None:
        raise BrowserError(
            "Se necesita Google Chrome o Microsoft Edge para grabar procesos web, "
            "y no se encontró ninguno en este equipo."
        )
    info.note = info.note.format(name=info.name)
    log.info("navegador predeterminado no compatible (%s); se usa %s", prog_id or exe, info.name)
    return info


# ── arranque ────────────────────────────────────────────────


def profile_dir(info: BrowserInfo) -> Path:
    path = paths.data_dir() / "web-profiles" / info.key
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_port_file(profile: Path) -> tuple[int, str] | None:
    try:
        lines = (profile / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
        if len(lines) >= 2 and lines[0].strip().isdigit():
            return int(lines[0]), lines[1].strip()
    except OSError:
        pass
    return None


def running_endpoint(info: BrowserInfo) -> str | None:
    """WebSocket del navegador de grabación si ya está abierto (de antes)."""
    found = _read_port_file(profile_dir(info))
    if not found:
        return None
    port, path = found
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("webSocketDebuggerUrl") or f"ws://127.0.0.1:{port}{path}"
    except (OSError, ValueError):
        return None


def launch(info: BrowserInfo, url: str, timeout: float = 25.0) -> str:
    """Abre el navegador en ``url`` y devuelve el WebSocket de su depuración."""
    profile = profile_dir(info)
    port_file = profile / "DevToolsActivePort"
    try:
        port_file.unlink(missing_ok=True)
    except OSError:
        pass
    args = [
        info.exe,
        "--remote-debugging-port=0",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        url or "about:blank",
    ]
    log.info("abriendo %s con perfil de grabación", info.name)
    try:
        process = subprocess.Popen(args, close_fds=True)
    except OSError as err:
        raise BrowserError(f"No se pudo abrir {info.name}: {err}") from err
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _read_port_file(profile)
        if found:
            return f"ws://127.0.0.1:{found[0]}{found[1]}"
        code = process.poll()
        if code not in (None, 0):
            raise BrowserError(f"{info.name} se cerró al abrirse (código {code}).")
        time.sleep(0.1)
    raise BrowserError(
        f"{info.name} no activó la conexión de grabación a tiempo. "
        "Puede que una directiva de tu empresa bloquee la depuración remota del navegador."
    )
