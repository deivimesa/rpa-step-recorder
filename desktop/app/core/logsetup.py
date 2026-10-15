"""Registro de eventos y captura de errores no controlados.

Antes, los fallos dentro de los callbacks de Tk o de los hilos se perdían en
una consola que no existe en el ejecutable (modo ventana). Ahora todo queda en
un registro rotativo y, si algo revienta, el usuario ve un aviso con la ruta
del registro en vez de un cierre silencioso.

Nunca se registran textos escritos por el usuario: solo tipos de paso,
controles y tiempos.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .. import __version__
from . import paths

log = logging.getLogger("rpa")

_fatal_callback = None


def ensure_std_streams() -> None:
    """En el .exe sin consola, sys.stdout/stderr son None.

    Cualquier print() o aviso de una librería lanzaría AttributeError y
    tumbaría la app; se redirigen a os.devnull.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass


def log_file() -> Path:
    return paths.logs_dir() / "recorder.log"


def setup_logging(level: int = logging.INFO) -> Path:
    """Configura un registro rotativo (2 MB x 3) y devuelve su ruta."""
    path = log_file()
    root = logging.getLogger()
    root.setLevel(level)
    # Evita duplicar handlers si se llama dos veces (pruebas, reinicios).
    for handler in list(root.handlers):
        if getattr(handler, "_rpa", False):
            root.removeHandler(handler)
    try:
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    handler._rpa = True  # type: ignore[attr-defined]
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
    if sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)():
        console = logging.StreamHandler(sys.stderr)
        console._rpa = True  # type: ignore[attr-defined]
        console.setLevel(logging.WARNING)
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(console)
    log.info("=== RPA Step Recorder %s ===", __version__)
    log.info("%s", system_summary())
    return path


def system_summary() -> str:
    """Línea compacta con lo esencial del entorno (para registros y soporte)."""
    try:
        import tkinter

        tk_version = str(tkinter.TkVersion)
    except Exception:
        tk_version = "?"
    frozen = "empaquetada" if getattr(sys, "frozen", False) else "código fuente"
    return (
        f"SO={platform.system()} {platform.release()} ({platform.machine()}) · "
        f"Python={platform.python_version()} · Tk={tk_version} · {frozen}"
    )


def system_report(extra: dict | None = None) -> str:
    """Informe de diagnóstico para copiar al pedir ayuda."""
    lines = [
        f"RPA Step Recorder {__version__}",
        system_summary(),
        f"Mac: {platform.mac_ver()[0]}" if paths.IS_MAC else f"Plataforma: {platform.platform()}",
        f"Datos: {paths.data_dir()}",
        f"Registro: {log_file()}",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def set_fatal_callback(callback) -> None:
    """La UI registra aquí cómo mostrar un error inesperado al usuario."""
    global _fatal_callback
    _fatal_callback = callback


def _report(kind: str, exc_type, exc, tb) -> None:
    log.critical("Error no controlado (%s)", kind, exc_info=(exc_type, exc, tb))
    callback = _fatal_callback
    if callback is not None:
        try:
            callback(f"{exc_type.__name__}: {exc}")
        except Exception:
            log.exception("fallo al notificar el error a la interfaz")


def install_crash_hooks() -> None:
    """Redirige las excepciones no capturadas (hilo principal e hilos) al registro."""

    def _sys_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _report("principal", exc_type, exc, tb)

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        _report(f"hilo {args.thread.name if args.thread else '?'}", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook
