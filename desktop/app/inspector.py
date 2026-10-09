"""Inspección del elemento de escritorio bajo el cursor con UI Automation.

Reemplaza la lectura del DOM de content.js. Para un punto de la pantalla
devuelve el control type, el nombre, el AutomationId, el ClassName, el
rectángulo y una ruta jerárquica estable que quien programe el bot puede usar
para localizar el control (equivale al selector CSS / XPath de la versión web).

Esta versión robustece la captura: lee muchas más propiedades UIA (de forma
defensiva, sin romper nunca si una falla), detecta los ControlPatterns
soportados, promueve el nodo hoja genérico al ancestro accionable más cercano
(arregla que los botones de la Calculadora salgan como "Text") y calcula una
heurística de fiabilidad del selector (`reliability`).

Contrato: el dict `element` conserva TODAS sus claves originales
(control_type, name, automation_id, class_name, checked, path, rect, window,
app) y solo añade claves nuevas; las firmas públicas (inspect_point, role_of,
describe, control_card, is_secret, EDITABLE_TYPES, PHRASE_ES, KIND_ES,
_control_type_name, _clean) se mantienen intactas.
"""

from __future__ import annotations

import os

import uiautomation as auto

# Verbo + sustantivo por tipo de control: el paso se lee como una instrucción.
PHRASE_ES = {
    "Button": ("Clic en", "el botón"),
    "Hyperlink": ("Clic en", "el enlace"),
    "CheckBox": ("Marcar", "la casilla"),
    "RadioButton": ("Seleccionar", "la opción"),
    "ComboBox": ("Seleccionar un valor en", "la lista desplegable"),
    "Edit": ("Escribir en", "el campo"),
    "TabItem": ("Abrir", "la pestaña"),
    "MenuItem": ("Elegir", "la opción de menú"),
    "ListItem": ("Elegir", "el elemento"),
    "TreeItem": ("Expandir", "el elemento"),
    "SplitButton": ("Clic en", "el botón"),
}

KIND_ES = {
    "Button": "Botón",
    "Hyperlink": "Enlace",
    "CheckBox": "Casilla",
    "RadioButton": "Opción",
    "ComboBox": "Lista",
    "Edit": "Campo",
    "TabItem": "Pestaña",
    "MenuItem": "Menú",
    "ListItem": "Elemento",
    "TreeItem": "Árbol",
    "SplitButton": "Botón",
}

# Campos cuyo contenido nunca se guarda.
SECRET_HINTS = ("pass", "contrase", "clave", "pin", "cvv", "cvc", "secret", "token", "tarjeta", "card")

# Tipos editables: lo interesante es lo que se escribe, no el clic.
EDITABLE_TYPES = {"Edit", "Document"}

# Tipos genéricos que, por sí solos, rara vez son el objetivo real del clic.
GENERIC_TYPES = {"Text", "Custom", "Image", "Pane", "Group"}

# Tipos que se consideran accionables aunque no expongan un patrón concreto.
ACTIONABLE_TYPES = {
    "Button",
    "Hyperlink",
    "MenuItem",
    "ListItem",
    "TabItem",
    "CheckBox",
    "RadioButton",
    "SplitButton",
}

# ClassName de ventanas Tk (Tkinter): la UI del grabador es Tkinter.
_TK_WINDOW_CLASSES = {"TkTopLevel", "tk"}

# Títulos de ventana propios del grabador. La UI los registra al arrancar con
# register_own_titles() para que el respaldo de es_ventana_propia() pueda
# descartar los clics sobre nuestras propias ventanas (y solo las nuestras).
_OWN_WINDOW_TITLES: set[str] = set()


def register_own_titles(titulos: list[str]) -> None:
    """Registra los títulos de las ventanas propias del grabador.

    La UI (Tkinter) debe llamar a esta función con los títulos de sus
    ventanas ("RPA Step Recorder" y las de revisión) para que el respaldo de
    es_ventana_propia() sepa reconocerlas. Se ignoran los títulos vacíos.
    """
    for titulo in titulos or []:
        texto = (titulo or "").strip()
        if texto:
            _OWN_WINDOW_TITLES.add(texto)


def unregister_own_titles(titulos: list[str]) -> None:
    """Da de baja títulos propios (p. ej. al cerrar una ventana de revisión).

    Evita que el set crezca sin límite. El título del panel principal no se
    da de baja porque la ventana vive toda la sesión.
    """
    for titulo in titulos or []:
        _OWN_WINDOW_TITLES.discard((titulo or "").strip())


