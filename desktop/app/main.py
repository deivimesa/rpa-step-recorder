"""Panel de control de la grabación (Tkinter).

Equivale al popup de la extensión: nombre del proceso, datos de portada,
iniciar/pausar/detener y acceso a las grabaciones anteriores para revisarlas
y exportarlas.

La interfaz tiene dos estados:
  - Reposo: formulario de portada + lista de grabaciones recientes.
  - Grabando: contador de pasos, cronómetro y lista de pasos en vivo.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from . import doc_common as dc
from . import storage
from . import inspector
from . import ui_theme as ut
from .recorder import Recorder
from .review import ReviewWindow
from .step_detail import StepDetail

# ── Paleta y tokens tipográficos (centralizados en ui_theme) ─
ACCENT = ut.ACCENT       # rojo de acento
INK = ut.INK             # tinta (texto principal)
MUTED = ut.MUTED         # texto tenue
BG = ut.BG               # fondo general
CARD = ut.CARD           # fondo de tarjetas

# Color del punto de fiabilidad según reliability.level.
REL_COLORS = ut.REL_COLORS


def _format_size(num_bytes: int) -> str:
    """Formatea un tamaño en bytes a MB o GB legibles."""
    mb = (num_bytes or 0) / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # Ya hay raíz Tk: resolvemos la monoespaciada preferida (Cascadia/Consolas).
        ut.resolve_mono()
        self.title("RPA Step Recorder")
        # Registramos el título propio para que el grabador no se capture a sí
        # mismo (respaldo de inspector.es_ventana_propia).
        inspector.register_own_titles(["RPA Step Recorder"])
        self.geometry("460x620")
        self.minsize(420, 520)
        self.configure(bg=BG)
        # Referencias a las miniaturas para que no las recolecte el GC de Tk.
        self._thumbs: list[ImageTk.PhotoImage] = []
        # Id del paso cuya descripción se está editando (foco en su editor).
        # Mientras no sea None, _refresh evita repintar la lista en vivo para
        # no romper lo que el usuario está escribiendo.
        self._editing_step_id: str | None = None
        # Referencia al Entry que tiene el foco, para volcar su texto antes de
        # cualquier re-render (destruir el widget no dispara <FocusOut>).
        self._active_editor: tk.Entry | None = None
        # Nº de pasos pintados en el último render de la lista en vivo; sirve
        # para detectar nuevos pasos durante una edición.
        self._live_step_count = 0
        # Timer del auto-descarte del mensaje de estado (_say). Un único id
        # vivo a la vez; se cancela el anterior al llegar un mensaje nuevo.
        self._msg_after: str | None = None
        # Estado del parpadeo del punto del header (_blink): un único timer.
        self._blink_after: str | None = None
        self._blink_on = True
        self.recorder = Recorder(on_change=self._on_change)
        self._setup_style()
        self._build()
        self._bind_shortcuts()
        self._refresh()

    # ── estilo ──────────────────────────────────────────────

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, font=ut.FONT_BODY)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=ut.FONT_CAPTION)
        style.configure("TLabelframe", background=BG, foreground=INK)
        style.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=ut.FONT_CAPTION_STRONG)
        style.configure("TEntry", fieldbackground=CARD, padding=ut.SPACE_1)
        style.configure("TButton", padding=ut.SPACE_2)
        # Botón grande de acento para "Iniciar grabación".
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#ffffff",
            font=ut.FONT_BODY_STRONG,
            padding=ut.SPACE_3,
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", ut.ACCENT_ACTIVE), ("disabled", ut.ACCENT_DISABLED)],
        )
        # Botón secundario "fantasma": menos peso visual que el acento.
        # Fondo = CARD (se funde con el panel), sin relieve agresivo y texto
        # tenue. Se usa en los controles secundarios de la grabación.
        style.configure(
            "Ghost.TButton",
            background=CARD,
            foreground=MUTED,
            font=ut.FONT_SMALL,
            padding=ut.SPACE_2,
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Ghost.TButton",
            background=[("active", ut.CARD_SOFT), ("disabled", BG)],
            foreground=[("active", INK), ("disabled", ut.BORDER)],
        )
        # Tarjetas de la lista en vivo.
        style.configure("Card.TFrame", background=CARD, relief="solid", borderwidth=1)
        style.configure("Card.TLabel", background=CARD, foreground=INK)
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=ut.FONT_CAPTION)
        # Botones pequeños de la barra de acciones de cada tarjeta. Se les da
        # algo más de área (targets táctiles) con padding del propio estilo.
        style.configure("CardAction.TButton", padding=(ut.SPACE_2, ut.SPACE_1), font=ut.FONT_CAPTION)

    # ── interfaz ────────────────────────────────────────────

    def _build(self):
        # Cabecera con el nombre de la app y el "pill" de estado.
        header = ttk.Frame(self, padding=(ut.SPACE_4, ut.SPACE_3))
        header.pack(fill="x")
        # Punto del header: lo guardamos para animarlo (_blink) según el estado.
        self._dot = tk.Label(header, text="●", fg=ACCENT, bg=BG, font=ut.FONT_NUMERIC)
        self._dot.pack(side="left")
        tk.Label(
            header, text="RPA Step Recorder", bg=BG, fg=INK, font=ut.FONT_H3
        ).pack(side="left", padx=ut.SPACE_2)
        self._pill = tk.Label(header, text="Listo", font=ut.FONT_CAPTION_STRONG, padx=ut.SPACE_2, pady=ut.SPACE_1 - 1)
        self._pill.pack(side="right")

        body = ttk.Frame(self, padding=ut.SPACE_4)
        body.pack(fill="both", expand=True)

        self._build_idle(body)
        self._build_live(body)

        # Mensaje de estado al pie.
        self._msg = tk.Label(self, text="", bg=BG, fg=MUTED, font=ut.FONT_CAPTION, anchor="w", padx=ut.SPACE_4)
        self._msg.pack(fill="x", pady=(0, ut.SPACE_2))

        self._tick()
        self._blink()

    def _build_idle(self, parent):
        """Zona visible en reposo: formulario + grabaciones recientes."""
        self._idle = ttk.Frame(parent)

        self._form = ttk.Frame(self._idle)
        self._form.pack(fill="x")
        ttk.Label(self._form, text="Nombre del proceso").pack(anchor="w")
        self._name = ttk.Entry(self._form)
        self._name.pack(fill="x", pady=(ut.SPACE_1, ut.SPACE_3))
        ttk.Label(self._form, text="Autor").pack(anchor="w")
        self._author = ttk.Entry(self._form)
        self._author.pack(fill="x", pady=(ut.SPACE_1, ut.SPACE_3))
        ttk.Label(self._form, text="Sistema o aplicación").pack(anchor="w")
        self._system = ttk.Entry(self._form)
        self._system.pack(fill="x", pady=(ut.SPACE_1, ut.SPACE_3))

        self._start_btn = ttk.Button(
            self._idle, text="Iniciar grabación", style="Accent.TButton", command=self._start
        )
        self._start_btn.pack(fill="x", pady=(0, ut.SPACE_3))

        # Lista de grabaciones recientes.
        self._recent = ttk.LabelFrame(self._idle, text="Grabaciones", padding=ut.SPACE_2)
        self._recent.pack(fill="both", expand=True)

        self._usage = ttk.Label(self._idle, text="", style="Muted.TLabel")
        self._usage.pack(anchor="w", pady=(ut.SPACE_2, 0))

    def _build_live(self, parent):
        """Zona visible mientras se graba: contador, cronómetro y pasos en vivo."""
        self._live = ttk.Frame(parent)

        counter = ttk.Frame(self._live)
        counter.pack(fill="x")
        self._count = tk.Label(counter, text="0", bg=BG, fg=ACCENT, font=ut.FONT_DISPLAY)
        self._count.pack(side="left")
        count_box = ttk.Frame(counter)
        count_box.pack(side="left", padx=(ut.SPACE_3, 0), anchor="s", pady=(0, ut.SPACE_2))
        self._count_label = tk.Label(count_box, text="pasos", bg=BG, fg=MUTED, font=ut.FONT_SMALL)
        self._count_label.pack(anchor="w")
        self._timer = tk.Label(counter, text="00:00", bg=BG, fg=INK, font=ut.FONT_NUMERIC)
        self._timer.pack(side="right", anchor="s", pady=(0, ut.SPACE_3))

        # Botones de control de la grabación con jerarquía clara:
        #  · Acción primaria "Detener y revisar": sola, ancho completo, arriba.
        #  · Acciones secundarias (Pausar/Nota/Deshacer): juntas, estilo Ghost
        #    con menos peso visual.
        self._stop_btn = ttk.Button(
            self._live, text="Detener y revisar", style="Accent.TButton", command=self._stop
        )
        self._stop_btn.pack(fill="x", pady=(ut.SPACE_2, ut.SPACE_1))

        actions = ttk.Frame(self._live)
        actions.pack(fill="x", pady=(0, ut.SPACE_3))
        self._pause_btn = ttk.Button(actions, text="Pausar", style="Ghost.TButton", command=self._toggle_pause)
        self._pause_btn.pack(side="left", expand=True, fill="x", padx=ut.SPACE_1 // 2)
        self._note_btn = ttk.Button(actions, text="Agregar nota", style="Ghost.TButton", command=self._add_note)
        self._note_btn.pack(side="left", expand=True, fill="x", padx=ut.SPACE_1 // 2)
        self._undo_btn = ttk.Button(actions, text="Deshacer último", style="Ghost.TButton", command=self._undo_last)
        self._undo_btn.pack(side="left", expand=True, fill="x", padx=ut.SPACE_1 // 2)

        ttk.Label(self._live, text="Pasos grabados", style="Muted.TLabel").pack(anchor="w")

        # Lista de pasos en vivo con scroll (Canvas + Frame interior).
        wrap = ttk.Frame(self._live)
        wrap.pack(fill="both", expand=True, pady=(ut.SPACE_1, 0))
        self._live_canvas = tk.Canvas(wrap, highlightthickness=0, bg=BG)
        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=self._live_canvas.yview)
        self._live_inner = ttk.Frame(self._live_canvas)
        self._live_inner.bind(
            "<Configure>",
            lambda e: self._live_canvas.configure(scrollregion=self._live_canvas.bbox("all")),
        )
        self._live_window = self._live_canvas.create_window((0, 0), window=self._live_inner, anchor="nw")
        self._live_canvas.bind(
            "<Configure>", lambda e: self._live_canvas.itemconfigure(self._live_window, width=e.width)
        )
        self._live_canvas.configure(yscrollcommand=scrollbar.set)
        self._live_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._live_canvas.bind(
            "<MouseWheel>", lambda e: self._live_canvas.yview_scroll(int(-e.delta / 120), "units")
        )

    def _bind_shortcuts(self):
        # Atajos locales de la ventana (no globales del SO).
        self.bind("<F9>", lambda e: self._toggle_record())
        self.bind("<F8>", lambda e: self._add_note())
        self.bind("<F10>", lambda e: self._toggle_pause() if self.recorder.recording else None)

    # ── acciones ────────────────────────────────────────────

    def _start(self):
        self.recorder.start_session(
            self._name.get().strip(), self._author.get().strip(), self._system.get().strip()
        )
        self._name.delete(0, "end")
        self._say("Grabando. Cada clic crea un paso. (F10 pausar · F9 detener)", kind="ok")

    def _toggle_record(self):
        """F9: inicia si está en reposo, detiene si está grabando."""
        if self.recorder.recording:
            self._stop()
        else:
            self._start()

    def _toggle_pause(self):
        if not self.recorder.recording:
            return
        paused = self.recorder.set_paused(not self.recorder.paused)
        if paused:
            self._say("En pausa: los clics no se graban.", kind="warn")
        else:
            self._say("Grabación reanudada.", kind="ok")

    def _add_note(self):
        if self.recorder.recording and not self.recorder.paused:
            self.recorder.note()
            self._say("Nota añadida.", kind="ok")

    def _undo_last(self):
        """Borra el último paso grabado delegando en el worker (sin tocar storage)."""
        session = self.recorder.current_session()
        steps = session.get("steps", []) if session else []
        if not steps:
            self._say("No hay pasos que deshacer.", kind="warn")
            return
        last = steps[-1]
        # El worker es el único que escribe la sesión: encolamos el borrado por
        # id en vez de manipular storage desde el hilo Tk (evita carreras).
        self.recorder.delete_step(last.get("id"))
        self._say(f"Paso {last.get('index')} deshecho.")

    def _stop(self):
        session = self.recorder.stop_session()
        if session and session.get("steps"):
            ReviewWindow(self, session["id"])
            self._say("Grabación detenida. Revisa y exporta la documentación.", kind="ok")
        else:
            self._say("Grabación detenida sin pasos.", kind="warn")

    def _say(self, text, kind="info"):
        """Muestra un mensaje de estado al pie que se auto-descarta.

        - ``kind`` ∈ {info, ok, warn} tiñe el texto: ok=verde, warn=ámbar,
          info=tenue (por defecto, compatible con las llamadas existentes).
        - Tras ~4 s el mensaje se limpia solo. Se guarda el id del ``after``
          en ``self._msg_after`` y se cancela el anterior si llega uno nuevo,
          de modo que haya como mucho un timer de mensaje vivo.
        - Si ``text`` está vacío no se programa auto-descarte.
        """
        colors = {
            "ok": REL_COLORS["alta"],
            "warn": REL_COLORS["media"],
            "info": MUTED,
        }
        self._msg.config(text=text, fg=colors.get(kind, MUTED))
        # Cancelamos cualquier auto-descarte pendiente del mensaje anterior.
        if self._msg_after is not None:
            try:
                self.after_cancel(self._msg_after)
            except Exception:
                pass
            self._msg_after = None
        if text:
            self._msg_after = self.after(4000, self._clear_msg)

    def _clear_msg(self):
        """Limpia el mensaje de estado (invocado por el auto-descarte)."""
        self._msg_after = None
        try:
            self._msg.config(text="")
        except Exception:
            pass

    def _blink(self):
        """Parpadeo suave del punto del header según el estado de grabación.

        - Grabando (sin pausa): alterna ACCENT / tono tenue cada ~700 ms.
        - En pausa: punto fijo ámbar.
        - Reposo: punto fijo gris.

        Mantiene un único timer en ``self._blink_after`` (independiente de
        ``_tick`` y de ``_msg_after``).
        """
        recording = self.recorder.recording
        paused = self.recorder.paused
        if recording and not paused:
            # Alternamos el color para transmitir actividad.
            self._blink_on = not self._blink_on
            self._dot.config(fg=ACCENT if self._blink_on else ut.ACCENT_DISABLED)
        elif recording and paused:
            self._dot.config(fg=REL_COLORS["media"])
            self._blink_on = True
        else:
            self._dot.config(fg=MUTED)
            self._blink_on = True
        self._blink_after = self.after(700, self._blink)

    # ── pintado ─────────────────────────────────────────────

    def _on_change(self):
        # Recorder llama a on_change desde su hilo worker: volvemos al hilo de Tk.
        self.after(0, self._refresh)

    def _set_pill(self, recording: bool, paused: bool):
        if recording and paused:
            text, fg, bg = "En pausa", INK, "#f1c40f"
        elif recording:
            text, fg, bg = "Grabando", "#ffffff", ACCENT
        else:
            text, fg, bg = "Listo", MUTED, "#ececed"
        self._pill.config(text=text, fg=fg, bg=bg)

    def _refresh(self):
        recording = self.recorder.recording
        paused = self.recorder.paused
        self._set_pill(recording, paused)

        if recording:
            self._idle.pack_forget()
            self._live.pack(fill="both", expand=True)
            self._pause_btn.config(text="Reanudar" if paused else "Pausar")
            session = self.recorder.current_session()
            steps = session.get("steps", []) if session else []
            count = len(steps)
            self._count.config(text=str(count))
            self._count_label.config(text="paso" if count == 1 else "pasos")
            self._undo_btn.state(["!disabled"] if count else ["disabled"])
            # Si la bandera apunta a un paso que ya no existe (se borró), la
            # limpiamos para no bloquear el repintado indefinidamente.
            if self._editing_step_id is not None and not any(
                s.get("id") == self._editing_step_id for s in steps
            ):
                self._editing_step_id = None
                self._active_editor = None
            # Si hay una edición de descripción en curso, no repintamos la lista
            # (destruir el Entry con foco perdería lo que se está escribiendo),
            # salvo que cambie el número de pasos (p. ej. llega un paso nuevo),
            # en cuyo caso _render_live_steps primero vuelca el texto activo.
            if self._editing_step_id is not None and count == self._live_step_count:
                pass
            else:
                self._render_live_steps(session, steps)
        else:
            self._live.pack_forget()
            self._idle.pack(fill="both", expand=True)
            self._render_recent()
            self._render_usage()

    def _load_thumb(self, session_id: str, name: str, width: int):
        """Carga una miniatura escalada y conserva la referencia PhotoImage."""
        if not name:
            return None
        try:
            path = storage.image_path(session_id, name)
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

    def _flush_active_editor(self):
        """Vuelca el texto del editor en edición antes de destruirlo.

        Destruir un Entry con foco NO dispara <FocusOut>, así que si repintamos
        la lista (p. ej. llega un paso nuevo) el commit por binding nunca
        correría y se perdería lo tecleado. Por eso guardamos aquí, de forma
        explícita, el texto del editor activo antes de cualquier re-render.
        """
        editor = self._active_editor
        sid = self._editing_step_id
        if editor is None or sid is None:
            return
        try:
            if editor.winfo_exists():
                # El guardado es asíncrono (cola del worker), pero el texto no
                # se pierde: queda encolado aunque el Entry se destruya al
                # repintar la lista.
                self.recorder.update_step_description(sid, editor.get())
        except Exception:
            pass
        finally:
            self._active_editor = None

    def _tooltip(self, widget, text):
        """Adjunta un tooltip simple a ``widget`` (Toplevel al pasar el ratón).

        Implementación robusta: si el widget se destruye, los manejadores no
        fallan (se protegen con winfo_exists y try/except) y el Toplevel se
        cierra limpiamente.
        """
        state = {"tip": None}

        def _show(_event=None):
            if state["tip"] is not None:
                return
            try:
                if not widget.winfo_exists():
                    return
                x = widget.winfo_rootx() + widget.winfo_width() // 2
                y = widget.winfo_rooty() + widget.winfo_height() + ut.SPACE_1
                tip = tk.Toplevel(widget)
                tip.wm_overrideredirect(True)
                tip.wm_geometry(f"+{x}+{y}")
                tk.Label(
                    tip, text=text, bg=INK, fg="#ffffff", font=ut.FONT_CAPTION,
                    padx=ut.SPACE_2, pady=ut.SPACE_1 // 2,
                ).pack()
                state["tip"] = tip
            except Exception:
                state["tip"] = None

        def _hide(_event=None):
            tip = state["tip"]
            state["tip"] = None
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass

        widget.bind("<Enter>", _show, add="+")
        widget.bind("<Leave>", _hide, add="+")
        # Al destruirse el widget, aseguramos cerrar el tooltip si estaba visible.
        widget.bind("<Destroy>", _hide, add="+")

    def _render_live_steps(self, session, steps):
        # Antes de destruir nada, salvamos lo que el usuario esté editando.
        self._flush_active_editor()
        for child in self._live_inner.winfo_children():
            child.destroy()
        # Se reinicia la lista de miniaturas en cada repintado.
        self._thumbs = []
        # Recordamos cuántos pasos pintamos para que _refresh detecte si llegan
        # pasos nuevos mientras se edita una descripción.
        self._live_step_count = len(steps)

        if not steps:
            ttk.Label(
                self._live_inner, text="Haz clic en cualquier app para registrar el primer paso.",
                style="Muted.TLabel", padding=8,
            ).pack(anchor="w")
            return

        session_id = session["id"]
        total = len(steps)
        # Se muestran los últimos primero para ver lo recién grabado. Se usa el
        # índice en la lista real (no el reversed) para calcular si un paso
        # puede subir o bajar.
        for pos in range(total - 1, -1, -1):
            step = steps[pos]
            self._render_step_card(session_id, step, pos, total)

    def _render_step_card(self, session_id, step, pos, total):
        """Pinta la tarjeta de un paso con edición inline y controles de orden.

        Diseño en tres filas para que la tarjeta «respire»:
          · Fila 1: badge con el nº, miniatura y etiqueta de fiabilidad.
          · Fila 2: descripción editable inline (Entry con estilo suave).
          · Fila 3: barra de acciones discreta (Ver detalle · ↑ · ↓ · ✕).
        """
        step_id = step.get("id")

        row = ttk.Frame(self._live_inner, style="Card.TFrame", padding=ut.SPACE_3)
        row.pack(fill="x", padx=ut.SPACE_1, pady=ut.SPACE_1 + 1)

        # ── Fila 1: nº (badge), miniatura y fiabilidad ──────────
        head = ttk.Frame(row, style="Card.TFrame")
        head.pack(fill="x")

        # Badge tenue con el número de paso.
        tk.Label(
            head, text=str(step.get("index")), bg=ut.BADGE_BG, fg=MUTED,
            font=ut.FONT_SMALL_STRONG, width=3, padx=ut.SPACE_1, pady=ut.SPACE_1 // 2,
        ).pack(side="left", padx=(0, ut.SPACE_2))

        # Miniatura pequeña (~56px).
        thumb = self._load_thumb(session_id, step.get("full_image", ""), 56)
        if thumb is not None:
            tk.Label(
                head, image=thumb, bg=CARD, borderwidth=1, relief="solid"
            ).pack(side="left", padx=(0, ut.SPACE_2))

        # Etiqueta de fiabilidad con color (a la derecha).
        level = (step.get("reliability") or {}).get("level", "")
        rel_color = REL_COLORS.get(level, MUTED)
        rel_text = {"alta": "Alta", "media": "Media", "baja": "Baja"}.get(level, "—")
        rel_box = ttk.Frame(head, style="Card.TFrame")
        rel_box.pack(side="right")
        tk.Label(
            rel_box, text="●", bg=CARD, fg=rel_color, font=ut.FONT_BODY
        ).pack(side="left")
        tk.Label(
            rel_box, text=rel_text, bg=CARD, fg=rel_color, font=ut.FONT_CAPTION_STRONG
        ).pack(side="left", padx=(ut.SPACE_1 - 1, 0))

        # ── Fila 2: descripción editable inline ─────────────────
        # Entry con estilo suave (sin borde agresivo, fondo casi blanco y algo
        # de padding). Al perder el foco o pulsar Enter se guarda vía
        # recorder.update_step_description. Se conserva la lógica de
        # _editing_step_id / _active_editor / _flush_active_editor.
        editor = tk.Entry(
            row, bg=ut.CARD_SOFT, fg=INK, font=ut.FONT_BODY,
            relief="flat", highlightthickness=1, highlightbackground=ut.BORDER,
            highlightcolor="#c9cace",
        )
        editor.insert(0, dc.step_text(step))
        editor.pack(fill="x", pady=(ut.SPACE_2, 0), ipady=ut.SPACE_1)

        def _on_focus_in(_event, sid=step_id, widget=editor):
            # Marca el paso en edición para que _refresh no repinte la lista y
            # recuerda el widget activo para poder volcarlo antes de un re-render.
            self._editing_step_id = sid
            self._active_editor = widget

        def _commit(_event=None, sid=step_id, widget=editor):
            # Guarda el texto y libera la edición.
            text = widget.get()
            if self._editing_step_id == sid:
                self._editing_step_id = None
                self._active_editor = None
            self.recorder.update_step_description(sid, text)

        editor.bind("<FocusIn>", _on_focus_in)
        editor.bind("<FocusOut>", _commit)
        editor.bind("<Return>", _commit)

        # Si esta tarjeta corresponde al paso que se estaba editando, le
        # devolvemos el foco tras un repintado forzado (p. ej. por un paso nuevo).
        if self._editing_step_id == step_id:
            editor.focus_set()
            editor.icursor("end")

        # ── Fila 3: barra de acciones discreta (alineada a la derecha) ──
        actions = ttk.Frame(row, style="Card.TFrame")
        actions.pack(fill="x", pady=(ut.SPACE_2, 0))

        ttk.Button(
            actions, text="Ver detalle", style="CardAction.TButton",
            command=lambda sid=step_id: self._open_detail(sid),
        ).pack(side="left")

        # Grupo de orden y borrado a la derecha.
        del_btn = ttk.Button(
            actions, text="✕", width=3, style="CardAction.TButton",
            command=lambda sid=step_id: self._delete_step(sid),
        )
        del_btn.pack(side="right")
        self._tooltip(del_btn, "Borrar paso")

        down_btn = ttk.Button(
            actions, text="↓", width=3, style="CardAction.TButton",
            command=lambda sid=step_id: self.recorder.move_step(sid, 1),
        )
        down_btn.pack(side="right", padx=(0, ut.SPACE_1))
        self._tooltip(down_btn, "Bajar paso")
        if pos == total - 1:
            down_btn.state(["disabled"])

        up_btn = ttk.Button(
            actions, text="↑", width=3, style="CardAction.TButton",
            command=lambda sid=step_id: self.recorder.move_step(sid, -1),
        )
        up_btn.pack(side="right", padx=(0, ut.SPACE_1))
        self._tooltip(up_btn, "Subir paso")
        if pos == 0:
            up_btn.state(["disabled"])

    def _open_detail(self, step_id):
        """Abre la ventana de detalle del paso para la sesión en curso.

        Primero vuelca cualquier edición en curso para no perderla y protege
        contra la ausencia de sesión activa.
        """
        self._flush_active_editor()
        # Liberamos la bandera de edición: si no, y el <FocusOut> no llegara a
        # dispararse, _refresh dejaría de repintar la lista con el mismo conteo
        # (p. ej. reordenar ↑/↓ no se reflejaría).
        self._editing_step_id = None
        self._active_editor = None
        session = self.recorder.current_session()
        if not session:
            self._say("No hay una grabación activa.", kind="warn")
            return
        StepDetail(self, session["id"], step_id)

    def _delete_step(self, step_id):
        """Borra un paso delegando en el worker; limpia la bandera de edición.

        Si se está editando OTRO paso, primero volcamos su texto para no
        perderlo en el re-render que provocará el borrado.
        """
        if self._editing_step_id and self._editing_step_id != step_id:
            self._flush_active_editor()
        # Confirmación de acción destructiva (coherente con _delete).
        if not messagebox.askyesno("Borrar paso", "¿Borrar este paso de la grabación?"):
            return
        if self._editing_step_id == step_id:
            self._editing_step_id = None
            self._active_editor = None
        self.recorder.delete_step(step_id)

    def _render_recent(self):
        for child in self._recent.winfo_children():
            child.destroy()
        sessions = [s for s in storage.list_sessions() if s.get("steps")]
        if not sessions:
            self._render_empty_state()
            return
        for item in sessions[:10]:
            row = ttk.Frame(self._recent)
            row.pack(fill="x", pady=2)
            n = len(item["steps"])
            label = f"{item['name']}   ·   {n} paso" + ("" if n == 1 else "s")
            # El nombre es el botón que abre la revisión (se elimina el botón
            # "Revisar" redundante que hacía exactamente lo mismo).
            ttk.Button(row, text=label, command=lambda s=item: ReviewWindow(self, s["id"])).pack(
                side="left", fill="x", expand=True
            )
            del_btn = ttk.Button(row, text="✕", width=3, command=lambda s=item: self._delete(s))
            del_btn.pack(side="left", padx=(4, 0))
            self._tooltip(del_btn, "Borrar grabación")

    def _render_empty_state(self):
        """Estado vacío con onboarding: título + 3 pasos numerados.

        Guía al usuario primerizo por el flujo básico cuando aún no hay
        grabaciones, en lugar de un mensaje escueto.
        """
        wrap = ttk.Frame(self._recent)
        wrap.pack(fill="x", anchor="w", pady=ut.SPACE_2)

        ttk.Label(
            wrap, text="Empieza tu primera grabación",
            font=ut.FONT_BODY_STRONG, background=BG, foreground=INK,
        ).pack(anchor="w", pady=(0, ut.SPACE_3))

        pasos = [
            "Escribe el nombre del proceso.",
            "Pulsa Iniciar grabación (o F9).",
            "Trabaja normal: cada clic se documenta solo.",
        ]
        for i, texto in enumerate(pasos, start=1):
            step_row = ttk.Frame(wrap)
            step_row.pack(fill="x", anchor="w", pady=(0, ut.SPACE_2))
            # Número en un badge pequeño, coherente con las tarjetas de pasos.
            tk.Label(
                step_row, text=str(i), bg=ut.BADGE_BG, fg=MUTED,
                font=ut.FONT_SMALL_STRONG, padx=ut.SPACE_2, pady=ut.SPACE_1 // 2,
            ).pack(side="left", padx=(0, ut.SPACE_2))
            tk.Label(
                step_row, text=texto, bg=BG, fg=MUTED, font=ut.FONT_SMALL,
                anchor="w", justify="left",
            ).pack(side="left", fill="x", expand=True)

    def _render_usage(self):
        try:
            used = storage.usage().get("used", 0)
            self._usage.config(text=f"Espacio usado: {_format_size(used)}")
        except Exception:
            self._usage.config(text="")

    def _delete(self, item):
        if messagebox.askyesno("Borrar grabación", f"¿Borrar «{item['name']}» y sus capturas?"):
            storage.delete_session(item["id"])
            self._refresh()

    def _tick(self):
        if self.recorder.recording and not self.recorder.paused:
            session = self.recorder.current_session()
            if session and session.get("started_at"):
                try:
                    start = datetime.fromisoformat(session["started_at"])
                    total = max(0, int((datetime.now() - start).total_seconds()))
                    self._timer.config(text=f"{total // 60:02d}:{total % 60:02d}")
                except (ValueError, TypeError):
                    pass
        self.after(1000, self._tick)


def run():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    run()
