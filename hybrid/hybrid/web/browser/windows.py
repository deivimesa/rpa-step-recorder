"""Navegador predeterminado en Windows: registro y rutas de instalación."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import DefaultBrowser

# Si el predeterminado no es compatible: Edge viene con Windows.
FALLBACK_ORDER = ("edge", "chrome")

# Ejecutable -> clave del catálogo (CHROMIUM).
_PROCESS_KEY = {
    "chrome.exe": "chrome",
    "msedge.exe": "edge",
    "brave.exe": "brave",
    "vivaldi.exe": "vivaldi",
    "chromium.exe": "chromium",
}

_INSTALL_DIRS = {
    "edge": (r"%ProgramFiles(x86)%\Microsoft\Edge\Application", r"%ProgramFiles%\Microsoft\Edge\Application"),
    "chrome": (r"%ProgramFiles%\Google\Chrome\Application", r"%ProgramFiles(x86)%\Google\Chrome\Application",
               r"%LOCALAPPDATA%\Google\Chrome\Application"),
}
_EXE = {"edge": "msedge.exe", "chrome": "chrome.exe"}


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


def exe_from_command(command: str) -> str:
    """Ejecutable de un comando de apertura del registro ("C:\\...\\chrome.exe" --single-argument %1)."""
    command = os.path.expandvars(command.strip())
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    match = re.match(r"(.+?\.exe)\b", command, re.IGNORECASE)
    return match.group(1) if match else ""


def friendly_name(exe: str, prog_id: str) -> str:
    stem = Path(exe).stem.lower() if exe else ""
    if "firefox" in stem or prog_id.lower().startswith("firefox"):
        return "Firefox"
    if "opera" in stem or prog_id.lower().startswith("opera") or stem == "launcher":
        return "Opera"
    return Path(exe).stem.capitalize() if exe else prog_id


def default_browser() -> DefaultBrowser:
    prog_id, command = _default_command()
    exe = exe_from_command(command) if command else ""
    key = _PROCESS_KEY.get(Path(exe).name.lower(), "") if exe else ""
    return DefaultBrowser(exe, key, friendly_name(exe, prog_id))


def installed(key: str) -> str:
    """Ruta del ejecutable de ``key`` en sus carpetas de instalación habituales ("" si no está)."""
    for folder in _INSTALL_DIRS.get(key, ()):
        exe = Path(os.path.expandvars(folder)) / _EXE[key]
        if exe.exists():
            return str(exe)
    return ""
