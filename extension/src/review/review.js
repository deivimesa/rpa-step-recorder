/**
 * Página de revisión: corrige las descripciones, reordena o elimina pasos
 * y genera los documentos. La exportación vive aquí (y no en el service
 * worker) porque una página sí puede crear object URLs y no se cierra sola.
 */

import * as db from "../lib/db.js";
import { buildDocx } from "../lib/docx.js";
import { buildPdf } from "../lib/pdf.js";
import { controlLabel, prettyDate, slugify } from "../lib/doc-common.js";

const $ = (sel) => document.querySelector(sel);
const send = (message) => chrome.runtime.sendMessage(message);

let session = null;
const imageUrls = new Map();

// ── mensajes ────────────────────────────────────────────────

function say(text, kind) {
  const box = $("#msg");
  if (!text) {
    box.removeAttribute("data-kind");
    box.textContent = "";
    return;
  }
  const icon = kind === "err" ? "#i-alert" : "#i-check";
  box.setAttribute("data-kind", kind || "info");
  box.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><use href="${icon}"/></svg><span></span>`;
  box.querySelector("span").textContent = text;
}

function progress(fraction) {
  const bar = $("#progress");
  if (fraction == null) {
    bar.hidden = true;
    $("#fill").style.width = "0";
    return;
  }
  bar.hidden = false;
  $("#fill").style.width = Math.round(fraction * 100) + "%";
}

// ── carga ───────────────────────────────────────────────────

async function load() {
  const wanted = new URLSearchParams(location.search).get("id");
  const list = await send({ type: "LIST_SESSIONS" });
  const sessions = (list && list.data) || [];
  session = wanted ? sessions.find((s) => s.id === wanted) : sessions[0];

  if (!session) {
    $("#empty").hidden = false;
    $("#empty").innerHTML = "<p>No hay ninguna grabación guardada todavía.</p>";
    $("#title").value = "Sin grabaciones";
    $("#export-docx").disabled = true;
    $("#export-pdf").disabled = true;
    $("#delete").disabled = true;
    return;
  }

  document.title = `${session.name} · RPA Step Recorder`;
  $("#title").value = session.name;
  $("#author").value = session.author || "";
  $("#system").value = session.system || "";
  renderMeta();
  await renderSteps();
}

function renderMeta() {
  const count = session.steps.length;
  const parts = [
    `${count} ${count === 1 ? "paso" : "pasos"}`,
    prettyDate(session.started_at),
  ];
  if (session.system) parts.push(session.system);
  if (session.author) parts.push(session.author);
  $("#meta").textContent = parts.filter(Boolean).join(" · ") + " · ";
  const disabled = count === 0;
  $("#export-docx").disabled = disabled;
  $("#export-pdf").disabled = disabled;
  $("#empty").hidden = count > 0;
}

async function imageUrl(name) {
  if (!name) return null;
  if (imageUrls.has(name)) return imageUrls.get(name);
  const bytes = await db.getImage(session.id, name);
  if (!bytes) return null;
  const url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
  imageUrls.set(name, url);
  return url;
}

async function renderSteps() {
  const list = $("#steps");
  list.textContent = "";
  const template = $("#tpl-step");

  for (const [position, step] of session.steps.entries()) {
    const node = template.content.cloneNode(true);
    const li = node.querySelector(".step");
    li.dataset.id = step.id;
    li.dataset.index = step.index;
    li.id = `paso-${step.index}`;

    node.querySelector(".num").textContent = step.index;
    node.querySelector(".chip").textContent = step.element
      ? `${controlLabel(step.element)}${step.element.text ? ` «${step.element.text}»` : ""}`
      : "Nota";

    const full = await imageUrl(step.full_image);
    const zoom = await imageUrl(step.zoom_image);
    const fullImg = node.querySelector(".full");
    const zoomImg = node.querySelector(".zoom");
    if (full) {
      fullImg.src = full;
      fullImg.alt = `Captura del paso ${step.index}`;
    }
    if (zoom) {
      zoomImg.src = zoom;
      zoomImg.alt = `Detalle del elemento del paso ${step.index}`;
    }

    const textarea = node.querySelector(".desc");
    textarea.value = step.description || step.suggestion || "";
    textarea.addEventListener("input", () => {
      step.description = textarea.value;
      queueSave(textarea);
    });

    const meta = node.querySelector(".meta");
    for (const [label, value] of technicalRows(step)) {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      dd.title = value;
      meta.append(dt, dd);
    }

    node.querySelector(".up").disabled = position === 0;
    node.querySelector(".down").disabled = position === session.steps.length - 1;
    node.querySelector(".up").addEventListener("click", () => move(step.id, -1));
    node.querySelector(".down").addEventListener("click", () => move(step.id, +1));
    node.querySelector(".del").addEventListener("click", () => remove(step));

    list.append(node);
  }
  renderRail();
}

// ── índice lateral ──────────────────────────────────────────

function renderRail() {
  const rail = $("#rail");
  rail.textContent = "";
  for (const step of session.steps) {
    const link = document.createElement("a");
    link.href = `#paso-${step.index}`;
    link.textContent = step.index;
    link.title = step.description || step.suggestion || "";
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const target = document.getElementById(`paso-${step.index}`);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    rail.append(link);
  }
  observeSteps();
}

