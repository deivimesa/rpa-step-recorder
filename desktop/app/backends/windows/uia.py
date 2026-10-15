"""Inspección del elemento de escritorio con UI Automation (Windows).

Evolución del antiguo ``inspector.py``. Para un punto de la pantalla (o para
el control con el foco) devuelve el dict ``element`` normalizado: tipo de
control, nombre, AutomationId, ClassName, rectángulo, cadena de ancestros con
índices, patrones de interacción y fiabilidad del selector.

Mejoras respecto a la versión anterior:
  - Un único recorrido de ancestros (antes eran tres) y un presupuesto de
    tiempo: una app colgada ya no bloquea la grabación varios segundos.
  - Índices entre hermanos acotados (MAX_SIBLINGS): una lista con miles de
    filas ya no dispara miles de llamadas COM.
  - Contraseñas detectadas con la propiedad real IsPassword, además de la
    heurística por nombre (ahora por palabra completa: "Shipping" ya no se
    toma por "PIN").
  - El valor de un campo confidencial nunca se lee.
  - Patrones detectados con GetPattern(PatternId), válido para cualquier
    control (antes solo para las subclases que exponían el getter).
  - Lectura del valor final de un campo (ValuePattern, TextPattern o
    LegacyIAccessible): lo escrito se toma del propio campo, no de las teclas.

Todo el módulo se usa solo desde el hilo de inspección, que inicializa COM:
los objetos Control no pueden cruzar de hilo.
"""

from __future__ import annotations

import logging
import time

import uiautomation as auto

from ...core import paths
from ..base import compute_reliability, secret_hint

log = logging.getLogger("rpa.uia")

# Los errores internos de uiautomation van a nuestra carpeta de registros y
# no a un @AutomationLog.txt en el directorio actual (que puede no ser escribible).
try:
    auto.Logger.SetLogFile(str(paths.logs_dir() / "uiautomation.log"))
except Exception:  # pragma: no cover - defensivo
    pass

# Tipos genéricos que, por sí solos, rara vez son el objetivo real del clic.
GENERIC_TYPES = {"Text", "Custom", "Image", "Pane", "Group"}

# Tipos accionables aunque no expongan un patrón concreto.
ACTIONABLE_TYPES = {
    "Button", "Hyperlink", "MenuItem", "ListItem", "TabItem", "CheckBox",
    "RadioButton", "SplitButton", "TreeItem", "DataItem", "HeaderItem", "ComboBox",
}

ACTION_PATTERNS = ("InvokePattern", "TogglePattern", "SelectionItemPattern", "ExpandCollapsePattern")

# Patrones que se registran (etiqueta corta, atributo en auto.PatternId).
_PATTERNS = (
    ("Invoke", "InvokePattern"),
    ("Value", "ValuePattern"),
    ("Toggle", "TogglePattern"),
    ("Selection", "SelectionPattern"),
    ("SelectionItem", "SelectionItemPattern"),
    ("ExpandCollapse", "ExpandCollapsePattern"),
    ("Scroll", "ScrollPattern"),
    ("Text", "TextPattern"),
    ("RangeValue", "RangeValuePattern"),
    ("GridItem", "GridItemPattern"),
)

_EXPAND_STATES = {0: "Collapsed", 1: "Expanded", 2: "PartiallyExpanded", 3: "LeafNode"}

MAX_DEPTH = 40        # niveles hasta el escritorio
MAX_PATH = 12         # segmentos de la ruta / selector
MAX_SIBLINGS = 300    # hermanos que se recorren para calcular un índice
INDEX_BUDGET = 1.0    # segundos máximos para ancestros + índices
MAX_VALUE = 4000      # caracteres máximos de un valor leído


# ── utilidades defensivas ───────────────────────────────────


def _ct(control) -> str:
    """'ButtonControl' -> 'Button'."""
    try:
        name = control.ControlTypeName or ""
    except Exception:
        return ""
    return name[:-7] if name.endswith("Control") else name


def _get(control, attr: str, default=None):
    try:
        value = getattr(control, attr)
        return default if value is None else value
    except Exception:
        return default


