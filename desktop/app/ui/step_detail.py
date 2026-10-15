"""Ventana de detalle de un paso (Tkinter).

Muestra UN paso de una grabación de forma amplia y legible: la captura
completa, el detalle del elemento (zoom), la fiabilidad con sus motivos, la
identificación del elemento, los selectores RPA (con botón de copiar) y las
coordenadas.

Es un archivo nuevo e independiente, pero reutiliza los patrones de review.py
(miniaturas con Pillow + ImageTk, copiar selector al portapapeles y lista con
scroll sobre un Canvas). No modifica ni depende de la lógica del grabador.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from ..exporters import doc_common as dc
from ..core import storage
from ..backends import get_backend
from . import theme as ut

# ── Paleta y tokens (centralizados en theme.py) ─────────────
ACCENT = ut.ACCENT   # rojo de acento
INK = ut.INK         # tinta (texto principal)
MUTED = ut.MUTED     # texto tenue
BG = ut.BG           # fondo general
CARD = ut.CARD       # fondo de tarjetas

# Colores y etiquetas del badge de fiabilidad según reliability.level.
REL_COLORS = ut.REL_COLORS
REL_LABELS = {"alta": "Fiabilidad alta", "media": "Fiabilidad media", "baja": "Fiabilidad baja"}

# Anchos máximos de las imágenes (en píxeles).
FULL_WIDTH = 720
ZOOM_WIDTH = 360


class StepDetail(tk.Toplevel):
    """Ventana modal-ligera con el detalle completo de un paso."""

    def __init__(self, master, session_id: str, step_id: str):
        super().__init__(master)
        self.session_id = session_id
        self.step_id = step_id

        # Referencias a las imágenes para que el GC de Tk no las recolecte.
        # Si se pierden estas referencias, Tk muestra las imágenes en blanco.
        self._images: list[ImageTk.PhotoImage] = []

        self.configure(bg=BG)
        self.geometry("900x720")
        self.minsize(560, 480)

        self._setup_style()

        # Buscamos el paso dentro de la sesión. Si algo falla, lo mostramos sin
        # reventar la ventana.
        session = storage.get_session(session_id)
        self.step = self._find_step(session, step_id)

        if self.step is None:
            self.title("Paso no disponible")
            self._build_missing()
            return

        short = self._short_description(self.step)
        self.title(f"Paso {self.step.get('index')} — {short}")
        self._build()

    # ── estilo ──────────────────────────────────────────────

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, font=ut.FONT_BODY)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Card.TLabel", background=CARD, foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=ut.FONT_CAPTION)
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=ut.FONT_CAPTION)
        style.configure("Title.TLabel", background=BG, foreground=INK, font=ut.FONT_H1)
        style.configure(
            "Section.TLabel", background=BG, foreground=INK, font=ut.FONT_H3
        )
        style.configure("TButton", padding=ut.SPACE_2)
        style.configure("Small.TButton", padding=(ut.SPACE_2, ut.SPACE_1 // 2), font=ut.FONT_CAPTION)

    # ── utilidades de datos ─────────────────────────────────

    @staticmethod
    def _find_step(session: dict | None, step_id: str) -> dict | None:
        """Busca un paso por id dentro de session['steps']."""
        if not session:
            return None
        for step in session.get("steps", []):
            if step.get("id") == step_id:
                return step
        return None

    @staticmethod
    def _short_description(step: dict, limit: int = 60) -> str:
        """Descripción recortada para el título de la ventana."""
        text = dc.step_text(step).replace("\n", " ").strip()
        if len(text) > limit:
            return text[: limit - 1].rstrip() + "…"
        return text

    # ── interfaz: caso de error ─────────────────────────────

    def _build_missing(self):
        """Mensaje amable cuando el paso ya no existe."""
        box = ttk.Frame(self, padding=ut.SPACE_6)
        box.pack(fill="both", expand=True)
        ttk.Label(
            box,
            text="Este paso ya no está disponible.",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            box,
            text="Puede que la grabación se haya borrado o modificado.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(ut.SPACE_2, ut.SPACE_4))
        ttk.Button(box, text="Cerrar", command=self.destroy).pack(anchor="w")

    # ── interfaz: caso normal ───────────────────────────────

    def _build(self):
        # Contenedor con scroll vertical (Canvas + Frame interior).
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(container, highlightthickness=0, bg=BG)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self._canvas.yview)
        self._body = ttk.Frame(self._canvas, padding=ut.SPACE_4)
        self._body.bind(
            "<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )
        self._body_window = self._canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._canvas.bind(
            "<Configure>", lambda e: self._canvas.itemconfigure(self._body_window, width=e.width)
        )
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        # bind (no bind_all) para no robar el scroll a otras ventanas.
        ut.bind_wheel(container, self._canvas)

        self._build_header(self._body)
        self._build_images(self._body)
        self._build_description(self._body)
        self._build_reliability(self._body)
        self._build_rows_section(self._body, "Identificación del elemento", dc.metadata_rows(self.step))
        self._build_selectors(self._body)
        self._build_rows_section(self._body, "Coordenadas", dc.coordinate_rows(self.step))

    def _build_header(self, parent):
        """Cabecera con el nº de paso y la descripción completa."""
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, ut.SPACE_3))
        ttk.Label(
            header, text=f"Paso {self.step.get('index')}", style="Title.TLabel"
        ).pack(anchor="w")
        ttk.Label(
            header, text=dc.step_text(self.step), font=ut.FONT_BODY_LG,
            background=BG, foreground=MUTED, wraplength=820
        ).pack(anchor="w", pady=(ut.SPACE_1, 0))

    def _build_images(self, parent):
        """Panel con la captura completa y, si existe, el detalle del elemento."""
        full = self._load_image(self.step.get("full_image", ""), FULL_WIDTH)
        zoom = self._load_image(self.step.get("zoom_image", ""), ZOOM_WIDTH)

        if full is None and zoom is None:
            ttk.Label(parent, text="(sin captura)", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
            return

        card = ttk.Frame(parent, style="Card.TFrame", padding=ut.SPACE_3)
        card.pack(fill="x", pady=(0, ut.SPACE_4))

        if full is not None:
            ttk.Label(card, text="Captura completa", style="CardMuted.TLabel").pack(anchor="w")
            full_lbl = tk.Label(
                card, image=full, cursor="hand2", bg=CARD, borderwidth=1, relief="solid"
            )
            full_lbl.pack(anchor="w", pady=(ut.SPACE_1, 0))
            full_lbl.bind("<Button-1>", lambda e: self._open_image(self.step.get("full_image", "")))

        if zoom is not None:
            ttk.Label(card, text="Detalle del elemento", style="CardMuted.TLabel").pack(
                anchor="w", pady=(ut.SPACE_3, 0)
            )
            zoom_lbl = tk.Label(
                card, image=zoom, cursor="hand2", bg=CARD, borderwidth=1, relief="solid"
            )
            zoom_lbl.pack(anchor="w", pady=(ut.SPACE_1, 0))
            zoom_lbl.bind("<Button-1>", lambda e: self._open_image(self.step.get("zoom_image", "")))

        ttk.Label(card, text="Clic en una imagen para abrirla", style="CardMuted.TLabel").pack(
            anchor="w", pady=(ut.SPACE_2, 0)
        )

    def _build_description(self, parent):
        """Sección «Descripción» (solo lectura)."""
        self._section_title(parent, "Descripción")
        card = ttk.Frame(parent, style="Card.TFrame", padding=ut.SPACE_3)
        card.pack(fill="x", pady=(0, ut.SPACE_4))
        tk.Label(
            card, text=dc.step_text(self.step), bg=CARD, fg=INK, font=ut.FONT_BODY_LG,
            anchor="w", justify="left", wraplength=820,
        ).pack(anchor="w", fill="x")

    def _build_reliability(self, parent):
        """Sección «Fiabilidad»: badge con color, resumen y motivos."""
        rel = self.step.get("reliability") or (self.step.get("element") or {}).get("reliability") or {}
        level = rel.get("level", "")
        summary = dc.reliability_summary(self.step)
        reasons = rel.get("reasons") or []

        if not level and not summary:
            return

        self._section_title(parent, "Fiabilidad")
        card = ttk.Frame(parent, style="Card.TFrame", padding=ut.SPACE_3)
        card.pack(fill="x", pady=(0, ut.SPACE_4))

        if level:
            tk.Label(
                card, text=f" {REL_LABELS.get(level, level)} ", bg=REL_COLORS.get(level, MUTED),
                fg="#ffffff", font=ut.FONT_CAPTION_STRONG, padx=ut.SPACE_2, pady=ut.SPACE_1 - 1,
            ).pack(anchor="w")

        if summary:
            tk.Label(
                card, text=summary, bg=CARD, fg=INK, font=ut.FONT_BODY,
                anchor="w", justify="left", wraplength=820,
            ).pack(anchor="w", pady=(ut.SPACE_2, 0))

        # Lista de motivos (si los hay) en viñetas.
        for reason in reasons:
            tk.Label(
                card, text=f"•  {reason}", bg=CARD, fg=MUTED, font=ut.FONT_CAPTION,
                anchor="w", justify="left", wraplength=800,
            ).pack(anchor="w", pady=(ut.SPACE_1 // 2, 0))

    def _build_rows_section(self, parent, title: str, rows: list):
        """Sección genérica de filas clave/valor (metadatos, coordenadas)."""
        if not rows:
            return
        self._section_title(parent, title)
        card = ttk.Frame(parent, style="Card.TFrame", padding=ut.SPACE_3)
        card.pack(fill="x", pady=(0, ut.SPACE_4))
        for key, value in rows:
            line = ttk.Frame(card, style="Card.TFrame")
            line.pack(fill="x", pady=ut.SPACE_1 // 2)
            tk.Label(
                line, text=key, bg=CARD, fg=MUTED, font=ut.FONT_SMALL_STRONG,
                width=22, anchor="nw", justify="left",
            ).pack(side="left", anchor="n")
            tk.Label(
                line, text=str(value), bg=CARD, fg=INK, font=ut.FONT_BODY,
                anchor="w", justify="left", wraplength=560,
            ).pack(side="left", fill="x", expand=True)

    def _build_selectors(self, parent):
        """Sección «Selectores para RPA» en monoespaciada con botón Copiar."""
        rows = dc.selector_rows(self.step)
        if not rows:
            return
        self._section_title(parent, "Selectores para RPA")
        card = ttk.Frame(parent, style="Card.TFrame", padding=ut.SPACE_3)
        card.pack(fill="x", pady=(0, ut.SPACE_4))
        for key, value in rows:
            block = ttk.Frame(card, style="Card.TFrame")
            block.pack(fill="x", pady=(0, ut.SPACE_2))

            head = ttk.Frame(block, style="Card.TFrame")
            head.pack(fill="x")
            tk.Label(
                head, text=key, bg=CARD, fg=MUTED, font=ut.FONT_SMALL_STRONG, anchor="w"
            ).pack(side="left")
            ttk.Button(
                head, text="Copiar", style="Small.TButton",
                command=lambda v=value: self._copy(v),
            ).pack(side="right")

            tk.Label(
                block, text=str(value), bg=ut.FIELD, fg=INK, font=ut.mono_body(),
                anchor="w", justify="left", wraplength=800, padx=ut.SPACE_2, pady=ut.SPACE_1,
                borderwidth=1, relief="solid",
            ).pack(fill="x", pady=(ut.SPACE_1, 0))

    # ── helpers de interfaz ─────────────────────────────────

    def _section_title(self, parent, text: str):
        """Subtítulo de sección con un pequeño espacio superior."""
        ttk.Label(parent, text=text, style="Section.TLabel").pack(anchor="w", pady=(0, ut.SPACE_2))

    # ── imágenes y portapapeles ─────────────────────────────

    def _load_image(self, name: str, width: int):
        """Carga una imagen escalada a 'width' y conserva la referencia PhotoImage.

        Nunca amplía por encima del tamaño original para no pixelar capturas
        pequeñas. Devuelve None si no hay imagen o no se puede abrir.
        """
        if not name:
            return None
        try:
            path = storage.image_path(self.session_id, name)
            if not path.exists():
                return None
            img = Image.open(path)
            target = min(width, img.width)  # No ampliar más allá del original.
            ratio = target / img.width
            size = (target, max(1, int(img.height * ratio)))
            img = img.resize(size, Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._images.append(photo)  # Referencia viva contra el GC.
            return photo
        except Exception:
            return None

    def _open_image(self, name: str):
        """Abre la imagen con el visor por defecto del sistema (Windows)."""
        if not name:
            return
        try:
            path = storage.image_path(self.session_id, name)
            if path.exists():
                get_backend().open_path(str(path))
        except Exception as err:
            messagebox.showerror("No se pudo abrir la imagen", str(err))

    def _copy(self, text: str):
        """Copia un selector al portapapeles."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass
