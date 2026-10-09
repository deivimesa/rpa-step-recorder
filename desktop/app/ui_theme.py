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

import tkinter.font as tkfont

# ── Familias tipográficas ───────────────────────────────────
FONT_UI = "Segoe UI"
_MONO_PREF = ("Cascadia Mono", "Consolas")
MONO = "Consolas"  # se resuelve en runtime con resolve_mono()


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


# ── Escala tipográfica (familia, px, peso) ──────────────────
FONT_DISPLAY        = (FONT_UI, 34, "bold")
FONT_H1             = (FONT_UI, 20, "bold")
FONT_H2             = (FONT_UI, 16, "bold")
FONT_NUMERIC        = (FONT_UI, 16, "normal")
FONT_H3             = (FONT_UI, 13, "bold")
FONT_BODY_LG        = (FONT_UI, 13, "normal")
FONT_BODY           = (FONT_UI, 11, "normal")
FONT_BODY_STRONG    = (FONT_UI, 11, "bold")
FONT_SMALL          = (FONT_UI, 10, "normal")
FONT_SMALL_STRONG   = (FONT_UI, 10, "bold")
FONT_CAPTION        = (FONT_UI, 9,  "normal")
FONT_CAPTION_STRONG = (FONT_UI, 9,  "bold")


def mono_body():
    """Fuente monoespaciada para detalle (selectores en vista de paso)."""
    return (MONO, 10, "normal")


def mono_small():
    """Fuente monoespaciada compacta para listas densas."""
    return (MONO, 9, "normal")


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
