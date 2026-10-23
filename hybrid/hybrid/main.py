"""Arranque del híbrido.

Prepara el registro, impide abrir dos grabadores a la vez (comparte bloqueo y
grabaciones con la app de escritorio) y alterna entre la pantalla de elección
y el panel del modo elegido hasta que el usuario cierra la ventana.
"""

from __future__ import annotations

import logging

from app.backends import get_backend
from app.core import logsetup
from app.core.settings import Settings
from app.main import _single_instance

from . import __version__
from .ui.chooser import WEB, ModeChooser

log = logging.getLogger("rpa.hybrid")


def run():
    logsetup.ensure_std_streams()
    logsetup.setup_logging()
    logsetup.install_crash_hooks()
    lock = _single_instance()
    if lock is None:
        return
    # Fija el DPI por monitor antes de crear ventanas (Windows; en macOS no hace nada).
    get_backend().prepare_process()
    log.info("híbrido %s", __version__)

    from .ui.apps import DesktopApp, WebApp

    while True:
        # Settings nuevo en cada vuelta: la ventana anterior pudo guardar cambios.
        chooser = ModeChooser(Settings())
        chooser.mainloop()
        if not chooser.choice:
            break
        mode, url = chooser.choice
        log.info("modo: %s", mode)
        app = WebApp(url) if mode == WEB else DesktopApp()
        app.mainloop()
        if not app.switch_requested:
            break


if __name__ == "__main__":
    run()
