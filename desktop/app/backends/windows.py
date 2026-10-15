"""Backend de Windows: UI Automation + pynput + integración Win32."""

from __future__ import annotations

import logging
import os
from typing import Any

from . import win_system
from .base import Backend, HookError, Permission

log = logging.getLogger("rpa.windows")

# El DPI por monitor debe fijarse antes de que nada cree ventanas o importe
# uiautomation (que, al importarse, fija su propio modo).
_DPI_MODE = win_system.set_dpi_awareness()

from . import win_uia  # noqa: E402  (tras fijar el DPI)


class WindowsBackend(Backend):
    name = "windows"
    label = "Windows (UI Automation)"
    inspection = True

    def __init__(self):
        self._hooks = None
        self._elevated_self = win_system.is_current_process_elevated()
        self._last_fg_pid = None
        self._last_fg_elevated = None
        log.info("DPI: %s · build %s · admin: %s", _DPI_MODE, win_system.windows_build(), self._elevated_self)

    # ── hilos ──
    def thread_init(self) -> None:
        win_uia.thread_init()

    def thread_exit(self) -> None:
        win_uia.thread_exit()

    # ── inspección ──
    def inspect_point(self, x: int, y: int) -> tuple[dict | None, Any]:
        control = win_uia.control_at(x, y)
        if control is None:
            return None, None
        try:
            control, promoted_from = win_uia.promote_actionable(control, x, y)
        except Exception:
            promoted_from = None
        try:
            return win_uia.build_element(control, promoted_from), control
        except Exception:
            log.exception("fallo al construir el elemento en (%s,%s)", x, y)
            return None, None

    def inspect_focused(self) -> tuple[dict | None, Any]:
        control = win_uia.focused_control()
        if control is None:
            return None, None
        try:
            return win_uia.build_element(control, None), control
        except Exception:
            log.exception("fallo al construir el elemento con el foco")
            return None, None

    def focused_handle(self) -> Any:
        return win_uia.focused_control()

    def same_element(self, a: Any, b: Any) -> bool:
        return win_uia.same(a, b)

    def read_value(self, handle: Any) -> str | None:
        try:
            return win_uia.read_value(handle)
        except Exception:
            return None

    def is_editable(self, element: dict | None) -> bool:
        return win_uia.is_editable(element)

    def is_own_point(self, x: int, y: int) -> bool | None:
        pid = win_system.pid_at_point(x, y)
        if pid is None:
            return None
        return pid == os.getpid()

    def build_selectors(self, element: dict | None) -> dict:
        from ..selectors import build_windows_selectors

        return build_windows_selectors(element or {})

    # ── entrada ──
    def start_hooks(self, on_mouse, on_key) -> None:
        from .win_hooks import WinHooks

        self.stop_hooks()
        try:
            self._hooks = WinHooks(on_mouse, on_key)
            self._hooks.start()
        except Exception as err:
            self._hooks = None
            raise HookError(f"No se pudieron activar los hooks de ratón y teclado: {err}") from err

    def stop_hooks(self) -> None:
        if self._hooks is not None:
            self._hooks.stop()
            self._hooks = None

    def hooks_alive(self) -> bool:
        return bool(self._hooks and self._hooks.alive())

    def cursor_position(self) -> tuple[int, int]:
        return win_system.cursor_pos()

    def double_click_time(self) -> float:
        return win_system.double_click_time()

    def double_click_slop(self) -> int:
        return win_system.double_click_slop()

    # ── sistema ──
    def set_capture_excluded(self, window, excluded: bool) -> bool:
        return win_system.set_capture_excluded(window, excluded)

    def reveal_path(self, path: str) -> None:
        import subprocess

        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            self.open_path(path if os.path.isdir(path) else os.path.dirname(path))

    def permissions(self) -> list[Permission]:
        return [
            Permission(
                key="admin",
                title="Apps que se ejecutan como administrador",
                description=(
                    "Windows impide grabar ventanas elevadas desde una app normal. "
                    "Si vas a documentar una app abierta como administrador, abre "
                    "también RPA Step Recorder como administrador."
                ),
                granted=self._elevated_self,
            )
        ]

    def environment_warnings(self) -> list[str]:
        """Avisa si la ventana activa es elevada y nosotros no (no recibiríamos sus clics)."""
        if self._elevated_self:
            return []
        pid = win_system.foreground_pid()
        if not pid or pid == os.getpid():
            return []
        if pid != self._last_fg_pid:
            self._last_fg_pid = pid
            self._last_fg_elevated = win_system.is_process_elevated(pid)
        if self._last_fg_elevated:
            name = win_uia.process_name(pid) or "La ventana activa"
            return [
                f"{name} se ejecuta como administrador: Windows no deja grabar sus clics. "
                "Abre RPA Step Recorder como administrador para documentarla."
            ]
        return []
