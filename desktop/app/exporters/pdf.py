"""Exportación a PDF con fpdf2.

Mismo PDD que el exportador de Word, con diseño cuidado y coherente: portada con
banda de acento y resumen de fiabilidad, índice de pasos en tabla de 3 columnas
y una página por paso con secciones etiquetadas, control de saltos de página y
pie con número de página + nombre del proceso.

No cambia la firma pública: export(session, out_path) -> Path.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF
from PIL import Image

from . import doc_common as dc
from ..core import storage


# ── Localización robusta de la carpeta de fuentes ───────────
def _resolve_fonts_dir() -> Path:
    """Devuelve la carpeta de fuentes DejaVu tanto en dev como empaquetado.

    En PyInstaller onefile los datos se extraen a ``sys._MEIPASS``; si ahí
    existe ``app/assets/fonts`` se usa. En desarrollo (o si no está en
    _MEIPASS) se cae a la ruta relativa al paquete: este archivo vive en
    ``app/exporters/`` y las fuentes en ``app/assets/fonts``.
    """
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidate = Path(meipass) / "app" / "assets" / "fonts"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[1] / "assets" / "fonts"


FONTS_DIR = _resolve_fonts_dir()

# Si falta algún .ttf, el PDF se degrada a "Helvetica" (fuente core) y _text()
# vuelve al saneado latin-1 para no romper la exportación. _UNICODE_OK refleja
# si las fuentes DejaVu (Unicode completas) están activas.
_UNICODE_OK = True


def _register_fonts(pdf: FPDF) -> bool:
    """Registra las variantes DejaVu (Unicode) en el objeto PDF.

    Devuelve True si todas se registraron. Ante cualquier fallo (p. ej. un
    .ttf ausente en el empaquetado) devuelve False para activar el fallback a
    Helvetica + latin-1 y así no reventar la exportación.
    """
    try:
        pdf.add_font(dc.PDF_FONT, "", str(FONTS_DIR / "DejaVuSans.ttf"))
        pdf.add_font(dc.PDF_FONT, "B", str(FONTS_DIR / "DejaVuSans-Bold.ttf"))
        pdf.add_font(dc.PDF_FONT, "I", str(FONTS_DIR / "DejaVuSans-Oblique.ttf"))
        pdf.add_font(dc.PDF_FONT, "BI", str(FONTS_DIR / "DejaVuSans-BoldOblique.ttf"))
        pdf.add_font(dc.PDF_FONT_MONO, "", str(FONTS_DIR / "DejaVuSansMono.ttf"))
        pdf.add_font(dc.PDF_FONT_MONO, "B", str(FONTS_DIR / "DejaVuSansMono-Bold.ttf"))
        return True
    except Exception:
        return False


def _lh(pt: float, factor: float) -> float:
    """Altura de línea en mm para un cuerpo en pt y un factor de interlineado.

    1 pt = 0.3528 mm. Se usa para alturas de celda proporcionales al tamaño
    real en vez de valores fijos (5/6/7).
    """
    return pt * 0.3528 * factor


# ── constantes de color (reutilizadas, sin números mágicos dispersos) ──
def _rgb(hex_str: str) -> tuple[int, int, int]:
    return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


ACCENT = _rgb(dc.ACCENT_HEX)
INK = _rgb(dc.INK_HEX)
MUTED = _rgb(dc.MUTED_HEX)
RULE = _rgb(dc.RULE_HEX)
REL_COLORS = {
    "alta": _rgb(dc.GREEN_HEX),
    "media": _rgb(dc.AMBER_HEX),
    "baja": _rgb(dc.RED_HEX),
}
HEADER_FILL = (242, 242, 242)  # fondo tenue de cabeceras de tabla

# ── geometría de página (mm) ──
PAGE_W = 210
PAGE_H = 297
MARGIN = 18
CONTENT_W = PAGE_W - 2 * MARGIN
BOTTOM_LIMIT = PAGE_H - MARGIN  # y máximo antes de forzar salto de página

# ── tamaños de fuente (pt): escala unificada de doc_common ──
FS_TITLE = dc.FS_TITLE
FS_SUBTITLE = dc.FS_SUBTITLE
FS_H1 = dc.FS_H1
FS_STEP = dc.FS_STEP
FS_DESC = dc.FS_LEAD
FS_SECTION = dc.FS_SECTION
FS_BODY = dc.FS_BODY
FS_SMALL = dc.FS_SMALL
FS_CAPTION = dc.FS_CAPTION

# ── alturas de línea (mm) proporcionales al tamaño real ─────
# Se calculan con _lh() a partir de los FS_* y los factores LH_* de doc_common,
# en lugar de los 5/6/7 fijos anteriores. KV_LH se usa como alto de fila en las
# tablas clave/valor (medición y dibujo deben coincidir para alinear bien).
KV_LH = _lh(FS_BODY, dc.LH_BODY)
LEAD_LH = _lh(FS_DESC, dc.LH_LEAD)
BODY_LH = _lh(FS_BODY, dc.LH_BODY)
SMALL_LH = _lh(FS_SMALL, dc.LH_BODY)


class _PDF(FPDF):
    """PDF con pie de página: nombre del proceso (izq., gris) y nº de página.

    Registra las fuentes DejaVu en el constructor para que el footer (que se
    dibuja durante output()) disponga de ellas. ``font_main``/``font_mono``
    guardan el nombre efectivo tras el posible fallback a Helvetica.
    """

    def __init__(self, *args, process_name: str = "Proceso", **kwargs):
        super().__init__(*args, **kwargs)
        self._process_name = process_name
        # Registramos las fuentes aquí para que estén disponibles también en el
        # footer, que fpdf2 ejecuta al generar la salida.
        global _UNICODE_OK
        if _register_fonts(self):
            self.font_main = dc.PDF_FONT
            self.font_mono = dc.PDF_FONT_MONO
            _UNICODE_OK = True
        else:
            # Fallback: sin DejaVu usamos la core Helvetica (latin-1 vía _text).
            self.font_main = "Helvetica"
            self.font_mono = "Courier"
            _UNICODE_OK = False

    def header(self):
        pass

    def footer(self):
        self.set_y(-14)
        self.set_font(self.font_main, style="I", size=FS_CAPTION)
        self.set_text_color(*MUTED)
        # Nombre del proceso a la izquierda, número de página a la derecha.
        self.cell(CONTENT_W / 2, 8, _text(self._process_name), align="L")
        self.cell(CONTENT_W / 2, 8, f"{self.page_no()}", align="R")


def _text(value) -> str:
    """Normaliza un valor a texto para el PDF.

    Con las fuentes DejaVu (Unicode) se devuelve tal cual, sin mutilar comillas
    tipográficas, «…», etc. Solo en el modo de fallback a fuentes core
    (Helvetica, cuando falta algún .ttf) se sanea a latin-1 para no romper la
    exportación. Se mantiene la firma para no tocar las llamadas existentes.
    """
    if _UNICODE_OK:
        return str(value)
    return str(value).encode("latin-1", "replace").decode("latin-1")


def _rule(pdf: _PDF, color=RULE):
    """Dibuja una línea separadora fina a lo ancho del contenido."""
    pdf.set_draw_color(*color)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())


def _section_title(pdf: _PDF, text):
    """Subtítulo de sección con regla fina debajo y espaciado uniforme."""
    pdf.ln(3)
    pdf.set_font(pdf.font_main, style="B", size=FS_SECTION)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 6, _text(str(text).upper()))
    pdf.ln(7)
    _rule(pdf)
    pdf.ln(2)


def _kv_table(pdf: _PDF, rows, mono: bool = False):
    """Tabla clave/valor: clave gris en negrita, valor en tinta, línea separadora.

    Si ``mono`` es True el valor se pinta en la monoespaciada (DejaVuMono),
    útil para selectores donde importa distinguir caracteres similares.
    """
    key_w = 48
    val_w = CONTENT_W - key_w
    val_font = pdf.font_mono if mono else pdf.font_main
    for key, value in rows:
        value = _text(value)
        # Salto de página si la fila no cabe (estimación conservadora).
        if pdf.get_y() + KV_LH + 4 > BOTTOM_LIMIT:
            pdf.add_page()
        pdf.set_text_color(*MUTED)
        pdf.set_font(pdf.font_main, style="B", size=FS_SMALL)
        start_y = pdf.get_y()
        pdf.multi_cell(key_w, KV_LH, _text(key), border=0)
        key_end = pdf.get_y()
        pdf.set_xy(MARGIN + key_w, start_y)
        pdf.set_text_color(*INK)
        pdf.set_font(val_font, size=FS_BODY)
        pdf.multi_cell(val_w, KV_LH, value, border=0)
        val_end = pdf.get_y()
        pdf.set_y(max(key_end, val_end) + 1)
        _rule(pdf)
        pdf.ln(1)


def _measure_kv_height(pdf: _PDF, rows, mono: bool = False) -> float:
    """Estima la altura (mm) de una tabla clave/valor sin dibujarla.

    Sirve para decidir saltos de página y evitar cortar un bloque de datos.
    """
    key_w = 48
    val_w = CONTENT_W - key_w
    val_font = pdf.font_mono if mono else pdf.font_main
    total = 0.0
    for key, value in rows:
        pdf.set_font(pdf.font_main, style="B", size=FS_SMALL)
        key_lines = len(pdf.multi_cell(key_w, KV_LH, _text(key), dry_run=True, output="LINES"))
        pdf.set_font(val_font, size=FS_BODY)
        val_lines = len(pdf.multi_cell(val_w, KV_LH, _text(value), dry_run=True, output="LINES"))
        total += max(key_lines, val_lines) * KV_LH + 2
    return total


def _section_block(pdf: _PDF, title, rows, mono: bool = False):
    """Pinta una sección (título + tabla) evitando cortarla si cabe en una página.

    Si el bloque no cabe en lo que queda de página pero sí en una página
    completa, salta de página antes de empezar. ``mono`` propaga la fuente
    monoespaciada a los valores (p. ej. selectores).
    """
    if not rows:
        return
    needed = _measure_kv_height(pdf, rows, mono=mono) + 15  # + título y regla
    remaining = BOTTOM_LIMIT - pdf.get_y()
    if needed > remaining and needed <= (BOTTOM_LIMIT - MARGIN):
        pdf.add_page()
    _section_title(pdf, title)
    _kv_table(pdf, rows, mono=mono)


def _image_fit(pdf: _PDF, path: Path, max_w: float, max_h: float, caption: str = ""):
    """Inserta una imagen centrada, con borde sutil y pie de figura en gris."""
    try:
        with Image.open(path) as img:
            ratio = img.height / img.width
    except Exception:
        return
    width = max_w
    height = width * ratio
    if height > max_h:
        height = max_h
        width = height / ratio

    # Salto de página si la imagen (y su pie) no caben.
    if pdf.get_y() + height + 8 > BOTTOM_LIMIT:
        pdf.add_page()

    x = MARGIN + (CONTENT_W - width) / 2  # centrada horizontalmente
    y = pdf.get_y()
    pdf.image(str(path), x=x, y=y, w=width, h=height)
    # Borde sutil alrededor de la imagen.
    pdf.set_draw_color(*RULE)
    pdf.rect(x, y, width, height)
    pdf.set_y(y + height + 1)

    if caption:
        # Pie de figura en itálica y tamaño de "caption".
        pdf.set_font(pdf.font_main, style="I", size=FS_CAPTION)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, _text(caption), align="C")
        pdf.ln(6)
    else:
        pdf.ln(3)


def _cover(pdf: _PDF, session):
    """Portada: título, banda de acento, datos y resumen de fiabilidad."""
    pdf.add_page()
    pdf.ln(36)
    pdf.set_font(pdf.font_main, style="B", size=FS_TITLE)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, _lh(FS_TITLE, dc.LH_TITLE), _text(session.get("name", "Proceso")))
    pdf.ln(1)
    pdf.set_font(pdf.font_main, size=FS_SUBTITLE)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 8, _text(dc.DOC_SUBTITLE))
    pdf.ln(10)

    # Banda de acento bajo el título.
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(1.2)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(10)

    _kv_table(pdf, dc.cover_rows(session))

    # Bloque "Resumen de fiabilidad".
    _section_title(pdf, "Resumen de fiabilidad")
    pdf.set_font(pdf.font_main, style="B", size=FS_BODY)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, BODY_LH, _text(dc.reliability_overview(session)))

    warning = dc.reliability_warning(session)
    if warning:
        pdf.ln(1)
        pdf.set_font(pdf.font_main, size=FS_SMALL)
        pdf.set_text_color(*REL_COLORS["baja"])
        pdf.multi_cell(CONTENT_W, SMALL_LH, _text(warning))


def _step_index(pdf: _PDF, session):
    """Índice de pasos en tabla de 3 columnas: # | Descripción | Fiabilidad."""
    pdf.add_page()
    pdf.set_font(pdf.font_main, style="B", size=FS_H1)
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, _text("Resumen de pasos"))
    pdf.ln(12)

    num_w = 12
    rel_w = 28
    desc_w = CONTENT_W - num_w - rel_w

    # Cabecera con fondo tenue.
    pdf.set_fill_color(*HEADER_FILL)
    pdf.set_text_color(*INK)
    pdf.set_font(pdf.font_main, style="B", size=FS_SMALL)
    pdf.cell(num_w, 8, _text("#"), fill=True, align="C")
    pdf.cell(desc_w, 8, _text("Descripción"), fill=True)
    pdf.cell(rel_w, 8, _text("Fiabilidad"), fill=True, align="C")
    pdf.ln(8)

    for step in session.get("steps", []):
        desc = _text(dc.step_text(step))
        pdf.set_font(pdf.font_main, size=FS_BODY)
        # Número de líneas que ocupará la descripción, para alinear la fila.
        lines = pdf.multi_cell(desc_w, KV_LH, desc, dry_run=True, output="LINES")
        row_h = max(KV_LH, len(lines) * KV_LH)
        if pdf.get_y() + row_h > BOTTOM_LIMIT:
            pdf.add_page()

        x0 = MARGIN
        y0 = pdf.get_y()
        level = dc.step_level(step)

        # Columna #.
        pdf.set_text_color(*ACCENT)
        pdf.set_font(pdf.font_main, style="B", size=FS_BODY)
        pdf.set_xy(x0, y0)
        pdf.cell(num_w, row_h, str(step.get("index", "")), align="C")

        # Columna descripción (multi_cell para texto largo).
        pdf.set_text_color(*INK)
        pdf.set_font(pdf.font_main, size=FS_BODY)
        pdf.set_xy(x0 + num_w, y0)
        pdf.multi_cell(desc_w, KV_LH, desc)

        # Columna fiabilidad con color según nivel.
        pdf.set_text_color(*REL_COLORS.get(level, MUTED))
        pdf.set_font(pdf.font_main, style="B", size=FS_BODY)
        pdf.set_xy(x0 + num_w + desc_w, y0)
        pdf.cell(rel_w, row_h, _text(dc.REL_SHORT.get(level, "—")), align="C")

        pdf.set_y(y0 + row_h + 1)
        _rule(pdf)
        pdf.ln(1)