def _text(value, limit: int = 160) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())[:limit]


def _rect(control) -> dict | None:
    try:
        r = control.BoundingRectangle
        width, height = r.right - r.left, r.bottom - r.top
        if width <= 0 or height <= 0:
            return None
        return {"x": int(r.left), "y": int(r.top), "width": int(width), "height": int(height)}
    except Exception:
        return None


def _contains(control, x: int, y: int) -> bool:
    rect = _rect(control)
    return bool(rect) and rect["x"] <= x < rect["x"] + rect["width"] and rect["y"] <= y < rect["y"] + rect["height"]


def _runtime_id(control) -> str:
    try:
        rid = control.GetRuntimeId()
        return "-".join(str(part) for part in rid) if rid else ""
    except Exception:
        return ""


def _pattern(control, attr: str):
    pid = getattr(auto.PatternId, attr, None)
    if pid is None:
        return None
    try:
        return control.GetPattern(pid)
    except Exception:
        return None


def _parent(control):
    try:
        return control.GetParentControl()
    except Exception:
        return None


# ── patrones ────────────────────────────────────────────────


def _detect_patterns(control, read_value: bool) -> tuple[list[str], dict]:
    patterns: list[str] = []
    extras: dict = {}
    for label, attr in _PATTERNS:
        pattern = _pattern(control, attr)
        if pattern is None:
            continue
        patterns.append(label)
        if label == "Value":
            readonly = _get(pattern, "IsReadOnly", None)
            if readonly is not None:
                extras["value_readonly"] = bool(readonly)
            if read_value:
                value = _get(pattern, "Value", "")
                if value:
                    extras["value_text"] = str(value)[:MAX_VALUE]
        elif label == "Toggle":
            state = _get(pattern, "ToggleState", None)
            if state is not None:
                extras["checked"] = state == auto.ToggleState.On
        elif label == "ExpandCollapse":
            state = _get(pattern, "ExpandCollapseState", None)
            if state is not None:
                extras["expand_state"] = _EXPAND_STATES.get(int(state), str(state))
        elif label == "SelectionItem":
            selected = _get(pattern, "IsSelected", None)
            if selected is not None:
                extras["selected"] = bool(selected)
        elif label == "GridItem":
            row, column = _get(pattern, "Row", None), _get(pattern, "Column", None)
            if row is not None and column is not None:
                extras["grid_row"], extras["grid_column"] = int(row), int(column)
    return patterns, extras


def _is_actionable(control) -> bool:
    if _ct(control) in ACTIONABLE_TYPES:
        return True
    return any(_pattern(control, attr) is not None for attr in ACTION_PATTERNS)


def promote_actionable(control, x: int, y: int):
    """Sube del nodo hoja genérico al ancestro accionable más cercano.

    Arregla que, p. ej., los botones de la Calculadora salgan como "Text". Se
    suben como máximo 4 niveles y solo si el ancestro sigue conteniendo el
    punto. Nunca se promociona un campo editable ni a una ventana.
    Devuelve (control_final, tipo_original_o_None).
    """
    original = _ct(control)
    if original not in GENERIC_TYPES:
        return control, None
    node = control
    for _ in range(4):
        parent = _parent(node)
        if parent is None:
            break
        parent_type = _ct(parent)
        if parent_type in {"Edit", "Document", "Window"}:
            break
        node = parent
        if _is_actionable(node) and _contains(node, x, y):
            return node, original
    return control, None


# ── ancestros y ruta ────────────────────────────────────────


def _chain(control, deadline: float) -> tuple[list, bool]:
    """[control, padre, abuelo, ...] y si se llegó a la raíz (escritorio)."""
    chain = [control]
    node = control
    for _ in range(MAX_DEPTH):
        if time.monotonic() > deadline:
            return chain, False
        parent = _parent(node)
        if parent is None:
            return chain, True
        chain.append(parent)
        node = parent
    return chain, False


