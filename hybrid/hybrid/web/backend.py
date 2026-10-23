"""Backend web: graba dentro del navegador a través del protocolo CDP.

En vez de hooks globales de ratón y teclado, el backend se engancha a cada
pestaña (y a cada iframe de otro dominio) del navegador de grabación e inyecta
``agent.js`` en un mundo aislado. El agente describe el elemento del DOM y
llama a la función puente; aquí llega como ``Runtime.bindingCalled``.

Hilos:
  - Lector CDP: recibe eventos. No espera respuestas; si el evento es un
    paso, pide la captura de inmediato (``send_async``) para retratar la
    página antes de que el clic la cambie, y se lo pasa al grabador.
  - Preparación: engancha pestañas e iframes nuevos (necesita respuestas).
  - Worker del grabador: espera la captura y guarda el paso.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import queue
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Callable

from PIL import Image

from app.backends.base import Backend, HookError

from . import browser as web_browser
from . import elements
from .cdp import CDPConnection, CDPError

log = logging.getLogger("rpa.web")

BINDING = "__rpaEmit"
WORLD = "rpa-step-recorder"
SHOT_TIMEOUT = 6.0


def _agent_source() -> str:
    """Código del agente (junto a este módulo, o en el .exe bajo _MEIPASS)."""
    import sys

    here = Path(__file__).resolve().parent / "agent.js"
    meipass = getattr(sys, "_MEIPASS", "")
    for candidate in (Path(meipass) / "hybrid" / "web" / "agent.js" if meipass else None, here):
        if candidate and candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError("agent.js")


class WebBackend(Backend):
    name = "web"
    label = "Navegador web (CDP)"
    inspection = True

    def __init__(self):
        self.browser: web_browser.BrowserInfo | None = None
        self.browser_error = ""
        try:
            self.browser = web_browser.pick()
        except web_browser.BrowserError as err:
            self.browser_error = str(err)
        self.start_url = ""
        self._agent = _agent_source()
        self._conn: CDPConnection | None = None
        self._lock = threading.RLock()
        self._pages: dict[str, dict] = {}       # targetId -> {"session", "url", "title"}
        self._sessions: dict[str, str] = {}     # sessionId -> sessionId de su pestaña
        self._attaching: set[str] = set()
        self._last_page: str | None = None
        self._listener: Callable | None = None
        self._on_lost: Callable | None = None
        self._setup: queue.Queue = queue.Queue()
        threading.Thread(target=self._setup_loop, name="rpa-web-setup", daemon=True).start()

    # ── API para el grabador y la interfaz ──────────────────

    def set_listener(self, on_event: Callable, on_lost: Callable | None = None) -> None:
        """``on_event(page_session, data, shoot)`` corre en el hilo lector."""
        self._listener = on_event
        self._on_lost = on_lost

    @property
    def browser_name(self) -> str:
        return self.browser.name if self.browser else "navegador"

    def connected(self) -> bool:
        conn = self._conn
        return bool(conn and not conn.closed)

    def open(self, url: str) -> None:
        """Abre ``url``: lanza el navegador de grabación o navega en el ya abierto."""
        if self.browser is None:
            raise web_browser.BrowserError(self.browser_error or "No hay un navegador compatible.")
        url = url or "about:blank"
        if self.connected():
            self._navigate(url)
            return
        endpoint = web_browser.running_endpoint(self.browser)
        if endpoint:
            self._connect(endpoint)
            self._conn.send("Target.createTarget", {"url": url})
            return
        self._connect(web_browser.launch(self.browser, url))

    def disconnect(self) -> None:
        """Suelta el navegador sin cerrarlo (al salir de la app)."""
        conn, self._conn = self._conn, None
        if conn:
            conn.close()
        with self._lock:
            self._pages.clear()
            self._sessions.clear()

    def current_page(self) -> dict:
        """{"url", "title"} de la pestaña con la que se interactuó por última vez."""
        return self.page_info(self._page_session())

    def page_info(self, page_session: str | None) -> dict:
        """{"url", "title"} de la pestaña enganchada con ``page_session``."""
        with self._lock:
            for page in self._pages.values():
                if page_session and page.get("session") == page_session:
                    return {"url": page.get("url", ""), "title": page.get("title", "")}
        return {"url": "", "title": ""}

    def request_shot(self, page_session: str | None) -> Future:
        """Pide la captura de la pestaña sin esperar (seguro desde el hilo lector)."""
        conn = self._conn
        session = page_session or self._page_session()
        if conn is None or session is None:
            future: Future = Future()
            future.set_exception(CDPError("sin pestaña que capturar"))
            return future
        return conn.send_async("Page.captureScreenshot", {"format": "png"}, session)

    @staticmethod
    def shot_image(future: Future) -> Image.Image:
        """Espera la captura pedida y la devuelve como imagen RGB."""
        data = future.result(SHOT_TIMEOUT)["data"]
        image = Image.open(io.BytesIO(base64.b64decode(data)))
        image.load()
        return image.convert("RGB")

    # ── Backend ─────────────────────────────────────────────

    def start_hooks(self, on_mouse, on_key) -> None:
        """Al empezar a grabar: asegura que el navegador está abierto y enganchado."""
        if self.connected():
            return
        try:
            self.open(self.start_url)
        except (web_browser.BrowserError, CDPError, OSError) as err:
            raise HookError(str(err)) from err

    def stop_hooks(self) -> None:
        """Detener la grabación no cierra el navegador: el grabador ignora sus eventos."""

    def hooks_alive(self) -> bool:
        return self.connected()

    def build_selectors(self, element: dict | None) -> dict:
        return elements.build_selectors(element, self.browser.process if self.browser else "")

    def environment_warnings(self) -> list[str]:
        return []

    # ── conexión ────────────────────────────────────────────

    def _connect(self, ws_url: str) -> None:
        self.disconnect()
        conn = CDPConnection(ws_url, self._on_event, self._on_close)
        self._conn = conn
        conn.send("Target.setDiscoverTargets", {"discover": True})
        log.info("conectado a %s", self.browser_name)

    def _on_close(self, conn: CDPConnection) -> None:
        # Una conexión soltada a propósito (o ya reemplazada) no es una pérdida.
        if conn is not self._conn:
            return
        with self._lock:
            self._pages.clear()
            self._sessions.clear()
        log.info("el navegador de grabación se cerró")
        if self._on_lost:
            self._on_lost()

    def _page_session(self) -> str | None:
        with self._lock:
            sessions = {p.get("session") for p in self._pages.values() if p.get("session")}
            if self._last_page in sessions:
                return self._last_page
            return next(iter(sessions), None)

    def _navigate(self, url: str) -> None:
        session = self._page_session()
        if session is None:
            self._conn.send("Target.createTarget", {"url": url})
            return
        self._conn.send("Page.navigate", {"url": url}, session)
        try:
            self._conn.send("Page.bringToFront", {}, session, timeout=3)
        except CDPError:
            pass

    # ── eventos (hilo lector: nunca espera respuestas) ──────

    def _on_event(self, method: str, params: dict, session_id: str | None) -> None:
        if method == "Runtime.bindingCalled":
            if params.get("name") != BINDING:
                return
            try:
                data = json.loads(params.get("payload") or "{}")
            except ValueError:
                return
            with self._lock:
                page = self._sessions.get(session_id or "", session_id)
                self._last_page = page
                # El marco superior manda URL y título actuales; Chrome los avisa
                # tarde y los iframes no los conocen, así que se guardan aquí.
                if data.get("url"):
                    for info in self._pages.values():
                        if info.get("session") == page:
                            info["url"], info["title"] = data["url"], data.get("title") or info.get("title", "")
                            break
            if self._listener:
                self._listener(page, data, lambda: self.request_shot(page))
        elif method in ("Target.targetCreated", "Target.targetInfoChanged"):
            info = params.get("targetInfo") or {}
            if info.get("type") != "page" or info.get("subtype") == "prerender":
                return
            with self._lock:
                page = self._pages.setdefault(info["targetId"], {})
                page["url"] = info.get("url", "")
                page["title"] = info.get("title", "")
                new = "session" not in page and info["targetId"] not in self._attaching
                if new:
                    self._attaching.add(info["targetId"])
            if new and not info.get("url", "").startswith(("devtools://", "chrome-extension://")):
                self._setup.put(("page", info["targetId"]))
        elif method == "Target.targetDestroyed":
            with self._lock:
                page = self._pages.pop(params.get("targetId", ""), None)
                if page and page.get("session"):
                    self._sessions = {s: root for s, root in self._sessions.items() if root != page["session"]}
        elif method == "Target.attachedToTarget" and session_id:
            # Iframe de otro dominio (proceso propio) dentro de una pestaña ya enganchada.
            info = params.get("targetInfo") or {}
            child = params.get("sessionId")
            if info.get("type") == "iframe" and child:
                with self._lock:
                    self._sessions[child] = self._sessions.get(session_id, session_id)
                self._setup.put(("frame", child))
        elif method == "Target.detachedFromTarget":
            with self._lock:
                self._sessions.pop(params.get("sessionId", ""), None)

    # ── preparación de pestañas e iframes (hilo propio) ─────

    def _setup_loop(self) -> None:
        while True:
            kind, ident = self._setup.get()
            conn = self._conn
            if conn is None or conn.closed:
                with self._lock:
                    self._attaching.discard(ident)
                continue
            try:
                if kind == "page":
                    session = conn.send("Target.attachToTarget", {"targetId": ident, "flatten": True})["sessionId"]
                    with self._lock:
                        self._sessions[session] = session
                        self._pages.setdefault(ident, {})["session"] = session
                        self._attaching.discard(ident)
                    self._prepare(conn, session)
                else:
                    self._prepare(conn, ident)
            except CDPError as err:
                with self._lock:
                    self._attaching.discard(ident)
                log.info("no se pudo preparar %s: %s", kind, err)

    def _prepare(self, conn: CDPConnection, session: str) -> None:
        """Inyecta el agente (también en lo ya cargado) y sigue a los iframes."""
        conn.send("Page.enable", {}, session)
        conn.send("Runtime.enable", {}, session)
        conn.send("Runtime.addBinding", {"name": BINDING, "executionContextName": WORLD}, session)
        conn.send("Page.addScriptToEvaluateOnNewDocument",
                  {"source": self._agent, "worldName": WORLD, "runImmediately": True}, session)
        conn.send("Target.setAutoAttach",
                  {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True}, session)
