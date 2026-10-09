/** Textos y tablas que comparten el generador de Word y el de PDF. */

export const ACCENT_HEX = "D62D2D";
export const INK_HEX = "1A1A1A";
export const MUTED_HEX = "6B6B6B";
export const RULE_HEX = "DDDDDD";

export const DOC_SUBTITLE = "Documento de definición de proceso (PDD)";

// El documento lo lee gente de negocio: el tipo de control va en español.
const CONTROL_ES = {
  button: "Botón",
  link: "Enlace",
  checkbox: "Casilla de verificación",
  radio: "Botón de opción",
  combobox: "Lista desplegable",
  select: "Lista desplegable",
  textbox: "Campo de texto",
  tab: "Pestaña",
  menuitem: "Opción de menú",
  option: "Opción",
  img: "Imagen",
  a: "Enlace",
  input: "Campo",
  div: "Área de la pantalla",
  span: "Texto",
  td: "Celda de tabla",
  li: "Elemento de lista",
};

const INPUT_TYPE_ES = {
  password: "contraseña",
  email: "correo",
  number: "número",
  date: "fecha",
  file: "archivo",
  search: "búsqueda",
  tel: "teléfono",
};

export function controlLabel(element) {
  if (!element) return "Elemento";
  const base =
    CONTROL_ES[element.role] ||
    CONTROL_ES[element.tag] ||
    ((element.tag || "Elemento").charAt(0).toUpperCase() + (element.tag || "lemento").slice(1));
  const detail = INPUT_TYPE_ES[(element.type || "").toLowerCase()];
  return detail ? `${base} (${detail})` : base;
}

export function prettyDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} ` +
         `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function domainOf(url) {
  if (!url) return "";
  return String(url).split("://").pop().split("/")[0];
}

export function stepText(step) {
  return (step.description || step.suggestion || `Paso ${step.index}`).trim();
}

export function duration(session) {
  if (!session.started_at || !session.finished_at) return "";
  const total = Math.max(0, Math.round((Date.parse(session.finished_at) - Date.parse(session.started_at)) / 1000));
  if (!total) return "";
  const minutes = Math.floor(total / 60);
  return minutes ? `${minutes} min ${total % 60} s` : `${total} s`;
}

export function coverRows(session) {
  const rows = [
    ["Proceso", session.name],
    ["Sistema / aplicación", session.system || "—"],
    ["Autor", session.author || "—"],
    ["Fecha de grabación", prettyDate(session.started_at) || "—"],
    ["Total de pasos", String(session.steps.length)],
  ];
  const span = duration(session);
  if (span) rows.push(["Duración de la grabación", span]);

  const origins = [];
  for (const step of session.steps) {
    const origin = domainOf(step.url);
    if (origin && !origins.includes(origin)) origins.push(origin);
  }
  if (origins.length) rows.push(["Origen", origins.slice(0, 3).join("\n")]);
  return rows;
}

/** Datos técnicos que necesita quien programa el bot. */
export function metadataRows(step) {
  const element = step.element;
  const rows = [];
  if (element) {
    rows.push(["Elemento", controlLabel(element)]);
    if (element.text) rows.push(["Texto visible", element.text]);
  }
  // Lo que el bot tendrá que escribir o elegir.
  if (step.secret) {
    rows.push(["Valor", "(contraseña — no se guarda)"]);
  } else if (step.value) {
    rows.push([step.kind === "select" ? "Opción elegida" : "Valor escrito", step.value]);
  }
  if (element) {
    if (element.id) rows.push(["ID", element.id]);
    if (element.name) rows.push(["Name", element.name]);
    if (element.css) rows.push(["Selector CSS", element.css]);
    if (element.xpath) rows.push(["XPath", element.xpath]);
  }
  if (step.url) rows.push(["URL", step.url]);
  rows.push(["Registrado", prettyDate(step.timestamp)]);
  return rows;
}

/** Nombre de archivo seguro en Windows y macOS. */
export function slugify(text, fallback = "proceso") {
  const ascii = String(text || "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "");
  const slug = ascii.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase();
  return slug.slice(0, 60) || fallback;
}
