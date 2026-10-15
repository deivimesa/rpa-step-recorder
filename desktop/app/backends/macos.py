"""Backend de macOS: Accesibilidad (AX) + event tap de Quartz + permisos TCC."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from typing import Any

import Quartz
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

from . import mac_ax
from .base import Backend, HookError, Permission

log = logging.getLogger("rpa.macos")

_SETTINGS_URLS = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "input": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
}

try:
    _carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
    _carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
except OSError:  # pragma: no cover
    _carbon = None


def _call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


class MacBackend(Backend):
    name = "macos"
    label = "macOS (Accesibilidad)"
    inspection = True

    def __init__(self):
        self._hooks = None

    # ── inspección ──
    def inspect_point(self, x: int, y: int) -> tuple[dict | None, Any]:
        element = mac_ax.element_at(x, y)
        if element is None:
            return None, None
        try:
            element, promoted = mac_ax.promote_actionable(element, x, y)
            return mac_ax.build_element(element, promoted), element
        except Exception:
            log.exception("fallo al inspeccionar (%s,%s)", x, y)
            return None, None

    def inspect_focused(self) -> tuple[dict | None, Any]:
        element = mac_ax.focused_element()
        if element is None:
            return None, None
        try:
            return mac_ax.build_element(element, None), element
        except Exception:
            log.exception("fallo al inspeccionar el foco")
            return None, None

    def focused_handle(self) -> Any:
        return mac_ax.focused_element()

    def same_element(self, a, b) -> bool:
        return mac_ax.same(a, b)

    def read_value(self, handle) -> str | None:
        return _call(lambda: mac_ax.read_value(handle))

    def is_editable(self, element) -> bool:
        return mac_ax.is_editable(element)

    def is_own_point(self, x: int, y: int) -> bool | None:
        element = mac_ax.element_at(x, y)
        if element is None:
            return None
        return mac_ax.pid_of(element) == os.getpid()

    def build_selectors(self, element) -> dict:
        from ..selectors import build_mac_selectors

        return build_mac_selectors(element or {})

    # ── entrada ──
    def start_hooks(self, on_mouse, on_key) -> None:
        from .mac_hooks import MacHooks

        self.stop_hooks()
        self._hooks = MacHooks(on_mouse, on_key)
        try:
            self._hooks.start()
        except HookError:
            self._hooks = None
            raise

    def stop_hooks(self) -> None:
        if self._hooks is not None:
            self._hooks.stop()
            self._hooks = None

    def hooks_alive(self) -> bool:
        return bool(self._hooks and self._hooks.alive())

    def cursor_position(self) -> tuple[int, int]:
        point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return int(point.x), int(point.y)

    def double_click_time(self) -> float:
        from AppKit import NSEvent

        return float(_call(NSEvent.doubleClickInterval, 0.5))

    # ── sistema ──
    def reveal_path(self, path: str) -> None:
        subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])

    def permissions(self) -> list[Permission]:
        return [
            Permission("accessibility", "Accesibilidad",
                       "Para identificar el botón o campo en el que haces clic.",
                       bool(_call(AXIsProcessTrusted, False))),
            Permission("input", "Monitorización de entrada",
                       "Para detectar clics y lo que escribes en otras apps.",
                       _call(Quartz.CGPreflightListenEventAccess), restart_needed=True),
            Permission("screen", "Grabación de pantalla",
                       "Para capturar la pantalla en cada paso (sin él solo se ve el escritorio).",
                       _call(Quartz.CGPreflightScreenCaptureAccess), restart_needed=True),
        ]

    def request_permission(self, key: str) -> None:
        if key == "accessibility":
            _call(lambda: AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
        elif key == "screen":
            _call(Quartz.CGRequestScreenCaptureAccess)
        elif key == "input":
            _call(Quartz.CGRequestListenEventAccess)

    def open_permission_settings(self, key: str) -> None:
        url = _SETTINGS_URLS.get(key)
        if url:
            subprocess.Popen(["open", url])

    def environment_warnings(self) -> list[str]:
        warnings = [f"Falta el permiso de {p.title} (Ajustes del Sistema > Privacidad y seguridad)."
                    for p in self.permissions() if p.granted is False]
        if _carbon is not None and _call(_carbon.IsSecureEventInputEnabled, False):
            warnings.append("La entrada segura está activa (campo de contraseña): no se registran pulsaciones.")
        return warnings
