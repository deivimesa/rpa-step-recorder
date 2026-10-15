"""Escucha global de ratón y teclado en macOS con un event tap de Quartz.

Se usa un tap propio (y no pynput) por robustez:
  - Es de solo escucha (kCGEventTapOptionListenOnly): nunca retiene ni
    modifica los eventos del usuario.
  - Si macOS desactiva el tap por lentitud o por la entrada del usuario, se
    reactiva al momento (pynput no lo hacía y la grabación «se quedaba sorda»).
  - Los caracteres se leen del propio evento (CGEventKeyboardGetUnicodeString),
    sin llamar a Text Services Manager desde un hilo secundario: esas llamadas
    hacen abortar el proceso en las versiones recientes de macOS.
  - Si falta el permiso de Monitorización de entrada, se intenta un tap solo
    de ratón para que, al menos, los clics se sigan grabando.

Con la entrada segura activa (un campo de contraseña con el foco, o una app
con «Entrada de teclado segura»), macOS no entrega las pulsaciones a nadie:
la contraseña ni siquiera llega a este proceso.
"""

from __future__ import annotations

import logging
import threading
import time

import Quartz

from ..keys import KeyEvent, MouseEvent
from .base import HookError

log = logging.getLogger("rpa.tap")

_KEYCODES = {
    36: "enter", 76: "enter", 48: "tab", 53: "esc", 51: "backspace", 117: "delete",
    49: "space", 126: "up", 125: "down", 123: "left", 124: "right", 115: "home",
    119: "end", 116: "pageup", 121: "pagedown", 114: "insert",
    122: "f1", 120: "f2", 99: "f3", 118: "f4", 96: "f5", 97: "f6", 98: "f7", 100: "f8",
    101: "f9", 109: "f10", 103: "f11", 111: "f12", 105: "f13", 107: "f14", 113: "f15",
    106: "f16", 64: "f17", 79: "f18", 80: "f19", 90: "f20",
}
# Posiciones ANSI -> tecla base (para nombrar atajos aunque Opción altere el carácter).
_ANSI = {
    0: "A", 11: "B", 8: "C", 2: "D", 14: "E", 3: "F", 5: "G", 4: "H", 34: "I", 38: "J",
    40: "K", 37: "L", 46: "M", 45: "N", 31: "O", 35: "P", 12: "Q", 15: "R", 1: "S",
    17: "T", 32: "U", 9: "V", 13: "W", 7: "X", 16: "Y", 6: "Z",
    29: "0", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7", 28: "8", 25: "9",
    82: "Num0", 83: "Num1", 84: "Num2", 85: "Num3", 86: "Num4", 87: "Num5", 88: "Num6",
    89: "Num7", 91: "Num8", 92: "Num9",
    27: "-", 24: "=", 33: "[", 30: "]", 42: "\\", 41: ";", 39: "'", 43: ",", 47: ".", 44: "/", 50: "`",
}


def _mods(flags: int) -> frozenset:
    mods = set()
    if flags & Quartz.kCGEventFlagMaskCommand:
        mods.add("cmd")
    if flags & Quartz.kCGEventFlagMaskControl:
        mods.add("ctrl")
    if flags & Quartz.kCGEventFlagMaskAlternate:
        mods.add("alt")
    if flags & Quartz.kCGEventFlagMaskShift:
        mods.add("shift")
    return frozenset(mods)


