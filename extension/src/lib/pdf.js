/**
 * Generador de PDF sin dependencias.
 * Usa las fuentes base-14 (Helvetica), que todo lector trae, y empotra las
 * capturas como imágenes RGB comprimidas con Flate (CompressionStream nativo).
 */

import {
  ACCENT_HEX, INK_HEX, MUTED_HEX, RULE_HEX,
  DOC_SUBTITLE, coverRows, domainOf, metadataRows, stepText,
} from "./doc-common.js";

const PAGE_W = 595.28;   // A4 en puntos
const PAGE_H = 841.89;
const MARGIN = 56.7;     // 20 mm
const CONTENT_W = PAGE_W - 2 * MARGIN;
const FOOTER_Y = 31;
const BOTTOM = 62;       // límite inferior del contenido

const MONO_LABELS = new Set(["Selector CSS", "XPath", "ID", "Name", "URL"]);

const rgb = (hex) => {
  const n = parseInt(hex, 16);
  return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
};
const ACCENT = rgb(ACCENT_HEX);
const INK = rgb(INK_HEX);
const MUTED = rgb(MUTED_HEX);
const RULE = rgb(RULE_HEX);

// ── texto ───────────────────────────────────────────────────

/** Codifica a WinAnsi (CP1252), que es lo que declaran las fuentes base-14. */
const WINANSI_EXTRA = {
  "€": 0x80, "‚": 0x82, "ƒ": 0x83, "„": 0x84, "…": 0x85, "†": 0x86, "‡": 0x87,
  "ˆ": 0x88, "‰": 0x89, "Š": 0x8a, "‹": 0x8b, "Œ": 0x8c, "Ž": 0x8e, "‘": 0x91,
  "’": 0x92, "“": 0x93, "”": 0x94, "•": 0x95, "–": 0x96, "—": 0x97, "˜": 0x98,
  "™": 0x99, "š": 0x9a, "›": 0x9b, "œ": 0x9c, "ž": 0x9e, "Ÿ": 0x9f,
};

function winAnsi(text) {
  let out = "";
  for (const ch of String(text ?? "")) {
    const code = WINANSI_EXTRA[ch] ?? ch.codePointAt(0);
    out += code <= 0xff ? String.fromCharCode(code) : "?";
  }
  return out;
}

const escapePdf = (text) => winAnsi(text).replace(/[\\()]/g, (c) => "\\" + c);

/** Un byte por carácter. Escribir con TextEncoder rompería los acentos,
    porque el PDF declara WinAnsiEncoding, no UTF-8. */
function latin1(text) {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) out[i] = text.charCodeAt(i) & 0xff;
  return out;
}

/** Ancho del texto medido con el canvas: Arial y Helvetica comparten métricas. */
let measurer = null;
function textWidth(text, size, bold, mono) {
  if (!measurer) measurer = new OffscreenCanvas(8, 8).getContext("2d");
  const family = mono ? "Courier, monospace" : "Helvetica, Arial, sans-serif";
  measurer.font = `${bold ? "bold " : ""}${size}px ${family}`;
  return measurer.measureText(winAnsi(text)).width;
}

function wrap(text, maxWidth, size, bold, mono) {
  const lines = [];
  for (const paragraph of String(text ?? "").split("\n")) {
    let line = "";
    for (const word of paragraph.split(/\s+/)) {
      const candidate = line ? line + " " + word : word;
      if (line && textWidth(candidate, size, bold, mono) > maxWidth) {
        lines.push(line);
        line = word;
        // Una palabra sola más ancha que la columna (una URL, un XPath) se parte.
        while (textWidth(line, size, bold, mono) > maxWidth && line.length > 1) {
          let cut = line.length - 1;
          while (cut > 1 && textWidth(line.slice(0, cut), size, bold, mono) > maxWidth) cut -= 1;
          lines.push(line.slice(0, cut));
          line = line.slice(cut);
        }
      } else {
        line = candidate;
      }
    }
    lines.push(line);
  }
  return lines;
}

// ── imágenes ────────────────────────────────────────────────