def _step_header(pdf: _PDF, step):
    """Cabecera del paso: 'Paso N' en acento + badge de fiabilidad a la derecha."""
    y0 = pdf.get_y()
    pdf.set_font(pdf.font_main, style="B", size=FS_STEP)
    pdf.set_text_color(*ACCENT)
    pdf.cell(CONTENT_W / 2, 10, _text(f"Paso {step.get('index', '')}"))

    level = dc.step_level(step)
    if level:
        pdf.set_xy(MARGIN + CONTENT_W / 2, y0)
        pdf.set_font(pdf.font_main, style="B", size=FS_SMALL)
        pdf.set_text_color(*REL_COLORS.get(level, MUTED))
        pdf.cell(CONTENT_W / 2, 10, _text(f"Fiabilidad: {dc.REL_SHORT.get(level, level)}"), align="R")

    pdf.set_y(y0 + 11)


def _step_body(pdf: _PDF, session, step):
    """Contenido completo de un paso con jerarquía y secciones etiquetadas."""
    pdf.add_page()
    _step_header(pdf, step)

    # Descripción destacada (interlineado de "lead").
    pdf.set_font(pdf.font_main, size=FS_DESC)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, LEAD_LH, _text(dc.step_text(step)))
    pdf.ln(1)

    # Fiabilidad detallada (motivo).
    summary = dc.reliability_summary(step)
    if summary:
        level = dc.step_level(step)
        pdf.set_font(pdf.font_main, style="B", size=FS_SMALL)
        pdf.set_text_color(*REL_COLORS.get(level, MUTED))
        pdf.multi_cell(CONTENT_W, SMALL_LH, _text(f"Fiabilidad del selector: {summary}"))
        pdf.ln(1)

    # Capturas con pie de figura.
    full = step.get("full_image")
    if full:
        path = storage.image_path(session["id"], full)
        if path.exists():
            _image_fit(pdf, path, CONTENT_W, 150, caption="Pantalla completa")

    zoom = step.get("zoom_image")
    if zoom:
        path = storage.image_path(session["id"], zoom)
        if path.exists():
            _image_fit(pdf, path, CONTENT_W * 0.6, 80, caption="Detalle del elemento")

    # Datos agrupados en secciones; cada bloque evita cortarse si cabe entero.
    _section_block(pdf, "Identificación del elemento", dc.identification_rows(step))
    _section_block(pdf, "Ubicación", dc.location_rows(step))
    _section_block(pdf, "Selectores para RPA", dc.selector_rows(step), mono=True)


def export(session: dict, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    pdf = _PDF(orientation="P", unit="mm", format="A4", process_name=session.get("name", "Proceso"))
    pdf.set_auto_page_break(auto=True, margin=MARGIN)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)

    _cover(pdf, session)
    _step_index(pdf, session)

    for step in session.get("steps", []):
        _step_body(pdf, session, step)

    pdf.output(str(out_path))
    return out_path
