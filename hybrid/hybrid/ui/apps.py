"""Ventanas principales del híbrido: el panel de escritorio y el panel web.

Las dos son el panel de grabación de la app de escritorio (``App``) con un
distintivo del modo y un enlace para volver a la pantalla de elección. El
panel web cambia el grabador por el del navegador y añade la URL de inicio
con el botón «Abrir navegador».
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse

from app import APP_NAME
from app.ui import theme as ut
from app.ui.main_window import App

from ..web.browser import BrowserError
from ..web.cdp import CDPError
from ..web.recorder import WebRecorder
from .chooser import fit_geometry, normalize_url, wrap_to_width

log = logging.getLogger("rpa.ui.hybrid")


class ModeSwitchMixin:
    """Distintivo del modo en la cabecera y enlace «Cambiar a ...» al pie."""

    mode_label = ""
    other_mode_label = ""
    switch_requested = False

    def _add_mode_controls(self, width: int = 460, height: int = 660):
        fit_geometry(self, width, height)
        header = self._pill.master
        tk.Label(
            header, text=self.mode_label, bg=ut.BRAND_SOFT, fg=ut.BRAND_DARK, font=ut.FONT_CAPTION_STRONG,
            padx=ut.SPACE_2, pady=ut.SPACE_1 - 1,
        ).pack(side="right", padx=(0, ut.SPACE_2))
        link = tk.Label(
            self, text=f"⇄  Cambiar a {self.other_mode_label}", bg=ut.BG, fg=ut.BRAND_DARK,
            font=ut.FONT_CAPTION, cursor="hand2", anchor="w", padx=ut.SPACE_4,
        )
        # Se empaqueta antes que el cuerpo: si falta alto, se recorta la lista, no el enlace.
        link.pack(fill="x", side="bottom", pady=(0, ut.SPACE_2), before=self._idle.master)
        link.bind("<Button-1>", lambda e: self._switch_mode())

    def _switch_mode(self):
        if self.recorder.recording:
            self._say("Detén la grabación antes de cambiar de modo.", kind="warn")
            return
        self.switch_requested = True
        self.destroy()

    def destroy(self):
        # Sin cancelar sus temporizadores, al abrir la ventana siguiente (cambio
        # de modo) Tk avisaría de comandos de esta que ya no existen.
        try:
            for after_id in self.tk.splitlist(self.tk.call("after", "info")):
                self.after_cancel(after_id)
        except tk.TclError:
            pass
        super().destroy()


class DesktopApp(ModeSwitchMixin, App):
    mode_label = "Escritorio"
    other_mode_label = "web"

    def __init__(self):
        super().__init__()
        self._add_mode_controls()


class WebApp(ModeSwitchMixin, App):
    mode_label = "Web"
    other_mode_label = "escritorio"
    live_empty_text = "Haz clic en la página del navegador para registrar el primer paso."

    def __init__(self, url: str = ""):
        self._initial_url = url
        self._opened_url = ""
        self._opening = False
        super().__init__()
        self._add_mode_controls(460, 740)
        # Con el navegador cerrado, el aviso del pie permite reabrirlo.
        self._warn.config(cursor="hand2")
        self._warn.bind("<Button-1>", lambda e: self._reopen())
        if url:
            self.after(150, self._open_browser)

    def _make_recorder(self):
        return WebRecorder(on_change=self._on_change, on_hotkey=self._on_hotkey, settings=self.settings)

    # ── interfaz ────────────────────────────────────────────

    def _build_idle(self, parent):
        super()._build_idle(parent)
        first = self._form.winfo_children()[0]
        ttk.Label(self._form, text="URL de inicio").pack(anchor="w", before=first)
        row = ttk.Frame(self._form)
        row.pack(fill="x", pady=(ut.SPACE_1, 0), before=first)
        self._url = ttk.Entry(row)
        self._url.insert(0, self._initial_url)
        self._url.pack(side="left", fill="x", expand=True)
        self._url.bind("<Return>", lambda e: self._open_browser())
        self._open_btn = ttk.Button(row, text="Abrir navegador", style="Ghost.TButton", command=self._open_browser)
        self._open_btn.pack(side="left", padx=(ut.SPACE_2, 0))
        backend = self.recorder.backend
        if backend.browser is None:
            hint = backend.browser_error
        else:
            hint = backend.browser.note or f"Se abre en {backend.browser.name} (tu navegador predeterminado)."
        note = ttk.Label(self._form, text=hint, style="Muted.TLabel", justify="left")
        note.pack(fill="x", pady=(ut.SPACE_1, ut.SPACE_3), before=first)
        wrap_to_width(note)

    # ── navegador ───────────────────────────────────────────

    def _url_value(self) -> str:
        url = normalize_url(self._url.get())
        if not url:
            messagebox.showinfo(APP_NAME, "Escribe la URL de la página donde empieza el proceso.", parent=self)
            self._url.focus_set()
        return url

    def _open_browser(self):
        """Abre (o navega) el navegador de grabación en un hilo: la ventana no se congela."""
        if self._opening:
            return
        url = self._url_value()
        if not url:
            return
        self._opening = True
        self._open_btn.state(["disabled"])
        self._say(f"Abriendo {self.recorder.backend.browser_name}…")
        result: dict = {}

        def work():
            try:
                self.recorder.backend.open(url)
            except (BrowserError, CDPError, OSError) as err:
                result["error"] = str(err)
            except Exception as err:  # noqa: BLE001 - se muestra y se registra
                log.exception("no se pudo abrir el navegador")
                result["error"] = str(err)
            self._post(lambda: self._opened(url, result.get("error")))

        threading.Thread(target=work, name="rpa-open-browser", daemon=True).start()

    def _opened(self, url: str, error: str | None):
        self._opening = False
        try:
            self._open_btn.state(["!disabled"])
        except tk.TclError:
            return
        if error:
            messagebox.showerror(APP_NAME, error, parent=self)
            return
        self._opened_url = url
        self.settings.set("hybrid.last_url", url)
        host = urlparse(url).hostname or ""
        if host and not self._system.get().strip():
            self._system.insert(0, host)
        if self.recorder.recording:
            self._say("Navegador abierto: sigue con el proceso.", kind="ok")
        else:
            self._say("Navegador listo. Ve al punto de partida y pulsa «Iniciar grabación».", kind="ok")

    def _reopen(self):
        backend = self.recorder.backend
        if self.recorder.recording and not backend.connected() and not self._opening:
            self._open_browser()

    # ── acciones ────────────────────────────────────────────

    def _start(self):
        if self._opening:
            self._say("Espera a que termine de abrirse el navegador.", kind="warn")
            return
        url = self._url_value()
        if not url:
            return
        backend = self.recorder.backend
        backend.start_url = url
        if backend.connected() and url != self._opened_url:
            # Se cambió la URL sin abrirla: se navega antes de grabar.
            try:
                backend.open(url)
            except (BrowserError, CDPError, OSError) as err:
                messagebox.showerror(APP_NAME, str(err), parent=self)
                return
        elif not backend.connected():
            self._say(f"Abriendo {backend.browser_name}…")
            self.update_idletasks()
        super()._start()
        if backend.connected():
            self._opened_url = url
            self.settings.set("hybrid.last_url", url)

    def destroy(self):
        # Se suelta el navegador sin cerrarlo: el usuario puede seguir usándolo.
        try:
            self.recorder.backend.disconnect()
        except Exception:  # noqa: BLE001
            pass
        super().destroy()
