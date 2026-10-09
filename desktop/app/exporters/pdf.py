"""Exportación a PDF con fpdf2.

Mismo PDD que el exportador de Word, con diseño cuidado y coherente: portada con
banda de acento y resumen de fiabilidad, índice de pasos en tabla de 3 columnas
y una página por paso con secciones etiquetadas, control de saltos de página y
pie con número de página + nombre del proceso.

No cambia la firma pública: export(session, out_path) -> Path.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from PIL import Image

from .. import doc_common as dc
from .. import storage


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

# ── tamaños de fuente (pt) ──
FS_TITLE = 26
FS_SUBTITLE = 12
FS_H1 = 16
FS_STEP = 14
FS_DESC = 13
FS_SECTION = 9
FS_BODY = 9
FS_SMALL = 8


class _PDF(FPDF):
    """PDF con pie de página: nombre del proceso (izq., gris) y nº de página."""

    def __init__(self, *args, process_name: str = "Proceso", **kwargs):
        super().__init__(*args, **kwargs)
        self._process_name = process_name

    def header(self):
        pass

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", size=FS_SMALL)
        self.set_text_color(*MUTED)
        # Nombre del proceso a la izquierda, número de página centrado.
        self.cell(CONTENT_W / 2, 8, _text(self._process_name), align="L")
        self.cell(CONTENT_W / 2, 8, f"{self.page_no()}", align="R")


def _text(value) -> str:
    """fpdf2 con fuentes core usa latin-1: sustituye lo que no entra."""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def _rule(pdf: _PDF, color=RULE):
    """Dibuja una línea separadora fina a lo ancho del contenido."""
    pdf.set_draw_color(*color)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())


def _section_title(pdf: _PDF, text):
    """Subtítulo de sección con regla fina debajo y espaciado uniforme."""
    pdf.ln(3)
    pdf.set_font("Helvetica", style="B", size=FS_SECTION)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 6, _text(str(text).upper()))
    pdf.ln(7)
    _rule(pdf)
    pdf.ln(2)


def _kv_table(pdf: _PDF, rows):
    """Tabla clave/valor: clave gris en negrita, valor en tinta, línea separadora."""
    key_w = 48
    val_w = CONTENT_W - key_w
    for key, value in rows:
        value = _text(value)
        # Salto de página si la fila no cabe (estimación conservadora).
        if pdf.get_y() + 10 > BOTTOM_LIMIT:
            pdf.add_page()
        pdf.set_text_color(*MUTED)
        pdf.set_font("Helvetica", style="B", size=FS_SMALL)
        start_y = pdf.get_y()
        pdf.multi_cell(key_w, 6, _text(key), border=0)
        key_end = pdf.get_y()
        pdf.set_xy(MARGIN + key_w, start_y)
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", size=FS_BODY)
        pdf.multi_cell(val_w, 6, value, border=0)
        val_end = pdf.get_y()
        pdf.set_y(max(key_end, val_end) + 1)
        _rule(pdf)
        pdf.ln(1)


def _measure_kv_height(pdf: _PDF, rows) -> float:
    """Estima la altura (mm) de una tabla clave/valor sin dibujarla.

    Sirve para decidir saltos de página y evitar cortar un bloque de datos.
    """
    key_w = 48
    val_w = CONTENT_W - key_w
    total = 0.0
    for key, value in rows:
        pdf.set_font("Helvetica", style="B", size=FS_SMALL)
        key_lines = len(pdf.multi_cell(key_w, 6, _text(key), dry_run=True, output="LINES"))
        pdf.set_font("Helvetica", size=FS_BODY)
        val_lines = len(pdf.multi_cell(val_w, 6, _text(value), dry_run=True, output="LINES"))
        total += max(key_lines, val_lines) * 6 + 2
    return total


def _section_block(pdf: _PDF, title, rows):
    """Pinta una sección (título + tabla) evitando cortarla si cabe en una página.

    Si el bloque no cabe en lo que queda de página pero sí en una página
    completa, salta de página antes de empezar.
    """
    if not rows:
        return
    needed = _measure_kv_height(pdf, rows) + 15  # + título y regla
    remaining = BOTTOM_LIMIT - pdf.get_y()
    if needed > remaining and needed <= (BOTTOM_LIMIT - MARGIN):
        pdf.add_page()
    _section_title(pdf, title)
    _kv_table(pdf, rows)


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
        pdf.set_font("Helvetica", style="I", size=FS_SMALL)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, _text(caption), align="C")
        pdf.ln(6)
    else:
        pdf.ln(3)


def _cover(pdf: _PDF, session):
    """Portada: título, banda de acento, datos y resumen de fiabilidad."""
    pdf.add_page()
    pdf.ln(36)
    pdf.set_font("Helvetica", style="B", size=FS_TITLE)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, 12, _text(session.get("name", "Proceso")))
    pdf.ln(1)
    pdf.set_font("Helvetica", size=FS_SUBTITLE)
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
    pdf.set_font("Helvetica", style="B", size=FS_BODY)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, 6, _text(dc.reliability_overview(session)))

    warning = dc.reliability_warning(session)
    if warning:
        pdf.ln(1)
        pdf.set_font("Helvetica", size=FS_SMALL)
        pdf.set_text_color(*REL_COLORS["baja"])
        pdf.multi_cell(CONTENT_W, 5, _text(warning))


def _step_index(pdf: _PDF, session):
    """Índice de pasos en tabla de 3 columnas: # | Descripción | Fiabilidad."""
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=FS_H1)
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, _text("Resumen de pasos"))
    pdf.ln(12)

    num_w = 12
    rel_w = 28
    desc_w = CONTENT_W - num_w - rel_w

    # Cabecera con fondo tenue.
    pdf.set_fill_color(*HEADER_FILL)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", style="B", size=FS_SMALL)
    pdf.cell(num_w, 8, _text("#"), fill=True, align="C")
    pdf.cell(desc_w, 8, _text("Descripción"), fill=True)
    pdf.cell(rel_w, 8, _text("Fiabilidad"), fill=True, align="C")
    pdf.ln(8)

    for step in session.get("steps", []):
        desc = _text(dc.step_text(step))
        pdf.set_font("Helvetica", size=FS_BODY)
        # Número de líneas que ocupará la descripción, para alinear la fila.
        lines = pdf.multi_cell(desc_w, 6, desc, dry_run=True, output="LINES")
        row_h = max(6, len(lines) * 6)
        if pdf.get_y() + row_h > BOTTOM_LIMIT:
            pdf.add_page()

        x0 = MARGIN
        y0 = pdf.get_y()
        level = dc.step_level(step)

        # Columna #.
        pdf.set_text_color(*ACCENT)
        pdf.set_font("Helvetica", style="B", size=FS_BODY)
        pdf.set_xy(x0, y0)
        pdf.cell(num_w, row_h, str(step.get("index", "")), align="C")

        # Columna descripción (multi_cell para texto largo).
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", size=FS_BODY)
        pdf.set_xy(x0 + num_w, y0)
        pdf.multi_cell(desc_w, 6, desc)

        # Columna fiabilidad con color según nivel.
        pdf.set_text_color(*REL_COLORS.get(level, MUTED))
        pdf.set_font("Helvetica", style="B", size=FS_BODY)
        pdf.set_xy(x0 + num_w + desc_w, y0)
        pdf.cell(rel_w, row_h, _text(dc.REL_SHORT.get(level, "—")), align="C")

        pdf.set_y(y0 + row_h + 1)
        _rule(pdf)
        pdf.ln(1)


