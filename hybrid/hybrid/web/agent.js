/**
 * Agente de grabación web del RPA Step Recorder híbrido.
 *
 * La app lo inyecta (por el protocolo de depuración del navegador) en un mundo
 * aislado de cada página y de cada iframe: la página no ve este código ni
 * puede alterarlo. Detecta clics, escritura, selecciones y teclas, describe el
 * elemento (selector CSS, XPath, id...) y se lo pasa a la app con la función
 * puente __rpaEmit. La captura, la anotación y el guardado ocurren en la app.
 *
 * Port de extension/src/content/content.js sin la tarjeta de descripción: en
 * el híbrido los pasos se editan en el panel de la app.
 */

(() => {
  if (window.__rpaHybridAgent) return;
  window.__rpaHybridAgent = true;

  const BINDING = "__rpaEmit";
  const FRAME_MSG = "__rpaHybrid";
  const IS_TOP = window.top === window;
  const IS_MAC = /Mac/i.test(navigator.platform || navigator.userAgent || "");

  function emit(payload) {
    const bridge = window[BINDING];
    if (typeof bridge !== "function") return;
    try {
      bridge(JSON.stringify(payload));
    } catch (err) {
      /* la app se desconectó: no hay a quién avisar */
    }
  }

  // --- descripción del elemento --------------------------------------------

  // Controles con los que se interactúa. Se dejan fuera los roles de
  // estructura (main, region, dialog...) y tabindex=-1, que suelen marcar
  // contenedores enormes y no lo que el usuario pulsó.
  const CLICKABLE = [
    "a", "button", "input", "select", "textarea", "label", "summary", "option",
    "[onclick]", "[tabindex]:not([tabindex='-1'])", "[contenteditable='true']",
    ...["button", "link", "checkbox", "radio", "switch", "tab", "menuitem", "menuitemcheckbox",
        "menuitemradio", "option", "combobox", "textbox", "searchbox", "treeitem", "gridcell",
        "slider", "spinbutton"].map((r) => `[role='${r}']`),
  ].join(",");

  const TEST_ATTRS = ["data-testid", "data-test-id", "data-test", "data-qa", "data-cy", "data-automation-id"];

  const attr = (el, name) => (el && el.getAttribute && el.getAttribute(name)) || "";
  const clean = (text) => String(text || "").replace(/\s+/g, " ").trim();

  /** Texto del <label> asociado, que es como el usuario llama al campo. */
  function labelText(el) {
    const id = attr(el, "id");
    if (id) {
      const label = document.querySelector(`label[for="${cssEscape(id)}"]`);
      if (label) return label.innerText;
    }
    const wrapper = el.closest("label");
    if (wrapper) return wrapper.innerText;
    const described = attr(el, "aria-labelledby");
    if (described) {
      const source = document.getElementById(described.split(/\s+/)[0]);
      if (source) return source.innerText;
    }
    return "";
  }

  // El value solo nombra al control cuando es un botón; en una casilla es "on"
  // y en un select o un campo es el dato que el usuario escribió.
  const VALUE_AS_NAME = new Set(["button", "submit", "reset"]);

  function ownValue(el) {
    if (el.tagName.toLowerCase() !== "input") return "";
    return VALUE_AS_NAME.has(attr(el, "type").toLowerCase()) ? el.value || "" : "";
  }

  function isFormControl(el) {
    return ["input", "select", "textarea"].includes(el.tagName.toLowerCase());
  }

  function visibleText(el) {
    const candidates = [
      attr(el, "aria-label"),
      labelText(el),
      ownValue(el),
      attr(el, "title"),
      attr(el, "placeholder"),
      isFormControl(el) ? "" : el.innerText,
      attr(el, "alt"),
    ];
    for (const raw of candidates) {
      const text = clean(raw);
      if (text) return text.slice(0, 120);
    }
    return "";
  }

  const TAG_ROLE = {
    a: "link", button: "button", select: "combobox", textarea: "textbox", option: "option",
    img: "img", td: "cell", th: "columnheader", li: "listitem", summary: "button",
    h1: "heading", h2: "heading", h3: "heading", h4: "heading", h5: "heading", h6: "heading",
  };

  function roleOf(el) {
    const explicit = attr(el, "role").toLowerCase().split(/\s+/)[0];
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "input") {
      const type = attr(el, "type").toLowerCase() || "text";
      if (["button", "submit", "reset", "image", "file"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "range") return "slider";
      return "textbox";
    }
    if (el.isContentEditable) return "textbox";
    return TAG_ROLE[tag] || tag;
  }

  // Campos cuyo contenido nunca se envía a la app.
  const SECRET = /pass|contrase|clave|secret|token|tarjeta|card.?num|cvv|cvc|(^|[^a-z])(pin|otp|nip)([^a-z]|$)/i;

  function secretKind(el) {
    if (attr(el, "type").toLowerCase() === "password") return "password";
    const auto = attr(el, "autocomplete").toLowerCase();
    if (/password/.test(auto)) return "password";
    if (/cc-|one-time-code/.test(auto)) return "sensitive";
    const hints = [attr(el, "name"), attr(el, "id"), attr(el, "aria-label"), attr(el, "placeholder")];
    return hints.some((h) => h && SECRET.test(h)) ? "sensitive" : "";
  }

  function isEditable(el) {
    if (!(el instanceof Element)) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "textarea") return true;
    if (tag === "input") {
      const type = attr(el, "type").toLowerCase() || "text";
      return !["button", "submit", "reset", "image", "checkbox", "radio", "file", "range", "color"].includes(type);
    }
    return el.isContentEditable;
  }

  const fieldValue = (el) => (el.isContentEditable ? el.innerText || "" : el.value || "");

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
  }

  const cssString = (value) => String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');

  function count(selector) {
    try {
      return document.querySelectorAll(selector).length;
    } catch (err) {
      return 0;
    }
  }

  /** Selector CSS estable: prioriza id y atributos de prueba antes que clases volátiles. */
  function cssSelector(el) {
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 6) {
      const tag = node.tagName.toLowerCase();
      const id = attr(node, "id");
      if (id && !/^\d|[:.\s]|\d{4,}/.test(id) && count("#" + cssEscape(id)) === 1) {
        parts.unshift("#" + cssEscape(id));
        break;
      }
      let part = tag;
      const testAttr = [...TEST_ATTRS, "name"].find((a) => attr(node, a));
      if (testAttr) {
        part += `[${testAttr}="${cssString(attr(node, testAttr))}"]`;
      } else {
        const classes = attr(node, "class")
          .split(/\s+/)
          .filter((c) => c && c.length < 32 && !/\d{3,}|^(ng|css|sc|jsx|svelte)-|--/.test(c))
          .slice(0, 2);
        if (classes.length) part += "." + classes.map(cssEscape).join(".");
      }
      const qualified = part !== tag;
      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      // En cuanto el selector ya es único no hace falta subir más (una etiqueta
      // sola, como "span", sí necesita contexto aunque hoy sea única).
      if ((qualified || depth >= 1) && count(parts.join(" > ")) === 1) break;
      node = node.parentElement;
      depth += 1;
    }
    return parts.join(" > ");
  }

  function xPath(el) {
    const id = attr(el, "id");
    if (id && count("#" + cssEscape(id)) === 1) return `//*[@id=${xpathLiteral(id)}]`;
    const segments = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      const parent = node.parentElement;
      const siblings = parent ? Array.from(parent.children).filter((c) => c.tagName === node.tagName) : [node];
      segments.unshift(`${node.tagName.toLowerCase()}[${siblings.indexOf(node) + 1}]`);
      node = parent;
    }
    return "/html/" + segments.join("/");
  }

  function xpathLiteral(text) {
    if (!text.includes("'")) return `'${text}'`;
    if (!text.includes('"')) return `"${text}"`;
    return "concat('" + text.split("'").join(`', "'", '`) + "')";
  }

  function xpathMatches(xp) {
    try {
      const result = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      const nodes = [];
      for (let i = 0; i < result.snapshotLength; i += 1) nodes.push(result.snapshotItem(i));
      return nodes;
    } catch (err) {
      return [];
    }
  }

  /** XPath por el texto que ve el usuario: aguanta cambios de maquetación. */
  function textXPath(el, tag, text) {
    if (!text || text.length > 60) return "";
    const literal = xpathLiteral(text);
    let xp = "";
    if (clean(el.innerText) === text && !isFormControl(el)) xp = `//${tag}[normalize-space()=${literal}]`;
    else if (attr(el, "aria-label") === text) xp = `//${tag}[@aria-label=${literal}]`;
    else if (attr(el, "placeholder") === text) xp = `//${tag}[@placeholder=${literal}]`;
    else if (attr(el, "title") === text) xp = `//${tag}[@title=${literal}]`;
    else if (ownValue(el) === text) xp = `//${tag}[@value=${literal}]`;
    if (!xp) return "";
    const nodes = xpathMatches(xp);
    const index = nodes.indexOf(el);
    if (index < 0) return "";
    return nodes.length === 1 ? xp : `(${xp})[${index + 1}]`;
  }

  function describe(el) {
    const tag = el.tagName.toLowerCase();
    const id = attr(el, "id");
    const name = attr(el, "name");
    const testAttr = TEST_ATTRS.find((a) => attr(el, a)) || "";
    const text = visibleText(el);
    const css = cssSelector(el);
    const root = el.getRootNode && el.getRootNode();
    return {
      tag,
      type: attr(el, "type").toLowerCase(),
      role: roleOf(el),
      text,
      label: clean(labelText(el)).slice(0, 120),
      id,
      id_unique: Boolean(id) && count("#" + cssEscape(id)) === 1,
      name,
      name_unique: Boolean(name) && count(`${tag}[name="${cssString(name)}"]`) === 1,
      test_attr: testAttr,
      test_id: testAttr ? attr(el, testAttr) : "",
      aria_label: attr(el, "aria-label"),
      placeholder: attr(el, "placeholder"),
      href: tag === "a" ? el.href || "" : "",
      css,
      css_unique: count(css) === 1,
      xpath: xPath(el),
      xpath_text: textXPath(el, tag, text),
      checked: el.checked === true || attr(el, "aria-checked") === "true",
      disabled: el.disabled === true || attr(el, "aria-disabled") === "true",
      in_shadow: typeof ShadowRoot !== "undefined" && root instanceof ShadowRoot,
    };
  }

  /** Sube desde el nodo real del evento hasta el control interactivo que lo contiene. */
  function targetElement(event) {
    const path = typeof event.composedPath === "function" ? event.composedPath() : [];
    const start = path.find((n) => n instanceof Element) || event.target;
    if (!(start instanceof Element)) return null;
    const interactive = start.closest(CLICKABLE);
    if (interactive) {
      // Un clic en la etiqueta de una casilla actúa sobre la casilla.
      if (interactive.tagName === "LABEL" && interactive.control) return interactive.control;
      return interactive;
    }
    // Sin control interactivo: el propio nodo, salvo que sea un contenedor enorme.
    const rect = start.getBoundingClientRect();
    if (rect.width > window.innerWidth * 0.9 && rect.height > window.innerHeight * 0.9) return null;
    return start;
  }

  // --- posición del iframe dentro del área visible superior -----------------

  const offsetWaiters = new Map();

  /**
   * Desplazamiento del marco respecto a la página superior, tamaño visible de
   * esa página y selectores CSS de los <iframe> que hay que atravesar.
   */
  function frameOffset() {
    if (IS_TOP) return Promise.resolve({ x: 0, y: 0, vw: window.innerWidth, vh: window.innerHeight, frames: [] });
    return new Promise((resolve) => {
      const nonce = Math.random().toString(36).slice(2);
      const timer = setTimeout(() => {
        offsetWaiters.delete(nonce);
        resolve(null);
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
      if (waiter) waiter(data.known ? { x: data.x, y: data.y, vw: data.vw, vh: data.vh, frames: data.frames || [] } : null);
      return;
    }

    if (data[FRAME_MSG] === "offset-request") {
      let host = null;
      for (const frame of document.querySelectorAll("iframe, frame")) {
        if (frame.contentWindow === event.source) {
          host = frame;
          break;
        }
      }
      if (!host || !event.source) return;
      const rect = host.getBoundingClientRect();
      const style = window.getComputedStyle(host);
      const base = await frameOffset();
      event.source.postMessage(
        {
          [FRAME_MSG]: "offset-response",
          nonce: data.nonce,
          known: Boolean(base),
          x: base ? base.x + rect.left + parseFloat(style.borderLeftWidth || 0) + parseFloat(style.paddingLeft || 0) : 0,
          y: base ? base.y + rect.top + parseFloat(style.borderTopWidth || 0) + parseFloat(style.paddingTop || 0) : 0,
          vw: base ? base.vw : 0,
          vh: base ? base.vh : 0,
          frames: base ? [...base.frames, cssSelector(host)] : [],
        },
        "*"
      );
    }
  });

  // --- envío de pasos ----------------------------------------------------------

  // La descripción se toma YA (antes de que el clic navegue o cierre un modal);
  // solo el desplazamiento del iframe se resuelve después. La cadena mantiene
  // el orden: lo escrito en un campo llega antes que el clic que lo abandona.
  let chain = Promise.resolve();

  function send(kind, el, extra, point) {
    const rect = el ? el.getBoundingClientRect() : null;
    const payload = Object.assign(
      {
        kind,
        url: IS_TOP ? location.href : "",
        title: IS_TOP ? document.title : "",
        frame_url: IS_TOP ? "" : location.href,
        element: el ? describe(el) : null,
        rect: rect ? { x: rect.left, y: rect.top, width: rect.width, height: rect.height } : null,
        point: point || null,
      },
      extra || {}
    );
    chain = chain
      .then(async () => {
        const offset = await frameOffset();
        if (offset) {
          if (payload.rect) {
            payload.rect.x += offset.x;
            payload.rect.y += offset.y;
          }
          if (payload.point) {
            payload.point.x += offset.x;
            payload.point.y += offset.y;
          }
          payload.viewport = { width: offset.vw, height: offset.vh };
          payload.frame_path = offset.frames;
        } else {
          // Marco cuya posición no se pudo averiguar: sin recuadro antes que uno mal puesto.
          payload.rect = null;
          payload.point = null;
        }
        emit(payload);
      })
      .catch(() => {});
  }

  // ── escritura en campos ───────────────────────────────────

  let watched = null; // { el, initial }

  function watch(el) {
    if (watched && watched.el === el) return;
    if (watched) flushField("switch");
    watched = { el, initial: fieldValue(el) };
  }

  /** Registra el valor escrito al salir del campo, si de verdad cambió. */
  function flushField(reason) {
    if (!watched) return;
    const { el, initial } = watched;
    watched = null;
    if (!el.isConnected) return;
    const raw = fieldValue(el);
    if (raw === initial) return;
    const secret = secretKind(el);
    send("input", el, { reason, secret, value: secret ? "" : raw.slice(0, 2000) });
  }

  document.addEventListener(
    "focusin",
    (event) => {
      if (isEditable(event.target)) watch(event.target);
    },
    true
  );

  document.addEventListener("focusout", () => flushField("blur"), true);
  window.addEventListener("pagehide", () => flushField("leave"));

  // ── clics ─────────────────────────────────────────────────

  // Se captura en mousedown (fase de captura) para retratar la pantalla ANTES
  // de que el clic dispare una navegación o cierre un modal.
  document.addEventListener(
    "mousedown",
    (event) => {
      if (event.button !== 0 && event.button !== 2) return;
      // En macOS, Ctrl+clic es el clic derecho (abre el menú contextual).
      const button = IS_MAC && event.button === 0 && event.ctrlKey ? 2 : event.button;
      const el = targetElement(event);
      if (watched && watched.el !== el) flushField("click");
      if (!el) return;
      // Segunda pulsación de un doble clic: la app convierte el paso anterior.
      if (button === 0 && event.detail >= 2) {
        send("dblclick", el);
        return;
      }
      // En un campo, lo interesante es lo que se escriba: se registra al salir.
      if (button === 0 && isEditable(el)) {
        watch(el);
        return;
      }
      send(button === 2 ? "right_click" : "click", el, null, { x: event.clientX, y: event.clientY });
    },
    true
  );

  // Una lista desplegable importa por lo que se elige, no por el clic.
  document.addEventListener(
    "change",
    (event) => {
      const el = event.target;
      if (!(el instanceof Element) || el.tagName.toLowerCase() !== "select") return;
      const chosen = Array.from(el.selectedOptions || [])
        .map((o) => clean(o.text))
        .join(", ");
      send("select", el, { value: chosen || el.value || "" });
    },
    true
  );

  // ── teclas ────────────────────────────────────────────────

  const KEY_LABEL = { Enter: "Enter", Escape: "Esc" };
  const HOTKEYS = { F9: "toggle_record", F10: "toggle_pause", F8: "add_note" };
  // Alternativa sin teclas F (en los portátiles Mac van con fn): Cmd+Mayús+8/9/0
  // en macOS y Ctrl+Mayús+8/9/0 en Windows, como en la app de escritorio.
  const HOTKEY_DIGITS = { Digit9: "toggle_record", Digit0: "toggle_pause", Digit8: "add_note" };

  function hotkeyOf(event) {
    if (!event.ctrlKey && !event.altKey && !event.metaKey && HOTKEYS[event.key]) return HOTKEYS[event.key];
    const command = IS_MAC ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey;
    if (command && event.shiftKey && !event.altKey) return HOTKEY_DIGITS[event.code] || "";
    return "";
  }

  /** Nombre del sitio donde se pulsó la tecla; vacío si el foco está en el documento. */
  function keyTarget(el) {
    if (!(el instanceof Element)) return null;
    const target = el.closest(CLICKABLE);
    if (!target) return null;
    const rect = target.getBoundingClientRect();
    if (rect.width > window.innerWidth * 0.9 && rect.height > window.innerHeight * 0.5) return null;
    return target;
  }

  document.addEventListener(
    "keydown",
    (event) => {
      const hotkey = hotkeyOf(event);
      if (hotkey) {
        event.preventDefault();
        if (!event.repeat) emit({ kind: "hotkey", action: hotkey });
        return;
      }
      if (!KEY_LABEL[event.key] || event.repeat) return;
      const el = event.target;
      // Enter en un área de texto es un salto de línea, no una acción.
      if (event.key === "Enter" && el instanceof Element && (el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      // Enter dentro de un campo confirma el valor: primero el texto, luego la tecla.
      if (watched) flushField("key");
      send("key", keyTarget(el), { key: KEY_LABEL[event.key] });
    },
    true
  );
})();