def es_ventana_propia(element: dict) -> bool:
    """¿El elemento pertenece a una ventana del propio grabador?

    Evita que el grabador se capture a sí mismo. Criterios (OR):
      1. El process_id del elemento coincide con el de este proceso Python
         (la UI Tkinter corre en el mismo proceso que el worker).
      2. Respaldo combinado: la ventana es Tk (window_class en
         _TK_WINDOW_CLASSES o vacío) Y su título está entre los títulos
         propios registrados. Esta doble condición evita descartar por error
         aplicaciones Tk de terceros.
    """
    if not element:
        return False

    # Criterio 1: mismo proceso.
    if element.get("process_id") == os.getpid():
        return True

    # Criterio 2: respaldo por clase Tk EXPLÍCITA + título propio registrado.
    # No tratamos window_class vacío como Tk: si UIA falla al leer el
    # ClassName, un título coincidente de una app de terceros daría un falso
    # positivo y descartaría clics legítimos.
    window_class = element.get("window_class") or ""
    window_title = (element.get("window") or "").strip()
    if window_class in _TK_WINDOW_CLASSES and window_title and window_title in _OWN_WINDOW_TITLES:
        return True

    return False


def _control_type_name(control) -> str:
    """'ButtonControl' -> 'Button'."""
    try:
        name = control.ControlTypeName or ""
    except Exception:
        return ""
    return name[:-7] if name.endswith("Control") else name


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(str(text).split())[:120]


def is_secret(element: dict) -> bool:
    hints = " ".join(
        str(element.get(key, "")) for key in ("name", "automation_id", "class_name")
    ).lower()
    return any(hint in hints for hint in SECRET_HINTS)


def _window_of(control):
    """Sube hasta la ventana de nivel superior que contiene al control."""
    node = control
    top = control
    try:
        depth = 0
        while node and depth < 40:
            if _control_type_name(node) == "Window":
                top = node
            parent = node.GetParentControl()
            if parent is None:
                break
            node = parent
            depth += 1
    except Exception:
        pass
    return top


def _build_path(control) -> str:
    """Ruta jerárquica estable desde la ventana hasta el control.

    Cada segmento es ControlType con AutomationId o nombre cuando existen.
    Es el equivalente al selector CSS: ayuda a quien programa el bot a volver
    a encontrar el elemento.
    """
    segments: list[str] = []
    node = control
    depth = 0
    try:
        while node and depth < 12:
            ctype = _control_type_name(node)
            if not ctype:
                break
            auto_id = ""
            name = ""
            try:
                auto_id = node.AutomationId or ""
                name = node.Name or ""
            except Exception:
                pass
            if auto_id:
                segments.append(f'{ctype}[AutomationId="{auto_id}"]')
            elif name:
                segments.append(f'{ctype}["{_clean(name)[:40]}"]')
            else:
                segments.append(ctype)
            if ctype == "Window":
                break
            parent = node.GetParentControl()
            if parent is None:
                break
            node = parent
            depth += 1
    except Exception:
        pass
    return " > ".join(reversed(segments))


def describe(element: dict, role: str) -> str:
    name = element.get("name") or ""
    verb, noun = PHRASE_ES.get(role, ("Clic en", "el elemento"))
    if role == "CheckBox" and element.get("checked"):
        verb = "Desmarcar"
    return f"{verb} {noun} «{name}»" if name else f"{verb} {noun}"


def control_card(role: str, name: str) -> dict:
    """Lo que la tarjeta muestra para confirmar de un vistazo qué se capturó."""
    return {"role": role, "kind": KIND_ES.get(role, "Elemento"), "name": name}


def _checked(control) -> bool:
    try:
        pattern = control.GetTogglePattern()
        return bool(pattern) and pattern.ToggleState == auto.ToggleState.On
    except Exception:
        return False


# ── nuevas utilidades defensivas ────────────────────────────


def _safe(control, attr: str) -> str:
    """Lee un atributo string del control sin romper nunca."""
    try:
        value = getattr(control, attr, "")
        return value or ""
    except Exception:
        return ""


def _safe_bool(control, attr: str, default: bool = False) -> bool:
    try:
        value = getattr(control, attr, default)
        return bool(value)
    except Exception:
        return default


def _safe_int(control, attr: str):
    try:
        value = getattr(control, attr, None)
        return int(value) if value is not None else None
    except Exception:
        return None


def _runtime_id(control) -> str:
    """RuntimeId (lista de enteros) como cadena unida por '-'."""
    try:
        rid = getattr(control, "GetRuntimeId", None)
        values = rid() if callable(rid) else None
        if not values:
            return ""
        return "-".join(str(part) for part in values)
    except Exception:
        return ""


