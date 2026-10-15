"""Hooks globales de ratón y teclado en Windows (pynput) -> eventos normalizados.

Los callbacks de pynput corren dentro del hook de bajo nivel del sistema: si
tardan, Windows los descarta y acaba quitando el hook sin avisar. Por eso aquí
solo se traduce el evento y se entrega (la cola del grabador hace el resto).

Correcciones respecto a la versión anterior:
  - La barra espaciadora (Key.space) se trataba como tecla especial y se
    perdían los espacios ("Hola mundo" -> "Holamundo").
  - Los modificadores se leen del estado real del teclado (GetAsyncKeyState)
    y no de pulsaciones acumuladas, que se descuadran si se pierde una
    liberación (p. ej. tras Win+L).
  - Tab, atajos (Ctrl+S, Alt+F4...) y teclas de función ahora llegan al
    grabador, que decide si son pasos.
"""

from __future__ import annotations

import ctypes
import logging
import time

from ...core.keys import KeyEvent, MouseEvent

log = logging.getLogger("rpa.hooks")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short

_VK_SHIFT, _VK_CONTROL, _VK_MENU, _VK_LWIN, _VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C


def current_mods() -> frozenset:
    def down(vk: int) -> bool:
        return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

    mods = set()
    if down(_VK_CONTROL):
        mods.add("ctrl")
    if down(_VK_MENU):
        mods.add("alt")
    if down(_VK_SHIFT):
        mods.add("shift")
    if down(_VK_LWIN) or down(_VK_RWIN):
        mods.add("win")
    return frozenset(mods)


def _base_from_vk(vk, char: str) -> str:
    """Tecla base de un atajo a partir del código virtual (independiente de Mayús)."""
    if vk is None:
        return (char or "").upper() if char and char.isprintable() else ""
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"Num{vk - 0x60}"
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if char and char.isprintable():
        return char.upper()
    return ""


class WinHooks:
    def __init__(self, on_mouse, on_key):
        self._on_mouse = on_mouse
        self._on_key = on_key
        self._mouse = None
        self._keyboard = None
        self._special: dict = {}
        self._modifiers: set = set()

    def start(self) -> None:
        from pynput import keyboard, mouse

        Key = keyboard.Key
        names = {
            "enter": "enter", "tab": "tab", "esc": "esc", "backspace": "backspace",
            "delete": "delete", "space": "space", "up": "up", "down": "down",
            "left": "left", "right": "right", "home": "home", "end": "end",
            "page_up": "pageup", "page_down": "pagedown", "insert": "insert",
        }
        for attr, name in names.items():
            key = getattr(Key, attr, None)
            if key is not None:
                self._special[key] = name
        for i in range(1, 25):
            key = getattr(Key, f"f{i}", None)
            if key is not None:
                self._special[key] = f"f{i}"
        for attr in ("ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr", "shift",
                     "shift_l", "shift_r", "cmd", "cmd_l", "cmd_r", "caps_lock", "num_lock",
                     "scroll_lock", "menu"):
            key = getattr(Key, attr, None)
            if key is not None:
                self._modifiers.add(key)
        self._buttons = {mouse.Button.left: "left", mouse.Button.right: "right", mouse.Button.middle: "middle"}

        self._mouse = mouse.Listener(on_click=self._handle_click)
        self._keyboard = keyboard.Listener(on_press=self._handle_press)
        self._mouse.start()
        self._keyboard.start()
        # pynput arranca los hooks en sus propios hilos; damos un margen para
        # detectar un fallo inmediato (p. ej. política de seguridad).
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if self._mouse.is_alive() and self._keyboard.is_alive():
                break
            time.sleep(0.02)
        log.info("hooks de Windows activos")

    def stop(self) -> None:
        for listener in (self._mouse, self._keyboard):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    log.exception("fallo al detener un listener")
        for listener in (self._mouse, self._keyboard):
            if listener is not None:
                try:
                    listener.join(2)
                except Exception:
                    pass
        self._mouse = self._keyboard = None

    def alive(self) -> bool:
        return bool(
            self._mouse is not None and self._keyboard is not None
            and self._mouse.is_alive() and self._keyboard.is_alive()
        )

    # ── callbacks (hilo del hook: rápidos y sin excepciones) ──

    def _handle_click(self, x, y, button, pressed, injected=False):
        try:
            if not pressed:
                return
            name = self._buttons.get(button)
            if name is None:
                return
            self._on_mouse(MouseEvent(x=int(x), y=int(y), button=name, t=time.monotonic(), mods=current_mods()))
        except Exception:
            log.exception("fallo en el callback de ratón")

    def _handle_press(self, key, injected=False):
        try:
            if key is None or key in self._modifiers:
                return
            mods = current_mods()
            name = self._special.get(key)
            if name is not None:
                event = KeyEvent(key=name, char=" " if name == "space" else "", mods=mods,
                                 base=name.upper() if name.startswith("f") else "", t=time.monotonic())
            else:
                char = getattr(key, "char", None) or ""
                vk = getattr(key, "vk", None)
                dead = bool(getattr(key, "is_dead", False))
                if char and not char.isprintable():
                    char = ""  # Ctrl+C llega como '\x03'
                event = KeyEvent(key="char", char=char, mods=mods, base=_base_from_vk(vk, char),
                                 dead=dead, t=time.monotonic())
            self._on_key(event)
        except Exception:
            log.exception("fallo en el callback de teclado")
