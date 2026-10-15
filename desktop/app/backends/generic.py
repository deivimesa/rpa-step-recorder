"""Backend genérico (Linux / fallo del nativo): solo coordenadas y capturas."""

from __future__ import annotations

import logging
import time

from ..keys import KeyEvent, MouseEvent
from .base import Backend, HookError

log = logging.getLogger("rpa.generic")


class GenericBackend(Backend):
    name = "generic"
    label = "Genérico (sin inspección de elementos)"

    def __init__(self):
        self._listeners = []

    def start_hooks(self, on_mouse, on_key) -> None:
        try:
            from pynput import keyboard, mouse
        except Exception as err:
            raise HookError(f"pynput no disponible: {err}") from err
        buttons = {mouse.Button.left: "left", mouse.Button.right: "right"}

        def click(x, y, button, pressed, injected=False):
            if pressed and button in buttons:
                on_mouse(MouseEvent(int(x), int(y), buttons[button], time.monotonic()))

        def press(key, injected=False):
            char = getattr(key, "char", None) or ""
            name = getattr(key, "name", "") or "char"
            if name == "space":
                char = " "
            on_key(KeyEvent(key=name if not char or name == "space" else "char", char=char, t=time.monotonic()))

        self._listeners = [mouse.Listener(on_click=click), keyboard.Listener(on_press=press)]
        for listener in self._listeners:
            listener.start()

    def stop_hooks(self) -> None:
        for listener in self._listeners:
            listener.stop()
        self._listeners = []

    def hooks_alive(self) -> bool:
        return bool(self._listeners) and all(l.is_alive() for l in self._listeners)

    def cursor_position(self) -> tuple[int, int]:
        try:
            from pynput.mouse import Controller

            x, y = Controller().position
            return int(x), int(y)
        except Exception:
            return (0, 0)
