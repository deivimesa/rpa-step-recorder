"""Arranque de la app de escritorio.

Prepara el registro de eventos, impide abrir dos grabadores a la vez y abre la
ventana principal (``ui/main_window.py``).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from . import APP_NAME
from .backends import get_backend
from .core import logsetup
from .ui.main_window import App


def run():
    logsetup.ensure_std_streams()
    logsetup.setup_logging()
    logsetup.install_crash_hooks()
    lock = _single_instance()
    if lock is None:
        return
    get_backend().prepare_process()
    app = App()
    app.mainloop()


def _single_instance():
    """Impide dos grabadores a la vez (duplicarían cada paso). El SO libera el
    bloqueo solo aunque la app se cierre de golpe."""
    from .core import paths

    handle = open(paths.lock_path(), "a+")
    try:
        if paths.IS_WINDOWS:
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        if paths.IS_WINDOWS:
            from .backends.windows import system as win_system

            if win_system.bring_to_front(APP_NAME):
                return None
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_NAME, "RPA Step Recorder ya está abierto.")
        root.destroy()
        return None


if __name__ == "__main__":
    run()