let observer = null;
function observeSteps() {
  if (observer) observer.disconnect();
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const index = entry.target.dataset.index;
        for (const link of $("#rail").children) {
          link.classList.toggle("here", link.textContent === index);
        }
      }
    },
    { rootMargin: "-80px 0px -60% 0px" }
  );
  for (const li of document.querySelectorAll(".step")) observer.observe(li);
}

function technicalRows(step) {
  const element = step.element;
  const rows = [];
  if (step.secret) rows.push(["Valor", "(contraseña — no se guarda)"]);
  else if (step.value) rows.push([step.kind === "select" ? "Opción" : "Valor", step.value]);
  if (element) {
    // El id va primero: es el localizador más estable para el bot.
    if (element.id) rows.push(["ID", element.id]);
    if (element.name) rows.push(["Name", element.name]);
    if (element.css) rows.push(["CSS", element.css]);
    if (element.xpath) rows.push(["XPath", element.xpath]);
  }
  if (step.url) rows.push(["URL", step.url]);
  return rows;
}

// ── edición ─────────────────────────────────────────────────

let saveTimer = null;
function queueSave(field) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    await db.saveSession(session);
    if (field) {
      field.classList.add("saved");
      setTimeout(() => field.classList.remove("saved"), 900);
    }
  }, 400);
}

async function move(id, delta) {
  const from = session.steps.findIndex((s) => s.id === id);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= session.steps.length) return;
  const [step] = session.steps.splice(from, 1);
  session.steps.splice(to, 0, step);
  session.steps.forEach((s, i) => (s.index = i + 1));
  await db.saveSession(session);
  await renderSteps();
  // Devuelve el foco al mismo paso tras redibujar.
  const moved = document.querySelector(`.step[data-id="${id}"]`);
  if (moved) {
    moved.scrollIntoView({ block: "nearest", behavior: "smooth" });
    moved.querySelector(delta < 0 ? ".up" : ".down").focus();
  }
}

async function remove(step) {
  await send({ type: "DELETE_STEP", id: step.id, sessionId: session.id });
  session.steps = session.steps.filter((s) => s.id !== step.id);
  session.steps.forEach((s, i) => (s.index = i + 1));
  renderMeta();
  await renderSteps();
  say(`Paso eliminado. Quedan ${session.steps.length}.`, "info");
}

$("#title").addEventListener("input", (event) => {
  session.name = event.target.value;
  queueSave();
});

$("#delete").addEventListener("click", () => {
  const count = session.steps.length;
  $("#confirm-text").textContent =
    `Se borrarán «${session.name}» y sus ${count} ${count === 1 ? "captura" : "capturas"}. No se puede deshacer.`;
  $("#confirm").showModal();
});

$("#confirm").addEventListener("close", async () => {
  if ($("#confirm").returnValue !== "ok") return;
  await send({ type: "DELETE_SESSION", sessionId: session.id });
  location.href = chrome.runtime.getURL("src/review/review.html");
});

$("#edit-cover").addEventListener("click", () => $("#cover").showModal());
$("#cover").addEventListener("close", async () => {
  if ($("#cover").returnValue !== "ok") return;
  session.author = $("#author").value.trim();
  session.system = $("#system").value.trim();
  await db.saveSession(session);
  await chrome.storage.local.set({ author: session.author, system: session.system });
  renderMeta();
});

// ── exportación ─────────────────────────────────────────────

async function exportAs(format, button) {
  const label = button.innerHTML;
  button.disabled = true;
  button.textContent = "Generando…";
  say("");
  progress(0.05);

  try {
    session.name = $("#title").value.trim() || session.name;
    if (!session.finished_at) session.finished_at = new Date().toISOString();
    await db.saveSession(session);

    progress(0.25);
    const images = await db.loadImages(session);
    progress(0.5);

    const blob = format === "docx" ? await buildDocx(session, images) : await buildPdf(session, images);
    progress(0.9);

    const filename = `${slugify(session.name)}.${format}`;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);

    progress(1);
    say(`${filename} descargado (${(blob.size / 1048576).toFixed(1)} MB).`, "ok");
  } catch (err) {
    console.error(err);
    say("No se pudo generar el documento: " + (err.message || err), "err");
  } finally {
    button.disabled = false;
    button.innerHTML = label;
    setTimeout(() => progress(null), 800);
  }
}

$("#export-docx").addEventListener("click", (e) => exportAs("docx", e.currentTarget));
$("#export-pdf").addEventListener("click", (e) => exportAs("pdf", e.currentTarget));

window.addEventListener("beforeunload", () => {
  for (const url of imageUrls.values()) URL.revokeObjectURL(url);
});

load();
