"""Del evento del agente web al paso: elemento, fiabilidad, selectores y texto.

Funciones puras (sin navegador ni interfaz) para poder probarlas solas. El
``element`` resultante usa el mismo vocabulario que el de escritorio
(``control_type``, ``name``, ``rect``...) para que las frases automáticas,
la interfaz y los documentos lo traten igual, y añade los datos del DOM
(etiqueta, id, selector CSS, XPath, URL) con ``platform == "web"``.
"""

from __future__ import annotations

import json
import re

from app.backends.base import looks_volatile, secret_hint
from app.core import phrases

# Rol ARIA (o implícito de la etiqueta) -> tipo de control de UI Automation.
ROLE_TO_CONTROL = {
    "button": "Button",
    "link": "Hyperlink",
    "checkbox": "CheckBox",
    "switch": "CheckBox",
    "radio": "RadioButton",
    "combobox": "ComboBox",
    "listbox": "List",
    "textbox": "Edit",
    "searchbox": "Edit",
    "tab": "TabItem",
    "menuitem": "MenuItem",
    "menuitemcheckbox": "MenuItem",
    "menuitemradio": "MenuItem",
    "option": "ListItem",
    "listitem": "ListItem",
    "treeitem": "TreeItem",
    "gridcell": "DataItem",
    "cell": "DataItem",
    "columnheader": "HeaderItem",
    "img": "Image",
    "image": "Image",
    "slider": "Slider",
    "spinbutton": "Spinner",
    "heading": "Text",
}

# Roles con los que Playwright localiza bien por get_by_role.
_PLAYWRIGHT_ROLES = {
    "button", "link", "checkbox", "radio", "switch", "tab", "menuitem", "option",
    "combobox", "textbox", "searchbox", "treeitem", "heading", "slider", "spinbutton",
}

# Ids que generan los frameworks y cambian entre cargas de la página.
_WEB_VOLATILE = re.compile(
    r"^:r[0-9a-z]+:$"                      # React useId
    r"|^(ember|ext-gen|ext-comp|gwt-uid-|j_idt|yui_|ui-id-)\S*\d"  # Ember, ExtJS, GWT, JSF, YUI, jQuery UI
    r"|^(mat|cdk|mui|radix|headlessui|react-select)-\S*\d+$"     # Angular Material, MUI, Radix...
    r"|\d{5,}",
    re.IGNORECASE,
)


def web_volatile(identifier: str) -> bool:
    """¿El id del DOM parece generado y cambiante entre cargas?"""
    return looks_volatile(identifier) or bool(_WEB_VOLATILE.search(identifier or ""))


def _round_rect(rect: dict | None) -> dict | None:
    if not rect or not rect.get("width") or not rect.get("height"):
        return None
    return {key: round(float(rect.get(key) or 0)) for key in ("x", "y", "width", "height")}


def build_element(data: dict, browser_name: str, page_url: str = "", page_title: str = "") -> dict | None:
    """``element`` normalizado a partir del evento del agente (o None)."""
    dom = data.get("element")
    if not dom:
        return None
    role = dom.get("role") or dom.get("tag") or ""
    url = data.get("url") or page_url
    title = data.get("title") or page_title
    element = {
        "platform": "web",
        "control_type": ROLE_TO_CONTROL.get(role, "Custom"),
        "role": role,
        "tag": dom.get("tag", ""),
        "input_type": dom.get("type", ""),
        "name": dom.get("text", ""),
        "label": dom.get("label", ""),
        "dom_id": dom.get("id", ""),
        "id_unique": bool(dom.get("id_unique")),
        "dom_name": dom.get("name", ""),
        "name_unique": bool(dom.get("name_unique")),
        "test_attr": dom.get("test_attr", ""),
        "test_id": dom.get("test_id", ""),
        "aria_label": dom.get("aria_label", ""),
        "placeholder": dom.get("placeholder", ""),
        "href": dom.get("href", ""),
        "css": dom.get("css", ""),
        "css_unique": bool(dom.get("css_unique")),
        "xpath": dom.get("xpath", ""),
        "xpath_text": dom.get("xpath_text", ""),
        "checked": bool(dom.get("checked")),
        "is_enabled": not dom.get("disabled"),
        "in_shadow": bool(dom.get("in_shadow")),
        "is_password": dom.get("type") == "password",
        "url": url,
        "page_title": title,
        "frame_url": data.get("frame_url", ""),
        "frame_path": [f for f in (data.get("frame_path") or []) if isinstance(f, str)],
        "rect": _round_rect(data.get("rect")),
        "app": browser_name,
        "window": title,
    }
    element["reliability"] = reliability(element)
    return element


