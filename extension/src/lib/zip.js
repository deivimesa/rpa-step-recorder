/**
 * Escritor de ZIP mínimo. Un .docx no es más que un ZIP con XML dentro,
 * así que con esto y CompressionStream (nativo en Chrome) no hace falta
 * ninguna librería externa: la extensión no carga código remoto.
 */

const TEXT = new TextEncoder();

// Tabla CRC-32 (polinomio 0xEDB88320), la que exige el formato ZIP.
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

export function crc32(bytes) {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

async function deflateRaw(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Fecha y hora en el formato empaquetado de MS-DOS que usa el ZIP. */
function dosStamp(date) {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
  const day = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, day };
}

class Writer {
  constructor() {
    this.parts = [];
    this.length = 0;
  }
  push(bytes) {
    this.parts.push(bytes);
    this.length += bytes.length;
  }
  u16(value) {
    const b = new Uint8Array(2);
    new DataView(b.buffer).setUint16(0, value, true);
    this.push(b);
  }
  u32(value) {
    const b = new Uint8Array(4);
    new DataView(b.buffer).setUint32(0, value >>> 0, true);
    this.push(b);
  }
  blob(type) {
    return new Blob(this.parts, { type });
  }
}

/**
 * @param {Array<{name: string, data: Uint8Array|string, store?: boolean}>} files
 *   `store: true` guarda sin comprimir (útil para PNG, que ya vienen comprimidos).
 * @returns {Promise<Blob>}
 */
export async function zip(files, mime = "application/zip") {
  const out = new Writer();
  const entries = [];
  const stamp = dosStamp(new Date());

  for (const file of files) {
    const raw = typeof file.data === "string" ? TEXT.encode(file.data) : file.data;
    const store = Boolean(file.store);
    const body = store ? raw : await deflateRaw(raw);
    const name = TEXT.encode(file.name);
    const offset = out.length;

    out.u32(0x04034b50);           // firma de cabecera local
    out.u16(20);                   // versión necesaria
    out.u16(0x0800);               // bit 11: nombres en UTF-8
    out.u16(store ? 0 : 8);        // método: 0 almacenar, 8 deflate
    out.u16(stamp.time);
    out.u16(stamp.day);
    out.u32(crc32(raw));
    out.u32(body.length);
    out.u32(raw.length);
    out.u16(name.length);
    out.u16(0);                    // sin campo extra
    out.push(name);
    out.push(body);

    entries.push({ name, offset, crc: crc32(raw), packed: body.length, raw: raw.length, store });
  }

  const centralStart = out.length;
  for (const entry of entries) {
    out.u32(0x02014b50);           // firma de cabecera central
    out.u16(0x031e);               // creado en UNIX, versión 3.0
    out.u16(20);
    out.u16(0x0800);
    out.u16(entry.store ? 0 : 8);
    out.u16(stamp.time);
    out.u16(stamp.day);
    out.u32(entry.crc);
    out.u32(entry.packed);
    out.u32(entry.raw);
    out.u16(entry.name.length);
    out.u16(0);                    // extra
    out.u16(0);                    // comentario
    out.u16(0);                    // número de disco
    out.u16(0);                    // atributos internos
    out.u32(0);                    // atributos externos
    out.u32(entry.offset);
    out.push(entry.name);
  }

  const centralSize = out.length - centralStart;

  out.u32(0x06054b50);             // fin del directorio central
  out.u16(0);                      // disco actual
  out.u16(0);                      // disco del directorio
  out.u16(entries.length);
  out.u16(entries.length);
  out.u32(centralSize);
  out.u32(centralStart);
  out.u16(0);                      // comentario

  return out.blob(mime);
}