def _step_header(pdf: _PDF, step):
    """Cabecera del paso: 'Paso N' en acento + badge de fiabilidad a la derecha."""
    y0 = pdf.get_y()
    pdf.set_font("Helvetica", style="B", size=FS_STEP)
    pdf.set_text_color(*ACCENT)
    pdf.cell(CONTENT_W / 2, 10, _text(f"Paso {step.get('index', '')}"))

    level = dc.step_level(step)
    if level:
        pdf.set_xy(MARGIN + CONTENT_W / 2, y0)
        pdf.set_font("Helvetica", style="B", size=FS_SMALL)
        pdf.set_text_color(*REL_COLORS.get(level, MUTED))
        pdf.cell(CONTENT_W / 2, 10, _text(f"Fiabilidad: {dc.REL_SHORT.get(level, level)}"), align="R")

    pdf.set_y(y0 + 11)


def _step_body(pdf: _PDF, session, step):
    """Contenido completo de un paso con jerarquía y secciones etiquetadas."""
    pdf.add_page()
    _step_header(pdf, step)

    # Descripción destacada.
    pdf.set_font("Helvetica", size=FS_DESC)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, 7, _text(dc.step_text(step)))
    pdf.ln(1)

    # Fiabilidad detallada (motivo).
    summary = dc.reliability_summary(step)
    if summary:
        level = dc.step_level(step)
        pdf.set_font("Helvetica", style="B", size=FS_SMALL)
        pdf.set_text_color(*REL_COLORS.get(level, MUTED))
        pdf.multi_cell(CONTENT_W, 5, _text(f"Fiabilidad del selector: {summary}"))
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
    _section_block(pdf, "Selectores para RPA", dc.selector_rows(step))


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
