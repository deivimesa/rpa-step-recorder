"""Descripciones automáticas de los pasos, en español y como instrucciones.

Comunes a Windows y macOS: el backend de macOS traduce los roles de
Accesibilidad (AXButton, AXTextField...) al mismo vocabulario de tipos de
control que UI Automation (Button, Edit...), así que una única tabla sirve
para ambos.
"""

from __future__ import annotations

# Verbo + sustantivo por tipo de control: el paso se lee como una instrucción.
PHRASE_ES = {
    "Button": ("Clic en", "el botón"),
    "SplitButton": ("Clic en", "el botón"),
    "Hyperlink": ("Clic en", "el enlace"),
    "CheckBox": ("Marcar", "la casilla"),
    "RadioButton": ("Seleccionar", "la opción"),
    "ComboBox": ("Abrir", "la lista desplegable"),
    "Edit": ("Clic en", "el campo"),
    "Document": ("Clic en", "el documento"),
    "TabItem": ("Abrir", "la pestaña"),
    "MenuItem": ("Elegir", "la opción de menú"),
    "MenuBar": ("Clic en", "la barra de menús"),
    "ListItem": ("Seleccionar", "el elemento"),
    "TreeItem": ("Seleccionar", "el elemento del árbol"),
    "DataItem": ("Seleccionar", "la celda"),
    "HeaderItem": ("Clic en", "el encabezado"),
    "Slider": ("Ajustar", "el control deslizante"),
    "Spinner": ("Ajustar", "el selector numérico"),
    "ScrollBar": ("Usar", "la barra de desplazamiento"),
    "Image": ("Clic en", "la imagen"),
    "Text": ("Clic en", "el texto"),
    "TitleBar": ("Clic en", "la barra de título"),
    "Window": ("Clic en", "la ventana"),
    "ToolBar": ("Clic en", "la barra de herramientas"),
    "StatusBar": ("Clic en", "la barra de estado"),
    "Table": ("Clic en", "la tabla"),
    "List": ("Clic en", "la lista"),
    "Tree": ("Clic en", "el árbol"),
    "Calendar": ("Elegir una fecha en", "el calendario"),
    "Tab": ("Clic en", "las pestañas"),
}

# Etiqueta corta para tarjetas e índices.
KIND_ES = {
    "Button": "Botón",
    "SplitButton": "Botón",
    "Hyperlink": "Enlace",
    "CheckBox": "Casilla",
    "RadioButton": "Opción",
    "ComboBox": "Lista",
    "Edit": "Campo",
    "Document": "Documento",
    "TabItem": "Pestaña",
    "MenuItem": "Menú",
    "ListItem": "Elemento",
    "TreeItem": "Árbol",
    "DataItem": "Celda",
    "Image": "Imagen",
    "Text": "Texto",
    "Window": "Ventana",
}

# Tipo de acción del paso -> etiqueta para la interfaz y el documento.
STEP_KIND_ES = {
    "click": "Clic",
    "right_click": "Clic derecho",
    "double_click": "Doble clic",
    "input": "Escritura",
    "select": "Selección",
    "key": "Tecla",
    "shortcut": "Atajo",
    "note": "Nota",
}

MAX_QUOTE = 60


def quote(text: str, limit: int = MAX_QUOTE) -> str:
    """Texto entre comillas angulares, en una línea y recortado si es largo."""
    clean = " ".join(str(text or "").replace("\r", " ").replace("\n", " ↵ ").split())
    if len(clean) > limit:
        clean = clean[: limit - 1].rstrip() + "…"
    return f"«{clean}»"


def describe_click(element: dict | None, kind: str = "click", point: tuple | None = None) -> str:
    """Descripción de un clic (simple, derecho o doble) sobre un elemento."""
    if not element:
        where = f" en la posición ({point[0]}, {point[1]})" if point else " en la pantalla"
        prefix = {"right_click": "Clic derecho", "double_click": "Doble clic"}.get(kind, "Clic")
        return prefix + where
    role = element.get("control_type") or "Custom"
    name = element.get("name") or ""
    verb, noun = PHRASE_ES.get(role, ("Clic en", "el elemento"))
    if kind == "right_click":
        verb = "Clic derecho en"
    elif kind == "double_click":
        verb = "Doble clic en"
    elif role == "CheckBox" and element.get("checked"):
        verb = "Desmarcar"
    return f"{verb} {noun} {quote(name)}" if name else f"{verb} {noun}"


def describe_input(element: dict | None, value: str, secret: str = "") -> str:
    """Escritura en un campo. ``secret``: "" | "password" | "sensitive"."""
    name = (element or {}).get("name") or ""
    target = f" en el campo {quote(name)}" if name else " en el campo"
    if secret == "password":
        return "Escribir la contraseña" + target
    if secret:
        return "Escribir un dato confidencial" + target
    if not value:
        return "Vaciar el campo" + (f" {quote(name)}" if name else "")
    return f"Escribir {quote(value)}" + target


def describe_key(label: str, element: dict | None = None, app: str = "") -> str:
    name = (element or {}).get("name") or ""
    if name:
        return f"Pulsar {label} en {quote(name, 40)}"
    if app:
        return f"Pulsar {label} en {app}"
    return f"Pulsar {label}"


def control_card(element: dict | None) -> dict:
    """Lo que la interfaz muestra para confirmar de un vistazo qué se capturó."""
    if not element:
        return {"role": "", "kind": "Pantalla", "name": ""}
    role = element.get("control_type") or ""
    return {"role": role, "kind": KIND_ES.get(role, "Elemento"), "name": element.get("name", "")}
