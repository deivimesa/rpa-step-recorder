"""Grabador: hooks globales de ratón/teclado que orquestan la captura de pasos.

Funciona igual en Windows y macOS: la parte dependiente del sistema
(inspección de elementos, hooks, capturas) vive en ``app.backends``.

Diseño: los hooks solo encolan eventos; un ÚNICO hilo worker los procesa en
orden (en Windows inicializa COM ahí). La sesión vive en memoria protegida por
un lock: la interfaz lee copias (``current_session``) y nunca relee el JSON
mientras se escribe.

Correcciones respecto a la 3.x:
  - Detener ya no pierde lo último escrito ni las ediciones pendientes: el
    worker vacía la cola hasta el marcador de parada.
  - La barra espaciadora se registraba como tecla especial y se perdían los
    espacios; Tab no cerraba el campo y mezclaba dos campos en un paso.
  - El texto final se lee del propio campo (pegados, autocompletado, tildes);
    las teclas solo son el respaldo. Escribir en un campo con el foco sin
    haber hecho clic (diálogos, Tab) también se registra.
  - Clic derecho, doble clic (fusiona el paso anterior) y atajos de teclado
    (Ctrl+S, Cmd+C...) como pasos. F8/F9/F10 funcionan de forma global.
  - Si la captura de pantalla falla, el paso se guarda igualmente sin imagen.
"""

from __future__ import annotations

import copy
import logging
import queue
import threading
import time
from datetime import datetime

from . import annotate, capture, keys, phrases, storage
from ..backends import HookError, get_backend

log = logging.getLogger("rpa.recorder")

_STOP = {"type": "stop"}


