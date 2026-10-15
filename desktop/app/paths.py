"""Rutas de datos según el sistema operativo.

Un único sitio decide dónde viven las grabaciones, los ajustes y los
registros, para que el resto del código no tenga que preguntar por la
plataforma:

  - Windows: %LOCALAPPDATA%\\RPAStepRecorder\\ (misma ruta que las versiones
    anteriores, así las grabaciones existentes siguen apareciendo).
  - macOS:   ~/Library/Application Support/RPAStepRecorder/ y los registros en
    ~/Library/Logs/RPAStepRecorder/ (donde los busca la app Consola).
  - Linux:   $XDG_DATA_HOME/rpa-step-recorder/ (soporte experimental).

La variable de entorno RPA_STEP_RECORDER_HOME fuerza otra carpeta base; la
usan las pruebas automáticas para no tocar los datos reales.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "RPAStepRecorder"

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

_cache: dict[str, Path] = {}


def reset_cache() -> None:
    """Olvida las rutas calculadas (las pruebas cambian la carpeta base)."""
    _cache.clear()


def _ensure(key: str, path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _cache[key] = path
    return path


def data_dir() -> Path:
    """Carpeta base de datos de la app (se crea si no existe)."""
    if "data" in _cache:
        return _cache["data"]
    override = os.environ.get("RPA_STEP_RECORDER_HOME")
    if override:
        base = Path(override)
    elif IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(local) / APP_DIR_NAME
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(xdg) / "rpa-step-recorder"
    return _ensure("data", base)


def sessions_dir() -> Path:
    """Carpeta con una subcarpeta por grabación."""
    if "sessions" in _cache:
        return _cache["sessions"]
    return _ensure("sessions", data_dir() / "sessions")


def logs_dir() -> Path:
    """Carpeta de registros (en macOS, la estándar del sistema)."""
    if "logs" in _cache:
        return _cache["logs"]
    if IS_MAC and not os.environ.get("RPA_STEP_RECORDER_HOME"):
        return _ensure("logs", Path.home() / "Library" / "Logs" / APP_DIR_NAME)
    return _ensure("logs", data_dir() / "logs")


def settings_path() -> Path:
    return data_dir() / "settings.json"


def lock_path() -> Path:
    """Archivo de bloqueo que impide abrir dos grabadores a la vez."""
    return data_dir() / "instance.lock"


def resource_path(*parts: str) -> Path:
    """Ruta a un recurso empaquetado (fuentes, iconos...).

    Con PyInstaller los datos viven bajo ``sys._MEIPASS``; en desarrollo,
    junto al paquete ``app``. Se prueban ambas para que funcione igual en el
    código fuente, en el .exe de Windows y en la .app de macOS.
    """
    here = Path(__file__).resolve().parent
    candidates = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "app" / Path(*parts))
    candidates.append(here / Path(*parts))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]
