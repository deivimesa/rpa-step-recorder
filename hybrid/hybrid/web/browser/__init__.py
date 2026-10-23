"""Navegador predeterminado: detección y arranque con depuración remota.

La grabación web controla el navegador por el protocolo de depuración (CDP),
que solo hablan los navegadores basados en Chromium. Si el predeterminado es
uno de ellos (Chrome, Edge, Brave, Vivaldi...) se usa ese; si no (Firefox,
Safari, Opera...), se recurre al primero compatible que esté instalado: Edge
o Chrome en Windows, Chrome, Edge o Brave en macOS.

Cómo se averigua el predeterminado y dónde está instalado cada navegador
depende del sistema y vive en ``windows.py`` y ``macos.py``; aquí queda lo
común: el catálogo de navegadores compatibles, la elección y el arranque.

El navegador se abre con un perfil propio de la grabación: desde Chrome 136 la
depuración remota no se permite sobre el perfil habitual, y así tampoco se
toca la sesión normal del usuario. El perfil se conserva entre grabaciones,
de modo que los inicios de sesión hechos allí se recuerdan la próxima vez.
"""

from __future__ import annotations

import functools
import json
import logging
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.core import paths

log = logging.getLogger("rpa.browser")

# Clave -> (nombre visible, ejecutable en Windows). Todos hablan CDP. El
# ejecutable de Windows también se usa en los selectores UiPath, que se
# ejecutan en Windows aunque la grabación se haga en un Mac.
CHROMIUM = {
    "chrome": ("Google Chrome", "chrome.exe"),
    "edge": ("Microsoft Edge", "msedge.exe"),
    "brave": ("Brave", "brave.exe"),
    "vivaldi": ("Vivaldi", "vivaldi.exe"),
    "chromium": ("Chromium", "chromium.exe"),
}


class BrowserError(Exception):
    """No se pudo encontrar o abrir el navegador (mensaje apto para el usuario)."""


@dataclass
class BrowserInfo:
    exe: str          # ruta completa del ejecutable
    process: str      # ejecutable en Windows (chrome.exe), para los selectores UiPath
    key: str          # nombre corto para la carpeta del perfil
    name: str         # nombre visible ("Google Chrome")
    is_default: bool  # es el navegador predeterminado del usuario
    note: str = ""    # por qué no se usa el predeterminado, si aplica


@dataclass
class DefaultBrowser:
    """Lo que cada sistema sabe del navegador predeterminado."""

    exe: str = ""     # ejecutable, si se pudo averiguar
    key: str = ""     # clave de CHROMIUM si es compatible; "" si no
    label: str = ""   # nombre para los avisos ("Firefox", "Safari")


# ── detección ───────────────────────────────────────────────


def _platform():
    """Módulo de detección del sistema actual."""
    if sys.platform == "win32":
        from . import windows

        return windows
    if sys.platform == "darwin":
        from . import macos

        return macos
    raise BrowserError("La grabación web del híbrido solo está disponible en Windows y macOS.")


def _info(key: str, exe: str, is_default: bool, note: str = "") -> BrowserInfo:
    name, process = CHROMIUM[key]
    return BrowserInfo(exe, process, key, name, is_default, note)


@functools.lru_cache(maxsize=1)
def pick() -> BrowserInfo:
    """El navegador con el que se graba: el predeterminado si es compatible.

    Se calcula una sola vez por ejecución: la pantalla de elección y el panel
    web lo consultan, y en Windows supone leer el registro.
    """
    system = _platform()
    default = system.default_browser()
    if default.key in CHROMIUM and default.exe and Path(default.exe).exists():
        return _info(default.key, default.exe, True)
    if default.label:
        note = f"Tu navegador predeterminado ({default.label}) no admite la grabación web; se usa {{name}}."
    else:
        note = "No se encontró el navegador predeterminado; se usa {name}."
    for key in system.FALLBACK_ORDER:
        exe = system.installed(key)
        if exe:
            name = CHROMIUM[key][0]
            log.info("navegador predeterminado no compatible (%s); se usa %s", default.label or "?", name)
            return _info(key, exe, False, note.format(name=name))
    names = " o ".join(CHROMIUM[key][0] for key in system.FALLBACK_ORDER[:2])
    raise BrowserError(f"Se necesita {names} para grabar procesos web, y no se encontró ninguno en este equipo.")


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
        # Salida descartada: la app empaquetada no tiene consola. En macOS, una
        # sesión propia evita que el navegador se cierre con la terminal que
        # lanzó la app.
        process = subprocess.Popen(
            args, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=sys.platform != "win32",
        )
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
