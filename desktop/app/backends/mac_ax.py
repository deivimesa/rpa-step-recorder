"""Inspección de elementos con la API de Accesibilidad de macOS (AXUIElement).

Equivalente al inspector de UI Automation de Windows: para un punto de la
pantalla (o el control con el foco) devuelve el mismo dict ``element``
normalizado. Los roles AX se traducen al vocabulario de tipos de control de
UI Automation (AXButton -> Button, AXTextField -> Edit...) para que las
descripciones, la fiabilidad y los documentos funcionen igual; los datos
propios de macOS (rol, subrol, AXIdentifier, acciones, bundle id) se
conservan para los selectores de AppleScript y la ruta AX.

Notas de robustez:
  - Se fija un tiempo máximo de mensajería (MESSAGING_TIMEOUT): una app
    colgada no bloquea la grabación (el valor por defecto de macOS es 6 s).
  - Se piden muchos atributos en UNA sola llamada IPC
    (AXUIElementCopyMultipleAttributeValues).
  - El valor de un campo seguro (AXSecureTextField) nunca se lee.
  - Las apps Electron (Slack, Teams, VS Code...) solo construyen su árbol de
    accesibilidad si se les pide (AXManualAccessibility): se activa la
    primera vez que se inspecciona cada app.
"""

from __future__ import annotations

import logging
import os
import time

from ApplicationServices import (
    AXUIElementCopyActionNames,
    AXUIElementCopyAttributeValue,
    AXUIElementCopyAttributeValues,
    AXUIElementCopyElementAtPosition,
    AXUIElementCopyMultipleAttributeValues,
    AXUIElementCreateApplication,
    AXUIElementCreateSystemWide,
    AXUIElementGetPid,
    AXUIElementIsAttributeSettable,
    AXUIElementSetAttributeValue,
    AXUIElementSetMessagingTimeout,
    AXValueGetType,
    AXValueGetValue,
    kAXValueAXErrorType,
    kAXValueCGPointType,
    kAXValueCGRectType,
    kAXValueCGSizeType,
)

from .base import compute_reliability, secret_hint

log = logging.getLogger("rpa.ax")

MESSAGING_TIMEOUT = 0.8
MAX_DEPTH = 40
MAX_PATH = 12
MAX_SIBLINGS = 300
INDEX_BUDGET = 1.0
MAX_VALUE = 4000

# Rol AX -> tipo de control normalizado (vocabulario de UI Automation).
ROLE_TO_TYPE = {
    "AXButton": "Button",
    "AXMenuButton": "Button",
    "AXDisclosureTriangle": "Button",
    "AXColorWell": "Button",
    "AXDockItem": "Button",
    "AXPopUpButton": "ComboBox",
    "AXComboBox": "ComboBox",
    "AXCheckBox": "CheckBox",
    "AXRadioButton": "RadioButton",
    "AXLink": "Hyperlink",
    "AXTextField": "Edit",
    "AXDateField": "Edit",
    "AXTextArea": "Document",
    "AXWebArea": "Document",
    "AXStaticText": "Text",
    "AXHeading": "Text",
    "AXImage": "Image",
    "AXGroup": "Group",
    "AXRadioGroup": "Group",
    "AXLayoutArea": "Pane",
    "AXLayoutItem": "Group",
    "AXScrollArea": "Pane",
    "AXSplitGroup": "Pane",
    "AXSplitter": "Thumb",
    "AXDrawer": "Pane",
    "AXApplication": "Pane",
    "AXMatte": "Pane",
    "AXRuler": "Pane",
    "AXWindow": "Window",
    "AXSheet": "Window",
    "AXMenuBar": "MenuBar",
    "AXMenuBarItem": "MenuItem",
    "AXMenu": "Menu",
    "AXMenuItem": "MenuItem",
    "AXToolbar": "ToolBar",
    "AXTabGroup": "Tab",
    "AXTable": "Table",
    "AXOutline": "Tree",
    "AXBrowser": "List",
    "AXList": "List",
    "AXGrid": "Table",
    "AXRow": "ListItem",
    "AXCell": "DataItem",
    "AXColumn": "HeaderItem",
    "AXSlider": "Slider",
    "AXLevelIndicator": "Slider",
    "AXIncrementor": "Spinner",
    "AXStepper": "Spinner",
    "AXProgressIndicator": "ProgressBar",
    "AXBusyIndicator": "ProgressBar",
    "AXRelevanceIndicator": "ProgressBar",
    "AXValueIndicator": "Thumb",
    "AXScrollBar": "ScrollBar",
    "AXHelpTag": "ToolTip",
    "AXUnknown": "Custom",
}

