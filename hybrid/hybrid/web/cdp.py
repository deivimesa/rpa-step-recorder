"""Cliente mínimo del Chrome DevTools Protocol (CDP) sobre WebSocket.

Un hilo lector recibe todos los mensajes: las respuestas resuelven el
``Future`` de su orden (por id) y los eventos van al callback ``on_event``.
El callback corre en el hilo lector, así que NUNCA debe esperar una
respuesta (se bloquearía a sí mismo); puede enviar órdenes con ``send_async``.

Solo escucha en 127.0.0.1 y no envía cabecera Origin: el navegador acepta la
conexión sin necesidad de abrir --remote-allow-origins.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
from concurrent.futures import Future
from typing import Callable

import websocket

log = logging.getLogger("rpa.cdp")


class CDPError(Exception):
    """El navegador respondió con un error o la conexión se cerró."""


class CDPConnection:
    def __init__(self, ws_url: str, on_event: Callable[[str, dict, str | None], None],
                 on_close: Callable[["CDPConnection"], None] | None = None):
        self._ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=10)
        self._ws.settimeout(None)
        self._on_event = on_event
        self._on_close = on_close
        self._ids = itertools.count(1)
        self._pending: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._reader = threading.Thread(target=self._read_loop, name="rpa-cdp", daemon=True)
        self._reader.start()

    @property
    def closed(self) -> bool:
        return self._closed

    def send_async(self, method: str, params: dict | None = None, session_id: str | None = None) -> Future:
        """Envía una orden sin esperar; el Future se resuelve con su ``result``."""
        future: Future = Future()
        msg_id = next(self._ids)
        message = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        with self._lock:
            if self._closed:
                future.set_exception(CDPError("conexión cerrada"))
                return future
            self._pending[msg_id] = future
        try:
            self._ws.send(json.dumps(message))
        except Exception as err:  # noqa: BLE001 - socket roto: se informa al que espera
            with self._lock:
                self._pending.pop(msg_id, None)
            future.set_exception(CDPError(f"{method}: {err}"))
        return future

    def send(self, method: str, params: dict | None = None, session_id: str | None = None,
             timeout: float = 10.0) -> dict:
        """Envía una orden y espera su resultado (no usar desde el hilo lector)."""
        future = self.send_async(method, params, session_id)
        try:
            return future.result(timeout)
        except TimeoutError as err:
            raise CDPError(f"{method}: sin respuesta en {timeout:.0f} s") from err

    def close(self) -> None:
        self._closed = True
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001
            pass

    def _read_loop(self) -> None:
        try:
            while True:
                raw = self._ws.recv()
                if not raw or self._closed:
                    break
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if "id" in message:
                    with self._lock:
                        future = self._pending.pop(message["id"], None)
                    if future is None or future.done():
                        continue
                    if "error" in message:
                        future.set_exception(CDPError(message["error"].get("message", "error")))
                    else:
                        future.set_result(message.get("result") or {})
                elif "method" in message:
                    try:
                        self._on_event(message["method"], message.get("params") or {}, message.get("sessionId"))
                    except Exception:
                        log.exception("fallo procesando el evento %s", message.get("method"))
        except Exception as err:  # noqa: BLE001 - el navegador se cerró o cortó la conexión
            if not self._closed:
                log.info("conexión CDP terminada: %s", err)
        finally:
            with self._lock:
                self._closed = True
                pending, self._pending = list(self._pending.values()), {}
            for future in pending:
                if not future.done():
                    future.set_exception(CDPError("el navegador cerró la conexión"))
            if self._on_close:
                try:
                    self._on_close(self)
                except Exception:
                    log.exception("fallo en on_close")
