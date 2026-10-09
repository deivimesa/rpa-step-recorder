/**
 * Service worker: toda la lógica vive aquí. Captura la pantalla, anota el
 * elemento, guarda el paso en IndexedDB y genera los documentos.
 * No necesita ningún servidor ni conexión a internet.
 */

import { annotate } from "./lib/annotate.js";
import * as db from "./lib/db.js";
import { domainOf } from "./lib/doc-common.js";

const state = {
  sessionId: null,
  recording: false,
  paused: false,
  pending: null,
};

// ── utilidades ──────────────────────────────────────────────

const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

async function persist() {
  await chrome.storage.session.set({ pending: state.pending });
  await chrome.storage.local.set({
    sessionId: state.sessionId,
    recording: state.recording,
    paused: state.paused,
  });
}

async function restore() {
  const local = await chrome.storage.local.get(["sessionId", "recording", "paused"]);
  const ephemeral = await chrome.storage.session.get(["pending"]);
  state.sessionId = local.sessionId || null;
  state.recording = Boolean(local.recording);
  state.paused = Boolean(local.paused);
  state.pending = ephemeral.pending || null;
  if (state.sessionId && !(await db.getSession(state.sessionId))) {
    state.sessionId = null;
    state.recording = false;
  }
  setBadge();
}

async function currentSession() {
  return state.sessionId ? db.getSession(state.sessionId) : null;
}

async function setBadge() {
  const session = await currentSession();
  const count = session ? session.steps.length : 0;
  const text = !state.recording ? "" : state.paused ? "❙❙" : String(count || "REC");
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color: state.paused ? "#6b6b6b" : "#b91c1c" });
}

const notifyPopup = () => chrome.runtime.sendMessage({ type: "STATE_CHANGED" }).catch(() => {});

async function tellTab(tabId, message) {
  try {
    await chrome.tabs.sendMessage(tabId, message);
  } catch (err) {
    /* la pestaña puede estar navegando o ser interna del navegador */
  }
}

async function notifyAllTabs(message) {
  const tabs = await chrome.tabs.query({});
  await Promise.all(tabs.filter((t) => t.id != null).map((t) => tellTab(t.id, message)));
}

// ── sesión ──────────────────────────────────────────────────

async function startSession({ name, author, system }) {
  const now = new Date();
  const title = (name || "").trim() || `Proceso ${now.toLocaleDateString("es")} ${now.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}`;
  const session = {
    id: uid(),
    name: title,
    author: (author || "").trim(),
    system: (system || "").trim(),
    started_at: now.toISOString(),
    finished_at: "",
    steps: [],
  };
  await db.saveSession(session);
  await chrome.storage.local.set({ author: session.author, system: session.system });

  state.sessionId = session.id;
  state.recording = true;
  state.paused = false;
  state.pending = null;
  await persist();
  await setBadge();
  notifyPopup();
  await notifyAllTabs({ type: "RECORDING_STATE", recording: true, paused: false });
  return session;
}

async function setPaused(paused) {
  state.paused = Boolean(paused);
  state.pending = null;
  await persist();
  await setBadge();
  notifyPopup();
  await notifyAllTabs({ type: "RECORDING_STATE", recording: state.recording, paused: state.paused });
  return state.paused;
}

/** Reabre una grabación ya detenida para seguir añadiendo pasos. */
async function resumeSession(sessionId) {
  const session = await db.getSession(sessionId);
  if (!session) throw new Error("Esa grabación ya no existe");
  session.finished_at = "";
  await db.saveSession(session);
  state.sessionId = session.id;
  state.recording = true;
  state.paused = false;
  state.pending = null;
  await persist();
  await setBadge();
  notifyPopup();
  await notifyAllTabs({ type: "RECORDING_STATE", recording: true, paused: false });
  return session;
}

async function stopSession() {
  const session = await currentSession();
  if (session) {
    session.finished_at = new Date().toISOString();
    await db.saveSession(session);
  }
  state.recording = false;
  state.paused = false;
  state.pending = null;
  await persist();
  await setBadge();
  notifyPopup();
  await notifyAllTabs({ type: "RECORDING_STATE", recording: false, paused: false });
  return session;
}

// ── pasos ───────────────────────────────────────────────────

/** captureVisibleTab está limitado por segundo; se reintenta con margen. */
async function captureTab(windowId) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await chrome.tabs.captureVisibleTab(windowId, { format: "png" });
    } catch (err) {
      if (attempt === 2) throw err;
      await new Promise((resolve) => setTimeout(resolve, 260));
    }
  }
  return null;
}