class MacHooks:
    def __init__(self, on_mouse, on_key):
        self._on_mouse = on_mouse
        self._on_key = on_key
        self._thread: threading.Thread | None = None
        self._loop = None
        self._tap = None
        self._ready = threading.Event()
        self._error: str | None = None
        self.keyboard_ok = True
        self._callback_ref = self._callback  # referencia viva para pyobjc

    def start(self) -> None:
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="rpa-tap", daemon=True)
        self._thread.start()
        if not self._ready.wait(3.0):
            raise HookError("El sistema no respondió al activar la escucha de ratón y teclado.")
        if self._error:
            raise HookError(self._error)

    def _create_tap(self, mask: int):
        return Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback_ref,
            None,
        )

    def _run(self) -> None:
        mouse_mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown)
        )
        tap = self._create_tap(mouse_mask | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown))
        if tap is None:
            tap = self._create_tap(mouse_mask)
            self.keyboard_ok = False
            if tap is None:
                self._error = (
                    "macOS no permite escuchar el ratón y el teclado. Concede los permisos de "
                    "Accesibilidad y Monitorización de entrada en Ajustes del Sistema > Privacidad y seguridad."
                )
                self._ready.set()
                return
            log.warning("tap sin teclado: falta el permiso de Monitorización de entrada")
        self._tap = tap
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        log.info("event tap activo (teclado: %s)", self.keyboard_ok)
        self._ready.set()
        try:
            Quartz.CFRunLoopRun()
        finally:
            try:
                Quartz.CGEventTapEnable(tap, False)
                Quartz.CFRunLoopRemoveSource(self._loop, source, Quartz.kCFRunLoopCommonModes)
                Quartz.CFMachPortInvalidate(tap)
            except Exception:
                pass
            self._tap = None
            log.info("event tap detenido")

    def stop(self) -> None:
        loop = self._loop
        if loop is not None:
            try:
                Quartz.CFRunLoopStop(loop)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(2.0)
        self._thread = None
        self._loop = None

    def alive(self) -> bool:
        if self._thread is None or not self._thread.is_alive() or self._tap is None:
            return False
        try:
            return bool(Quartz.CGEventTapIsEnabled(self._tap))
        except Exception:
            return True

    # ── callback (hilo del tap: rápido y sin excepciones) ──

    def _callback(self, proxy, etype, event, refcon):
        try:
            if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                if self._tap is not None:
                    Quartz.CGEventTapEnable(self._tap, True)
                    log.warning("macOS desactivó el tap (%s); reactivado", hex(etype))
                return event
            if etype == Quartz.kCGEventKeyDown:
                self._handle_key(event)
            elif etype in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventRightMouseDown, Quartz.kCGEventOtherMouseDown):
                self._handle_mouse(etype, event)
        except Exception:
            log.exception("fallo en el callback del tap")
        return event

    def _handle_mouse(self, etype, event) -> None:
        location = Quartz.CGEventGetLocation(event)
        mods = _mods(Quartz.CGEventGetFlags(event))
        clicks = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventClickState))
        if etype == Quartz.kCGEventLeftMouseDown:
            # Control+clic es el clic secundario de macOS.
            button = "right" if "ctrl" in mods else "left"
        elif etype == Quartz.kCGEventRightMouseDown:
            button = "right"
        else:
            number = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventButtonNumber))
            if number != 2:
                return  # botones laterales: no son pasos del proceso
            button = "middle"
        self._on_mouse(MouseEvent(
            x=int(round(location.x)), y=int(round(location.y)), button=button,
            t=time.monotonic(), clicks=clicks, mods=mods,
        ))

    def _handle_key(self, event) -> None:
        keycode = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode))
        repeat = bool(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat))
        mods = _mods(Quartz.CGEventGetFlags(event))
        name = _KEYCODES.get(keycode)
        if name is not None:
            self._on_key(KeyEvent(
                key=name, char=" " if name == "space" else "", mods=mods,
                base=name.upper() if name.startswith("f") else "", repeat=repeat, t=time.monotonic(),
            ))
            return
        try:
            _, chars = Quartz.CGEventKeyboardGetUnicodeString(event, 8, None, None)
        except Exception:
            chars = ""
        chars = chars or ""
        if chars and not chars.isprintable():
            chars = ""
        base = _ANSI.get(keycode, chars.upper() if len(chars) == 1 else "")
        # Con Opción, macOS cambia el carácter (Opción+E es una tecla muerta).
        dead = not chars and "alt" in mods and not (mods & {"cmd", "ctrl"})
        self._on_key(KeyEvent(key="char", char=chars, mods=mods, base=base, dead=dead,
                              repeat=repeat, t=time.monotonic()))
