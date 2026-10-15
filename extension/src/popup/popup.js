/**
 * Panel de control de la grabación. Todo el estado vive en el service worker;
 * aquí sólo se pinta y se disparan acciones.
 */

const $ = (id) => document.getElementById(id);

async function send(message) {
  const res = await chrome.runtime.sendMessage(message);
  if (!res || !res.ok) throw new Error((res && res.error) || "Sin respuesta de la extensión");
  return res.data;
}

let view = { recording: false, paused: false, session: null, sessions: [] };
let ticker = null;

// ── mensajes ────────────────────────────────────────────────

function say(text, kind) {
  const box = $("msg");
  if (!text) {
    box.removeAttribute("data-kind");
    box.textContent = "";
    return;
  }
  const icon = kind === "err" ? "#i-alert" : "#i-check";
  box.setAttribute("data-kind", kind || "info");
  box.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" aria-hidden="true"><use href="${icon}"/></svg><span></span>`;
  box.querySelector("span").textContent = text;
}

// ── formato ─────────────────────────────────────────────────

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function clock(iso) {
  const start = Date.parse(iso);
  if (Number.isNaN(start)) return "00:00";
  const total = Math.max(0, Math.floor((Date.now() - start) / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function relative(iso) {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const time = when.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  return when.toDateString() === new Date().toDateString()
    ? `hoy ${time}`
    : `${when.toLocaleDateString("es", { day: "numeric", month: "short" })} ${time}`;
}

// ── pintado ─────────────────────────────────────────────────

function render() {
  const state = view.recording ? "recording" : "idle";
  document.body.dataset.state = state;
  document.body.dataset.paused = view.paused ? "1" : "";
  $("pill-text").textContent = !view.recording ? "listo" : view.paused ? "en pausa" : "grabando";

  clearInterval(ticker);
  ticker = null;

  if (view.recording && view.session) {
    const count = view.session.steps.length;
    $("count").textContent = count;
    $("count-label").textContent = count === 1 ? "paso" : "pasos";
    $("empty").hidden = count > 0;
    $("live").hidden = count === 0;
    renderSteps(view.session.steps.slice(-6));
    $("pause-label").textContent = view.paused ? "Reanudar" : "Pausar";
    $("pause").querySelector("use").setAttribute("href", view.paused ? "#i-play" : "#i-pause");
    $("count-label").textContent = view.paused
      ? "pausado"
      : count === 1 ? "paso" : "pasos";

    const tick = () => ($("timer").textContent = clock(view.session.started_at));
    tick();
    if (!view.paused) ticker = setInterval(tick, 1000);
    return;
  }

  const saved = view.sessions.filter((s) => s.steps.length > 0);
  $("last-wrap").hidden = saved.length === 0;
  if (saved.length) {
    const latest = saved[0];
    $("last-name").textContent = latest.name;
    $("last-meta").textContent =
      `${plural(latest.steps.length, "paso", "pasos")} · ${relative(latest.started_at)}`;
    $("last-title").textContent = latest.finished_at ? "Listo para exportar" : "Última grabación";
    renderOlder(saved.slice(1, 5));
  }
}

function renderSteps(steps) {
  const list = $("steps");
  list.textContent = "";
  for (const step of [...steps].reverse()) {
    const row = document.createElement("div");
    row.className = "step";
    const n = document.createElement("span");
    n.className = "n";
    n.textContent = step.index;
    const txt = document.createElement("span");
    txt.className = "txt";
    txt.textContent = step.description || "(sin descripción)";
    txt.title = txt.textContent;
    row.append(n, txt);
    list.append(row);
  }
}

function renderOlder(sessions) {
  $("older-title").hidden = sessions.length === 0;
  const box = $("older");
  box.textContent = "";
  for (const item of sessions) {
    const row = document.createElement("button");
    row.className = "session";
    row.type = "button";
    const name = document.createElement("span");
    name.className = "s-name";
    name.textContent = item.name;
    const meta = document.createElement("span");
    meta.className = "s-meta";
    meta.textContent = `${item.steps.length} · ${relative(item.started_at)}`;
    row.append(name, meta);
    row.addEventListener("click", () => openReview(item.id));
    box.append(row);
  }
}

// ── datos ───────────────────────────────────────────────────

async function refresh() {
  try {
    const [state, sessions] = await Promise.all([
      send({ type: "GET_STATE" }),
      send({ type: "LIST_SESSIONS" }),
    ]);
    view = {
      recording: state.recording,
      paused: Boolean(state.paused),
      session: state.session,
      sessions: sessions || [],
    };
    if (!$("author").value) $("author").value = state.defaults.author || "";
    if (!$("system").value) $("system").value = state.defaults.system || "";
    showUsage(state.usage);
    render();
  } catch (err) {
    say(err.message, "err");
  }
}

function showUsage(usage) {
  if (!usage || !usage.used) return;
  const mb = usage.used / 1048576;
  $("storage").textContent = mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
  $("storage").title = "Espacio ocupado por las grabaciones guardadas";
}

async function act(button, work, busyText) {
  const label = button.innerHTML;
  button.disabled = true;
  if (busyText) button.textContent = busyText;
  try {
    await work();
  } catch (err) {
    say(err.message, "err");
  } finally {
    button.disabled = false;
    button.innerHTML = label;
    await refresh();
  }
}

const openReview = (sessionId) =>
  send({ type: "OPEN_REVIEW", sessionId }).then(() => window.close());

// ── acciones ────────────────────────────────────────────────

$("start").addEventListener("click", (event) =>
  act(event.currentTarget, async () => {
    await send({
      type: "START_SESSION",
      name: $("name").value.trim(),
      author: $("author").value.trim(),
      system: $("system").value.trim(),
    });
    $("name").value = "";
    say("Grabando. Cada clic crea un paso.", "ok");
  }, "Iniciando…")
);

$("stop").addEventListener("click", (event) =>
  act(event.currentTarget, async () => {
    const session = await send({ type: "STOP_SESSION" });
    if (session && session.steps.length) await openReview(session.id);
    else say("Grabación detenida sin pasos.", "info");
  }, "Deteniendo…")
);

$("undo").addEventListener("click", (event) =>
  act(event.currentTarget, async () => {
    const steps = view.session ? view.session.steps : [];
    const last = steps[steps.length - 1];
    if (!last) return;
    await send({ type: "DELETE_STEP", id: last.id });
    say(`Paso ${last.index} eliminado.`, "info");
  }, "Eliminando…")
);

$("pause").addEventListener("click", (event) =>
  act(event.currentTarget, async () => {
    const paused = await send({ type: "SET_PAUSED", paused: !view.paused });
    say(paused ? "En pausa: los clics no se graban." : "Grabación reanudada.", "info");
  })
);

$("resume").addEventListener("click", (event) =>
  act(event.currentTarget, async () => {
    const saved = view.sessions.filter((s) => s.steps.length > 0);
    if (!saved.length) return;
    await send({ type: "RESUME_SESSION", sessionId: saved[0].id });
    say("Continuando esa grabación.", "ok");
  }, "Abriendo…")
);

$("review").addEventListener("click", () => {
  const saved = view.sessions.filter((s) => s.steps.length > 0);
  if (saved.length) openReview(saved[0].id);
});

$("name").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("start").click();
});

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "STATE_CHANGED") refresh();
});

// Las teclas se muestran según el sistema, no fijas a macOS.
const mac = navigator.userAgent.includes("Mac");
$("k-rec").textContent = mac ? "⌘⇧9" : "Ctrl+Shift+9";
$("k-note").textContent = mac ? "⌘⇧8" : "Ctrl+Shift+8";

setInterval(refresh, 1500);
refresh();
