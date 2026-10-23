"""Pantalla inicial del híbrido: elegir entre grabar en la web o en el escritorio.

Web pide la URL y abre el navegador predeterminado; Escritorio abre el
grabador de siempre (UI Automation en Windows, Accesibilidad en macOS). La
elección y la última URL se recuerdan en settings.json.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app import APP_NAME
from app.core.paths import IS_MAC
from app.core.settings import Settings
from app.ui import theme as ut

from .. import __version__
from ..web import browser as web_browser

WEB = "web"
DESKTOP = "desktop"

WEB_TEXT = ("Aplicaciones en el navegador: portales, SaaS, intranet. "
            "Captura selector CSS, XPath, id y URL de cada elemento.")
if IS_MAC:
    WEB_TEXT += " No necesita permisos de macOS."
    DESKTOP_TEXT = ("Cualquier app de macOS: ERP, utilidades, apps nativas. Usa la Accesibilidad "
                    "(rol AX, AXIdentifier, AppleScript) y necesita permisos de macOS.")
else:
    DESKTOP_TEXT = ("Cualquier programa de Windows: ERP, SAP GUI, apps nativas. "
                    "Usa UI Automation (AutomationId, selectores UiPath / pywinauto).")


def fit_geometry(win: tk.Misc, width: int, height: int) -> None:
    """Tamaño pensado a 100 % de escala, ajustado al DPI real y a la pantalla.

    Con la escala de Windows al 150 % las fuentes crecen pero las medidas en
    píxeles no: sin esto la ventana se queda corta y corta el contenido. En
    macOS Tk ya trabaja en puntos y el factor queda en 1.
    """
    factor = max(1.0, float(win.tk.call("tk", "scaling")) / (96 / 72))
    w = min(round(width * factor), win.winfo_screenwidth() - 40)
    h = min(round(height * factor), win.winfo_screenheight() - 120)
    win.geometry(f"{w}x{h}")


def wrap_to_width(label: tk.Widget) -> None:
    """El texto del label se reparte en líneas según el ancho disponible."""
    label.bind("<Configure>", lambda e: label.config(wraplength=max(100, e.width - 8)))


def normalize_url(raw: str) -> str:
    """Completa el esquema si falta ("intranet/app" -> "https://intranet/app")."""
    url = (raw or "").strip()
    if not url:
        return ""
    if "://" not in url and not url.startswith(("about:", "file:", "data:")):
        url = "https://" + url
    return url


class ModeChooser(tk.Tk):
    """Ventana de elección. Tras cerrarse, ``choice`` es (modo, url) o None."""

    def __init__(self, settings: Settings):
        super().__init__()
        ut.resolve_mono()
        self.settings = settings
        self.choice: tuple[str, str] | None = None
        self.title(APP_NAME)
        fit_geometry(self, 480, 540)
        self.configure(bg=ut.BG)
        self._mode = tk.StringVar(value=settings.get("hybrid.mode", WEB) or WEB)
        try:
            self._browser = web_browser.pick()
            self._browser_error = ""
        except web_browser.BrowserError as err:
            self._browser, self._browser_error = None, str(err)
        self._setup_style()
        self._build()
        self._sync()
        self.bind("<Return>", lambda e: self._continue())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=ut.BG, foreground=ut.INK, font=ut.FONT_BODY)
        style.configure("TFrame", background=ut.BG)
        style.configure("TLabel", background=ut.BG, foreground=ut.INK)
        style.configure("Muted.TLabel", background=ut.BG, foreground=ut.MUTED, font=ut.FONT_CAPTION)
        style.configure("TEntry", fieldbackground=ut.CARD, padding=ut.SPACE_1)
        style.configure("Card.TFrame", background=ut.CARD)
        style.configure(
            "Accent.TButton", background=ut.BRAND, foreground=ut.BRAND_ON,
            font=ut.FONT_BODY_STRONG, padding=ut.SPACE_3, borderwidth=0,
        )
        style.map("Accent.TButton", background=[("active", ut.BRAND_ACTIVE), ("disabled", ut.BRAND_DISABLED)])

    def _build(self):
        head = ttk.Frame(self, padding=(ut.SPACE_5, ut.SPACE_5, ut.SPACE_5, ut.SPACE_2))
        head.pack(fill="x")
        tk.Label(head, text="RPA Step Recorder", bg=ut.BG, fg=ut.INK, font=ut.FONT_H2).pack(anchor="w")
        tk.Label(head, text=f"Híbrido {__version__} · ¿Qué proceso vas a documentar?", bg=ut.BG, fg=ut.MUTED,
                 font=ut.FONT_SMALL).pack(anchor="w", pady=(ut.SPACE_1, 0))

        body = ttk.Frame(self, padding=(ut.SPACE_5, ut.SPACE_3))
        body.pack(fill="both", expand=True)

        self._cards = {}
        self._cards[WEB] = self._card(body, WEB, "Web", WEB_TEXT)
        # La URL va dentro de la opción Web: solo se pide si se elige.
        self._url_box = ttk.Frame(self._cards[WEB]["frame"], style="Card.TFrame")
        tk.Label(self._url_box, text="URL de inicio", bg=ut.CARD, fg=ut.INK,
                 font=ut.FONT_SMALL_STRONG).pack(anchor="w")
        self._url = ttk.Entry(self._url_box)
        self._url.insert(0, self.settings.get("hybrid.last_url", "") or "")
        self._url.pack(fill="x", pady=(ut.SPACE_1, ut.SPACE_1))
        self._browser_note = tk.Label(self._url_box, text="", bg=ut.CARD, fg=ut.MUTED, font=ut.FONT_CAPTION,
                                      anchor="w", justify="left")
        self._browser_note.pack(fill="x")
        wrap_to_width(self._browser_note)

        self._cards[DESKTOP] = self._card(body, DESKTOP, "Escritorio", DESKTOP_TEXT)

        self._go = ttk.Button(self, text="Continuar", style="Accent.TButton", command=self._continue)
        self._go.pack(fill="x", padx=ut.SPACE_5, pady=(0, ut.SPACE_5))

    def _card(self, parent, mode: str, title: str, text: str) -> dict:
        frame = tk.Frame(parent, bg=ut.CARD, highlightthickness=2, highlightbackground=ut.BORDER,
                         padx=ut.SPACE_4, pady=ut.SPACE_3, cursor="hand2")
        frame.pack(fill="x", pady=(0, ut.SPACE_3))
        top = tk.Frame(frame, bg=ut.CARD)
        top.pack(fill="x")
        radio = tk.Radiobutton(top, variable=self._mode, value=mode, command=self._sync, bg=ut.CARD,
                               activebackground=ut.CARD, highlightthickness=0, takefocus=True)
        radio.pack(side="left")
        tk.Label(top, text=title, bg=ut.CARD, fg=ut.INK, font=ut.FONT_H3).pack(side="left")
        desc = tk.Label(frame, text=text, bg=ut.CARD, fg=ut.MUTED, font=ut.FONT_SMALL, justify="left", anchor="w")
        desc.pack(fill="x", pady=(ut.SPACE_1, 0))
        wrap_to_width(desc)
        for widget in (frame, top, desc):
            widget.bind("<Button-1>", lambda e, m=mode: self._select(m))
        return {"frame": frame, "radio": radio}

    def _select(self, mode: str):
        self._mode.set(mode)
        self._sync()

    def _sync(self):
        mode = self._mode.get()
        for key, card in self._cards.items():
            # Mismo color con y sin foco: si no, macOS pinta de negro la tarjeta con el foco.
            color = ut.BRAND if key == mode else ut.BORDER
            card["frame"].config(highlightbackground=color, highlightcolor=color)
        if mode == WEB:
            self._url_box.pack(fill="x", pady=(ut.SPACE_3, 0))
            if self._browser is None:
                note = self._browser_error
            else:
                note = self._browser.note or f"Se abrirá en {self._browser.name}, tu navegador predeterminado."
                note += " Usa una ventana con perfil propio para la grabación."
            self._browser_note.config(text=note)
            self._go.config(text="Abrir navegador")
            self._url.focus_set()
        else:
            self._url_box.pack_forget()
            self._go.config(text="Continuar")

    def _continue(self):
        mode = self._mode.get()
        url = ""
        if mode == WEB:
            if self._browser is None:
                messagebox.showerror(APP_NAME, self._browser_error, parent=self)
                return
            url = normalize_url(self._url.get())
            if not url:
                messagebox.showinfo(APP_NAME, "Escribe la URL de la página donde empieza el proceso.", parent=self)
                self._url.focus_set()
                return
            self.settings.set("hybrid.last_url", url)
        self.settings.set("hybrid.mode", mode)
        self.choice = (mode, url)
        self.destroy()