SUBROLE_TO_TYPE = {
    "AXSecureTextField": "Edit",
    "AXSearchField": "Edit",
    "AXSwitch": "CheckBox",
    "AXToggle": "CheckBox",
    "AXTabButton": "TabItem",
    "AXSortButton": "HeaderItem",
    "AXOutlineRow": "TreeItem",
    "AXTableRow": "ListItem",
}

GENERIC_ROLES = {"AXStaticText", "AXImage", "AXGroup", "AXUnknown", "AXLayoutItem", "AXHeading"}
ACTIONABLE_ROLES = {
    "AXButton", "AXMenuButton", "AXPopUpButton", "AXCheckBox", "AXRadioButton", "AXLink",
    "AXMenuItem", "AXMenuBarItem", "AXCell", "AXRow", "AXDisclosureTriangle", "AXComboBox",
    "AXDockItem", "AXColorWell", "AXIncrementor",
}
EDITABLE_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXDateField"}
CONTAINER_ROLES = {"AXWindow", "AXSheet", "AXDrawer", "AXMenuBar", "AXMenu", "AXApplication"}

_ATTRS = [
    "AXRole", "AXSubrole", "AXRoleDescription", "AXTitle", "AXDescription", "AXHelp",
    "AXIdentifier", "AXDOMIdentifier", "AXPlaceholderValue", "AXEnabled", "AXFocused",
    "AXPosition", "AXSize", "AXSelected", "AXExpanded", "AXURL", "AXTitleUIElement",
]
_NODE_ATTRS = ["AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXIdentifier", "AXDOMIdentifier"]

_system_wide = None
_prepared_apps: set[int] = set()
_app_info: dict[int, tuple[float, dict]] = {}


# ── utilidades ──────────────────────────────────────────────


def _system():
    global _system_wide
    if _system_wide is None:
        _system_wide = AXUIElementCreateSystemWide()
        try:
            AXUIElementSetMessagingTimeout(_system_wide, MESSAGING_TIMEOUT)
        except Exception:
            pass
    return _system_wide