async function deflate(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Convierte un PNG en un XObject de imagen RGB, reduciéndolo si hace falta. */
async function toImageObject(pngBytes, maxWidth) {
  const bitmap = await createImageBitmap(new Blob([pngBytes], { type: "image/png" }));
  const scale = Math.min(1, maxWidth / bitmap.width);
  const width = Math.max(1, Math.round(bitmap.width * scale));
  const height = Math.max(1, Math.round(bitmap.height * scale));

  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();

  const rgba = ctx.getImageData(0, 0, width, height).data;
  const rgbBytes = new Uint8Array(width * height * 3);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) {
    rgbBytes[j] = rgba[i];
    rgbBytes[j + 1] = rgba[i + 1];
    rgbBytes[j + 2] = rgba[i + 2];
  }
  return { width, height, data: await deflate(rgbBytes) };
}

// ── documento ───────────────────────────────────────────────

class Pdf {
  constructor(title) {
    this.title = title;
    this.objects = [];          // cada entrada: Uint8Array o string
    this.pages = [];
    this.images = [];
    this.ops = [];              // operadores de la página en curso
    this.y = 0;
  }

  add(body) {
    this.objects.push(body);
    return this.objects.length;  // los números de objeto empiezan en 1
  }

  // -- dibujo -----------------------------------------------

  newPage() {
    if (this.ops.length) this.flushPage();
    this.ops = [];
    this.y = PAGE_H - MARGIN;
    this.pageImages = [];
  }

  flushPage() {
    this.pages.push({ ops: this.ops.join("\n"), images: this.pageImages });
    this.ops = [];
  }

  space(amount) {
    this.y -= amount;
  }

  ensure(needed) {
    if (this.y - needed < BOTTOM) {
      this.flushPage();
      this.ops = [];
      this.y = PAGE_H - MARGIN;
      this.pageImages = [];
      return true;
    }
    return false;
  }

  text(content, { size = 9.5, bold = false, mono = false, color = INK, x = MARGIN, leading } = {}) {
    const step = leading || size * 1.35;
    const font = mono ? "/F3" : bold ? "/F2" : "/F1";
    for (const line of String(content).split("\n")) {
      this.ensure(step);
      this.y -= step;
      this.ops.push(
        `BT ${font} ${size} Tf ${color.join(" ")} rg ${x.toFixed(2)} ${this.y.toFixed(2)} Td (${escapePdf(line)}) Tj ET`
      );
    }
  }

  paragraph(content, opts = {}) {
    const width = opts.width || CONTENT_W;
    const lines = wrap(content, width, opts.size || 9.5, opts.bold, opts.mono);
    this.text(lines.join("\n"), opts);
  }

  line(y, x0 = MARGIN, x1 = PAGE_W - MARGIN, color = RULE, weight = 0.6) {
    this.ops.push(
      `${color.join(" ")} RG ${weight} w ${x0.toFixed(2)} ${y.toFixed(2)} m ${x1.toFixed(2)} ${y.toFixed(2)} l S`
    );
  }

  box(x, y, w, h, { fill, stroke, weight = 0.4 } = {}) {
    let op = "";
    if (fill) op += `${fill.join(" ")} rg `;
    if (stroke) op += `${stroke.join(" ")} RG ${weight} w `;
    op += `${x.toFixed(2)} ${y.toFixed(2)} ${w.toFixed(2)} ${h.toFixed(2)} re `;
    op += fill && stroke ? "B" : fill ? "f" : "S";
    this.ops.push(op);
  }

  image(entry, maxW, maxH) {
    const ratio = Math.min(maxW / entry.width, maxH / entry.height);
    const w = entry.width * ratio;
    const h = entry.height * ratio;
    this.ensure(h + 8);
    this.y -= h + 4;
    const x = MARGIN + (CONTENT_W - w) / 2;
    this.ops.push(`q ${w.toFixed(2)} 0 0 ${h.toFixed(2)} ${x.toFixed(2)} ${this.y.toFixed(2)} cm /Img${entry.id} Do Q`);
    if (!this.pageImages.includes(entry.id)) this.pageImages.push(entry.id);
    this.space(4);
  }

