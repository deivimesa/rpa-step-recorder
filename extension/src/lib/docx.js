/**
 * Generador de .docx (OOXML) sin dependencias.
 * Reproduce el mismo documento que producía el exportador de Python:
 * portada, resumen de pasos y una página por paso con captura, zoom y datos técnicos.
 */

import { zip } from "./zip.js";
import { ACCENT_HEX, INK_HEX, MUTED_HEX, controlLabel, metadataRows, prettyDate, stepText, coverRows } from "./doc-common.js";

const EMU_PER_CM = 360000;
const CONTENT_CM = 16.0;
const ZOOM_CM = 9.0;
const FONT = "Calibri";

const esc = (text) =>
  String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

/** Word interpreta el salto de línea con <w:br/>, no con \n. */
function runs(text, props = "") {
  return String(text ?? "")
    .split("\n")
    .map((line, i) => `<w:r>${props}${i ? "<w:br/>" : ""}<w:t xml:space="preserve">${esc(line)}</w:t></w:r>`)
    .join("");
}

function rPr({ bold, size, color, font } = {}) {
  const parts = [];
  if (font) parts.push(`<w:rFonts w:ascii="${font}" w:hAnsi="${font}" w:cs="${font}"/>`);
  if (bold) parts.push("<w:b/>");
  if (color) parts.push(`<w:color w:val="${color}"/>`);
  if (size) parts.push(`<w:sz w:val="${Math.round(size * 2)}"/><w:szCs w:val="${Math.round(size * 2)}"/>`);
  return parts.length ? `<w:rPr>${parts.join("")}</w:rPr>` : "";
}

function para(content, { style, align, spaceBefore, spaceAfter, keepNext } = {}) {
  const pPr = [];
  if (style) pPr.push(`<w:pStyle w:val="${style}"/>`);
  if (keepNext) pPr.push("<w:keepNext/>");
  if (align) pPr.push(`<w:jc w:val="${align}"/>`);
  if (spaceBefore != null || spaceAfter != null) {
    pPr.push(`<w:spacing${spaceBefore != null ? ` w:before="${spaceBefore * 20}"` : ""}` +
             `${spaceAfter != null ? ` w:after="${spaceAfter * 20}"` : ""}/>`);
  }
  return `<w:p>${pPr.length ? `<w:pPr>${pPr.join("")}</w:pPr>` : ""}${content}</w:p>`;
}

const pageBreak = () => `<w:p><w:r><w:br w:type="page"/></w:r></w:p>`;

function image(relId, widthCm, heightCm, id, name) {
  const cx = Math.round(widthCm * EMU_PER_CM);
  const cy = Math.round(heightCm * EMU_PER_CM);
  return para(
    `<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">
      <wp:extent cx="${cx}" cy="${cy}"/>
      <wp:docPr id="${id}" name="${esc(name)}" descr="${esc(name)}"/>
      <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
        <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
          <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:nvPicPr><pic:cNvPr id="${id}" name="${esc(name)}"/><pic:cNvPicPr/></pic:nvPicPr>
            <pic:blipFill><a:blip r:embed="${relId}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
            <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm>
              <a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
          </pic:pic>
        </a:graphicData>
      </a:graphic>
    </wp:inline></w:drawing></w:r>`,
    { align: "center", spaceBefore: 6, spaceAfter: 6 }
  );
}

const MONO_LABELS = new Set(["Selector CSS", "XPath", "ID", "Name", "URL"]);

function cell(text, widthCm, opts = {}) {
  const shade = opts.shade ? `<w:shd w:val="clear" w:fill="${opts.shade}"/>` : "";
  const props = rPr({ bold: opts.bold, size: opts.size || 9.5, color: opts.color || INK_HEX, font: opts.font });
  const body = String(text ?? "")
    .split("\n")
    .map((line) => para(`<w:r>${props}<w:t xml:space="preserve">${esc(line)}</w:t></w:r>`, { spaceBefore: 3, spaceAfter: 3 }))
    .join("");
  return `<w:tc><w:tcPr><w:tcW w:w="${Math.round(widthCm * 567)}" w:type="dxa"/>` +
         `<w:vAlign w:val="center"/>${shade}</w:tcPr>${body}</w:tc>`;
}

