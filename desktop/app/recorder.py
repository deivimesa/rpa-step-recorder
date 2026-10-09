"""Grabador: hooks globales de ratón/teclado que orquestan la captura de pasos.

Reemplaza background.js (estado + grabación) y los listeners de content.js.
Al hacer clic sobre cualquier aplicación de escritorio:
  1. se inspecciona el elemento bajo el cursor (UI Automation),
  2. se captura el monitor y se anota el recuadro rojo,
  3. se guarda el paso con su descripción sugerida.

Diseño: los listeners de pynput solo encolan eventos; un ÚNICO hilo worker
los procesa en orden. Así UI Automation (COM) se inicializa una sola vez en
ese hilo, no hay condiciones de carrera y ningún clic se descarta por locks.

El teclado se agrupa por campo: lo que se escribe en un control editable se
registra como un único paso cuando el foco cambia o se pulsa Enter, nunca
tecla por tecla (así no se filtran contraseñas).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from datetime import datetime
from pathlib import Path

from pynput import keyboard, mouse

from . import annotate, capture, inspector, selectors, storage


def _log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = Path(base) / "RPAStepRecorder"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "recorder.log"


logging.basicConfig(
    filename=str(_log_path()),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("recorder")


class Recorder:
    def __init__(self, on_change=None):
        self.session_id: str | None = None
        self.recording = False
        self.paused = False
        self._on_change = on_change
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_stop = threading.Event()
        # Acumulador de escritura.
        self._typing: dict | None = None

    # ── estado ──────────────────────────────────────────────

    def _notify(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                log.exception("fallo en on_change")

    def current_session(self) -> dict | None:
        return storage.get_session(self.session_id) if self.session_id else None

    # ── ciclo de vida ───────────────────────────────────────

    def start_session(self, name: str, author: str, system: str) -> dict:
        now = datetime.now()
        title = (name or "").strip() or f"Proceso {now.strftime('%d/%m/%Y %H:%M')}"
        session = {
            "id": storage.uid(),
            "name": title,
            "author": (author or "").strip(),
            "system": (system or "").strip(),
            "started_at": now.isoformat(),
            "finished_at": "",
            "steps": [],
            # Contador propio de la sesión para nombrar las imágenes de forma
            # independiente del index (así borrar/reordenar nunca colisiona).
            "image_seq": 0,
        }
        storage.save_session(session)
        self.session_id = session["id"]
        self.recording = True
        self.paused = False
        self._typing = None
        log.info("sesión iniciada: %s (%s)", session["id"], title)
        self._start_worker()
        self._start_hooks()
        self._notify()
        return session

    def resume_session(self, session_id: str) -> dict:
        session = storage.get_session(session_id)
        if not session:
            raise ValueError("Esa grabación ya no existe")
        session["finished_at"] = ""
        # Sesiones antiguas pueden no tener contador de imágenes: lo inicializamos
        # a partir de los pasos existentes para no reutilizar nombres.
        if "image_seq" not in session:
            session["image_seq"] = len(session.get("steps", []))
        storage.save_session(session)
        self.session_id = session_id
        self.recording = True
        self.paused = False
        self._start_worker()
        self._start_hooks()
        self._notify()
        return session

    def set_paused(self, paused: bool) -> bool:
        self._enqueue({"type": "flush"})
        self.paused = bool(paused)
        log.info("pausa: %s", self.paused)
        self._notify()
        return self.paused

    def stop_session(self) -> dict | None:
        self._enqueue({"type": "flush"})
        self._stop_hooks()
        self._stop_worker()
        session = self.current_session()
        if session:
            session["finished_at"] = datetime.now().isoformat()
            storage.save_session(session)
        self.recording = False
        self.paused = False
        log.info("sesión detenida; pasos: %s", len(session["steps"]) if session else 0)
        self._notify()
        return session

    # ── worker ──────────────────────────────────────────────

    def _start_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker_stop.clear()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def _stop_worker(self):
        self._worker_stop.set()
        self._enqueue({"type": "stop"})
        if self._worker:
            self._worker.join(timeout=5)
        self._worker = None

    def _enqueue(self, event: dict):
        self._queue.put(event)

    def _run_worker(self):
        # UI Automation vive sobre COM: hay que inicializarlo en ESTE hilo,
        # que es el único que tocará los controles.
        try:
            import comtypes

            comtypes.CoInitializeEx()
        except Exception:
            log.exception("CoInitializeEx falló (puede seguir funcionando)")

        while not self._worker_stop.is_set():
            try:
                event = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process(event)
            except Exception:
                log.exception("fallo procesando evento %s", event.get("type"))
            finally:
                self._queue.task_done()

    def _process(self, event: dict):
        kind = event.get("type")
        if kind == "stop":
            return
        if kind == "flush":
            self._flush_typing()
            return
        if kind == "click":
            self._process_click(event["x"], event["y"])
        elif kind == "key":
            self._process_key(event["name"])
        elif kind == "note":
            self._flush_typing()
            self._record("note", None, "", None)
        elif kind == "edit_desc":
            self._edit_desc(event["id"], event.get("text", ""))
        elif kind == "del_step":
            self._del_step(event["id"])
        elif kind == "move_step":
            self._move_step(event["id"], int(event.get("delta", 0)))

    # ── hooks ───────────────────────────────────────────────

    def _start_hooks(self):
        self._stop_hooks()
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key)
        self._mouse_listener.start()
        self._keyboard_listener.start()
        log.info("hooks activos")

    def _stop_hooks(self):
        for name in ("_mouse_listener", "_keyboard_listener"):
            listener = getattr(self, name, None)
            if listener:
                listener.stop()
            setattr(self, name, None)

    # ── eventos de entrada (solo encolan) ───────────────────

    def _on_click(self, x, y, button, pressed):
        try:
            if not pressed or button != mouse.Button.left:
                return
            if not self.recording or self.paused:
                return
            # El clic cierra cualquier escritura pendiente y luego se procesa.
            self._enqueue({"type": "flush"})
            self._enqueue({"type": "click", "x": x, "y": y})
        except Exception:
            log.exception("fallo en _on_click")

    def _on_key(self, key):
        # Cualquier excepción no capturada aquí detendría el listener de
        # pynput de forma silenciosa, así que todo el cuerpo va protegido.
        try:
            if not self.recording or self.paused:
                return
            try:
                char = key.char
            except AttributeError:
                char = None

            if key == keyboard.Key.enter:
                self._enqueue({"type": "flush"})
                self._enqueue({"type": "key", "name": "Enter"})
                return
            if key == keyboard.Key.esc:
                self._enqueue({"type": "key", "name": "Escape"})
                return

            # Acumula escritura sobre el campo marcado al hacer clic. Se toma un
            # snapshot local porque el hilo worker puede poner self._typing =
            # None en cualquier momento.
            typing = self._typing
            if typing is not None:
                if char is not None:
                    typing["text"] += char
                elif key == keyboard.Key.backspace:
                    typing["text"] = typing["text"][:-1]
        except Exception:
            log.exception("fallo en _on_key")

    # ── procesamiento (en el hilo worker) ───────────────────

    def _process_click(self, x, y):
        element = inspector.inspect_point(x, y)
        if not element:
            log.info("clic en (%s,%s): sin elemento inspeccionable", x, y)
            return
        # Nunca grabamos clics sobre las ventanas del propio grabador.
        if inspector.es_ventana_propia(element):
            log.info("clic en (%s,%s): ignorado: ventana propia", x, y)
            return
        role = inspector.role_of(element)
        log.info("clic en (%s,%s): %s «%s»", x, y, role, element.get("name", ""))
        if role in inspector.EDITABLE_TYPES:
            self._typing = {"element": element, "text": "", "role": role}
            return
        suggestion = inspector.describe(element, role)
        label = inspector.control_card(role, element.get("name", ""))
        self._record("click", element, suggestion, label, click_point=(x, y))

    def _process_key(self, key_name: str):
        from pynput.mouse import Controller

        # La tecla pertenece al control CON EL FOCO de teclado, no al que está
        # bajo el ratón. Inspeccionamos el foco y usamos el ratón solo como
        # respaldo para las coordenadas de la captura.
        element = inspector.inspect_focused()
        if not element:
            pos = Controller().position
            element = inspector.inspect_point(int(pos[0]), int(pos[1]))
        # Si el foco está en una ventana propia, no grabamos la tecla.
        if element and inspector.es_ventana_propia(element):
            log.info("tecla %s: ignorado: ventana propia", key_name)
            return
        rect = element.get("rect") if element else None
        if rect and rect.get("width"):
            click_point = (rect["x"] + rect["width"] // 2, rect["y"] + rect["height"] // 2)
        else:
            p = Controller().position
            click_point = (int(p[0]), int(p[1]))
        name = element.get("name", "") if element else ""
        suggestion = f"Pulsar {key_name}" + (f" en «{name}»" if name else "")
        label = {"role": "key", "kind": "Tecla", "name": key_name}
        self._record("key", element, suggestion, label, click_point=click_point)

    def _flush_typing(self):
        """Registra como un paso lo escrito en el campo marcado, si cambió."""
        typing = self._typing
        self._typing = None
        if not typing or not self.recording:
            return
        element = typing["element"]
        secret = inspector.is_secret(element)
        text = typing["text"]
        if not text and not secret:
            return
        name = element.get("name", "")
        if secret:
            value = ""
            suggestion = "Escribir la contraseña" + (f" en el campo «{name}»" if name else " en el campo")
        else:
            value = text if len(text) <= 80 else text[:77] + "…"
            suggestion = f"Escribir «{value}»" + (f" en el campo «{name}»" if name else " en el campo")
        label = {"role": "textbox", "kind": "Campo", "name": name}
        self._record("input", element, suggestion, label, value=value, secret=secret)

    def note(self):
        """Paso de solo nota, sin elemento (equivale a add-note)."""
        if not self.recording or self.paused:
            return
        self._enqueue({"type": "note"})

    # ── edición en vivo (API pública, solo encola) ──────────
    # La UI (hilo Tk) llama a estos métodos; cada uno únicamente encola un
    # evento. El hilo worker es el ÚNICO que relee y escribe la sesión, de modo
    # que las ediciones quedan serializadas con la captura de pasos y no hay
    # condiciones de carrera. Funcionan aunque la grabación siga activa.

    def update_step_description(self, step_id: str, text: str) -> None:
        """Encola la edición de la descripción de un paso."""
        self._enqueue({"type": "edit_desc", "id": step_id, "text": text})

    def delete_step(self, step_id: str) -> None:
        """Encola el borrado de un paso (y sus imágenes)."""
        self._enqueue({"type": "del_step", "id": step_id})

    def move_step(self, step_id: str, delta: int) -> None:
        """Encola el desplazamiento de un paso (delta negativo sube, positivo baja)."""
        self._enqueue({"type": "move_step", "id": step_id, "delta": delta})

    # ── coordenadas cartesianas ─────────────────────────────

    @staticmethod
    def _clamp01(value: float) -> float:
        """Acota un valor normalizado al rango [0, 1]."""
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value

    def _build_coords(self, element, pos, monitor_info) -> dict:
        """Construye las coordenadas ricas del paso.

        pos es (cx, cy) global del clic. Devuelve siempre un dict con, como
        mínimo, el punto global del clic. Los bloques relativos (element,
        window, monitor) se incluyen solo si hay datos; las normalizadas se
        omiten si el ancho/alto es 0. Todo va protegido para no romper el
        guardado del paso.
        """
        cx, cy = int(pos[0]), int(pos[1])
        coords: dict = {"click_desktop": {"x": cx, "y": cy}}

        # Relativo al rectángulo del elemento.
        try:
            rect = element.get("rect") if element else None
            if rect and rect.get("width") and rect.get("height"):
                rx, ry = rect["x"], rect["y"]
                rw, rh = rect["width"], rect["height"]
                el: dict = {
                    "offset_x": cx - rx,
                    "offset_y": cy - ry,
                    "center": {"x": rx + rw // 2, "y": ry + rh // 2},
                }
                if rw:
                    el["norm_x"] = self._clamp01((cx - rx) / rw)
                if rh:
                    el["norm_y"] = self._clamp01((cy - ry) / rh)
                coords["element"] = el
            else:
                coords["element"] = None
        except Exception:
            coords["element"] = None

        # Relativo al rectángulo de la ventana top-level.
        try:
            wr = element.get("window_rect") if element else None
            if wr and wr.get("width") and wr.get("height"):
                wx, wy = wr["x"], wr["y"]
                ww, wh = wr["width"], wr["height"]
                win: dict = {
                    "offset_x": cx - wx,
                    "offset_y": cy - wy,
                }
                if ww:
                    win["norm_x"] = self._clamp01((cx - wx) / ww)
                if wh:
                    win["norm_y"] = self._clamp01((cy - wy) / wh)
                coords["window"] = win
            else:
                coords["window"] = None
        except Exception:
            coords["window"] = None

        # Relativo al monitor usado para la captura.
        try:
            if monitor_info and monitor_info.get("width") and monitor_info.get("height"):
                left = monitor_info["left"]
                top = monitor_info["top"]
                width = monitor_info["width"]
                height = monitor_info["height"]
                mon: dict = {
                    "index": monitor_info.get("index"),
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                }
                if width:
                    mon["norm_x"] = self._clamp01((cx - left) / width)
                if height:
                    mon["norm_y"] = self._clamp01((cy - top) / height)
                coords["monitor"] = mon
            else:
                coords["monitor"] = None
        except Exception:
            coords["monitor"] = None

        return coords

    # ── guardado del paso (en el hilo worker) ───────────────

    def _record(self, kind, element, suggestion, label, value="", secret=False, click_point=None):
        session = self.current_session()
        if not session:
            log.warning("_record sin sesión activa")
            return

        rect = element.get("rect") if element else None
        # Preferimos el punto real del clic; si no hay, caemos al centro del
        # rect y, en último término, a la posición actual del ratón.
        if click_point is not None:
            pos = (int(click_point[0]), int(click_point[1]))
        elif rect and rect.get("width"):
            pos = (rect["x"] + rect["width"] // 2, rect["y"] + rect["height"] // 2)
        else:
            from pynput.mouse import Controller

            pos = Controller().position

        try:
            image, local_rect, monitor_info = capture.grab_for_point(int(pos[0]), int(pos[1]), rect)
            full, zoom = annotate.annotate(image, local_rect)
        except Exception:
            log.exception("fallo en captura/anotación")
            return

        # Coordenadas cartesianas ricas del paso (nunca deben romper el guardado).
        coords = self._build_coords(element, pos, monitor_info)

        # Defensa en profundidad: en un paso secreto, el element nunca debe
        # arrastrar el contenido real del campo (ValuePattern).
        if secret and element:
            element.pop("value_text", None)

        index = len(session["steps"]) + 1
        # El nombre del archivo depende de un contador propio de la sesión, NO
        # del index: así borrar o reordenar pasos nunca provoca colisiones.
        seq = session.get("image_seq", 0) + 1
        session["image_seq"] = seq
        base = f"img-{seq:04d}"
        storage.put_image(session["id"], f"{base}.png", full)
        if zoom is not None:
            storage.put_image(session["id"], f"{base}-zoom.png", zoom)

        step = {
            "id": storage.uid(),
            "index": index,
            "kind": kind,
            "suggestion": (suggestion or "").strip(),
            "description": (suggestion or "").strip(),
            "app": element.get("app", "") if element else "",
            "window": element.get("window", "") if element else "",
            "timestamp": datetime.now().isoformat(),
            "value": value,
            "secret": secret,
            "element": element,
            "selectors": selectors.build_selectors(element) if element else {},
            "reliability": element.get("reliability") if element else None,
            "full_image": f"{base}.png",
            "zoom_image": f"{base}-zoom.png" if zoom is not None else "",
            "label": label,
            "coords": coords,
        }
        session["steps"].append(step)
        storage.save_session(session)
        rel = (step.get("reliability") or {}).get("level", "-")
        log.info("paso %s guardado [fiabilidad=%s]: %s", index, rel, step["suggestion"])
        self._notify()

    # ── handlers de edición (en el hilo worker, único escritor) ──

    @staticmethod
    def _reindex(steps: list[dict]) -> None:
        """Reasigna el campo de presentación index=1..n. NO toca las imágenes."""
        for i, s in enumerate(steps, start=1):
            s["index"] = i

    def _edit_desc(self, step_id: str, text: str) -> None:
        """Actualiza la descripción de un paso buscándolo por id."""
        session = self.current_session()
        if not session:
            log.warning("edit_desc sin sesión activa")
            return
        for step in session.get("steps", []):
            if step.get("id") == step_id:
                # Si el texto queda vacío, se vuelve a la sugerencia automática.
                step["description"] = text.strip() or step.get("suggestion", "")
                storage.save_session(session)
                log.info("paso %s descripción editada", step.get("index"))
                self._notify()
                return
        log.warning("edit_desc: paso %s no encontrado", step_id)

    def _del_step(self, step_id: str) -> None:
        """Borra un paso, sus imágenes y re-indexa el resto."""
        session = self.current_session()
        if not session:
            log.warning("del_step sin sesión activa")
            return
        steps = session.get("steps", [])
        for pos, step in enumerate(steps):
            if step.get("id") == step_id:
                # Borramos las imágenes asociadas (los nombres son propios del
                # paso, independientes del index, así que no afectan a otros).
                storage.delete_images(
                    session["id"], [step.get("full_image"), step.get("zoom_image")]
                )
                steps.pop(pos)
                self._reindex(steps)
                storage.save_session(session)
                log.info("paso %s borrado", step.get("index"))
                self._notify()
                return
        log.warning("del_step: paso %s no encontrado", step_id)

    def _move_step(self, step_id: str, delta: int) -> None:
        """Mueve un paso delta posiciones (negativo sube, positivo baja)."""
        session = self.current_session()
        if not session:
            log.warning("move_step sin sesión activa")
            return
        steps = session.get("steps", [])
        for pos, step in enumerate(steps):
            if step.get("id") == step_id:
                nueva = pos + delta
                if nueva < 0 or nueva >= len(steps):
                    # Fuera de rango: no hacemos nada.
                    return
                steps[pos], steps[nueva] = steps[nueva], steps[pos]
                self._reindex(steps)
                storage.save_session(session)
                log.info("paso movido de %s a %s", pos + 1, nueva + 1)
                self._notify()
                return
        log.warning("move_step: paso %s no encontrado", step_id)
