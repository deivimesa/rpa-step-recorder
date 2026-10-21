"""Grabador web: el ``Recorder`` de escritorio alimentado por el navegador.

Reutiliza del grabador de escritorio el hilo worker, la sesión en memoria, la
edición de pasos (notas, descripciones, borrar, reordenar) y el guardado. Lo
que cambia es de dónde salen los pasos (eventos del agente web en vez de
hooks de ratón) y la captura (la de la pestaña, pedida en cuanto llega el
evento, en vez de la del monitor).
"""

from __future__ import annotations

import logging
import time

from app.core import annotate, storage
from app.core.recorder import Recorder

from . import elements
from .backend import WebBackend

log = logging.getLogger("rpa.web.recorder")

# Eventos del agente que se convierten en paso (y necesitan captura).
STEP_KINDS = {"click", "right_click", "input", "select", "key"}

# Margen para unir la segunda pulsación de un doble clic al paso anterior.
DOUBLE_CLICK_WINDOW = 1.5


class WebRecorder(Recorder):
    def __init__(self, on_change=None, on_hotkey=None, settings=None):
        super().__init__(on_change=on_change, on_hotkey=on_hotkey, settings=settings)
        self.backend = WebBackend()
        self.backend.set_listener(self._on_dom, self._on_browser_lost)
        # Captura del paso que procesa el worker; la lee _grab (mismo hilo).
        self._shot: dict | None = None
        self._last_web_click: dict | None = None

    # ── ciclo de vida ───────────────────────────────────────

    def start_session(self, name: str, author: str, system: str) -> dict:
        """Como en escritorio; la URL de inicio es ``backend.start_url`` (la fija la ventana)."""
        session = storage.new_session(name, author, system, self.backend.name)
        page = self.backend.current_page() if self.backend.connected() else {}
        session["start_url"] = page.get("url") or self.backend.start_url
        storage.save_session(session)
        return self._begin(session)

    def resume_session(self, session_id: str) -> dict:
        session = storage.get_session(session_id) or {}
        self.backend.start_url = session.get("start_url", "")
        return super().resume_session(session_id)

    def _begin(self, session: dict) -> dict:
        self._last_web_click = None
        return super()._begin(session)

    def _on_browser_lost(self) -> None:
        if self.recording:
            self.last_error = (f"Se cerró {self.backend.browser_name}. Haz clic aquí para volver a abrirlo "
                               "y seguir grabando.")
        self._notify()

    # ── eventos del agente (hilo lector CDP: solo encola) ───

    def _on_dom(self, page_session, data: dict, shoot) -> None:
        kind = data.get("kind")
        if kind == "hotkey":
            if self.recording and self._on_hotkey and self._setting("global_hotkeys"):
                self._on_hotkey(data.get("action"))
            return
        if not self.recording or self.paused:
            return
        if kind == "right_click" and not self._setting("record_right_click"):
            return
        shot = shoot() if kind in STEP_KINDS else None
        self._enqueue({"type": "web", "page": page_session, "data": data, "shot": shot})

    # ── procesamiento (hilo worker) ─────────────────────────

    def _process(self, event: dict):
        if event.get("type") == "web":
            self._process_web(event)
        else:
            super()._process(event)

    def _process_web(self, event: dict) -> None:
        data = event["data"]
        page = self.backend.current_page()
        element = elements.build_element(data, self.backend.browser_name, page.get("url", ""), page.get("title", ""))
        if data.get("kind") == "dblclick":
            last = self._last_web_click
            same = last and element and last.get("xpath") == element.get("xpath")
            if same and time.monotonic() - last["t"] <= DOUBLE_CLICK_WINDOW and self._setting("merge_double_click"):
                self._promote_double(last["step_id"], element)
            self._last_web_click = None
            return
        kind, text, value, secret = elements.describe(data, element)
        point = data.get("point")
        self._shot = {"future": event.get("shot"), "page": event.get("page"), "viewport": data.get("viewport")}
        try:
            step_id = self._record(kind, element, text, value=value, secret=bool(secret),
                                   point=(point["x"], point["y"]) if point else None)
        finally:
            self._shot = None
        if kind == "click" and step_id and element:
            self._last_web_click = {"step_id": step_id, "xpath": element.get("xpath"), "t": time.monotonic()}

    # ── captura y coordenadas (llamadas desde _record) ──────

    def _grab(self, pos, rect):
        shot = self._shot or {}
        future = shot.get("future") or self.backend.request_shot(shot.get("page"))
        image = self.backend.shot_image(future)
        viewport = shot.get("viewport") or {}
        width = float(viewport.get("width") or 0)
        # Captura en píxeles físicos; el agente mide en píxeles CSS (zoom y escala de Windows).
        scale = image.width / width if width else 1.0
        local = None
        if rect:
            local = {k: round(rect[k] * scale) for k in ("x", "y", "width", "height")}
        full, zoom = annotate.annotate(image, local)
        limit = int(self._setting("capture_max_width", 2560) or 0)
        if limit and full.width > limit:
            full = full.resize((limit, round(full.height * limit / full.width)))
        info = {"width": round(width), "height": round(float(viewport.get("height") or 0)), "scale": round(scale, 3)}
        return full, zoom, info

    def _build_coords(self, element, pos, monitor_info) -> dict:
        if not element:
            return {}
        cx, cy = round(pos[0]), round(pos[1])
        coords: dict = {"click_viewport": {"x": cx, "y": cy}, "element": None, "viewport": None}
        rect = element.get("rect")
        if rect and rect.get("width") and rect.get("height"):
            coords["element"] = {
                "offset_x": cx - rect["x"], "offset_y": cy - rect["y"],
                "center": {"x": rect["x"] + rect["width"] // 2, "y": rect["y"] + rect["height"] // 2},
                "norm_x": self._clamp01((cx - rect["x"]) / rect["width"]),
                "norm_y": self._clamp01((cy - rect["y"]) / rect["height"]),
            }
        if monitor_info and monitor_info.get("width"):
            coords["viewport"] = dict(monitor_info)
        return coords