def _sibling_index(node, parent, ctype: str, deadline: float) -> int | None:
    """Posición (base 1) entre los hermanos del MISMO tipo; None si no se sabe.

    Un índice equivocado haría que el selector apuntara a otro control, así
    que ante la duda (tiempo agotado, demasiados hermanos) se devuelve None y
    el selector se apoya solo en nombre / AutomationId.
    """
    if parent is None:
        return 1
    target = _runtime_id(node)
    if not target:
        return None
    try:
        child = parent.GetFirstChildControl()
    except Exception:
        return None
    index = 0
    seen = 0
    while child is not None and seen < MAX_SIBLINGS:
        if time.monotonic() > deadline:
            return None
        seen += 1
        if _ct(child) == ctype:
            index += 1
            if _runtime_id(child) == target:
                return index
        try:
            child = child.GetNextSiblingControl()
        except Exception:
            return None
    return None


def _segment(info: dict) -> str:
    """Segmento de la ruta legible: Button[AutomationId="num5Button"]."""
    ctype = info["control_type"] or "Custom"
    if info.get("automation_id"):
        return f'{ctype}[AutomationId="{info["automation_id"]}"]'
    if info.get("name"):
        return f'{ctype}["{info["name"][:40]}"]'
    return ctype


# ── procesos ────────────────────────────────────────────────

_process_names: dict[int, tuple[float, str]] = {}


def process_name(pid) -> str:
    """Nombre del ejecutable dueño del proceso (p. ej. 'notepad.exe'), con caché."""
    if not pid:
        return ""
    now = time.monotonic()
    cached = _process_names.get(pid)
    if cached and now - cached[0] < 60:
        return cached[1]
    name = ""
    try:
        import psutil

        name = psutil.Process(int(pid)).name()
    except Exception:
        name = ""
    _process_names[pid] = (now, name)
    if len(_process_names) > 256:
        _process_names.clear()
    return name


# ── API ─────────────────────────────────────────────────────


def thread_init() -> None:
    auto.InitializeUIAutomationInCurrentThread()


def thread_exit() -> None:
    try:
        auto.UninitializeUIAutomationInCurrentThread()
    except Exception:
        pass


def control_at(x: int, y: int):
    try:
        return auto.ControlFromPoint(int(x), int(y))
    except Exception:
        log.debug("ControlFromPoint falló en (%s,%s)", x, y, exc_info=True)
        return None


def focused_control():
    try:
        return auto.GetFocusedControl()
    except Exception:
        return None


def same(a, b) -> bool:
    if a is None or b is None:
        return False
    try:
        return bool(auto.ControlsAreSame(a, b))
    except Exception:
        return False