def _rect_contains(rect, x: int, y: int) -> bool:
    """¿El BoundingRectangle contiene el punto (x, y)?"""
    try:
        return bool(rect.left <= x <= rect.right and rect.top <= y <= rect.bottom)
    except Exception:
        return False


def _bounds_of(control):
    """Dict con el BoundingRectangle del control, o None si falla."""
    try:
        rect = control.BoundingRectangle
        return {
            "x": rect.left,
            "y": rect.top,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        }
    except Exception:
        return None


def _detect_patterns(control) -> dict:
    """Detecta los ControlPatterns soportados probando sus getters.

    Devuelve un dict con:
      - "patterns": lista de nombres de patrón detectados.
      - extras opcionales: value_text, checked, expand_state.
    Cada getter va en su propio try/except: si devuelve algo no-None, el
    patrón se considera soportado.
    """
    patterns: list[str] = []
    extras: dict = {}

    try:
        pattern = control.GetInvokePattern()
        if pattern is not None:
            patterns.append("Invoke")
    except Exception:
        pass

    try:
        pattern = control.GetValuePattern()
        if pattern is not None:
            patterns.append("Value")
            try:
                text = pattern.Value
                if text:
                    extras["value_text"] = _clean(text)
            except Exception:
                pass
    except Exception:
        pass

    try:
        pattern = control.GetTogglePattern()
        if pattern is not None:
            patterns.append("Toggle")
            try:
                extras["checked"] = pattern.ToggleState == auto.ToggleState.On
            except Exception:
                pass
    except Exception:
        pass

    try:
        pattern = control.GetSelectionPattern()
        if pattern is not None:
            patterns.append("Selection")
    except Exception:
        pass

    try:
        pattern = control.GetSelectionItemPattern()
        if pattern is not None:
            patterns.append("SelectionItem")
    except Exception:
        pass

    try:
        pattern = control.GetExpandCollapsePattern()
        if pattern is not None:
            patterns.append("ExpandCollapse")
            try:
                extras["expand_state"] = str(pattern.ExpandCollapseState)
            except Exception:
                pass
    except Exception:
        pass

    try:
        pattern = control.GetScrollPattern()
        if pattern is not None:
            patterns.append("Scroll")
    except Exception:
        pass

    try:
        pattern = control.GetTextPattern()
        if pattern is not None:
            patterns.append("Text")
    except Exception:
        pass

    return {"patterns": patterns, "extras": extras}


def _is_actionable(control, patterns: list[str] | None = None) -> bool:
    """¿El control es accionable por tipo o por patrones expuestos?"""
    ctype = _control_type_name(control)
    if ctype in ACTIONABLE_TYPES:
        return True
    if patterns is None:
        patterns = _detect_patterns(control)["patterns"]
    return any(
        name in patterns
        for name in ("Invoke", "Toggle", "SelectionItem", "ExpandCollapse")
    )


def _promote_actionable(control, x: int, y: int):
    """Promueve el nodo hoja genérico al ancestro accionable más cercano.

    Si el nodo es de tipo genérico (Text/Custom/Image/Pane/Group) y NO es
    editable, sube como máximo 4 niveles buscando un ancestro accionable cuyo
    BoundingRectangle siga conteniendo (x, y). Nunca promueve editables.

    Devuelve (control_final, promoted_from) donde promoted_from es el
    ControlType original si hubo promoción, o None si no la hubo.
    """
    ctype = _control_type_name(control)
    if ctype in EDITABLE_TYPES:
        return control, None
    if ctype not in GENERIC_TYPES:
        return control, None

    node = control
    try:
        for _ in range(4):
            parent = node.GetParentControl()
            if parent is None:
                break
            parent_type = _control_type_name(parent)
            if parent_type in EDITABLE_TYPES:
                break
            node = parent
            if _is_actionable(node):
                rect = None
                try:
                    rect = node.BoundingRectangle
                except Exception:
                    rect = None
                if rect is not None and _rect_contains(rect, x, y):
                    return node, ctype
    except Exception:
        pass
    return control, None