# ── fiabilidad ──────────────────────────────────────────────

_FORM_TAGS = {"input", "select", "textarea", "button"}


def reliability(element: dict) -> dict:
    """Heurística de fiabilidad del mejor selector web (como la de escritorio)."""
    reasons: list[str] = []
    dom_id = element.get("dom_id") or ""
    stable_id = bool(dom_id) and element.get("id_unique") and not web_volatile(dom_id)
    text = element.get("name") or ""
    role = element.get("role") or ""

    if stable_id:
        score, best = 95, "id"
        reasons.append("Tiene un id único y estable en la página")
    elif element.get("test_id"):
        score, best = 92, "atributo de prueba"
        reasons.append(f"Tiene un atributo de prueba ({element.get('test_attr')})")
    elif element.get("dom_name") and element.get("name_unique") and element.get("tag") in _FORM_TAGS:
        score, best = 90, "name"
        reasons.append("Campo con un atributo name único")
    elif text and (element.get("xpath_text") or role in _PLAYWRIGHT_ROLES):
        score, best = 75, "texto+rol"
        reasons.append("Sin id; se identifica por su texto visible y su rol")
    elif element.get("css_unique") and ":nth-of-type" not in (element.get("css") or ""):
        score, best = 60, "css"
        reasons.append("Sin id ni texto; se usa un selector CSS por clases")
    else:
        score, best = 40, "ruta"
        reasons.append("Sin id ni texto; solo una ruta por posición en la página")

    if dom_id and web_volatile(dom_id):
        reasons.append("El id parece generado automáticamente (puede cambiar)")
    if element.get("frame_url"):
        reasons.append("Está dentro de un iframe: el bot debe entrar antes en ese marco")
    if element.get("in_shadow"):
        score = min(score, 45)
        reasons.append("Está dentro de un Shadow DOM: el XPath del documento no lo alcanza")
    if element.get("is_enabled") is False:
        score = min(score, 45)
        reasons.append("El elemento estaba deshabilitado")

    level = "alta" if score >= 90 else "media" if score >= 50 else "baja"
    return {"level": level, "score": score, "reasons": reasons, "best_selector": best}


# ── selectores ──────────────────────────────────────────────


def _q(value: str) -> str:
    """Literal de cadena con comillas dobles, válido en Python y en JavaScript."""
    return json.dumps(value, ensure_ascii=False)


