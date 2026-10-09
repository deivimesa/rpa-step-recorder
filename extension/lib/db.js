/**
 * Almacén local en IndexedDB.
 * Las capturas pesan más de 1 MB cada una, así que no caben en chrome.storage
 * (tope de 10 MB): van aquí, con el permiso `unlimitedStorage`.
 */

const DB_NAME = "rpa-step-recorder";
const DB_VERSION = 1;
const SESSIONS = "sessions";
const IMAGES = "images";

let connection = null;

function open() {
  if (connection) return connection;
  connection = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(SESSIONS)) {
        db.createObjectStore(SESSIONS, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(IMAGES)) {
        // clave: `${sessionId}/${nombre}`
        db.createObjectStore(IMAGES);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return connection;
}

async function tx(store, mode, work) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(store, mode);
    const result = work(transaction.objectStore(store));
    // Ojo: para una clave inexistente, request.result es undefined. Comprobar
    // el tipo (y no la verdad del valor) evita devolver el propio IDBRequest.
    transaction.oncomplete = () => resolve(result instanceof IDBRequest ? result.result : result);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

export const saveSession = (session) => tx(SESSIONS, "readwrite", (s) => s.put(session));
export const getSession = (id) => tx(SESSIONS, "readonly", (s) => s.get(id));
export const deleteSession = (id) => tx(SESSIONS, "readwrite", (s) => s.delete(id));

export const listSessions = async () => {
  const all = await tx(SESSIONS, "readonly", (s) => s.getAll());
  return (all || []).sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
};

export const putImage = (sessionId, name, bytes) =>
  tx(IMAGES, "readwrite", (s) => s.put(bytes, `${sessionId}/${name}`));

export const getImage = async (sessionId, name) =>
  tx(IMAGES, "readonly", (s) => s.get(`${sessionId}/${name}`));

export async function deleteImages(sessionId, names) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(IMAGES, "readwrite");
    const store = transaction.objectStore(IMAGES);
    for (const name of names) store.delete(`${sessionId}/${name}`);
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error);
  });
}

/** Carga todas las imágenes de una sesión, listas para el exportador. */
export async function loadImages(session) {
  const out = new Map();
  for (const step of session.steps) {
    for (const name of [step.full_image, step.zoom_image]) {
      if (!name || out.has(name)) continue;
      const bytes = await getImage(session.id, name);
      if (bytes) out.set(name, { bytes: new Uint8Array(bytes) });
    }
  }
  return out;
}

/** Espacio ocupado, para avisar antes de que el disco se llene. */
export async function usage() {
  if (!navigator.storage || !navigator.storage.estimate) return null;
  const { usage: used = 0, quota = 0 } = await navigator.storage.estimate();
  return { used, quota };
}