  /** Tabla de dos columnas con ajuste de línea y corte entre páginas. */
  facts(rows, { labelWidth = 119, technical = false } = {}) {
    const pad = 5;
    const valueWidth = CONTENT_W - labelWidth - pad * 2;
    for (const [label, value] of rows) {
      const mono = technical && MONO_LABELS.has(label);
      const size = technical ? 8.5 : 9.5;
      const labelLines = wrap(label, labelWidth - pad * 2, 8, true);
      const valueLines = wrap(value, valueWidth, size, false, mono);
      const rowH = Math.max(labelLines.length, valueLines.length) * (size * 1.32) + pad * 2;

      this.ensure(rowH);
      const top = this.y;
      this.box(MARGIN, top - rowH, labelWidth, rowH, { fill: [0.98, 0.98, 0.98], stroke: RULE });
      this.box(MARGIN + labelWidth, top - rowH, CONTENT_W - labelWidth, rowH, { stroke: RULE });

      let ly = top - pad;
      for (const line of labelLines) {
        ly -= 8 * 1.32;
        this.ops.push(`BT /F2 8 Tf ${MUTED.join(" ")} rg ${(MARGIN + pad).toFixed(2)} ${ly.toFixed(2)} Td (${escapePdf(line)}) Tj ET`);
      }
      let vy = top - pad;
      for (const line of valueLines) {
        vy -= size * 1.32;
        this.ops.push(
          `BT ${mono ? "/F3" : "/F1"} ${size} Tf ${INK.join(" ")} rg ` +
          `${(MARGIN + labelWidth + pad).toFixed(2)} ${vy.toFixed(2)} Td (${escapePdf(line)}) Tj ET`
        );
      }
      this.y = top - rowH;
    }
    this.space(8);
  }

  // -- serialización ----------------------------------------

  async build() {
    if (this.ops.length) this.flushPage();

    const fonts = {
      F1: this.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"),
      F2: this.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"),
      F3: this.add("<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"),
    };

    const imageRefs = new Map();
    for (const img of this.images) {
      const header =
        `<< /Type /XObject /Subtype /Image /Width ${img.width} /Height ${img.height} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length ${img.data.length} >>`;
      imageRefs.set(img.id, this.add({ dict: header, stream: img.data }));
    }

    const pagesRef = this.objects.length + 1 + this.pages.length * 2;
    const pageRefs = [];
    this.pages.forEach((page, index) => {
      const footer =
        `BT /F1 7.5 Tf ${MUTED.join(" ")} rg ` +
        `${(PAGE_W / 2 - textWidth(`${this.title}  ·  Página ${index + 1}`, 7.5) / 2).toFixed(2)} ${FOOTER_Y} Td ` +
        `(${escapePdf(`${this.title}  ·  Página ${index + 1}`)}) Tj ET`;
      const rule = index === 0 ? "" :
        `${RULE.join(" ")} RG 0.4 w ${MARGIN} 42.5 m ${(PAGE_W - MARGIN).toFixed(2)} 42.5 l S`;
      const content = index === 0 ? page.ops : `${page.ops}\n${rule}\n${footer}`;
      const bytes = latin1(content);
      const contentRef = this.add({ dict: `<< /Length ${bytes.length} >>`, stream: bytes });

      const xobjects = page.images.map((id) => `/Img${id} ${imageRefs.get(id)} 0 R`).join(" ");
      pageRefs.push(
        this.add(
          `<< /Type /Page /Parent ${pagesRef} 0 R /MediaBox [0 0 ${PAGE_W} ${PAGE_H}] ` +
          `/Resources << /Font << /F1 ${fonts.F1} 0 R /F2 ${fonts.F2} 0 R /F3 ${fonts.F3} 0 R >> ` +
          `${xobjects ? `/XObject << ${xobjects} >>` : ""} >> /Contents ${contentRef} 0 R >>`
        )
      );
    });

    const pages = this.add(
      `<< /Type /Pages /Count ${pageRefs.length} /Kids [${pageRefs.map((r) => `${r} 0 R`).join(" ")}] >>`
    );
    const info = this.add(
      `<< /Title (${escapePdf(this.title)}) /Subject (${escapePdf(DOC_SUBTITLE)}) ` +
      `/Producer (RPA Step Recorder) >>`
    );
    const catalog = this.add(`<< /Type /Catalog /Pages ${pages} 0 R >>`);

    return this.serialize(catalog, info);
  }