def _ancestors(control) -> list[dict]:
    """Lista de ancestros desde el top-level hacia el elemento.

    Cada entrada es un dict {control_type, name, automation_id, class_name,
    index}, donde index es la posición (base 1) del nodo entre los hermanos
    del MISMO ControlType. Si es hijo único de ese tipo, index=1. Máximo 12
    niveles.
    """
    chain = []
    node = control
    depth = 0
    try:
        while node and depth < 12:
            chain.append(node)
            if _control_type_name(node) == "Window":
                break
            parent = node.GetParentControl()
            if parent is None:
                break
            node = parent
            depth += 1
    except Exception:
        pass

    chain.reverse()  # de top-level hacia el elemento

    result: list[dict] = []
    for node in chain:
        ctype = _control_type_name(node)
        info = {
            "control_type": ctype,
            "name": _clean(_safe(node, "Name")),
            "automation_id": _safe(node, "AutomationId"),
            "class_name": _safe(node, "ClassName"),
            "index": _sibling_index(node, ctype),
        }
        result.append(info)
    return result


def _sibling_index(node, ctype: str) -> int:
    """Posición (base 1) del nodo entre sus hermanos del MISMO ControlType.

    Compara por RuntimeId cuando está disponible y, como respaldo, por la
    igualdad de control de uiautomation. Si no se logra identificar el nodo
    (ningún match), devuelve 1 en vez del total de hermanos: un índice mayor
    al real haría que el selector apuntara al elemento equivocado.
    """
    try:
        parent = node.GetParentControl()
        if parent is None:
            return 1
        index = 0
        node_rid = _runtime_id(node)
        for child in parent.GetChildren():
            if _control_type_name(child) != ctype:
                continue
            index += 1
            if node_rid:
                if _runtime_id(child) == node_rid:
                    return index
            else:
                try:
                    if child == node or child.Element == node.Element:
                        return index
                except Exception:
                    pass
        return 1
    except Exception:
        return 1


def _looks_volatile(automation_id: str) -> bool:
    """¿El AutomationId parece volátil (puramente numérico o muy largo)?"""
    if not automation_id:
        return True
    if automation_id.isdigit():
        return True
    if len(automation_id) > 20:
        return True
    return False


def _compute_reliability(element: dict) -> dict:
    """Heurística de fiabilidad del mejor selector disponible.

    Devuelve {level, score, reasons, best_selector}. Combina la presencia de
    identificadores estables (AutomationId, Name + ControlType significativo,
    ClassName + ruta) con señales negativas (fuera de pantalla, deshabilitado,
    AutomationId volátil).
    """
    reasons: list[str] = []
    control_type = element.get("control_type") or ""
    automation_id = element.get("automation_id") or ""
    name = element.get("name") or ""
    class_name = element.get("class_name") or ""
    is_offscreen = bool(element.get("is_offscreen"))
    is_enabled = element.get("is_enabled")
    has_indexed_ancestors = any(
        isinstance(a, dict) and a.get("index") for a in element.get("ancestors") or []
    )
    significant_type = bool(control_type) and control_type not in {"Text", "Custom", "Pane"}

    score = 0
    best_selector = "ruta"

    if automation_id and not _looks_volatile(automation_id):
        score = 95
        best_selector = "AutomationId"
        reasons.append("Tiene AutomationId estable")
    elif name and significant_type:
        score = 80
        best_selector = "Name+ControlType"
        reasons.append("Sin AutomationId; se usa Name junto al ControlType")
    elif class_name and has_indexed_ancestors:
        score = 60
        best_selector = "ClassName+ruta"
        reasons.append("Sin Name fuerte; se usa ClassName con la ruta de ancestros")
    else:
        score = 40
        best_selector = "ruta"
        reasons.append("Elemento genérico sin identificadores fuertes; solo ruta por índices")

    if automation_id and _looks_volatile(automation_id):
        reasons.append("El AutomationId parece volátil (numérico o muy largo)")

    if is_offscreen:
        score = min(score, 45)
        reasons.append("El elemento está fuera de pantalla (IsOffscreen)")
    if is_enabled is False:
        score = min(score, 45)
        reasons.append("El elemento está deshabilitado (IsEnabled=False)")

    score = max(0, min(100, score))

    if score >= 90:
        level = "alta"
    elif score >= 50:
        level = "media"
    else:
        level = "baja"

    return {
        "level": level,
        "score": score,
        "reasons": reasons,
        "best_selector": best_selector,
    }


def inspect_point(x: int, y: int) -> dict | None:
    """Inspecciona el control de escritorio en la coordenada de pantalla (x, y).

    Devuelve un dict con los datos del elemento o None si no hay nada útil.
    Robustece la captura: promueve el nodo hoja genérico al ancestro
    accionable más cercano, lee propiedades UIA extra de forma defensiva,
    detecta patrones soportados, construye la cadena de ancestros y calcula la
    fiabilidad del selector.
    """
    try:
        control = auto.ControlFromPoint(x, y)
    except Exception:
        return None
    if not control:
        return None

    try:
        # Promoción "closest accionable" sobre el nodo hoja genérico.
        promoted_from = None
        try:
            control, promoted_from = _promote_actionable(control, x, y)
        except Exception:
            promoted_from = None
        return _build_element(control, promoted_from)
    except Exception:
        return None