function table(rows, widths, opts = {}) {
  const grid = widths.map((w) => `<w:gridCol w:w="${Math.round(w * 567)}"/>`).join("");
  const body = rows
    .map((cells) => `<w:tr>${cells.map((c, i) => cell(c.text, widths[i], c)).join("")}</w:tr>`)
    .join("");
  return `<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>` +
         `<w:tblW w:w="${Math.round(widths.reduce((a, b) => a + b, 0) * 567)}" w:type="dxa"/>` +
         `<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>${grid}</w:tblGrid>${body}</w:tbl>` +
         (opts.after === false ? "" : para(""));
}

function factsTable(rows, technical = false) {
  return table(
    rows.map(([label, value]) => [
      { text: label, bold: true, size: 9, color: MUTED_HEX, shade: "FAFAFA" },
      { text: value, size: technical ? 8.5 : 9.5, font: technical && MONO_LABELS.has(label) ? "Consolas" : null },
    ]),
    [4.4, 11.6]
  );
}

// ── el documento ────────────────────────────────────────────

function coverXml(session) {
  let out = para("") + para("") + para("");
  out += para(runs("DOCUMENTO DE DEFINICIÓN DE PROCESO (PDD)",
    rPr({ bold: true, size: 9, color: ACCENT_HEX })));
  out += para(runs(session.name, rPr({ bold: true, size: 28, color: ACCENT_HEX })),
    { style: "Heading1", spaceAfter: 4 });
  if (session.system) {
    out += para(runs(session.system, rPr({ size: 13, color: MUTED_HEX })));
  }
  out += `<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:color="DDDDDD"/></w:pBdr>` +
         `<w:spacing w:before="200" w:after="240"/></w:pPr></w:p>`;
  out += factsTable(coverRows(session));
  out += para(runs("Capturas y descripciones registradas automáticamente durante la ejecución manual del proceso.",
    `<w:rPr><w:i/><w:sz w:val="17"/><w:color w:val="${MUTED_HEX}"/></w:rPr>`));
  return out + pageBreak();
}

function summaryXml(session) {
  const rows = [[
    { text: "#", bold: true, size: 9.5, shade: "F2F2F2" },
    { text: "Acción", bold: true, size: 9.5, shade: "F2F2F2" },
  ]];
  for (const step of session.steps) {
    rows.push([
      { text: String(step.index), bold: true, size: 9.5, color: ACCENT_HEX },
      { text: stepText(step), size: 9.5 },
    ]);
  }
  return para(runs("Resumen de pasos", rPr({ bold: true, size: 13 })), { style: "Heading2" }) +
         table(rows, [1.6, 14.4]) + pageBreak();
}

function stepXml(step, media, idBase) {
  let out = "";
  out += para(
    runs(`Paso ${step.index}  `, rPr({ bold: true, size: 13, color: ACCENT_HEX })) +
      runs(stepText(step), rPr({ bold: true, size: 13 })),
    { style: "Heading2", keepNext: true }
  );
  if (step.title || step.url) {
    const context = [step.title, step.domain].filter(Boolean).join(" · ");
    out += para(runs(context, rPr({ size: 8.5, color: MUTED_HEX })), { keepNext: true });
  }
  if (media.full) {
    out += image(media.full.rel, CONTENT_CM, CONTENT_CM * (media.full.height / media.full.width), idBase, "Captura completa");
  }
  if (media.zoom) {
    out += para(runs("Detalle del elemento", rPr({ bold: true, size: 8.5, color: MUTED_HEX })),
      { spaceBefore: 8, spaceAfter: 2, keepNext: true });
    out += image(media.zoom.rel, ZOOM_CM, ZOOM_CM * (media.zoom.height / media.zoom.width), idBase + 1, "Detalle del elemento");
  }
  const rows = metadataRows(step);
  if (rows.length) {
    out += para(runs("Datos técnicos", rPr({ bold: true, size: 11, color: MUTED_HEX })),
      { style: "Heading3", keepNext: true });
    out += factsTable(rows, true);
  }
  return out;
}

