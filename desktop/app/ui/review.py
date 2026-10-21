"""Ventana de revisión: corregir descripciones, reordenar/borrar pasos y exportar.

Equivale a review.html / review.js de la extensión.

Cada paso se muestra como una tarjeta con su miniatura (clickable para abrir
la imagen completa en el visor del SO), un editor de descripción, un badge de
fiabilidad, metadatos y los selectores RPA con botón para copiar el XPath.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from ..exporters import doc_common as dc
from ..core import storage
from ..backends import get_backend
from . import theme as ut
from ..exporters import pdf as pdf_exporter
from ..exporters import word as word_exporter

# ── Paleta y tokens (centralizados en theme.py) ─────────────
ACCENT = ut.ACCENT
INK = ut.INK
MUTED = ut.MUTED
BG = ut.BG
CARD = ut.CARD

# Colores y etiquetas del badge de fiabilidad.
REL_COLORS = ut.REL_COLORS
REL_LABELS = {"alta": "Fiabilidad alta", "media": "Fiabilidad media", "baja": "Fiabilidad baja"}


class ReviewWindow(tk.Toplevel):
    def __init__(self, master, session_id: str):
        super().__init__(master)
        self.session_id = session_id
        self.session = storage.get_session(session_id)
        window_title = "Revisar y exportar — " + (self.session.get("name", "") if self.session else "")
        self.title(window_title)
        # Registramos el título propio para que el grabador no capture esta
        # ventana de revisión si se graba mientras está abierta. Al cerrarla lo
        # damos de baja para que el set de títulos no crezca sin límite.
        self._own_title = window_title
        self.bind("<Destroy>", self._on_destroy)
        self.geometry("960x680")
        self.configure(bg=BG)
        self._editors: dict[str, tk.Text] = {}
        # Referencias a las miniaturas para que no las recolecte el GC de Tk.
        self._thumbs: list[ImageTk.PhotoImage] = []

        if not self.session:
            tk.Label(self, text="Esa grabación ya no existe.", bg=BG, padx=20, pady=20).pack()
            return

        self._setup_style()
        self._build()

    def _on_destroy(self, event):
        # Solo al destruirse la ventana en sí (no un hijo), damos de baja el
        # título propio del set del inspector.
        if event.widget is self:
            pass

    # ── estilo ──────────────────────────────────────────────

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, font=ut.FONT_BODY)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=ut.FONT_CAPTION)
        style.configure("TLabelframe", background=BG, foreground=INK)
        style.configure("TLabelframe.Label", background=BG, foreground=INK, font=ut.FONT_SMALL_STRONG)
        style.configure("TButton", padding=ut.SPACE_2)
        style.configure(
            "Accent.TButton", background=ut.BRAND, foreground=ut.BRAND_ON,
            font=ut.FONT_SMALL_STRONG, padding=ut.SPACE_2, borderwidth=0,
        )
        style.map("Accent.TButton", background=[("active", ut.BRAND_ACTIVE)])

    # ── interfaz ────────────────────────────────────────────

    def _build(self):
        # Barra superior: nombre, resumen de fiabilidad y exportación.
        toolbar = ttk.Frame(self, padding=ut.SPACE_3)
        toolbar.pack(fill="x")
        title_box = ttk.Frame(toolbar)
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(
            title_box, text=self.session.get("name", ""), font=ut.FONT_H1
        ).pack(anchor="w")
        self._summary = ttk.Label(title_box, text=self._reliability_summary(), style="Muted.TLabel")
        self._summary.pack(anchor="w", pady=(ut.SPACE_1, 0))

        ttk.Button(toolbar, text="Exportar Word", style="Accent.TButton",
                   command=lambda: self._export("word")).pack(side="right", padx=ut.SPACE_1)
        ttk.Button(toolbar, text="Exportar PDF", style="Accent.TButton",
                   command=lambda: self._export("pdf")).pack(side="right", padx=ut.SPACE_1)

        # Lista de pasos con scroll.
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(container, highlightthickness=0, bg=BG)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self._canvas.yview)
        self._list = ttk.Frame(self._canvas)
        self._list.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._list_window = self._canvas.create_window((0, 0), window=self._list, anchor="nw")
        self._canvas.bind(
            "<Configure>", lambda e: self._canvas.itemconfigure(self._list_window, width=e.width)
        )
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        # bind (no bind_all) para no robar el scroll a otras ventanas.
        ut.bind_wheel(container, self._canvas)

        self._render_steps()

    def _reliability_summary(self) -> str:
        """Resumen tipo «3 pasos: 2 alta, 1 baja» contando reliability.level."""
        steps = self.session.get("steps", [])
        total = len(steps)
        counts = {"alta": 0, "media": 0, "baja": 0}
        for step in steps:
            level = (step.get("reliability") or {}).get("level", "")
            if level in counts:
                counts[level] += 1
        partes = [f"{counts[lvl]} {lvl}" for lvl in ("alta", "media", "baja") if counts[lvl]]
        base = f"{total} paso" + ("" if total == 1 else "s")
        return f"{base}: {', '.join(partes)}" if partes else base

    def _render_steps(self):
        for child in self._list.winfo_children():
            child.destroy()
        self._editors.clear()
        self._thumbs = []

        steps = self.session.get("steps", [])
        if not steps:
            ttk.Label(self._list, text="Esta grabación no tiene pasos.", padding=20).pack()
            return

        for step in steps:
            self._render_card(step)

    def _render_card(self, step):
        frame = ttk.LabelFrame(self._list, text=f"Paso {step.get('index')}", padding=ut.SPACE_3)
        frame.pack(fill="x", padx=ut.SPACE_3, pady=ut.SPACE_2)

        # Columna izquierda: miniatura clickable.
        left = ttk.Frame(frame)
        left.pack(side="left", anchor="n", padx=(0, ut.SPACE_3))
        thumb = self._load_thumb(step.get("full_image", ""), 220)
        if thumb is not None:
            img_lbl = tk.Label(left, image=thumb, cursor="hand2", bg=CARD, borderwidth=1, relief="solid")
            img_lbl.pack()
            img_lbl.bind("<Button-1>", lambda e, s=step: self._open_image(s))
            ttk.Label(left, text="Clic para ampliar", style="Muted.TLabel").pack(pady=(ut.SPACE_1, 0))
        else:
            ttk.Label(left, text="(sin imagen)", style="Muted.TLabel").pack()

        # Columna derecha: edición y detalles.
        right = ttk.Frame(frame)
        right.pack(side="left", fill="both", expand=True)

        # Badge de fiabilidad + primer motivo si es media/baja.
        rel = step.get("reliability") or {}
        level = rel.get("level", "")
        if level:
            badge_row = ttk.Frame(right)
            badge_row.pack(fill="x", anchor="w")
            tk.Label(
                badge_row, text=f" {REL_LABELS.get(level, level)} ", bg=REL_COLORS.get(level, MUTED),
                fg="#ffffff", font=ut.FONT_CAPTION_STRONG, padx=ut.SPACE_2, pady=ut.SPACE_1 // 2,
            ).pack(side="left")
            reasons = rel.get("reasons") or []
            if level in ("media", "baja") and reasons:
                ttk.Label(badge_row, text=reasons[0], style="Muted.TLabel").pack(side="left", padx=(ut.SPACE_2, 0))

        # Editor de descripción (2-3 líneas). spacing para dar aire al texto.
        editor = tk.Text(right, height=3, wrap="word", font=ut.FONT_BODY,
                         relief="solid", borderwidth=1,
                         spacing1=2, spacing3=ut.LH_BODY - 11)
        editor.insert("1.0", dc.step_text(step))
        editor.pack(fill="x", pady=(ut.SPACE_2, 0))
        self._editors[step["id"]] = editor

        # Línea meta: app · window · control_label (sin element, p.ej. notas,
        # no se muestra el tipo de control).
        control = dc.control_label(step.get("element")) if step.get("element") else ""
        meta = " · ".join(filter(None, [step.get("app"), step.get("window"), control]))
        if meta:
            ttk.Label(right, text=meta, style="Muted.TLabel").pack(anchor="w", pady=(ut.SPACE_1, 0))

        # Bloque de selectores RPA.
        self._render_selectors(right, step)

        # Botones por paso: reordenar y borrar.
        buttons = ttk.Frame(right)
        buttons.pack(fill="x", pady=(ut.SPACE_2, 0))
        ttk.Button(buttons, text="↑ Subir", width=9, command=lambda s=step: self._move(s, -1)).pack(side="left")
        ttk.Button(buttons, text="↓ Bajar", width=9, command=lambda s=step: self._move(s, +1)).pack(
            side="left", padx=(ut.SPACE_1, 0)
        )
        ttk.Button(buttons, text="Borrar", command=lambda s=step: self._delete(s)).pack(side="right")

    def _render_selectors(self, parent, step):
        """Bloque con los selectores clave/valor en fuente monoespaciada."""
        rows = dc.selector_rows(step)
        if not rows:
            return
        box = ttk.LabelFrame(parent, text="Selectores RPA", padding=ut.SPACE_2)
        box.pack(fill="x", pady=(ut.SPACE_2, 0))
        for key, value in rows:
            line = ttk.Frame(box)
            line.pack(fill="x", pady=1)
            ttk.Label(line, text=key, width=18, style="Muted.TLabel").pack(side="left", anchor="n")
            tk.Label(
                line, text=value, bg=BG, fg=INK, font=ut.mono_small(), anchor="w",
                justify="left", wraplength=460,
            ).pack(side="left", fill="x", expand=True)

        sel = step.get("selectors") or {}
        xpath = sel.get("uia_xpath") or sel.get("xpath") or ""
        if xpath:
            ttk.Button(box, text="Copiar XPath", command=lambda x=xpath: self._copy(x)).pack(
                anchor="e", pady=(ut.SPACE_2, 0)
            )

    # ── carga de imágenes ───────────────────────────────────

    def _load_thumb(self, name: str, width: int):
        """Carga una miniatura escalada y conserva la referencia PhotoImage."""
        if not name:
            return None
        try:
            path = storage.image_path(self.session_id, name)
            if not path.exists():
                return None
            img = Image.open(path)
            ratio = width / img.width
            size = (width, max(1, int(img.height * ratio)))
            img = img.resize(size, Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._thumbs.append(photo)
            return photo
        except Exception:
            return None

    def _open_image(self, step):
        """Abre la imagen completa con el visor por defecto del sistema."""
        name = step.get("full_image", "")
        if not name:
            return
        try:
            path = storage.image_path(self.session_id, name)
            if path.exists():
                get_backend().open_path(str(path))
        except Exception as err:
            messagebox.showerror("No se pudo abrir la imagen", str(err))

    def _copy(self, text: str):
        """Copia el selector al portapapeles."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    # ── edición de datos ────────────────────────────────────

    def _collect(self):
        """Vuelca las descripciones editadas a la sesión antes de persistir."""
        for step in self.session.get("steps", []):
            editor = self._editors.get(step["id"])
            if editor:
                step["description"] = editor.get("1.0", "end").strip() or step.get("suggestion", "")
        storage.save_session(self.session)

    def _move(self, step, delta):
        """Reordena un paso intercambiándolo con su vecino y re-indexa 1..n."""
        self._collect()
        steps = self.session.get("steps", [])
        try:
            pos = next(i for i, s in enumerate(steps) if s["id"] == step["id"])
        except StopIteration:
            return
        new_pos = pos + delta
        if new_pos < 0 or new_pos >= len(steps):
            return  # Ya está en el extremo.
        steps[pos], steps[new_pos] = steps[new_pos], steps[pos]
        for i, s in enumerate(steps, start=1):
            s["index"] = i
        storage.save_session(self.session)
        self._summary.config(text=self._reliability_summary())
        self._render_steps()

    def _delete(self, step):
        if not messagebox.askyesno("Borrar paso", f"¿Borrar el paso {step.get('index')}?"):
            return
        self._collect()
        steps = self.session.get("steps", [])
        storage.delete_images(self.session_id, [step.get("full_image"), step.get("zoom_image")])
        self.session["steps"] = [s for s in steps if s["id"] != step["id"]]
        for i, s in enumerate(self.session["steps"], start=1):
            s["index"] = i
        storage.save_session(self.session)
        self._summary.config(text=self._reliability_summary())
        self._render_steps()

    # ── exportación ─────────────────────────────────────────

    def _export(self, kind):
        self._collect()
        slug = dc.slugify(self.session.get("name", ""))
        if kind == "word":
            path = filedialog.asksaveasfilename(
                defaultextension=".docx", initialfile=f"{slug}.docx",
                filetypes=[("Documento de Word", "*.docx")],
            )
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".pdf", initialfile=f"{slug}.pdf",
                filetypes=[("Documento PDF", "*.pdf")],
            )
        if not path:
            return

        # Copia inmutable para el hilo: el usuario puede seguir editando.
        import copy

        snapshot = copy.deepcopy(self.session)

        result: dict = {}

        def work():
            try:
                if kind == "word":
                    word_exporter.export(snapshot, path)
                else:
                    pdf_exporter.export(snapshot, path)
                result["ok"] = True
            except PermissionError:
                result["error"] = "No se pudo escribir el archivo. ¿Está abierto en otra aplicación? Ciérralo o elige otro nombre."
            except Exception as err:  # noqa: BLE001
                result["error"] = str(err)

        # Tk no es seguro entre hilos (en macOS se cuelga): el hilo solo deja el
        # resultado y la ventana lo recoge con after().
        def poll():
            if not result:
                self.after(150, poll)
            elif result.get("ok"):
                if messagebox.askyesno("Listo", f"Documento guardado en:\n{path}\n\n¿Abrirlo ahora?"):
                    try:
                        get_backend().open_path(path)
                    except Exception:
                        pass
            else:
                messagebox.showerror("Error al exportar", result["error"])

        threading.Thread(target=work, daemon=True).start()
        poll()