  serialize(catalog, info) {
    const chunks = [];
    let offset = 0;
    const push = (data) => {
      const bytes = typeof data === "string" ? latin1(data) : data;
      chunks.push(bytes);
      offset += bytes.length;
    };

    push("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n");
    const offsets = [0];
    this.objects.forEach((body, index) => {
      offsets.push(offset);
      push(`${index + 1} 0 obj\n`);
      if (typeof body === "string") {
        push(body + "\n");
      } else {
        push(body.dict + "\nstream\n");
        push(body.stream);
        push("\nendstream\n");
      }
      push("endobj\n");
    });

    const xref = offset;
    let table = `xref\n0 ${this.objects.length + 1}\n0000000000 65535 f \n`;
    for (let i = 1; i <= this.objects.length; i += 1) {
      table += String(offsets[i]).padStart(10, "0") + " 00000 n \n";
    }
    push(table);
    push(`trailer\n<< /Size ${this.objects.length + 1} /Root ${catalog} 0 R /Info ${info} 0 R >>\n`);
    push(`startxref\n${xref}\n%%EOF\n`);

    return new Blob(chunks, { type: "application/pdf" });
  }
}

/**
 * @param {object} session
 * @param {Map<string, {bytes: Uint8Array}>} images
 * @returns {Promise<Blob>}
 */
export async function buildPdf(session, images) {
  const pdf = new Pdf(session.name);
  const cache = new Map();
  let nextId = 1;

  const place = async (key, maxPixels) => {
    if (!key) return null;
    if (cache.has(key)) return cache.get(key);
    const asset = images.get(key);
    if (!asset) return null;
    const entry = await toImageObject(asset.bytes, maxPixels);
    entry.id = nextId++;
    pdf.images.push(entry);
    cache.set(key, entry);
    return entry;
  };

  // Portada
  pdf.newPage();
  pdf.space(120);
  pdf.text(DOC_SUBTITLE.toUpperCase(), { size: 8, bold: true, color: ACCENT });
  pdf.space(6);
  pdf.paragraph(session.name, { size: 26, bold: true, color: ACCENT, leading: 30 });
  if (session.system) {
    pdf.space(2);
    pdf.paragraph(session.system, { size: 12, color: MUTED });
  }
  pdf.space(10);
  pdf.line(pdf.y);
  pdf.space(14);
  pdf.facts(coverRows(session));
  pdf.space(4);
  pdf.text("Capturas y descripciones registradas automáticamente durante", { size: 8, color: MUTED });
  pdf.text("la ejecución manual del proceso.", { size: 8, color: MUTED });

  // Resumen
  pdf.newPage();
  pdf.text("Resumen de pasos", { size: 13, bold: true });
  pdf.space(8);
  pdf.facts(session.steps.map((s) => [String(s.index), stepText(s)]), { labelWidth: 40 });

  // Detalle: una página por paso, para que la ficha técnica no quede huérfana.
  for (const step of session.steps) {
    pdf.newPage();
    pdf.text(`Paso ${step.index}`, { size: 12.5, bold: true, color: ACCENT });
    pdf.space(1);
    pdf.paragraph(stepText(step), { size: 12.5, bold: true, leading: 16 });
    const context = [step.title, domainOf(step.url)].filter(Boolean).join(" · ");
    if (context) {
      pdf.space(1);
      pdf.paragraph(context, { size: 8, color: MUTED });
    }
    pdf.space(6);

    const full = await place(step.full_image, 1500);
    if (full) pdf.image(full, CONTENT_W, 300);
    const zoom = await place(step.zoom_image, 1000);
    if (zoom) {
      pdf.space(6);
      pdf.text("Detalle del elemento", { size: 8, bold: true, color: MUTED });
      pdf.space(2);
      pdf.image(zoom, CONTENT_W * 0.62, 110);
    }

    const rows = metadataRows(step);
    if (rows.length) {
      pdf.space(8);
      pdf.text("Datos técnicos", { size: 9, bold: true, color: MUTED });
      pdf.space(4);
      pdf.facts(rows, { technical: true });
    }
  }

  return pdf.build();
}
