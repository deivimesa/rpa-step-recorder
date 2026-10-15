"""Selección del backend de plataforma (Windows, macOS o genérico)."""

from __future__ import annotations

import logging
import sys

from .base import Backend, HookError, Permission  # noqa: F401

log = logging.getLogger("rpa.backends")

_backend: Backend | None = None


def get_backend() -> Backend:
    """Devuelve (y cachea) el backend adecuado; cae al genérico si falla."""
    global _backend
    if _backend is not None:
        return _backend
    try:
        if sys.platform == "win32":
            from .windows import WindowsBackend

            _backend = WindowsBackend()
        elif sys.platform == "darwin":
            from .macos import MacBackend

            _backend = MacBackend()
    except Exception:
        log.exception("no se pudo cargar el backend nativo; se usa el genérico")
        _backend = None
    if _backend is None:
        from .generic import GenericBackend

        _backend = GenericBackend()
    log.info("backend: %s", _backend.label)
    return _backend