def build_element(control, promoted_from: str | None = None) -> dict:
    """Arma el dict ``element`` a partir de un Control de UI Automation."""
    started = time.monotonic()
    deadline = started + INDEX_BUDGET

    ctype = _ct(control)
    name = _text(_get(control, "Name", ""))
    automation_id = str(_get(control, "AutomationId", "") or "")
    class_name = str(_get(control, "ClassName", "") or "")
    help_text = _text(_get(control, "HelpText", ""))
    is_password = bool(_get(control, "IsPassword", False))
    secret = is_password or secret_hint(name, automation_id, help_text)

    patterns, extras = _detect_patterns(control, read_value=not secret)

    chain, reached_root = _chain(control, deadline)
    # Ventana top-level: hija directa del escritorio (penúltimo de la cadena).
    top = chain[-2] if reached_root and len(chain) >= 2 else chain[-1]
    window_idx = next((i for i, node in enumerate(chain) if _ct(node) == "Window"), None)
    if window_idx is None:
        window_idx = chain.index(top) if top in chain else len(chain) - 1
    nearest_window = chain[window_idx]

    # Ruta desde la ventana más cercana hasta el control.
    nodes = list(reversed(chain[: window_idx + 1]))
    truncated = False
    if len(nodes) > MAX_PATH:
        nodes = [nodes[0]] + nodes[-(MAX_PATH - 1):]
        truncated = True
    ancestors: list[dict] = []
    for pos, node in enumerate(nodes):
        node_type = _ct(node)
        info = {
            "control_type": node_type,
            "name": _text(_get(node, "Name", ""), 80),
            "automation_id": str(_get(node, "AutomationId", "") or ""),
            "class_name": str(_get(node, "ClassName", "") or ""),
            "index": 1,
        }
        if pos > 0:
            # El padre real del nodo es el siguiente en la cadena original.
            real_pos = chain.index(node) if node in chain else -1
            parent = chain[real_pos + 1] if 0 <= real_pos < len(chain) - 1 else _parent(node)
            info["index"] = _sibling_index(node, parent, node_type, deadline)
        ancestors.append(info)
    if truncated and len(ancestors) > 1:
        ancestors[1]["gap_before"] = True

    process_id = _get(control, "ProcessId", None) or _get(top, "ProcessId", None)
    element = {
        "platform": "windows",
        # ── claves de siempre (contrato con documentos y selectores) ──
        "control_type": ctype,
        "name": name,
        "automation_id": automation_id,
        "class_name": class_name,
        "checked": bool(extras.get("checked", False)),
        "path": " > ".join(_segment(a) for a in ancestors),
        "rect": _rect(control),
        "window": _text(_get(nearest_window, "Name", "")) or _text(_get(top, "Name", "")),
        "app": process_name(process_id),
        # ── ampliación ──
        "top_window": _text(_get(top, "Name", "")),
        "localized_control_type": _text(_get(control, "LocalizedControlType", "")),
        "framework_id": str(_get(control, "FrameworkId", "") or ""),
        "runtime_id": _runtime_id(control),
        "access_key": str(_get(control, "AccessKey", "") or ""),
        "accelerator_key": str(_get(control, "AcceleratorKey", "") or ""),
        "help_text": help_text,
        "is_enabled": bool(_get(control, "IsEnabled", True)),
        "is_offscreen": bool(_get(control, "IsOffscreen", False)),
        "is_password": is_password,
        "is_keyboard_focusable": bool(_get(control, "IsKeyboardFocusable", False)),
        "process_id": int(process_id) if process_id else None,
        "window_class": str(_get(top, "ClassName", "") or ""),
        "window_rect": _rect(top),
        "patterns": patterns,
        "ancestors": ancestors,
        "path_truncated": truncated,
    }
    for key in ("value_readonly", "expand_state", "selected", "grid_row", "grid_column"):
        if key in extras:
            element[key] = extras[key]
    if not secret and extras.get("value_text"):
        element["value_text"] = _text(extras["value_text"], 200)
    if promoted_from:
        element["promoted_from"] = promoted_from
    element["reliability"] = compute_reliability(element)
    element["inspect_ms"] = int((time.monotonic() - started) * 1000)
    return element


def read_value(control) -> str | None:
    """Contenido actual de un campo, o None si no se puede leer."""
    if control is None:
        return None
    if bool(_get(control, "IsPassword", False)):
        return None
    pattern = _pattern(control, "ValuePattern")
    if pattern is not None:
        value = _get(pattern, "Value", None)
        if value is not None:
            return str(value)[:MAX_VALUE]
    pattern = _pattern(control, "TextPattern")
    if pattern is not None:
        try:
            return str(pattern.DocumentRange.GetText(MAX_VALUE))
        except Exception:
            pass
    pattern = _pattern(control, "LegacyIAccessiblePattern")
    if pattern is not None:
        value = _get(pattern, "Value", None)
        if value is not None:
            return str(value)[:MAX_VALUE]
    return None


def is_editable(element: dict | None) -> bool:
    """¿Escribir en este control tiene sentido como paso de escritura?"""
    if not element:
        return False
    if element.get("is_password"):
        return True
    ctype = element.get("control_type")
    patterns = element.get("patterns") or []
    readonly = bool(element.get("value_readonly", False))
    if ctype == "Edit":
        return not readonly
    if ctype == "Document":
        # La página de Chrome/Edge es un Document de solo lectura: un clic ahí es un clic.
        if "Value" in patterns:
            return not readonly
        return "Text" in patterns and bool(element.get("is_keyboard_focusable")) and not readonly
    if ctype in {"ComboBox", "DataItem", "Custom", "Text", "ListItem", "Spinner"}:
        return "Value" in patterns and not readonly and bool(element.get("is_keyboard_focusable"))
    return False