async function recordStep(payload, sender) {
  if (!state.recording || state.paused) return { ok: false, reason: "not-recording" };
  const session = await currentSession();
  if (!session) return { ok: false, reason: "no-session" };

  const tab = sender.tab;
  const dataUrl = await captureTab(tab ? tab.windowId : undefined);
  if (!dataUrl) throw new Error("No se pudo capturar la pantalla");

  const screenshot = await (await fetch(dataUrl)).blob();
  const rect = payload.element ? payload.element.rect : null;
  const art = await annotate(screenshot, rect, payload.dpr || 1);

  const index = session.steps.length + 1;
  const base = `paso-${String(index).padStart(3, "0")}`;
  await db.putImage(session.id, `${base}.png`, art.full);
  if (art.zoom) await db.putImage(session.id, `${base}-zoom.png`, art.zoom);

  const step = {
    id: uid(),
    index,
    kind: payload.kind || "click",
    suggestion: (payload.suggestion || "").trim(),
    description: (payload.suggestion || "").trim(),
    url: payload.url || (tab && tab.url) || "",
    title: payload.title || (tab && tab.title) || "",
    domain: domainOf(payload.url || (tab && tab.url) || ""),
    timestamp: new Date().toISOString(),
    value: payload.value || "",
    secret: Boolean(payload.secret),
    element: payload.element || null,
    full_image: `${base}.png`,
    zoom_image: art.zoom ? `${base}-zoom.png` : "",
  };
  session.steps.push(step);
  await db.saveSession(session);

  state.pending = {
    id: step.id,
    index,
    suggestion: step.description,
    label: payload.label || null,
    rect,
  };
  await persist();
  await setBadge();
  notifyPopup();
  if (tab) await tellTab(tab.id, { type: "SHOW_PROMPT", pending: state.pending });
  return { ok: true };
}

async function describeStep(id, description) {
  const session = await currentSession();
  if (!session) return;
  const step = session.steps.find((s) => s.id === id);
  if (!step) return;
  step.description = (description || "").trim() || step.suggestion;
  await db.saveSession(session);
  if (state.pending && state.pending.id === id) {
    state.pending = null;
    await persist();
  }
  notifyPopup();
}

async function deleteStep(id, sessionId) {
  const session = sessionId ? await db.getSession(sessionId) : await currentSession();
  if (!session) return;
  const position = session.steps.findIndex((s) => s.id === id);
  if (position < 0) return;
  const [removed] = session.steps.splice(position, 1);
  await db.deleteImages(session.id, [removed.full_image, removed.zoom_image].filter(Boolean));
  session.steps.forEach((s, i) => (s.index = i + 1));
  await db.saveSession(session);
  if (state.pending && state.pending.id === id) {
    state.pending = null;
    await persist();
  }
  await setBadge();
  notifyPopup();
}

// ── mensajería ──────────────────────────────────────────────

const HANDLERS = {
  RECORD_STEP: (message, sender) => recordStep(message, sender),
  DESCRIBE_STEP: (m) => describeStep(m.id, m.description),
  DELETE_STEP: (m) => deleteStep(m.id, m.sessionId),
  START_SESSION: (m) => startSession(m),
  STOP_SESSION: () => stopSession(),
  SET_PAUSED: (m) => setPaused(m.paused),
  RESUME_SESSION: (m) => resumeSession(m.sessionId),
  GET_PENDING: async () => ({ recording: state.recording, paused: state.paused, pending: state.pending }),
  GET_STATE: async () => ({
    recording: state.recording,
    paused: state.paused,
    session: await currentSession(),
    defaults: await chrome.storage.local.get(["author", "system"]),
    usage: await db.usage(),
  }),
  LIST_SESSIONS: () => db.listSessions(),
  DELETE_SESSION: async (m) => {
    const session = await db.getSession(m.sessionId);
    if (session) {
      await db.deleteImages(
        session.id,
        session.steps.flatMap((s) => [s.full_image, s.zoom_image]).filter(Boolean)
      );
      await db.deleteSession(session.id);
      if (state.sessionId === session.id) {
        state.sessionId = null;
        state.recording = false;
        await persist();
        await setBadge();
      }
    }
    notifyPopup();
  },
  OPEN_REVIEW: async (m) => {
    const url = chrome.runtime.getURL("review.html") + (m.sessionId ? `?id=${m.sessionId}` : "");
    await chrome.tabs.create({ url });
  },
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handler = HANDLERS[message.type];
  if (!handler) {
    sendResponse({ ok: false, error: "mensaje desconocido: " + message.type });
    return false;
  }
  (async () => {
    try {
      sendResponse({ ok: true, data: await handler(message, sender) });
    } catch (err) {
      console.error("[RPA Step Recorder]", err);
      sendResponse({ ok: false, error: err.message || String(err) });
    }
  })();
  return true; // respuesta asíncrona
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command === "toggle-recording") {
    if (state.recording) await stopSession();
    else await startSession({});
    return;
  }
  if (command === "add-note" && state.recording) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) await tellTab(tab.id, { type: "REQUEST_NOTE" });
  }
});

chrome.runtime.onStartup.addListener(restore);
chrome.runtime.onInstalled.addListener(restore);
restore();
