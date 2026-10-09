/**
 * Anotación de capturas en el navegador: recuadro rojo sobre el elemento
 * y recorte ampliado. Equivale al antiguo images.py, con OffscreenCanvas.
 */

const HIGHLIGHT = "#d62d2d";
const SCRIM = 0.20;        // oscurecido suave: destaca sin ocultar el contexto
const BORDER_MIN = 3;
const ZOOM_MIN_WIDTH = 720;
const ZOOM_MAX_SCALE = 3;

function roundedPath(ctx, x, y, w, h, r) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

function clampBox(box, width, height) {
  const left = Math.max(0, Math.min(Math.round(box[0]), width));
  const top = Math.max(0, Math.min(Math.round(box[1]), height));
  const right = Math.max(0, Math.min(Math.round(box[2]), width));
  const bottom = Math.max(0, Math.min(Math.round(box[3]), height));
  if (right - left < 2 || bottom - top < 2) return null;
  return [left, top, right, bottom];
}

const toPng = async (canvas) =>
  new Uint8Array(await (await canvas.convertToBlob({ type: "image/png" })).arrayBuffer());

/**
 * @param {Blob|Uint8Array} source  PNG de la captura completa
 * @param {{x,y,width,height}|null} rect  en píxeles CSS del viewport superior
 * @param {number} dpr
 * @returns {Promise<{full: Uint8Array, zoom: Uint8Array|null, width: number, height: number}>}
 */
export async function annotate(source, rect, dpr) {
  const blob = source instanceof Blob ? source : new Blob([source], { type: "image/png" });
  const bitmap = await createImageBitmap(blob);
  const { width, height } = bitmap;
  const scale = dpr > 0 ? dpr : 1;

  const box =
    rect && rect.width > 0 && rect.height > 0
      ? clampBox(
          [rect.x * scale, rect.y * scale, (rect.x + rect.width) * scale, (rect.y + rect.height) * scale],
          width,
          height
        )
      : null;

  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0);

  if (!box) {
    bitmap.close();
    return { full: await toPng(canvas), zoom: null, width, height };
  }

  const border = Math.max(BORDER_MIN, Math.round(2 * scale));
  const radius = Math.max(4, Math.round(5 * scale));
  const pad = border * 2;
  const focus = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad];
  const fw = focus[2] - focus[0];
  const fh = focus[3] - focus[1];

  // Oscurece todo y devuelve la nitidez sólo dentro del recuadro.
  ctx.fillStyle = `rgba(0,0,0,${SCRIM})`;
  ctx.fillRect(0, 0, width, height);
  ctx.save();
  roundedPath(ctx, focus[0], focus[1], fw, fh, radius + pad);
  ctx.clip();
  ctx.drawImage(bitmap, 0, 0);
  ctx.restore();

  ctx.strokeStyle = HIGHLIGHT;
  ctx.lineWidth = border;
  roundedPath(ctx, focus[0], focus[1], fw, fh, radius + pad);
  ctx.stroke();

  const full = await toPng(canvas);
  const zoom = await buildZoom(bitmap, box, scale);
  bitmap.close();
  return { full, zoom, width, height };
}

async function buildZoom(bitmap, box, scale) {
  const w = box[2] - box[0];
  const h = box[3] - box[1];
  const marginX = Math.max(Math.round(60 * scale), Math.round(w * 0.45));
  const marginY = Math.max(Math.round(40 * scale), Math.round(h * 1.2));

  const crop = clampBox(
    [box[0] - marginX, box[1] - marginY, box[2] + marginX, box[3] + marginY],
    bitmap.width,
    bitmap.height
  );
  if (!crop) return null;

  const cw = crop[2] - crop[0];
  const ch = crop[3] - crop[1];
  const factor = Math.min(ZOOM_MAX_SCALE, Math.max(1, ZOOM_MIN_WIDTH / cw));
  const outW = Math.round(cw * factor);
  const outH = Math.round(ch * factor);

  const canvas = new OffscreenCanvas(outW, outH);
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(bitmap, crop[0], crop[1], cw, ch, 0, 0, outW, outH);

  const border = Math.max(BORDER_MIN, Math.round(2 * scale * factor));
  ctx.strokeStyle = HIGHLIGHT;
  ctx.lineWidth = border;
  roundedPath(
    ctx,
    (box[0] - crop[0]) * factor,
    (box[1] - crop[1]) * factor,
    w * factor,
    h * factor,
    Math.max(3, Math.round(4 * factor))
  );
  ctx.stroke();

  ctx.strokeStyle = "#d0d0d0";
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, outW - 1, outH - 1);

  return toPng(canvas);
}
