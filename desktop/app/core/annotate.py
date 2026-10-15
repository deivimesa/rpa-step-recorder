"""Anotación de capturas: recuadro de marca sobre el elemento y recorte ampliado.

Port de lib/annotate.js usando Pillow en lugar de OffscreenCanvas. Las
coordenadas del rectángulo ya vienen en píxeles físicos de pantalla (UI
Automation), así que aquí no hay que multiplicar por el devicePixelRatio.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

HIGHLIGHT = (0, 143, 87)        # #008f57 (verde primario de marca)
SCRIM = 0.20                     # oscurecido suave
BORDER = 3
ZOOM_MIN_WIDTH = 720
ZOOM_MAX_SCALE = 3.0


def _clamp_box(box, width, height):
    left = max(0, min(round(box[0]), width))
    top = max(0, min(round(box[1]), height))
    right = max(0, min(round(box[2]), width))
    bottom = max(0, min(round(box[3]), height))
    if right - left < 2 or bottom - top < 2:
        return None
    return [left, top, right, bottom]


def annotate(image: Image.Image, rect: dict | None) -> tuple[Image.Image, Image.Image | None]:
    """Devuelve (captura_completa_anotada, recorte_ampliado_o_None).

    `rect` tiene x, y, width, height en coordenadas de la captura (pantalla
    completa). Si viene de un monitor concreto, el llamador ya debe haberlo
    trasladado al origen de la imagen.
    """
    base = image.convert("RGB")
    width, height = base.size

    box = None
    if rect and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
        box = _clamp_box(
            [rect["x"], rect["y"], rect["x"] + rect["width"], rect["y"] + rect["height"]],
            width,
            height,
        )

    if not box:
        return base, None

    pad = BORDER * 2
    radius = 7
    focus = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad]

    # Oscurece todo y devuelve la nitidez solo dentro del recuadro.
    overlay = Image.new("RGB", base.size, (0, 0, 0))
    full = Image.blend(base, overlay, SCRIM)
    crop = base.crop((focus[0], focus[1], focus[2], focus[3]))
    full.paste(crop, (focus[0], focus[1]))

    draw = ImageDraw.Draw(full)
    draw.rounded_rectangle(
        [focus[0], focus[1], focus[2] - 1, focus[3] - 1],
        radius=radius + pad,
        outline=HIGHLIGHT,
        width=BORDER,
    )

    zoom = _build_zoom(base, box)
    return full, zoom


def _build_zoom(base: Image.Image, box) -> Image.Image | None:
    w = box[2] - box[0]
    h = box[3] - box[1]
    margin_x = max(60, round(w * 0.45))
    margin_y = max(40, round(h * 1.2))

    crop_box = _clamp_box(
        [box[0] - margin_x, box[1] - margin_y, box[2] + margin_x, box[3] + margin_y],
        base.width,
        base.height,
    )
    if not crop_box:
        return None

    cw = crop_box[2] - crop_box[0]
    ch = crop_box[3] - crop_box[1]
    factor = min(ZOOM_MAX_SCALE, max(1.0, ZOOM_MIN_WIDTH / cw))
    out_w = round(cw * factor)
    out_h = round(ch * factor)

    region = base.crop((crop_box[0], crop_box[1], crop_box[2], crop_box[3]))
    zoom = region.resize((out_w, out_h), Image.LANCZOS).convert("RGB")

    draw = ImageDraw.Draw(zoom)
    border = max(BORDER, round(2 * factor))
    draw.rounded_rectangle(
        [
            (box[0] - crop_box[0]) * factor,
            (box[1] - crop_box[1]) * factor,
            (box[0] - crop_box[0] + w) * factor - 1,
            (box[1] - crop_box[1] + h) * factor - 1,
        ],
        radius=max(3, round(4 * factor)),
        outline=HIGHLIGHT,
        width=border,
    )
    draw.rectangle([0, 0, out_w - 1, out_h - 1], outline=(208, 208, 208), width=1)
    return zoom
