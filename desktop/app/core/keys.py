"""Teclado: eventos normalizados, atajos globales y reconstrucción de lo tecleado.

Cada backend (Windows/macOS) traduce sus eventos nativos a ``KeyEvent`` y a
partir de ahí la lógica es común: qué es escribir, qué es un atajo que
merece un paso ("Pulsar Ctrl+S"), qué atajos son de edición dentro de un
campo (Ctrl+V no debe cortar el paso de escritura) y cuáles son los atajos
propios del grabador (F8/F9/F10), que nunca se graban.

``KeyBuffer`` reconstruye el texto a partir de las pulsaciones. Es solo el
respaldo: siempre que se puede, el texto final se lee del propio campo
(ValuePattern / AXValue), que sí refleja pegados, autocompletado y teclas de
acento.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

# ── eventos ─────────────────────────────────────────────────


@dataclass(frozen=True)
class KeyEvent:
    key: str                      # "char", "enter", "tab", "esc", "backspace", "delete", "f9"...
    char: str = ""                # carácter producido (si lo hay)
    mods: frozenset = frozenset()  # {"ctrl", "alt", "shift", "cmd", "win"}
    base: str = ""                # tecla base para atajos: "C", "F4", "9"...
    dead: bool = False            # tecla muerta (acento pendiente)
    repeat: bool = False          # autorepetición por mantener pulsado
    t: float = 0.0


@dataclass(frozen=True)
class MouseEvent:
    x: int
    y: int
    button: str                   # "left" | "right" | "middle"
    t: float = 0.0
    clicks: int = 0               # nº de clic según el SO (0 = desconocido)
    mods: frozenset = frozenset()


NAMED_KEYS = {
    "enter", "tab", "esc", "backspace", "delete", "space", "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown", "insert",
} | {f"f{i}" for i in range(1, 25)}

_LABELS_WIN = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Mayús", "win": "Win", "cmd": "Win"}
_LABELS_MAC = {"ctrl": "Control", "alt": "Opción", "shift": "Mayús", "cmd": "Cmd", "win": "Cmd"}
_ORDER_WIN = ("ctrl", "alt", "shift", "win", "cmd")
_ORDER_MAC = ("ctrl", "alt", "shift", "cmd", "win")

_KEY_LABELS = {
    "enter": "Enter",
    "tab": "Tab",
    "esc": "Esc",
    "backspace": "Retroceso",
    "delete": "Supr",
    "space": "Espacio",
    "up": "Flecha arriba",
    "down": "Flecha abajo",
    "left": "Flecha izquierda",
    "right": "Flecha derecha",
    "home": "Inicio",
    "end": "Fin",
    "pageup": "RePág",
    "pagedown": "AvPág",
    "insert": "Insert",
}


def key_label(key: str, base: str = "") -> str:
    if key in _KEY_LABELS:
        return _KEY_LABELS[key]
    if key.startswith("f") and key[1:].isdigit():
        return key.upper()
    return (base or key).upper() if len(base or key) == 1 else (base or key)


def shortcut_label(event: KeyEvent, platform: str) -> str:
    """Texto legible del atajo: «Ctrl+Mayús+S» (Windows) o «Cmd+S» (macOS)."""
    mac = platform == "macos"
    labels = _LABELS_MAC if mac else _LABELS_WIN
    order = _ORDER_MAC if mac else _ORDER_WIN
    parts = []
    for mod in order:
        if mod in event.mods and labels[mod] not in parts:
            parts.append(labels[mod])
    parts.append(key_label(event.key, event.base))
    return "+".join(parts)


def command_mod(platform: str) -> str:
    """Modificador principal de los atajos de edición: Ctrl o Cmd."""
    return "cmd" if platform == "macos" else "ctrl"


def has_command_mods(event: KeyEvent, platform: str) -> bool:
    """¿Lleva modificadores que convierten la tecla en un atajo?

    En Windows, AltGr llega como Ctrl+Alt y produce caracteres normales («@»,
    «€»): si hay carácter imprimible con Ctrl+Alt, es escritura, no atajo.
    En macOS, Opción produce caracteres especiales: tampoco es atajo.
    """
    mods = event.mods
    if platform == "macos":
        return bool(mods & {"cmd", "ctrl"})
    if "win" in mods or "cmd" in mods:
        return True
    ctrl, alt = "ctrl" in mods, "alt" in mods
    if ctrl and alt:
        return not _printable(event.char)
    return ctrl or alt


def _printable(char: str) -> bool:
    return bool(char) and all(c.isprintable() for c in char)


def is_typing(event: KeyEvent, platform: str) -> bool:
    """¿La pulsación escribe texto en el campo con el foco?"""
    if event.key == "space":
        return not has_command_mods(event, platform)
    if event.key != "char":
        return False
    if event.dead:
        return True
    return _printable(event.char) and not has_command_mods(event, platform)


_EDIT_BASES = {"A", "C", "V", "X", "Z", "Y"}
_TEXT_CHANGING_BASES = {"V", "X", "Z", "Y"}


def is_edit_shortcut(event: KeyEvent, platform: str) -> bool:
    """Atajos de edición de texto (copiar, pegar, deshacer...) dentro de un campo."""
    if command_mod(platform) not in event.mods:
        # En macOS, Opción+Retroceso borra una palabra.
        return platform == "macos" and "alt" in event.mods and event.key in {"backspace", "delete", "left", "right"}
    base = (event.base or "").upper()
    return base in _EDIT_BASES or event.key in {"backspace", "delete", "left", "right", "home", "end", "up", "down"}


def changes_text(event: KeyEvent, platform: str) -> bool:
    """¿El atajo de edición puede cambiar el contenido del campo?"""
    if event.key in {"backspace", "delete"}:
        return True
    return (event.base or "").upper() in _TEXT_CHANGING_BASES and command_mod(platform) in event.mods


# ── atajos propios del grabador ─────────────────────────────

# Acción -> lista de (tecla, modificadores). Las F-teclas funcionan en ambos
# sistemas (en portátiles Mac, con Fn). Las combinaciones con 8/9/0 son las
# mismas que usa la extensión de navegador.
_HOTKEYS_COMMON = {
    "toggle_record": [("f9", frozenset())],
    "toggle_pause": [("f10", frozenset())],
    "add_note": [("f8", frozenset())],
}
_HOTKEY_COMBOS = {
    "toggle_record": "9",
    "add_note": "8",
    "toggle_pause": "0",
}


def hotkey_action(event: KeyEvent, platform: str) -> str | None:
    """Devuelve la acción del grabador asociada a la pulsación, o None."""
    if event.repeat:
        return None
    for action, combos in _HOTKEYS_COMMON.items():
        for key, mods in combos:
            if event.key == key and not (event.mods - {"shift"}) and mods <= event.mods:
                return action
    main = command_mod(platform)
    if {main, "shift"} <= event.mods and not (event.mods - {main, "shift"}):
        for action, base in _HOTKEY_COMBOS.items():
            if (event.base or "").upper() == base:
                return action
    return None


def hotkey_hint(action: str, platform: str) -> str:
    """Texto corto para la interfaz: «F9» (Windows) o «fn F9» (macOS)."""
    key = {"toggle_record": "F9", "toggle_pause": "F10", "add_note": "F8"}.get(action, "")
    return key


# ── reconstrucción de lo tecleado (respaldo) ────────────────

# Carácter de tecla muerta -> diacrítico combinable.
_DEAD_TO_COMBINING = {
    "´": "́", "'": "́", "ˊ": "́",
    "`": "̀", "ˋ": "̀",
    "¨": "̈", '"': "̈",
    "^": "̂", "ˆ": "̂",
    "~": "̃", "˜": "̃",
    "¸": "̧",
    "°": "̊", "˚": "̊",
}

MAX_BUFFER = 4000


@dataclass
class KeyBuffer:
    """Texto aproximado a partir de las pulsaciones (cuando no se puede leer el campo)."""

    chars: list = field(default_factory=list)
    pending_dead: str = ""
    count: int = 0               # pulsaciones que modificaron el texto
    unknown_edits: bool = False  # hubo pegados/cortes cuyo contenido no conocemos

    def feed(self, event: KeyEvent, platform: str) -> None:
        if event.key == "space" and is_typing(event, platform):
            self._append(" ")
        elif event.key == "char" and is_typing(event, platform):
            if event.dead:
                if self.pending_dead:
                    self._append(self.pending_dead)
                self.pending_dead = event.char
                return
            self._append(event.char)
        elif event.key == "backspace":
            self._flush_dead()
            if is_edit_shortcut(event, platform):
                self._delete_word()
            elif self.chars:
                self.chars.pop()
            self.count += 1
        elif event.key == "delete":
            # Sin saber dónde está el cursor no podemos reflejarlo.
            self.unknown_edits = True
            self.count += 1
        elif changes_text(event, platform):
            self.unknown_edits = True
            self.count += 1

    def _append(self, char: str) -> None:
        if self.pending_dead:
            combined = _combine(self.pending_dead, char)
            self.pending_dead = ""
            char = combined
        if len(self.chars) < MAX_BUFFER:
            self.chars.extend(char)
        self.count += 1

    def _flush_dead(self) -> None:
        if self.pending_dead:
            self.chars.append(self.pending_dead)
            self.pending_dead = ""

    def _delete_word(self) -> None:
        while self.chars and self.chars[-1] == " ":
            self.chars.pop()
        while self.chars and self.chars[-1] != " ":
            self.chars.pop()

    def text(self) -> str:
        return "".join(self.chars) + self.pending_dead

    def clear(self) -> None:
        self.chars.clear()
        self.pending_dead = ""
        self.count = 0
        self.unknown_edits = False


def _combine(dead: str, char: str) -> str:
    """Aplica una tecla muerta: «´» + «e» = «é»; si no combina, ambos caracteres."""
    if char == " ":
        return dead
    combining = _DEAD_TO_COMBINING.get(dead)
    if combining:
        composed = unicodedata.normalize("NFC", char + combining)
        if len(composed) == 1:
            return composed
    return dead + char