def _xml(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&apos;").replace('"', "&quot;"))


def _playwright(element: dict) -> str:
    role = element.get("role") or ""
    text = element.get("name") or ""
    dom_id = element.get("dom_id") or ""
    if element.get("test_attr") == "data-testid" and element.get("test_id"):
        return f"page.get_by_test_id({_q(element['test_id'])})"
    if dom_id and element.get("id_unique") and not web_volatile(dom_id):
        return f"page.locator({_q('#' + dom_id)})"
    if role in ("textbox", "searchbox", "combobox") and element.get("label"):
        return f"page.get_by_label({_q(element['label'])})"
    if role in _PLAYWRIGHT_ROLES and text:
        return f"page.get_by_role({_q(role)}, name={_q(text)})"
    if element.get("placeholder"):
        return f"page.get_by_placeholder({_q(element['placeholder'])})"
    return f"page.locator({_q(element.get('css') or element.get('xpath') or '')})"


def _playwright_in_frames(element: dict) -> str:
    """Playwright entra en cada iframe con frame_locator antes de buscar el elemento."""
    locator = _playwright(element)
    frames = element.get("frame_path") or []
    if not frames:
        return locator
    return "page" + "".join(f".frame_locator({_q(f)})" for f in frames) + locator[len("page"):]


def _selenium(element: dict) -> str:
    dom_id = element.get("dom_id") or ""
    if dom_id and element.get("id_unique") and not web_volatile(dom_id):
        find = f"driver.find_element(By.ID, {_q(dom_id)})"
    elif element.get("dom_name") and element.get("name_unique"):
        find = f"driver.find_element(By.NAME, {_q(element['dom_name'])})"
    elif element.get("xpath_text"):
        find = f"driver.find_element(By.XPATH, {_q(element['xpath_text'])})"
    else:
        find = f"driver.find_element(By.CSS_SELECTOR, {_q(element.get('css') or '')})"
    # Selenium tiene que cambiar de marco antes de buscar dentro de un iframe.
    switches = [f"driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, {_q(f)}))"
                for f in element.get("frame_path") or []]
    return "; ".join(switches + [find])


def _uipath(element: dict, process: str) -> str:
    title = element.get("page_title") or ""
    if len(title) > 40:
        title = title[:40] + "*"
    top = f"<html app='{_xml(process or 'chrome.exe')}' title='{_xml(title)}' />" if title else \
        f"<html app='{_xml(process or 'chrome.exe')}' />"
    tag = (element.get("tag") or "*").upper()
    dom_id = element.get("dom_id") or ""
    if dom_id and element.get("id_unique") and not web_volatile(dom_id):
        ctrl = f"<webctrl id='{_xml(dom_id)}' tag='{tag}' />"
    elif element.get("dom_name") and element.get("name_unique"):
        ctrl = f"<webctrl name='{_xml(element['dom_name'])}' tag='{tag}' />"
    elif element.get("name"):
        ctrl = f"<webctrl aaname='{_xml(element['name'])}' tag='{tag}' />"
    else:
        ctrl = f"<webctrl css-selector='{_xml(element.get('css') or '')}' tag='{tag}' />"
    frames = "".join(f"<webctrl css-selector='{_xml(f)}' tag='IFRAME' />" for f in element.get("frame_path") or [])
    return top + frames + ctrl


def build_selectors(element: dict | None, process: str = "") -> dict:
    if not element:
        return {}
    sel = {"css": element.get("css", ""), "xpath": element.get("xpath", "")}
    if element.get("xpath_text"):
        sel["xpath_text"] = element["xpath_text"]
    sel["uipath"] = _uipath(element, process)
    sel["playwright"] = _playwright_in_frames(element)
    sel["selenium"] = _selenium(element)
    return {k: v for k, v in sel.items() if v}


# ── descripción del paso ────────────────────────────────────


def secret_of(data: dict, element: dict | None) -> str:
    """"password" | "sensitive" | "": la decisión del agente más la de la app."""
    kind = data.get("secret") or ""
    if kind:
        return kind
    if element and element.get("is_password"):
        return "password"
    if element and secret_hint(element.get("name", ""), element.get("dom_id", ""), element.get("dom_name", ""),
                               element.get("placeholder", ""), element.get("label", "")):
        return "sensitive"
    return ""


def describe(data: dict, element: dict | None) -> tuple[str, str, str, str]:
    """(tipo de paso, descripción, valor para el documento, secreto)."""
    kind = data.get("kind") or "click"
    if kind in ("click", "right_click"):
        return kind, phrases.describe_click(element, kind), "", ""
    if kind == "input":
        secret = secret_of(data, element)
        value = "" if secret else str(data.get("value") or "")
        return "input", phrases.describe_input(element, value, secret), value[:4000], secret
    if kind == "select":
        chosen = str(data.get("value") or "")
        name = (element or {}).get("label") or (element or {}).get("dom_name") or ""
        where = f" en la lista {phrases.quote(name)}" if name else ""
        return "select", f"Seleccionar {phrases.quote(chosen)}{where}", chosen, ""
    if kind == "key":
        label = data.get("key") or "Enter"
        return "key", phrases.describe_key(label, element), "", ""
    return kind, phrases.describe_click(element, "click"), "", ""