def _plain(value):
    """Convierte un valor AX a tipos de Python; None si es un error/ausente."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    try:
        kind = AXValueGetType(value)
    except Exception:
        return value
    if kind == kAXValueCGPointType:
        point = AXValueGetValue(value, kind, None)[1]
        return (float(point.x), float(point.y))
    if kind == kAXValueCGSizeType:
        size = AXValueGetValue(value, kind, None)[1]
        return (float(size.width), float(size.height))
    if kind == kAXValueCGRectType:
        rect = AXValueGetValue(value, kind, None)[1]
        return (float(rect.origin.x), float(rect.origin.y), float(rect.size.width), float(rect.size.height))
    if kind == kAXValueAXErrorType:
        return None
    return value  # AXUIElement, listas, URLs...


def _attrs(element, names: list[str]) -> dict:
    try:
        err, values = AXUIElementCopyMultipleAttributeValues(element, names, 0, None)
    except Exception:
        return {}
    if err != 0 or values is None:
        return {}
    return {name: _plain(value) for name, value in zip(names, values)}


def _attr(element, name: str):
    try:
        err, value = AXUIElementCopyAttributeValue(element, name, None)
    except Exception:
        return None
    return _plain(value) if err == 0 else None


def _text(value, limit: int = 160) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return " ".join(str(value).split())[:limit]


def _pid(element) -> int | None:
    try:
        err, pid = AXUIElementGetPid(element, None)
        return int(pid) if err == 0 else None
    except Exception:
        return None


def _actions(element) -> list[str]:
    try:
        err, names = AXUIElementCopyActionNames(element, None)
        return [str(n) for n in names] if err == 0 and names else []
    except Exception:
        return []


def _settable(element, name: str) -> bool:
    try:
        err, ok = AXUIElementIsAttributeSettable(element, name, None)
        return bool(ok) if err == 0 else False
    except Exception:
        return False


def _rect(attrs: dict) -> dict | None:
    pos, size = attrs.get("AXPosition"), attrs.get("AXSize")
    if not (isinstance(pos, tuple) and isinstance(size, tuple)):
        return None
    width, height = size
    if width <= 0 or height <= 0:
        return None
    return {"x": int(round(pos[0])), "y": int(round(pos[1])), "width": int(round(width)), "height": int(round(height))}


def _contains(rect: dict | None, x: float, y: float) -> bool:
    return bool(rect) and rect["x"] <= x < rect["x"] + rect["width"] and rect["y"] <= y < rect["y"] + rect["height"]


def control_type_for(role: str, subrole: str = "", parent_role: str = "") -> str:
    if subrole in SUBROLE_TO_TYPE:
        return SUBROLE_TO_TYPE[subrole]
    if role == "AXRadioButton" and parent_role == "AXTabGroup":
        return "TabItem"
    if role == "AXRow" and parent_role == "AXOutline":
        return "TreeItem"
    return ROLE_TO_TYPE.get(role, "Custom")


def _name(attrs: dict, role: str, element) -> str:
    """Nombre visible al estilo VoiceOver: título, descripción, etiqueta asociada..."""
    for key in ("AXTitle", "AXDescription"):
        text = _text(attrs.get(key))
        if text:
            return text
    label_element = attrs.get("AXTitleUIElement")
    if label_element is not None and not isinstance(label_element, (str, bool, int, float, tuple)):
        for key in ("AXValue", "AXTitle", "AXDescription"):
            text = _text(_attr(label_element, key))
            if text:
                return text
    if role in {"AXStaticText", "AXCell", "AXHeading", "AXMenuItem"}:
        text = _text(_attr(element, "AXValue"))
        if text:
            return text
    if role in {"AXRow", "AXCell"}:
        # Una fila suele no tener nombre: se usa el texto de su primera celda.
        text = _first_text_inside(element)
        if text:
            return text
    for key in ("AXPlaceholderValue", "AXHelp"):
        text = _text(attrs.get(key))
        if text:
            return text
    return ""


def _first_text_inside(element, depth: int = 0) -> str:
    if depth > 3:
        return ""
    children = _attr(element, "AXChildren") or []
    for child in list(children)[:6]:
        role = _text(_attr(child, "AXRole"))
        if role == "AXStaticText":
            text = _text(_attr(child, "AXValue"))
            if text:
                return text
        text = _first_text_inside(child, depth + 1)
        if text:
            return text
    return ""


def app_info(pid: int | None) -> dict:
    """Nombre visible, bundle id y ejecutable de la app (con caché)."""
    if not pid:
        return {}
    now = time.monotonic()
    cached = _app_info.get(pid)
    if cached and now - cached[0] < 60:
        return cached[1]
    info: dict = {}
    try:
        from AppKit import NSRunningApplication

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        if app is not None:
            info["name"] = str(app.localizedName() or "")
            info["bundle_id"] = str(app.bundleIdentifier() or "")
            url = app.executableURL()
            info["executable"] = os.path.basename(str(url.path())) if url is not None else ""
    except Exception:
        log.debug("no se pudo leer la app del pid %s", pid, exc_info=True)
    _app_info[pid] = (now, info)
    if len(_app_info) > 256:
        _app_info.clear()
    return info


def _prepare_app(pid: int | None) -> None:
    """Pide a apps Electron/Chromium que expongan su árbol de accesibilidad."""
    if not pid or pid in _prepared_apps or pid == os.getpid():
        return
    _prepared_apps.add(pid)
    try:
        app = AXUIElementCreateApplication(int(pid))
        AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    except Exception:
        pass


# ── ancestros ───────────────────────────────────────────────


def _chain(element, deadline: float) -> list:
    """[elemento, padre, ...] hasta AXApplication (incluida) o el límite."""
    chain = [element]
    node = element
    for _ in range(MAX_DEPTH):
        if time.monotonic() > deadline:
            break
        parent = _attr(node, "AXParent")
        if parent is None or isinstance(parent, (str, bool, int, float, tuple)):
            break
        chain.append(parent)
        if _text(_attr(parent, "AXRole")) == "AXApplication":
            break
        node = parent
    return chain


def _indexes(node, parent, role: str, deadline: float) -> tuple[int | None, int | None]:
    """(índice entre hermanos del mismo rol, índice entre todos los hijos), base 1."""
    if parent is None:
        return 1, 1
    try:
        err, children = AXUIElementCopyAttributeValues(parent, "AXChildren", 0, MAX_SIBLINGS, None)
    except Exception:
        return None, None
    if err != 0 or not children:
        return None, None
    same = 0
    for position, child in enumerate(children, start=1):
        if time.monotonic() > deadline:
            return None, None
        child_role = _text(_attr(child, "AXRole"))
        if child_role == role:
            same += 1
        try:
            if child == node:
                return (same if child_role == role else None), position
        except Exception:
            return None, None
    return None, None


# ── API ─────────────────────────────────────────────────────


def element_at(x: float, y: float):
    try:
        err, element = AXUIElementCopyElementAtPosition(_system(), float(x), float(y), None)
    except Exception:
        return None
    return element if err == 0 else None


def focused_element():
    element = _attr(_system(), "AXFocusedUIElement")
    if element is None or isinstance(element, (str, bool, int, float, tuple)):
        return None
    return element


def same(a, b) -> bool:
    if a is None or b is None:
        return False
    try:
        return bool(a == b)
    except Exception:
        return False


def pid_of(element) -> int | None:
    return _pid(element) if element is not None else None


def promote_actionable(element, x: float, y: float):
    """Del texto/imagen genéricos al botón, enlace o celda que los contiene."""
    role = _text(_attr(element, "AXRole"))
    if role not in GENERIC_ROLES:
        return element, None
    node = element
    for _ in range(4):
        parent = _attr(node, "AXParent")
        if parent is None or isinstance(parent, (str, bool, int, float, tuple)):
            break
        attrs = _attrs(parent, ["AXRole", "AXPosition", "AXSize"])
        parent_role = _text(attrs.get("AXRole"))
        if parent_role in CONTAINER_ROLES or parent_role in EDITABLE_ROLES:
            break
        node = parent
        if (parent_role in ACTIONABLE_ROLES or "AXPress" in _actions(node)) and _contains(_rect(attrs), x, y):
            return node, control_type_for(role)
    return element, None


def build_element(element, promoted_from: str | None = None) -> dict:
    started = time.monotonic()
    deadline = started + INDEX_BUDGET
    pid = _pid(element)
    _prepare_app(pid)

    attrs = _attrs(element, _ATTRS)
    role = _text(attrs.get("AXRole"))
    subrole = _text(attrs.get("AXSubrole"))
    identifier = _text(attrs.get("AXIdentifier"), 200) or _text(attrs.get("AXDOMIdentifier"), 200)
    is_password = subrole == "AXSecureTextField"
    name = _name(attrs, role, element)
    placeholder = _text(attrs.get("AXPlaceholderValue"))
    help_text = _text(attrs.get("AXHelp"))
    secret = is_password or secret_hint(name, identifier, help_text, placeholder)

    chain = _chain(element, deadline)
    parent_role = _text(_attr(chain[1], "AXRole")) if len(chain) > 1 else ""
    control_type = control_type_for(role, subrole, parent_role)

    # Contenedor más cercano (ventana, hoja, menú) y ventana top-level.
    window_title = ""
    window_rect = None
    container_label = ""
    for node in chain[1:]:
        node_attrs = _attrs(node, ["AXRole", "AXTitle", "AXPosition", "AXSize"])
        node_role = _text(node_attrs.get("AXRole"))
        if node_role in {"AXWindow", "AXSheet", "AXDrawer"}:
            window_title = window_title or _text(node_attrs.get("AXTitle"))
            window_rect = _rect(node_attrs) or window_rect
            if node_role == "AXWindow":
                break
        elif node_role in {"AXMenuBar", "AXMenu"} and not container_label:
            container_label = "Barra de menús" if node_role == "AXMenuBar" else "Menú"

    # Ruta desde el primer hijo de la app hasta el elemento.
    nodes = list(reversed(chain))
    if nodes and _text(_attr(nodes[0], "AXRole")) == "AXApplication":
        nodes = nodes[1:]
    truncated = False
    if len(nodes) > MAX_PATH:
        nodes = [nodes[0]] + nodes[-(MAX_PATH - 1):]
        truncated = True
    ancestors: list[dict] = []
    for pos, node in enumerate(nodes):
        node_attrs = attrs if node is element else _attrs(node, _NODE_ATTRS)
        node_role = _text(node_attrs.get("AXRole"))
        real = next((i for i, n in enumerate(chain) if n is node), -1)
        parent = chain[real + 1] if 0 <= real < len(chain) - 1 else None
        same_index, child_index = _indexes(node, parent, node_role, deadline)
        ancestors.append({
            "role": node_role,
            "subrole": _text(node_attrs.get("AXSubrole")),
            "control_type": control_type_for(node_role, _text(node_attrs.get("AXSubrole"))),
            "name": _text(node_attrs.get("AXTitle"), 80) or _text(node_attrs.get("AXDescription"), 80),
            "title": _text(node_attrs.get("AXTitle"), 80),
            "automation_id": _text(node_attrs.get("AXIdentifier"), 120) or _text(node_attrs.get("AXDOMIdentifier"), 120),
            "index": same_index,
            "child_index": child_index,
        })
    if truncated and len(ancestors) > 1:
        ancestors[1]["gap_before"] = True

    actions = _actions(element)
    info = app_info(pid)
    element_dict = {
        "platform": "macos",
        "control_type": control_type,
        "name": name,
        "automation_id": identifier,
        "class_name": "",
        "checked": False,
        "path": " > ".join(_segment(a) for a in ancestors),
        "rect": _rect(attrs),
        "window": window_title or container_label,
        "app": info.get("name", ""),
        "bundle_id": info.get("bundle_id", ""),
        "executable": info.get("executable", ""),
        "ax_role": role,
        "ax_subrole": subrole,
        "localized_control_type": _text(attrs.get("AXRoleDescription")),
        "help_text": help_text,
        "placeholder": placeholder,
        "is_enabled": attrs.get("AXEnabled") is not False,
        "is_offscreen": False,
        "is_password": is_password,
        "is_keyboard_focusable": True,
        "value_settable": _settable(element, "AXValue"),
        "process_id": pid,
        "window_class": "",
        "window_rect": window_rect,
        "patterns": actions,
        "ancestors": ancestors,
        "path_truncated": truncated,
    }
    url = attrs.get("AXURL")
    if url is not None and not isinstance(url, (bool, tuple)):
        element_dict["url"] = _text(url, 300)
    if isinstance(attrs.get("AXSelected"), bool):
        element_dict["selected"] = attrs["AXSelected"]
    if isinstance(attrs.get("AXExpanded"), bool):
        element_dict["expand_state"] = "Expanded" if attrs["AXExpanded"] else "Collapsed"
    if role in {"AXCheckBox", "AXRadioButton"}:
        value = _attr(element, "AXValue")
        element_dict["checked"] = value in (1, True)
    elif not secret and role in EDITABLE_ROLES | {"AXStaticText", "AXCell"}:
        value = _attr(element, "AXValue")
        if isinstance(value, str) and value:
            element_dict["value_text"] = _text(value, 200)
    if promoted_from:
        element_dict["promoted_from"] = promoted_from
    element_dict["reliability"] = compute_reliability(element_dict)
    element_dict["inspect_ms"] = int((time.monotonic() - started) * 1000)
    return element_dict


def _segment(info: dict) -> str:
    role = info.get("role") or "AXUnknown"
    if info.get("automation_id"):
        return f'{role}[id="{info["automation_id"]}"]'
    if info.get("name"):
        return f'{role}["{info["name"][:40]}"]'
    return role


def read_value(element) -> str | None:
    if element is None:
        return None
    if _text(_attr(element, "AXSubrole")) == "AXSecureTextField":
        return None
    value = _attr(element, "AXValue")
    if isinstance(value, str):
        return value[:MAX_VALUE]
    if value is None:
        return None
    return str(value)[:MAX_VALUE]


def secure_value_length(element) -> int | None:
    """Longitud (no el contenido) de un campo seguro, para saber si se escribió algo."""
    if element is None:
        return None
    count = _attr(element, "AXNumberOfCharacters")
    if isinstance(count, int):
        return count
    value = _attr(element, "AXValue")
    return len(value) if isinstance(value, str) else None


def is_editable(element: dict | None) -> bool:
    if not element:
        return False
    if element.get("is_password"):
        return True
    role = element.get("ax_role")
    if role in EDITABLE_ROLES:
        return bool(element.get("value_settable", True))
    return False