def inspect_focused() -> dict | None:
    """Inspecciona el control que tiene el FOCO de teclado.

    Se usa para las pulsaciones de tecla: la tecla pertenece al control
    enfocado, no al que esté bajo el ratón. Devuelve el mismo dict `element`
    que inspect_point o None si no hay foco accesible.
    """
    try:
        control = auto.GetFocusedControl()
    except Exception:
        return None
    if not control:
        return None
    try:
        # No se promociona: el foco ya apunta al control real (p. ej. un Edit).
        return _build_element(control, None)
    except Exception:
        return None


def _build_element(control, promoted_from) -> dict:
    """Arma el dict `element` a partir de un control de UI Automation.

    Lógica compartida por inspect_point e inspect_focused. Lee las propiedades
    de forma defensiva, detecta patrones, construye la cadena de ancestros y
    calcula la fiabilidad del selector.
    """
    control_type = _control_type_name(control)
    name = _clean(_safe(control, "Name"))
    bounds = _bounds_of(control)

    # Ventana top-level y datos de aplicación.
    window = _window_of(control)
    window_name = ""
    window_class = ""
    try:
        window_name = _clean(_safe(window, "Name"))
    except Exception:
        pass
    try:
        window_class = _safe(window, "ClassName")
    except Exception:
        pass

    process_id = _safe_int(control, "ProcessId")
    if process_id is None:
        process_id = _safe_int(window, "ProcessId")

    # Rectángulo de la ventana top-level (para coordenadas relativas a ella).
    try:
        window_rect = _bounds_of(window)
    except Exception:
        window_rect = None

    app_name = ""
    try:
        app_name = _process_name(window)
    except Exception:
        pass

    # Patrones soportados y extras derivados.
    detected = {"patterns": [], "extras": {}}
    try:
        detected = _detect_patterns(control)
    except Exception:
        pass
    patterns = detected.get("patterns", [])
    extras = detected.get("extras", {})

    checked = _checked(control)
    if "checked" in extras:
        checked = bool(extras["checked"])

    # Cadena de ancestros.
    try:
        ancestors = _ancestors(control)
    except Exception:
        ancestors = []

    element = {
        # ── claves originales (contrato intacto) ──
        "control_type": control_type,
        "name": name,
        "automation_id": _safe(control, "AutomationId"),
        "class_name": _safe(control, "ClassName"),
        "checked": checked,
        "path": _build_path(control),
        "rect": bounds,
        "window": window_name,
        "app": app_name,
        # ── claves nuevas ──
        "localized_control_type": _clean(_safe(control, "LocalizedControlType")),
        "framework_id": _safe(control, "FrameworkId"),
        "runtime_id": _runtime_id(control),
        "access_key": _safe(control, "AccessKey"),
        "accelerator_key": _safe(control, "AcceleratorKey"),
        "help_text": _clean(_safe(control, "HelpText")),
        "is_enabled": _safe_bool(control, "IsEnabled", True),
        "is_offscreen": _safe_bool(control, "IsOffscreen", False),
        "process_id": process_id,
        "window_class": window_class,
        "window_rect": window_rect,
        "patterns": patterns,
        "ancestors": ancestors,
    }

    if promoted_from:
        element["promoted_from"] = promoted_from
    # value_text es el contenido real del campo (ValuePattern). Si el campo
    # es secreto (contraseña, PIN, tarjeta...), NUNCA debe quedar en disco.
    if "value_text" in extras and not is_secret(element):
        element["value_text"] = extras["value_text"]
    if "expand_state" in extras:
        element["expand_state"] = extras["expand_state"]

    element["reliability"] = _compute_reliability(element)
    return element


def _process_name(window) -> str:
    """Nombre del ejecutable dueño de la ventana (p. ej. 'notepad.exe')."""
    try:
        import psutil  # opcional

        pid = window.ProcessId
        return psutil.Process(pid).name()
    except Exception:
        pass
    # Sin psutil: devuelve el nombre de la ventana como aproximación de la app.
    try:
        return _clean(window.Name)
    except Exception:
        return ""


def role_of(element: dict) -> str:
    return element.get("control_type") or "Custom"
