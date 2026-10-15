"""Tokens tipográficos y de color centralizados para la UI (Tkinter).

Punto único de verdad del diseño de la interfaz de escritorio: familias,
escala tipográfica (familia, tamaño en px, peso), interlineados para los
widgets ``tk.Text``, escala de espaciado (base 4) y la paleta de color.

Las ventanas (``main.py``, ``review.py``, ``step_detail.py``) importan estos
tokens en lugar de repetir tuplas de fuente y colores sueltos. Así un cambio
de marca o de jerarquía tipográfica se hace en un solo sitio.

La monoespaciada se resuelve en tiempo de ejecución con ``resolve_mono()``:
se prefiere "Cascadia Mono" si está instalada y, si no, "Consolas". Debe
llamarse después de crear la raíz Tk (necesita un intérprete Tk vivo para
consultar las familias disponibles).
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont

IS_MAC = sys.platform == "darwin"

# ── Familias tipográficas ───────────────────────────────────
# macOS: la fuente del sistema (San Francisco) vía su nombre interno de Tk.
FONT_UI = ".AppleSystemUIFont" if IS_MAC else "Segoe UI"
_MONO_PREF = ("SF Mono", "Menlo") if IS_MAC else ("Cascadia Mono", "Consolas")
MONO = "Menlo" if IS_MAC else "Consolas"  # se resuelve en runtime con resolve_mono()


def resolve_mono() -> str:
    """Elige "Cascadia Mono" si está instalada; si no, "Consolas".

    Debe llamarse tras crear la raíz Tk (hace falta un intérprete Tk activo
    para consultar ``tkfont.families()``). Actualiza la global ``MONO`` y la
    devuelve. Si algo falla, mantiene el valor por defecto ("Consolas").
    """
    global MONO
    try:
        fams = set(tkfont.families())
        for f in _MONO_PREF:
            if f in fams:
                MONO = f
                break
    except Exception:
        # Sin raíz Tk o error al consultar familias: conservamos el fallback.
        pass
    return MONO


# ── Escala tipográfica (familia, pt, peso) ──────────────────
# En Mac con Tk 8.6 un punto es un píxel (en Windows y Tk 9, 1,33 px): se
# compensa para que el tamaño visible sea el mismo en todos los sistemas.
_K = 1.33 if (IS_MAC and tk.TkVersion < 9) else 1.0


def _pt(size: int) -> int:
    return round(size * _K)

FONT_DISPLAY        = (FONT_UI, _pt(34), "bold")
FONT_H1             = (FONT_UI, _pt(20), "bold")
FONT_H2             = (FONT_UI, _pt(16), "bold")
FONT_NUMERIC        = (FONT_UI, _pt(16), "normal")
FONT_H3             = (FONT_UI, _pt(13), "bold")
FONT_BODY_LG        = (FONT_UI, _pt(13), "normal")
FONT_BODY           = (FONT_UI, _pt(11), "normal")
FONT_BODY_STRONG    = (FONT_UI, _pt(11), "bold")
FONT_SMALL          = (FONT_UI, _pt(10), "normal")
FONT_SMALL_STRONG   = (FONT_UI, _pt(10), "bold")
FONT_CAPTION        = (FONT_UI, _pt(9), "normal")
FONT_CAPTION_STRONG = (FONT_UI, _pt(9), "bold")


def mono_body():
    """Fuente monoespaciada para detalle (selectores en vista de paso)."""
    return (MONO, _pt(10), "normal")


def mono_small():
    """Fuente monoespaciada compacta para listas densas."""
    return (MONO, _pt(9), "normal")


# ── Interlínea (px) para tk.Text (spacing3 ≈ LH - size) ─────
LH_BODY, LH_BODY_LG, LH_SMALL, LH_CAPTION = 16, 18, 14, 13

# ── Espaciado (px), base 4 ──────────────────────────────────
SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_5, SPACE_6, SPACE_8 = 4, 8, 12, 16, 20, 24, 32

# ── Color (centralizado) ────────────────────────────────────
ACCENT = "#d62d2d"
ACCENT_ACTIVE = "#b92525"
ACCENT_DISABLED = "#e3a3a3"
INK = "#1a1a1a"
MUTED = "#6b6b6b"
BG = "#f7f7f8"
CARD = "#ffffff"
CARD_SOFT = "#fcfcfd"
FIELD = "#fbfbfc"
BORDER = "#e3e4e8"
BADGE_BG = "#eef0f2"
REL_COLORS = {"alta": "#2e9e5b", "media": "#e0a106", "baja": "#d62d2d"}


def bind_wheel(area, canvas) -> None:
    """Scroll con rueda y trackpad en Windows, macOS (Tk 8.6 y 9) y Linux.

    Se activa al entrar el ratón en ``area`` (incluidos sus hijos) para que
    funcione también sobre las tarjetas, no solo sobre el fondo del canvas.
    """
    state = {"acc": 0.0}

    def _wheel(event):
        delta = event.delta
        if IS_MAC and tk.TkVersion < 9:
            units = -delta  # Tk 8.6 en Mac: líneas
        else:
            state["acc"] += -delta / 120.0
            units = int(state["acc"])
            state["acc"] -= units
        if units:
            canvas.yview_scroll(units, "units")

    def _touchpad(event):  # Tk 9 en Mac: trackpad
        dy = event.delta & 0xFFFF
        if dy >= 0x8000:
            dy -= 0x10000
        state["acc"] += -dy / 10.0
        units = int(state["acc"])
        state["acc"] -= units
        if units:
            canvas.yview_scroll(units, "units")

    def _enter(_e=None):
        area.bind_all("<MouseWheel>", _wheel)
        area.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        area.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        try:
            area.bind_all("<TouchpadScroll>", _touchpad)
        except tk.TclError:
            pass

    def _leave(_e=None):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<TouchpadScroll>"):
            try:
                area.unbind_all(seq)
            except tk.TclError:
                pass

    area.bind("<Enter>", _enter, add="+")
    area.bind("<Leave>", _leave, add="+")