class Recorder:
    def __init__(self, on_change=None, on_hotkey=None, settings=None):
        self.backend = get_backend()
        self.settings = settings
        self.session_id: str | None = None
        self.recording = False
        self.paused = False
        self._on_change = on_change
        self._on_hotkey = on_hotkey
        self._lock = threading.RLock()
        self._session: dict | None = None
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._typing: dict | None = None
        self._last_click: dict | None = None
        self._last_focus_check = 0.0
        self._paused_at: float | None = None
        self.last_error = ""

    def _setting(self, key: str, default=True):
        if self.settings is None:
            return default
        return self.settings.get(key, default)

    # ── estado ──────────────────────────────────────────────

    def _notify(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                log.exception("fallo en on_change")

    def current_session(self) -> dict | None:
        """Copia de la sesión en curso (o la última grabada, leída de disco)."""
        with self._lock:
            if self._session is not None:
                return copy.deepcopy(self._session)
        return storage.get_session(self.session_id) if self.session_id else None

    # ── ciclo de vida ───────────────────────────────────────

    def start_session(self, name: str, author: str, system: str) -> dict:
        session = storage.new_session(name, author, system, self.backend.name)
        storage.save_session(session)
        return self._begin(session)

    def resume_session(self, session_id: str) -> dict:
        session = storage.get_session(session_id)
        if not session:
            raise ValueError("Esa grabación ya no existe")
        session["finished_at"] = ""
        storage.backup_session(session_id)
        return self._begin(session)

    def _begin(self, session: dict) -> dict:
        with self._lock:
            self._session = session
        self.session_id = session["id"]
        self._typing = None
        self._last_click = None
        self.paused = False
        self.last_error = ""
        self._start_worker()
        try:
            self.backend.start_hooks(self._on_mouse, self._on_key)
        except HookError as err:
            self.last_error = str(err)
            log.error("hooks: %s", err)
        self.recording = True
        log.info("sesión iniciada: %s", session["id"])
        self._notify()
        return copy.deepcopy(session)

    def set_paused(self, paused: bool) -> bool:
        self._enqueue({"type": "flush"})
        self.paused = bool(paused)
        self._paused_at = time.monotonic() if self.paused else None
        log.info("pausa: %s", self.paused)
        self._notify()
        return self.paused

    def stop_session(self) -> dict | None:
        if not self.recording:
            return self.current_session()
        self.recording = False
        self.backend.stop_hooks()
        self._enqueue({"type": "flush"})
        self._enqueue(_STOP)
        if self._worker:
            self._worker.join(timeout=30)
            if self._worker.is_alive():
                log.warning("el worker no terminó a tiempo")
        self._worker = None
        with self._lock:
            session = self._session
            if session:
                session["finished_at"] = datetime.now().isoformat(timespec="seconds")
                storage.save_session(session)
                storage.backup_session(session["id"])
            self._session = None
        self.paused = False
        storage.invalidate_cache(self.session_id)
        log.info("sesión detenida; pasos: %s", len(session["steps"]) if session else 0)
        self._notify()
        return copy.deepcopy(session) if session else None

    def hooks_alive(self) -> bool:
        return self.backend.hooks_alive()

    # ── worker ──────────────────────────────────────────────

    def _start_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._queue = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, name="rpa-worker", daemon=True)
        self._worker.start()

    def _enqueue(self, event: dict):
        self._queue.put(event)

    def _run_worker(self):
        try:
            self.backend.thread_init()
        except Exception:
            log.exception("inicialización del hilo de inspección falló (puede seguir funcionando)")
        try:
            while True:
                event = self._queue.get()
                if event is _STOP:
                    break
                try:
                    self._process(event)
                except Exception:
                    log.exception("fallo procesando evento %s", event.get("type"))
        finally:
            self.backend.thread_exit()

    def _process(self, event: dict):
        kind = event.get("type")
        if kind == "flush":
            self._flush_typing()
        elif kind == "click":
            self._process_click(event["event"])
        elif kind == "key":
            self._process_key(event["event"])
        elif kind == "note":
            self._flush_typing()
            self._record("note", None, event.get("text") or "Nota", step_id=event.get("id"))
        elif kind == "edit_desc":
            self._edit_desc(event["id"], event.get("text", ""))
        elif kind == "del_step":
            self._del_step(event["id"])
        elif kind == "move_step":
            self._move_step(event["id"], int(event.get("delta", 0)))

    # ── eventos de entrada (hilos de los hooks: solo encolan) ──

    def _on_mouse(self, event: keys.MouseEvent):
        if not self.recording or self.paused:
            return
        if event.button == "middle" or (event.button == "right" and not self._setting("record_right_click")):
            return
        self._enqueue({"type": "click", "event": event})

    def _on_key(self, event: keys.KeyEvent):
        action = keys.hotkey_action(event, self.backend.name)
        if action and self.recording and self._setting("global_hotkeys"):
            if self._on_hotkey:
                self._on_hotkey(action)
            return
        if not self.recording or self.paused:
            return
        self._enqueue({"type": "key", "event": event})

    # ── procesamiento (hilo worker) ─────────────────────────

    def _process_click(self, ev: keys.MouseEvent):
        self._flush_typing()
        if self.backend.is_own_point(ev.x, ev.y):
            return
        element, handle = self.backend.inspect_point(ev.x, ev.y)
        if element and self.backend.is_own_element(element):
            return
        # Doble clic: convierte el paso anterior en «Doble clic».
        last = self._last_click
        dbl = (
            ev.button == "left" and last and last.get("step_id")
            and (ev.clicks >= 2 or (
                ev.clicks == 0 and ev.t - last["t"] <= self.backend.double_click_time()
                and abs(ev.x - last["x"]) <= self.backend.double_click_slop()
                and abs(ev.y - last["y"]) <= self.backend.double_click_slop()))
        )
        if dbl and self._setting("merge_double_click"):
            self._promote_double(last["step_id"], element)
            self._last_click = None
            return
        if ev.button == "left" and self.backend.is_editable(element):
            self._start_typing(element, handle, (ev.x, ev.y))
            self._last_click = {"x": ev.x, "y": ev.y, "t": ev.t, "step_id": None}
            return
        kind = "right_click" if ev.button == "right" else "click"
        text = phrases.describe_click(element, kind, (ev.x, ev.y))
        step_id = self._record(kind, element, text, point=(ev.x, ev.y))
        self._last_click = {"x": ev.x, "y": ev.y, "t": ev.t, "step_id": step_id}

    def _process_key(self, ev: keys.KeyEvent):
        platform = self.backend.name
        typing_now = self._typing is not None
        if keys.is_typing(ev, platform) or (typing_now and keys.is_edit_shortcut(ev, platform)) \
                or (typing_now and ev.key in ("backspace", "delete")):
            self._ensure_typing_target()
            if self._typing is not None and not self._typing["secret"]:
                self._typing["buffer"].feed(ev, platform)
            if self._typing is not None:
                self._typing["dirty"] = True
            return
        if ev.key == "tab":
            self._flush_typing()
            return
        notable = ev.key in ("enter", "esc", "delete") or ev.key.startswith("f") and ev.key[1:].isdigit()
        shortcut = keys.has_command_mods(ev, platform) and self._setting("record_shortcuts")
        if not (notable or shortcut):
            return
        self._flush_typing()
        if ev.repeat:
            return
        element, _ = self.backend.inspect_focused()
        if element and self.backend.is_own_element(element):
            return
        label = keys.shortcut_label(ev, platform) if ev.mods - {"shift"} else keys.key_label(ev.key, ev.base)
        text = phrases.describe_key(label, element, (element or {}).get("app", ""))
        rect = (element or {}).get("rect")
        point = (rect["x"] + rect["width"] // 2, rect["y"] + rect["height"] // 2) if rect else None
        self._record("shortcut" if shortcut and not notable else "key", element, text, point=point)

    # ── escritura ───────────────────────────────────────────

    def _start_typing(self, element, handle, point=None):
        secret = self.backend.secret_kind(element)
        initial = None if secret else self.backend.read_value(handle)
        self._typing = {
            "element": element, "handle": handle, "secret": secret, "initial": initial,
            "buffer": keys.KeyBuffer(), "dirty": False, "point": point,
        }

    def _ensure_typing_target(self):
        """Si se escribe sin clic previo (Tab, diálogo), se usa el control con el foco."""
        now = time.monotonic()
        if self._typing is not None and now - self._last_focus_check < 2.0:
            return
        self._last_focus_check = now
        handle = self.backend.focused_handle()
        if self._typing is not None and (handle is None or self.backend.same_element(handle, self._typing["handle"])):
            return
        element, handle = self.backend.inspect_focused()
        if element and self.backend.is_own_element(element):
            self._flush_typing()
            return
        if self._typing is not None:
            self._flush_typing()
        self._start_typing(element, handle)

    def _flush_typing(self):
        typing, self._typing = self._typing, None
        if not typing or not typing["dirty"]:
            return
        element, secret = typing["element"], typing["secret"]
        value = ""
        if not secret:
            read = self.backend.read_value(typing["handle"])
            value = read if read is not None else typing["buffer"].text()
            if read is not None and read == typing["initial"]:
                return  # escribió y deshizo: no hay cambio
        text = phrases.describe_input(element, value, secret)
        label_value = "" if secret else value[:4000]
        self._record("input", element, text, value=label_value, secret=bool(secret), point=typing["point"])

    # ── API pública de edición (hilo Tk: solo encola) ───────

    def note(self, text: str = "", step_id: str | None = None) -> str:
        step_id = step_id or storage.uid()
        if self.recording and not self.paused:
            self._enqueue({"type": "note", "text": text, "id": step_id})
        return step_id

    def update_step_description(self, step_id: str, text: str) -> None:
        self._enqueue({"type": "edit_desc", "id": step_id, "text": text})

    def delete_step(self, step_id: str) -> None:
        self._enqueue({"type": "del_step", "id": step_id})

    def move_step(self, step_id: str, delta: int) -> None:
        self._enqueue({"type": "move_step", "id": step_id, "delta": delta})

    # ── guardado del paso (hilo worker) ─────────────────────

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    def _build_coords(self, element, pos, monitor_info) -> dict:
        cx, cy = int(pos[0]), int(pos[1])
        coords: dict = {"click_desktop": {"x": cx, "y": cy}, "element": None, "window": None, "monitor": None}
        rect = (element or {}).get("rect")
        if rect and rect.get("width") and rect.get("height"):
            coords["element"] = {
                "offset_x": cx - rect["x"], "offset_y": cy - rect["y"],
                "center": {"x": rect["x"] + rect["width"] // 2, "y": rect["y"] + rect["height"] // 2},
                "norm_x": self._clamp01((cx - rect["x"]) / rect["width"]),
                "norm_y": self._clamp01((cy - rect["y"]) / rect["height"]),
            }
        wr = (element or {}).get("window_rect")
        if wr and wr.get("width") and wr.get("height"):
            coords["window"] = {
                "offset_x": cx - wr["x"], "offset_y": cy - wr["y"],
                "norm_x": self._clamp01((cx - wr["x"]) / wr["width"]),
                "norm_y": self._clamp01((cy - wr["y"]) / wr["height"]),
            }
        if monitor_info and monitor_info.get("width") and monitor_info.get("height"):
            mon = dict(monitor_info)
            mon["norm_x"] = self._clamp01((cx - mon["left"]) / mon["width"])
            mon["norm_y"] = self._clamp01((cy - mon["top"]) / mon["height"])
            coords["monitor"] = mon
        return coords

    def _record(self, kind, element, suggestion, value="", secret=False, point=None, step_id=None) -> str | None:
        with self._lock:
            session = self._session
        if not session:
            log.warning("_record sin sesión activa")
            return None
        rect = (element or {}).get("rect")
        if point is not None:
            pos = (int(point[0]), int(point[1]))
        elif rect:
            pos = (rect["x"] + rect["width"] // 2, rect["y"] + rect["height"] // 2)
        else:
            pos = self.backend.cursor_position()

        full = zoom = None
        monitor_info = None
        try:
            image, local_rect, monitor_info = capture.grab_for_point(pos[0], pos[1], rect)
            limit = int(self._setting("capture_max_width", 2560) or 0)
            full, zoom = annotate.annotate(image, local_rect)
            if limit and full.width > limit:
                full = full.resize((limit, round(full.height * limit / full.width)))
        except Exception:
            log.exception("fallo en captura/anotación; el paso se guarda sin imagen")

        if secret and element:
            element.pop("value_text", None)

        with self._lock:
            seq = session.get("image_seq", 0) + 1
            session["image_seq"] = seq
        base = f"img-{seq:04d}"
        full_name = zoom_name = ""
        try:
            if full is not None:
                storage.put_image(session["id"], f"{base}.png", full)
                full_name = f"{base}.png"
            if zoom is not None:
                storage.put_image(session["id"], f"{base}-zoom.png", zoom)
                zoom_name = f"{base}-zoom.png"
        except Exception:
            log.exception("no se pudieron guardar las imágenes del paso")

        step = {
            "id": step_id or storage.uid(),
            "kind": kind,
            "suggestion": (suggestion or "").strip(),
            "description": (suggestion or "").strip(),
            "app": (element or {}).get("app", ""),
            "window": (element or {}).get("window", ""),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "value": value,
            "secret": secret,
            "element": element,
            "selectors": self.backend.build_selectors(element) if element else {},
            "reliability": (element or {}).get("reliability"),
            "full_image": full_name,
            "zoom_image": zoom_name,
            "thumb_image": "",
            "hide_image": False,
            "label": phrases.control_card(element),
            "coords": self._build_coords(element, pos, monitor_info),
        }
        with self._lock:
            session["steps"].append(step)
            step["index"] = len(session["steps"])
            storage.save_session(session)
        log.info("paso %s (%s) [fiabilidad=%s]", step["index"], kind, (step["reliability"] or {}).get("level", "-"))
        self._notify()
        return step["id"]

    def _promote_double(self, step_id: str, element) -> None:
        with self._lock:
            session = self._session
            for step in (session or {}).get("steps", []):
                if step.get("id") == step_id:
                    text = phrases.describe_click(step.get("element") or element, "double_click")
                    if step.get("description") == step.get("suggestion"):
                        step["description"] = text
                    step["suggestion"] = text
                    step["kind"] = "double_click"
                    storage.save_session(session)
                    break
        self._notify()

    # ── handlers de edición (hilo worker, único escritor) ──

    def _find(self, step_id):
        session = self._session or {}
        for pos, step in enumerate(session.get("steps", [])):
            if step.get("id") == step_id:
                return session, pos, step
        return session, -1, None

    def _edit_desc(self, step_id: str, text: str) -> None:
        with self._lock:
            session, _, step = self._find(step_id)
            if step is None:
                return
            step["description"] = text.strip() or step.get("suggestion", "")
            storage.save_session(session)
        self._notify()

    def _del_step(self, step_id: str) -> None:
        with self._lock:
            session, pos, step = self._find(step_id)
            if step is None:
                return
            storage.delete_images(session["id"], [step.get("full_image"), step.get("zoom_image")])
            session["steps"].pop(pos)
            for i, s in enumerate(session["steps"], start=1):
                s["index"] = i
            storage.save_session(session)
        self._notify()

    def _move_step(self, step_id: str, delta: int) -> None:
        with self._lock:
            session, pos, step = self._find(step_id)
            steps = session.get("steps", [])
            new = pos + delta
            if step is None or not 0 <= new < len(steps):
                return
            steps[pos], steps[new] = steps[new], steps[pos]
            for i, s in enumerate(steps, start=1):
                s["index"] = i
            storage.save_session(session)
        self._notify()