const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults><w:rPrDefault><w:rPr>
    <w:rFonts w:ascii="${FONT}" w:hAnsi="${FONT}" w:eastAsia="${FONT}" w:cs="${FONT}"/>
    <w:sz w:val="21"/><w:szCs w:val="21"/><w:color w:val="${INK_HEX}"/>
  </w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/><w:keepNext/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/><w:keepNext/>
    <w:spacing w:before="280" w:after="120"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="2"/><w:keepNext/>
    <w:spacing w:before="160" w:after="80"/></w:pPr></w:style>
  <w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>
    <w:tblPr><w:tblBorders>
      <w:top w:val="single" w:sz="4" w:color="DDDDDD"/><w:left w:val="single" w:sz="4" w:color="DDDDDD"/>
      <w:bottom w:val="single" w:sz="4" w:color="DDDDDD"/><w:right w:val="single" w:sz="4" w:color="DDDDDD"/>
      <w:insideH w:val="single" w:sz="4" w:color="DDDDDD"/><w:insideV w:val="single" w:sz="4" w:color="DDDDDD"/>
    </w:tblBorders></w:tblPr></w:style>
</w:styles>`;

function footerXml(session) {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p><w:pPr><w:jc w:val="center"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="16"/><w:color w:val="${MUTED_HEX}"/></w:rPr>
      <w:t xml:space="preserve">${esc(session.name)}  ·  Página </w:t></w:r>
    <w:r><w:rPr><w:sz w:val="16"/><w:color w:val="${MUTED_HEX}"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText xml:space="preserve">PAGE</w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r>
  </w:p></w:ftr>`;
}

/**
 * @param {object} session  { name, author, system, started_at, steps: [...] }
 * @param {Map<string, {bytes: Uint8Array, width: number, height: number}>} images
 *   indexadas por el nombre de archivo que referencia cada paso.
 * @returns {Promise<Blob>}
 */
export async function buildDocx(session, images) {
  const media = [];
  const rels = [
    `<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`,
    `<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>`,
  ];

  const register = (key) => {
    const asset = images.get(key);
    if (!asset) return null;
    const index = media.length + 1;
    const name = `image${index}.png`;
    media.push({ name, bytes: asset.bytes });
    rels.push(
      `<Relationship Id="rIdImg${index}" ` +
      `Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/${name}"/>`
    );
    return { rel: `rIdImg${index}`, width: asset.width, height: asset.height };
  };

  let body = coverXml(session) + summaryXml(session);
  body += para(runs("Detalle del proceso", rPr({ bold: true, size: 13 })), { style: "Heading2" });

  session.steps.forEach((step, position) => {
    if (position) body += pageBreak();
    body += stepXml(step, { full: register(step.full_image), zoom: register(step.zoom_image) }, 100 + position * 2);
  });

  const document = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <w:body>${body}
    <w:sectPr>
      <w:footerReference w:type="default" r:id="rIdFooter"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1247" w:right="1417" w:bottom="1134" w:left="1417" w:header="708" w:footer="708"/>
    </w:sectPr>
  </w:body></w:document>`;

  const files = [
    {
      name: "[Content_Types].xml",
      data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>`,
    },
    {
      name: "_rels/.rels",
      data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>`,
    },
    {
      name: "docProps/core.xml",
      data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>${esc(session.name)}</dc:title>
  <dc:creator>${esc(session.author || "RPA Step Recorder")}</dc:creator>
  <dc:subject>Documento de definición de proceso (PDD)</dc:subject>
  <dcterms:created xsi:type="dcterms:W3CDTF">${new Date().toISOString().slice(0, 19)}Z</dcterms:created>
</cp:coreProperties>`,
    },
    { name: "word/document.xml", data: document },
    { name: "word/styles.xml", data: STYLES },
    { name: "word/footer1.xml", data: footerXml(session) },
    {
      name: "word/_rels/document.xml.rels",
      data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels.join("")}</Relationships>`,
    },
    // Los PNG ya están comprimidos: almacenarlos evita recomprimir sin ganancia.
    ...media.map((m) => ({ name: `word/media/${m.name}`, data: m.bytes, store: true })),
  ];

  return zip(files, "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
}
