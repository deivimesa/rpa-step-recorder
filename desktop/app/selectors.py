"""Construcción de selectores multi-herramienta a partir de un `element`.

A partir del dict `element` que produce `inspector.inspect_point` genera tres
representaciones de selector para que quien programe el bot pueda localizar el
control con distintas herramientas:

  - "uia_xpath": una expresión XPath-like sobre la cadena de ancestros.
  - "pywinauto": kwargs listos para pywinauto (backend "uia").
  - "uipath": una cadena XML al estilo de los selectores de UiPath.

Todas las funciones degradan con elegancia: si falta un dato, el atributo
correspondiente simplemente se omite. Nunca lanzan por datos ausentes.
"""

from __future__ import annotations


def _xml_escape(value: str) -> str:
    """Escapa comillas y caracteres XML en un valor de atributo."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("'", "&apos;")
        .replace('"', "&quot;")
    )


def _segment_xpath(node: dict) -> str:
    """Construye un segmento XPath para un ancestro.

    Prioridad de identificador: AutomationId, luego Name, y como último
    recurso ControlType con índice entre hermanos del mismo tipo.
    """
    control_type = node.get("control_type") or "Custom"
    automation_id = node.get("automation_id") or ""
    name = node.get("name") or ""
    index = node.get("index") or 1

    if automation_id:
        return f"{control_type}[@AutomationId='{_xml_escape(automation_id)}']"
    if name:
        return f"{control_type}[@Name='{_xml_escape(name)}']"
    return f"{control_type}[{index}]"


def _uia_xpath(element: dict) -> str:
    """XPath-like sobre los ancestros (de top-level hacia el elemento).

    Ej.: /Window[@ClassName='...']/.../Button[@AutomationId='num5Button'].
    Si no hay ancestros, cae a un único segmento con los datos del elemento.
    """
    ancestors = element.get("ancestors") or []
    segments: list[str] = []

    for node in ancestors:
        if not isinstance(node, dict):
            continue
        control_type = node.get("control_type") or ""
        if not control_type:
            continue
        # La ventana top-level se identifica mejor por ClassName si lo hay.
        if control_type == "Window" and node.get("class_name"):
            segments.append(
                f"Window[@ClassName='{_xml_escape(node['class_name'])}']"
            )
        else:
            segments.append(_segment_xpath(node))

    if not segments:
        # Degradación: sin ancestros usamos lo que haya del propio elemento.
        fallback = {
            "control_type": element.get("control_type"),
            "automation_id": element.get("automation_id"),
            "name": element.get("name"),
            "index": 1,
        }
        segments.append(_segment_xpath(fallback))

    return "/" + "/".join(segments)


def _pywinauto(element: dict) -> dict:
    """Kwargs para pywinauto con backend "uia".

    - connect: por `process` (process_id) si está, si no por `title_re`
      (nombre de la ventana).
    - child_window: auto_id, title, control_type y class_name según existan.
    """
    connect: dict = {}
    process_id = element.get("process_id")
    window = element.get("window") or ""
    if process_id:
        connect["process"] = process_id
    elif window:
        # Título exacto (no title_re): un título con ()[].* rompería el regex.
        connect["title"] = window

    child_window: dict = {}
    if element.get("automation_id"):
        child_window["auto_id"] = element["automation_id"]
    if element.get("name"):
        child_window["title"] = element["name"]
    if element.get("control_type"):
        child_window["control_type"] = element["control_type"]
    if element.get("class_name"):
        child_window["class_name"] = element["class_name"]

    return {
        "backend": "uia",
        "connect": connect,
        "child_window": child_window,
    }


def _uipath(element: dict) -> str:
    """Selector XML al estilo UiPath.

    Ej.: <wnd app="chrome.exe" cls="..." title="..." />
         <uia automationid="..." name="..." role="button" />
    Omite los atributos cuyo valor esté vacío.
    """

    def attrs(pairs: list[tuple[str, str]]) -> str:
        parts = [f'{key}="{_xml_escape(value)}"' for key, value in pairs if value]
        return (" " + " ".join(parts)) if parts else ""

    wnd = attrs(
        [
            ("app", element.get("app") or ""),
            ("cls", element.get("window_class") or ""),
            ("title", element.get("window") or ""),
        ]
    )

    role = element.get("localized_control_type") or element.get("control_type") or ""
    uia = attrs(
        [
            ("automationid", element.get("automation_id") or ""),
            ("name", element.get("name") or ""),
            ("role", role.lower() if role else ""),
        ]
    )

    return f"<wnd{wnd} /><uia{uia} />"


def build_selectors(element: dict) -> dict:
    """Devuelve los tres selectores (uia_xpath, pywinauto, uipath).

    Degrada con elegancia ante datos ausentes y nunca lanza por un `element`
    incompleto; si `element` es falsy, trabaja sobre un dict vacío.
    """
    element = element or {}
    return {
        "uia_xpath": _uia_xpath(element),
        "pywinauto": _pywinauto(element),
        "uipath": _uipath(element),
    }
