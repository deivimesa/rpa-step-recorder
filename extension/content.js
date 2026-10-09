/**
 * Content script: detecta el clic, describe el elemento y muestra la ventanita
 * para redactar el paso. Corre en todos los frames, pero el prompt sólo se
 * dibuja en el frame superior.
 */

(() => {
  if (window.__rpaStepRecorderLoaded) return;
  window.__rpaStepRecorderLoaded = true;

  const IS_TOP = window.top === window;
  const HOST_ID = "rpa-step-recorder-host";
  const FRAME_MSG = "__rpaStepRecorder";

  let recording = false;
  let paused = false;
  let busy = false;
  let currentPending = null;

  // --- descripción del elemento --------------------------------------------

  const CLICKABLE = "a,button,input,select,textarea,label,summary,[role],[onclick],[tabindex]";

  /** Texto del <label> asociado, que es como el usuario llama al campo. */
  function labelText(el) {
    const id = el.getAttribute("id");
    if (id) {
      const label = document.querySelector(`label[for="${cssEscape(id)}"]`);
      if (label) return label.innerText;
    }
    const wrapper = el.closest("label");
    if (wrapper) {
      // Un label que envuelve el control incluye su propio texto; basta con eso.
      return wrapper.innerText;
    }
    const described = el.getAttribute("aria-labelledby");
    if (described) {
      const source = document.getElementById(described.split(/\s+/)[0]);
      if (source) return source.innerText;
    }
    return "";
  }

  // El value sólo nombra al control cuando es un botón; en una casilla es "on"
  // y en un select o un campo es el dato que el usuario escribió, no su nombre.
  const VALUE_AS_NAME = new Set(["button", "submit", "reset"]);

  function ownValue(el) {
    if (el.tagName.toLowerCase() !== "input") return "";
    const type = (el.getAttribute("type") || "text").toLowerCase();
    return VALUE_AS_NAME.has(type) ? el.value || "" : "";
  }

  function visibleText(el) {
    const candidates = [
      el.getAttribute("aria-label"),
      labelText(el),
      ownValue(el),
      el.getAttribute("title"),
      el.getAttribute("placeholder"),
      isFormControl(el) ? "" : el.innerText,
      el.getAttribute("alt"),
    ];
    for (const raw of candidates) {
      const text = (raw || "").replace(/\s+/g, " ").trim();
      if (text) return text.slice(0, 120);
    }
    return "";
  }

  function isFormControl(el) {
    return ["input", "select", "textarea"].includes(el.tagName.toLowerCase());
  }

  function roleOf(el) {
    const explicit = (el.getAttribute("role") || "").toLowerCase();
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "reset", "image"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      return "textbox";
    }
    return tag;
  }

  // Verbo + sustantivo por tipo de control: el paso se lee como una instrucción.
  const PHRASE_ES = {
    button: ["Clic en", "el botón"],
    link: ["Clic en", "el enlace"],
    checkbox: ["Marcar", "la casilla"],
    radio: ["Seleccionar", "la opción"],
    combobox: ["Seleccionar un valor en", "la lista desplegable"],
    textbox: ["Escribir en", "el campo"],
    tab: ["Abrir", "la pestaña"],
    menuitem: ["Elegir", "la opción de menú"],
    option: ["Elegir", "la opción"],
  };

  const KIND_ES = {
    button: "Botón",
    link: "Enlace",
    checkbox: "Casilla",
    radio: "Opción",
    combobox: "Lista",
    textbox: "Campo",
    tab: "Pestaña",
    menuitem: "Menú",
    option: "Opción",
  };

  /** Lo que la ventanita muestra para que confirmes de un vistazo qué se capturó. */
  function controlLabel(role, text) {
    return { role, kind: KIND_ES[role] || "Elemento", name: text };
  }

  function suggestionFor(el, role, text) {
    let [verb, noun] = PHRASE_ES[role] || ["Clic en", "el elemento"];
    // En mousedown el estado aún no cambió: el paso describe cómo quedará.
    if (role === "checkbox" && el.checked) verb = "Desmarcar";
    return text ? `${verb} ${noun} «${text}»` : `${verb} ${noun}`;
  }

  // ── valores escritos ──────────────────────────────────────

  // Nunca se guarda el contenido de estos campos, ni con los valores activados.
  const SECRET = /pass|contrase|clave|pin|cvv|cvc|secret|token|tarjeta|card.?num/i;

  function isSecret(el) {
    if ((el.getAttribute("type") || "").toLowerCase() === "password") return true;
    const hints = [el.getAttribute("name"), el.getAttribute("id"),
                   el.getAttribute("autocomplete"), el.getAttribute("aria-label")];
    return hints.some((h) => h && SECRET.test(h));
  }

  function isEditable(el) {
    if (!(el instanceof Element)) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "textarea") return true;
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      return !["button", "submit", "reset", "image", "checkbox", "radio", "file", "range"].includes(type);
    }
    return el.isContentEditable;
  }

  const fieldValue = (el) =>
    el.isContentEditable ? (el.innerText || "") : (el.value || "");

  /** Recorta y sanea el valor que acabará en el documento. */
  function shownValue(el, raw) {
    if (isSecret(el)) return null;
    const text = String(raw).replace(/\s+/g, " ").trim();
    if (!text) return "";
    return text.length > 80 ? text.slice(0, 77) + "…" : text;
  }

  function typedSuggestion(el, name, value) {
    const where = name ? ` en el campo «${name}»` : " en el campo";
    if (value === null) return `Escribir la contraseña${where}`;
    if (!value) return `Vaciar el campo${name ? ` «${name}»` : ""}`;
    return `Escribir «${value}»${where}`;
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
  }

  /** Selector CSS estable: prioriza id y atributos de prueba antes que clases volátiles. */
  function cssSelector(el) {
    if (!(el instanceof Element)) return "";
    const parts = [];
    let node = el;
    let depth = 0;

    while (node && node.nodeType === 1 && depth < 6) {
      const tag = node.tagName.toLowerCase();

      const id = node.getAttribute("id");
      if (id && !/^\d|[:.\s]|\d{4,}/.test(id) && document.querySelectorAll("#" + cssEscape(id)).length === 1) {
        parts.unshift("#" + cssEscape(id));
        break;
      }

      let part = tag;
      const testAttr = ["data-testid", "data-test", "data-qa", "data-cy", "name"].find((a) => node.getAttribute(a));
      if (testAttr) {
        part += `[${testAttr}="${node.getAttribute(testAttr)}"]`;
      } else {
        const classes = (node.getAttribute("class") || "")
          .split(/\s+/)
          .filter((c) => c && c.length < 32 && !/\d{3,}|^(ng|css|sc)-|--/.test(c))
          .slice(0, 2);
        if (classes.length) part += "." + classes.map(cssEscape).join(".");
      }

      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      }

      parts.unshift(part);
      node = node.parentElement;
      depth += 1;
    }

    return parts.join(" > ");
  }

  function xPath(el) {
    if (!(el instanceof Element)) return "";
    const id = el.getAttribute("id");
    if (id && document.querySelectorAll("#" + cssEscape(id)).length === 1) {
      return `//*[@id="${id}"]`;
    }
    const segments = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      const parent = node.parentElement;
      const siblings = parent ? Array.from(parent.children).filter((c) => c.tagName === node.tagName) : [node];
      const index = siblings.indexOf(node) + 1;
      segments.unshift(`${node.tagName.toLowerCase()}[${index}]`);
      node = parent;
    }
    return "/html/" + segments.join("/");
  }

  /** Sube desde el nodo real del evento hasta el control interactivo que lo contiene. */
  function targetElement(event) {
    const path = typeof event.composedPath === "function" ? event.composedPath() : [];
    const start = path.find((n) => n instanceof Element) || event.target;
    if (!(start instanceof Element)) return null;
    const interactive = start.closest(CLICKABLE);
    if (interactive) return interactive;
    // Sin control interactivo: usa el nodo, salvo que sea un contenedor enorme.
    const rect = start.getBoundingClientRect();
    if (rect.width > window.innerWidth * 0.9 && rect.height > window.innerHeight * 0.9) return null;
    return start;
  }

  // --- offset del iframe dentro del viewport superior ------------------------

  const offsetWaiters = new Map();

  function frameOffset() {
    if (IS_TOP) return Promise.resolve({ x: 0, y: 0 });
    return new Promise((resolve) => {
      const nonce = Math.random().toString(36).slice(2);
      const timer = setTimeout(() => {
        offsetWaiters.delete(nonce);
        resolve({ x: 0, y: 0 });
      }, 400);
      offsetWaiters.set(nonce, (offset) => {
        clearTimeout(timer);
        offsetWaiters.delete(nonce);
        resolve(offset);
      });
      window.parent.postMessage({ [FRAME_MSG]: "offset-request", nonce }, "*");
    });
  }

  window.addEventListener("message", async (event) => {
    const data = event.data;
    if (!data || typeof data !== "object") return;

    if (data[FRAME_MSG] === "offset-response") {
      const waiter = offsetWaiters.get(data.nonce);
      if (waiter) waiter({ x: data.x || 0, y: data.y || 0 });
      return;
    }

    if (data[FRAME_MSG] === "offset-request") {
      const frames = document.querySelectorAll("iframe, frame");
      let host = null;
      for (const frame of frames) {
        if (frame.contentWindow === event.source) {
          host = frame;
          break;
        }
      }
      if (!host || !event.source) return;
      const rect = host.getBoundingClientRect();
      const style = window.getComputedStyle(host);
      const inset = {
        x: parseFloat(style.borderLeftWidth || 0) + parseFloat(style.paddingLeft || 0),
        y: parseFloat(style.borderTopWidth || 0) + parseFloat(style.paddingTop || 0),
      };
      const base = await frameOffset();
      event.source.postMessage(
        {
          [FRAME_MSG]: "offset-response",
          nonce: data.nonce,
          x: base.x + rect.left + inset.x,
          y: base.y + rect.top + inset.y,
        },
        "*"
      );
    }
  });

  // --- captura del paso ------------------------------------------------------

  async function capture(event) {
    if (!recording || paused || busy) return;
    if (event.button !== 0) return;
    if (event.target && event.target.id === HOST_ID) return;

    const el = targetElement(event);
    if (!el) return;

    // Al hacer clic en un campo, el paso interesante es lo que se escriba
    // después, no el clic: se registra al salir del campo.
    if (isEditable(el)) {
      watch(el);
      return;
    }

    busy = true;
    try {
      await clearCardForShot();
      const rect = el.getBoundingClientRect();
      const offset = await frameOffset();
      const role = roleOf(el);
      const text = visibleText(el);

      await chrome.runtime.sendMessage({
        type: "RECORD_STEP",
        kind: "click",
        url: location.href,
        title: document.title,
        dpr: window.devicePixelRatio || 1,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        suggestion: suggestionFor(el, role, text),
        label: controlLabel(role, text),
        element: {
          tag: el.tagName.toLowerCase(),
          type: el.getAttribute("type") || "",
          role,
          text,
          id: el.getAttribute("id") || "",
          name: el.getAttribute("name") || "",
          css: cssSelector(el),
          xpath: xPath(el),
          rect: {
            x: rect.left + offset.x,
            y: rect.top + offset.y,
            width: rect.width,
            height: rect.height,
          },
        },
      });
    } catch (err) {
      console.warn("[RPA Step Recorder] no se pudo registrar el paso:", err);
    } finally {
      busy = false;
    }
  }

  /**
   * Cierra la tarjeta pendiente antes de una captura nueva.
   *
   * Sin esto, la tarjeta del paso anterior sale dentro del pantallazo del
   * siguiente. Se guarda lo que hubiera escrito (no se pierde) y se espera a
   * que el navegador repinte sin ella; sólo entonces se pide la foto.
   */
  async function clearCardForShot() {
    if (!currentPending) return;
    const field = card && card.querySelector("textarea");
    await submit(field ? field.value : "");
    // Se espera a un repintado, pero con tope: requestAnimationFrame no se
    // dispara si la pestaña está oculta o sin foco, y sin el tope el paso
    // se perdería en silencio.
    await Promise.race([
      new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      new Promise((resolve) => setTimeout(resolve, 50)),
    ]);
  }

  // ── escritura en campos ───────────────────────────────────

  let watched = null; // { el, initial }

  function watch(el) {
    if (watched && watched.el === el) return;
    watched = { el, initial: fieldValue(el) };
  }

  /** Registra el valor escrito al salir del campo, si de verdad cambió. */
  async function flushField(reason) {
    if (!watched || !recording || paused || busy) return;
    const { el, initial } = watched;
    watched = null;
    if (!el.isConnected) return;

    const raw = fieldValue(el);
    if (raw === initial) return;

    busy = true;
    try {
      await clearCardForShot();
      const rect = el.getBoundingClientRect();
      const offset = await frameOffset();
      const name = visibleText(el);
      const value = shownValue(el, raw);

      await chrome.runtime.sendMessage({
        type: "RECORD_STEP",
        kind: "input",
        reason,
        url: location.href,
        title: document.title,
        dpr: window.devicePixelRatio || 1,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        suggestion: typedSuggestion(el, name, value),
        label: { role: "textbox", kind: "Campo", name: name || "" },
        value: value === null ? "" : value,
        secret: value === null,
        element: {
          tag: el.tagName.toLowerCase(),
          type: el.getAttribute("type") || "",
          role: roleOf(el),
          text: name,
          id: el.getAttribute("id") || "",
          name: el.getAttribute("name") || "",
          css: cssSelector(el),
          xpath: xPath(el),
          rect: { x: rect.left + offset.x, y: rect.top + offset.y, width: rect.width, height: rect.height },
        },
      });
    } catch (err) {
      console.warn("[RPA Step Recorder] no se pudo registrar el valor escrito:", err);
    } finally {
      busy = false;
    }
  }

  document.addEventListener("focusin", (event) => {
    if (!recording || paused) return;
    const el = event.target;
    if (isEditable(el) && (!el.closest || !el.closest("#" + HOST_ID))) watch(el);
  }, true);

  document.addEventListener("focusout", () => flushField("blur"), true);

  // Una lista desplegable importa por lo que se elige, no por el clic.
  document.addEventListener("change", async (event) => {
    const el = event.target;
    if (!recording || paused || busy) return;
    if (!(el instanceof Element) || el.tagName.toLowerCase() !== "select") return;

    busy = true;
    try {
      await clearCardForShot();
      const rect = el.getBoundingClientRect();
      const offset = await frameOffset();
      const name = labelText(el).replace(/\s+/g, " ").trim() || el.getAttribute("name") || "";
      const chosen = el.selectedOptions && el.selectedOptions[0]
        ? el.selectedOptions[0].text.replace(/\s+/g, " ").trim()
        : el.value;
      await chrome.runtime.sendMessage({
        type: "RECORD_STEP",
        kind: "select",
        url: location.href,
        title: document.title,
        dpr: window.devicePixelRatio || 1,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        suggestion: `Seleccionar «${chosen}»${name ? ` en la lista «${name}»` : ""}`,
        label: { role: "combobox", kind: "Lista", name: name || chosen },
        value: chosen,
        element: {
          tag: "select", type: "", role: "combobox", text: name,
          id: el.getAttribute("id") || "", name: el.getAttribute("name") || "",
          css: cssSelector(el), xpath: xPath(el),
          rect: { x: rect.left + offset.x, y: rect.top + offset.y, width: rect.width, height: rect.height },
        },
      });
    } catch (err) {
      console.warn("[RPA Step Recorder] no se pudo registrar la selección:", err);
    } finally {
      busy = false;
    }
  }, true);

  // ── teclas con significado propio ─────────────────────────

  const KEY_ES = { Enter: "Enter", Escape: "Escape", Tab: "Tabulador" };

  /** Nombre del sitio donde se pulsó la tecla. Vacío si el foco está en el
      documento: el innerText del body sería la página entera. */
  function keyContextName(el) {
    if (!(el instanceof Element)) return "";
    const target = el.closest(CLICKABLE);
    if (!target) return "";
    const rect = target.getBoundingClientRect();
    if (rect.width > window.innerWidth * 0.9 && rect.height > window.innerHeight * 0.5) return "";
    return visibleText(target);
  }

  document.addEventListener("keydown", async (event) => {
    if (!recording || paused || busy) return;
    if (event.target && event.target.id === HOST_ID) return;
    if (!KEY_ES[event.key] || event.key === "Tab") return;

    // Enter dentro de un campo confirma el valor: primero el texto, luego la tecla.
    if (watched) await flushField("key");

    const el = event.target instanceof Element ? event.target : document.body;
    busy = true;
    try {
      await clearCardForShot();
      const rect = el.getBoundingClientRect();
      const offset = await frameOffset();
      const name = keyContextName(el);
      await chrome.runtime.sendMessage({
        type: "RECORD_STEP",
        kind: "key",
        url: location.href,
        title: document.title,
        dpr: window.devicePixelRatio || 1,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        suggestion: `Pulsar ${KEY_ES[event.key]}${name ? ` en «${name}»` : ""}`,
        label: { role: "key", kind: "Tecla", name: KEY_ES[event.key] },
        element: {
          tag: el.tagName ? el.tagName.toLowerCase() : "",
          role: roleOf(el),
          text: name,
          id: el.getAttribute ? el.getAttribute("id") || "" : "",
          name: el.getAttribute ? el.getAttribute("name") || "" : "",
          css: cssSelector(el),
          xpath: xPath(el),
          rect: { x: rect.left + offset.x, y: rect.top + offset.y, width: rect.width, height: rect.height },
        },
      });
    } catch (err) {
      console.warn("[RPA Step Recorder] no se pudo registrar la tecla:", err);
    } finally {
      busy = false;
    }
  }, true);

  // Se captura en mousedown (fase de captura) para retratar la pantalla ANTES
  // de que el clic dispare una navegación o cierre un modal.
  document.addEventListener("mousedown", capture, true);

  // --- ventanita de descripción ---------------------------------------------

  let shadow = null;
  let card = null;
  let host = null;
  let mounted = null;

  /**
   * Dónde colgar la tarjeta.
   *
   * Un <dialog> abierto con showModal() vuelve inerte TODO lo demás del
   * documento: ni un position:fixed con z-index máximo ni un popover del
   * top layer pueden recibir foco, así que no se podría escribir la
   * descripción. Colgando el host del propio diálogo queda dentro del
   * subárbol no inerte, y position:fixed sigue posicionando respecto al
   * viewport. Lo mismo vale para un elemento en pantalla completa.
   */
  function mountPoint() {
    try {
      const modal = document.querySelector("dialog:modal");
      if (modal) return modal;
    } catch (err) {
      /* :modal no soportado; se usa el cuerpo */
    }
    if (document.fullscreenElement) return document.fullscreenElement;
    return document.body || document.documentElement;
  }

  function mount() {
    if (!host) return;
    const target = mountPoint();
    if (mounted === target && host.isConnected) return;
    target.appendChild(host);
    mounted = target;
    // Al cerrarse el diálogo la tarjeta se iría con él: vuelve al cuerpo.
    if (target.tagName === "DIALOG") {
      target.addEventListener("close", () => { if (currentPending) mount(); }, { once: true });
    }
  }

  const CONTROL_ICON = {
    button: '<rect x="2.5" y="6" width="15" height="9" rx="2.5"/><path d="m13 13 7 3-2.8 1.2L16 20z" fill="currentColor" stroke="none"/>',
    link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    textbox: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10v4"/>',
    checkbox: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 12 3 3 5-6"/>',
    radio: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5" fill="currentColor" stroke="none"/>',
    combobox: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="m9 11 3 3 3-3"/>',
    generic: '<path d="m4 4 7 16 2.5-6.5L20 11z"/>',
  };

  function buildOverlay() {
    if (shadow) return shadow;
    host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "all: initial !important; position: static !important;";
    shadow = host.attachShadow({ mode: "closed" });

    const styles = document.createElement("link");
    styles.rel = "stylesheet";
    styles.href = chrome.runtime.getURL("overlay.css");

    card = document.createElement("div");
    card.className = "card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", "Descripción del paso grabado");
    card.innerHTML = `
      <div class="head">
        <span class="badge"><span class="dot"></span><span class="step-n"></span></span>
        <span class="total"></span>
      </div>
      <div class="target">
        <svg class="target-icon" width="14" height="14" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"
             aria-hidden="true"></svg>
        <span class="kind"></span>
        <span class="name"></span>
      </div>
      <label for="rpa-desc">¿Qué hiciste en este paso?</label>
      <textarea id="rpa-desc" spellcheck="true"></textarea>
      <div class="actions">
        <button class="save" type="button">Guardar paso</button>
        <span class="keys"><kbd>Enter</kbd> guarda<span aria-hidden="true">·</span><kbd>Esc</kbd> omite</span>
        <button class="discard" type="button" title="Descartar esta captura"
                aria-label="Descartar esta captura">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
            <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>
          </svg>
        </button>
      </div>`;

    shadow.append(styles, card);

    const textarea = card.querySelector("textarea");
    card.querySelector(".save").addEventListener("click", () => submit(textarea.value));
    card.querySelector(".discard").addEventListener("click", discard);
    textarea.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit(textarea.value);
      } else if (event.key === "Escape") {
        event.preventDefault();
        submit(currentPending ? currentPending.suggestion : "", true);
      }
    });
    // Los clics dentro de la tarjeta no son pasos del proceso.
    card.addEventListener("mousedown", (event) => event.stopPropagation());
    return shadow;
  }

  /** Esquina más lejana al elemento pulsado: la ventanita nunca lo tapa. */
  function cornerFor(rect) {
    if (!rect) return "br";
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    const left = cx > window.innerWidth / 2;
    const top = cy > window.innerHeight / 2;
    return (top ? "t" : "b") + (left ? "l" : "r");
  }

  function describeTarget(pending) {
    const label = pending.label || {};
    card.querySelector(".kind").textContent = label.kind || "Elemento";
    const name = card.querySelector(".name");
    name.textContent = label.name ? "«" + label.name + "»" : "";
    name.title = label.name || "";
    card.querySelector(".target-icon").innerHTML =
      CONTROL_ICON[label.role] || CONTROL_ICON.generic;
  }

  function showPrompt(pending) {
    if (!IS_TOP || !pending) return;
    currentPending = pending;
    buildOverlay();
    mount();

    card.style.display = "";
    card.dataset.corner = cornerFor(pending.rect);
    card.querySelector(".step-n").textContent = "PASO " + (pending.index || "");
    card.querySelector(".total").textContent =
      pending.index === 1 ? "1 paso grabado" : pending.index + " pasos grabados";
    describeTarget(pending);

    const textarea = card.querySelector("textarea");
    textarea.value = pending.suggestion || "";
    textarea.select();
    textarea.focus({ preventScroll: true });

    // Entrada breve; con reduced-motion los tokens la anulan sola.
    card.dataset.enter = "1";
    requestAnimationFrame(() => requestAnimationFrame(() => delete card.dataset.enter));
  }

  function hidePrompt() {
    currentPending = null;
    if (card) card.style.display = "none";
  }

  async function submit(description, skipped) {
    if (!currentPending) return;
    const id = currentPending.id;
    hidePrompt();
    await chrome.runtime.sendMessage({ type: "DESCRIBE_STEP", id, description, skipped }).catch(() => {});
  }

  async function discard() {
    if (!currentPending) return;
    const id = currentPending.id;
    hidePrompt();
    await chrome.runtime.sendMessage({ type: "DELETE_STEP", id }).catch(() => {});
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "SHOW_PROMPT") showPrompt(message.pending);
    if (message.type === "RECORDING_STATE") {
      recording = message.recording;
      paused = Boolean(message.paused);
      if (!recording) hidePrompt();
    }
    if (message.type === "REQUEST_NOTE" && IS_TOP) {
      clearCardForShot().then(() => chrome.runtime
        .sendMessage({
          type: "RECORD_STEP",
          kind: "note",
          url: location.href,
          title: document.title,
          dpr: window.devicePixelRatio || 1,
          viewport: { width: window.innerWidth, height: window.innerHeight },
          suggestion: "",
          element: null,
        })
        .catch(() => {}));
    }
  });

  // Al cargar (o volver) la página se recupera el estado y cualquier paso
  // que quedó sin describir porque el clic provocó una navegación.
  async function sync() {
    try {
      const res = await chrome.runtime.sendMessage({ type: "GET_PENDING" });
      if (!res || !res.ok || !res.data) return;
      recording = res.data.recording;
      paused = Boolean(res.data.paused);
      if (recording && res.data.pending) showPrompt(res.data.pending);
    } catch (err) {
      /* el service worker puede estar despertando */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", sync, { once: true });
  } else {
    sync();
  }
  window.addEventListener("pageshow", sync);
})();
