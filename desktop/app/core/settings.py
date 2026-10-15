"""Preferencias del usuario persistidas en settings.json.

Se guardan con escritura atómica (archivo temporal + reemplazo) para que un
cierre inesperado nunca deje el archivo a medias. Si el archivo está dañado se
ignora y se usan los valores por defecto, sin impedir que la app arranque.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from pathlib import Path

from . import paths

log = logging.getLogger("rpa.settings")

DEFAULTS: dict = {
    # Apariencia: "system" sigue al sistema operativo; "light" / "dark" lo fuerzan.
    "theme": "system",
    # Grabación.
    "compact_while_recording": True,   # ventana mini siempre visible al grabar
    "hide_from_capture": True,         # nuestras ventanas no salen en las capturas
    "record_right_click": True,
    "merge_double_click": True,
    "record_shortcuts": True,          # Ctrl+C, Alt+F4, Cmd+S... como pasos
    "global_hotkeys": True,            # F8/F9/F10 funcionan aunque la app no tenga el foco
    "capture_max_width": 2560,         # 0 = resolución original de la pantalla
    # Portada.
    "default_author": "",
    "last_system": "",
    # Exportación.
    "export": {
        "format": "pdf",               # "pdf" | "docx" | "both"
        "include_technical": True,
        "include_zoom": True,
        "image_quality": "balanced",   # "high" | "balanced" | "compact"
        "open_after": True,
        "last_dir": "",
    },
    # Geometría de ventanas recordada entre sesiones.
    "geometry": {},
}


def _merge(defaults: dict, data: dict) -> dict:
    """Mezcla recursiva: lo guardado gana, pero se respetan las claves nuevas."""
    result = copy.deepcopy(defaults)
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    def __init__(self, path: Path | None = None):
        self._path = path or paths.settings_path()
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings.json no es un objeto")
            return _merge(DEFAULTS, raw)
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)
        except (OSError, ValueError) as err:
            log.warning("settings.json ilegible (%s); se usan valores por defecto", err)
            return copy.deepcopy(DEFAULTS)

    def get(self, key: str, default=None):
        """Lee una clave; admite rutas con puntos ("export.format")."""
        node = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return copy.deepcopy(node) if isinstance(node, (dict, list)) else node

    def set(self, key: str, value) -> None:
        """Cambia una clave y guarda de inmediato."""
        with self._lock:
            node = self._data
            parts = key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            self._save_locked()

    def update(self, values: dict) -> None:
        for key, value in values.items():
            self.set(key, value)

    def _save_locked(self) -> None:
        from .storage import atomic_write_text

        try:
            atomic_write_text(self._path, json.dumps(self._data, ensure_ascii=False, indent=2))
        except OSError as err:
            log.warning("no se pudo guardar settings.json: %s", err)
