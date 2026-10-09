"""Textos y tablas que comparten el generador de Word y el de PDF.

Port de lib/doc-common.js a Python. El documento lo lee gente de negocio,
por eso los tipos de control van en español.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

ACCENT_HEX = "D62D2D"
INK_HEX = "1A1A1A"
MUTED_HEX = "6B6B6B"
RULE_HEX = "DDDDDD"

# ── Tipografía del documento (unificada Word + PDF) ─────────
# Familias de documento.
DOC_FONT = "Calibri"            # cuerpo en Word
DOC_FONT_HEADING = "Segoe UI"   # encabezados en Word
PDF_FONT = "DejaVu"             # fuente Unicode incrustada en el PDF
PDF_FONT_MONO = "DejaVuMono"    # monoespaciada Unicode del PDF

# Escala del documento (pt) — compartida Word/PDF.
FS_TITLE, FS_H1, FS_STEP, FS_SUBTITLE = 26, 16, 15, 13
FS_LEAD, FS_SECTION, FS_BODY, FS_SMALL, FS_CAPTION = 12, 10, 10, 9, 8

# Interlineado (factor) por rol tipográfico.
LH_TITLE, LH_HEADING, LH_LEAD, LH_BODY = 1.1, 1.25, 1.35, 1.4

# Colores de los niveles de fiabilidad (compartidos por Word y PDF).
GREEN_HEX = "1F8A3B"
AMBER_HEX = "B87A00"
RED_HEX = "C02B2B"

# Mapa nivel -> color y etiqueta corta, para badges y tablas de resumen.
REL_LEVEL_HEX = {"alta": GREEN_HEX, "media": AMBER_HEX, "baja": RED_HEX}
REL_SHORT = {"alta": "Alta", "media": "Media", "baja": "Baja"}

DOC_SUBTITLE = "Documento de definición de proceso (PDD)"

# Tipo de control de UI Automation -> nombre en español para el documento.
CONTROL_ES = {
    "Button": "Botón",
    "Hyperlink": "Enlace",
    "CheckBox": "Casilla de verificación",
    "RadioButton": "Botón de opción",
    "ComboBox": "Lista desplegable",
    "Edit": "Campo de texto",
    "Document": "Área de texto",
    "TabItem": "Pestaña",
    "MenuItem": "Opción de menú",
    "ListItem": "Elemento de lista",
    "TreeItem": "Elemento de árbol",
    "Image": "Imagen",
    "Text": "Texto",
    "DataItem": "Celda de datos",
    "Spinner": "Selector numérico",
    "Slider": "Control deslizante",
    "Window": "Ventana",
    "Pane": "Panel",
    "Custom": "Elemento",
}


def control_label(element: dict | None) -> str:
    """Nombre legible del tipo de control."""
    if not element:
        return "Elemento"
    control_type = element.get("control_type") or ""
    base = CONTROL_ES.get(control_type)
    if base:
        return base
    if control_type:
        return control_type
    return "Elemento"


def pretty_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        date = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso
    return date.strftime("%d/%m/%Y %H:%M")


def step_text(step: dict) -> str:
    return (step.get("description") or step.get("suggestion") or f"Paso {step.get('index')}").strip()


def duration(session: dict) -> str:
    started = session.get("started_at")
    finished = session.get("finished_at")
    if not started or not finished:
        return ""
    try:
        total = max(0, round((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()))
    except (ValueError, TypeError):
        return ""
    if not total:
        return ""
    minutes = total // 60
    seconds = total % 60
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


def cover_rows(session: dict) -> list[list[str]]:
    steps = session.get("steps", [])
    rows = [
        ["Proceso", session.get("name", "")],
        ["Sistema / aplicación", session.get("system") or "—"],
        ["Autor", session.get("author") or "—"],
        ["Fecha de grabación", pretty_date(session.get("started_at", "")) or "—"],
        ["Total de pasos", str(len(steps))],
    ]
    span = duration(session)
    if span:
        rows.append(["Duración de la grabación", span])

    apps: list[str] = []
    for step in steps:
        app_name = step.get("app") or ""
        if app_name and app_name not in apps:
            apps.append(app_name)
    if apps:
        rows.append(["Aplicaciones", "\n".join(apps[:3])])
    return rows


RELIABILITY_ES = {
    "alta": "Alta — el bot debería localizar el elemento sin problemas",
    "media": "Media — revisar el selector antes de automatizar",
    "baja": "Baja — este paso puede hacer fallar la automatización",
}


def metadata_rows(step: dict) -> list[list[str]]:
    """Datos técnicos que necesita quien programa el bot."""
    element = step.get("element")
    rows: list[list[str]] = []
    if element:
        rows.append(["Elemento", control_label(element)])
        if element.get("name"):
            rows.append(["Texto visible", element["name"]])

    if step.get("secret"):
        rows.append(["Valor", "(contraseña — no se guarda)"])
    elif step.get("value"):
        label = "Opción elegida" if step.get("kind") == "select" else "Valor escrito"
        rows.append([label, step["value"]])

    if element:
        if element.get("automation_id"):
            rows.append(["AutomationId", element["automation_id"]])
        if element.get("class_name"):
            rows.append(["ClassName", element["class_name"]])
        if element.get("control_type"):
            rows.append(["ControlType", element["control_type"]])
        if element.get("localized_control_type"):
            rows.append(["Tipo (local)", element["localized_control_type"]])
        if element.get("framework_id"):
            rows.append(["Framework", element["framework_id"]])
        if element.get("access_key"):
            rows.append(["Tecla de acceso", element["access_key"]])
        if element.get("patterns"):
            rows.append(["Interacción (patrones)", ", ".join(element["patterns"])])
        if element.get("path"):
            rows.append(["Ruta del control", element["path"]])
    if step.get("app"):
        rows.append(["Aplicación", step["app"]])
    if step.get("window"):
        rows.append(["Ventana", step["window"]])

    # Coordenadas cartesianas: fallback para cuando el selector no basta
    # (elementos por capas o la app abre en otra resolución).
    rows.extend(coordinate_rows(step))

    rows.append(["Registrado", pretty_date(step.get("timestamp", ""))])
    return rows


def coordinate_rows(step: dict) -> list[list[str]]:
    """Coordenadas del clic para reproducirlo si el selector falla.

    Incluye el punto absoluto, el clic relativo al elemento (en píxeles y
    normalizado 0..1, robusto a cambios de tamaño) y relativo a la ventana.
    """
    coords = step.get("coords") or {}
    rows: list[list[str]] = []

    click = coords.get("click_desktop")
    if click:
        rows.append(["Clic (pantalla)", f"x={click.get('x')}, y={click.get('y')}"])

    el = coords.get("element")
    if el:
        parts = [f"offset {el.get('offset_x')},{el.get('offset_y')} px"]
        if el.get("norm_x") is not None and el.get("norm_y") is not None:
            parts.append(f"normalizado {el['norm_x']:.3f},{el['norm_y']:.3f}")
        rows.append(["Clic en el elemento", " · ".join(parts)])

    win = coords.get("window")
    if win and win.get("norm_x") is not None and win.get("norm_y") is not None:
        rows.append(
            ["Clic en la ventana", f"normalizado {win['norm_x']:.3f},{win['norm_y']:.3f}"]
        )

    mon = coords.get("monitor")
    if mon and mon.get("index") is not None:
        rows.append(["Monitor", f"#{mon['index']} ({mon.get('width')}×{mon.get('height')})"])

    return rows


def reliability_summary(step: dict) -> str:
    """Texto legible de la fiabilidad del paso para el documento."""
    rel = step.get("reliability") or (step.get("element") or {}).get("reliability")
    if not rel:
        return ""
    level = rel.get("level", "")
    base = RELIABILITY_ES.get(level, level)
    reasons = rel.get("reasons") or []
    if reasons:
        return f"{base}. {reasons[0]}."
    return base


def step_level(step: dict) -> str:
    """Nivel de fiabilidad del paso ('alta' | 'media' | 'baja' | '')."""
    rel = step.get("reliability") or (step.get("element") or {}).get("reliability") or {}
    return rel.get("level", "")


def reliability_counts(session: dict) -> dict:
    """Cuenta los pasos por nivel de fiabilidad.

    Devuelve {total, alta, media, baja}. Un paso sin nivel (p. ej. notas sin
    elemento) solo suma al total.
    """
    steps = session.get("steps", [])
    counts = {"total": len(steps), "alta": 0, "media": 0, "baja": 0}
    for step in steps:
        level = step_level(step)
        if level in ("alta", "media", "baja"):
            counts[level] += 1
    return counts


def reliability_overview(session: dict) -> str:
    """Línea compacta tipo «Pasos: 10 · Alta 7 · Media 2 · Baja 1»."""
    counts = reliability_counts(session)
    partes = [f"Pasos: {counts['total']}"]
    for level in ("alta", "media", "baja"):
        if counts[level]:
            partes.append(f"{REL_SHORT[level]} {counts[level]}")
    return " · ".join(partes)


def reliability_warning(session: dict) -> str:
    """Aviso breve si hay pasos de fiabilidad baja que requieren revisión."""
    counts = reliability_counts(session)
    if not counts["baja"]:
        return ""
    plural = "s" if counts["baja"] != 1 else ""
    return (
        f"{counts['baja']} paso{plural} con fiabilidad baja requiere{'n' if counts['baja'] != 1 else ''} "
        "revisión manual antes de automatizar."
    )


# Claves de metadata_rows que describen la identificación del elemento. Las
# demás (aplicación, ventana, coordenadas, registro) van a "Ubicación".
_IDENTIFICATION_KEYS = {
    "Elemento",
    "Texto visible",
    "Valor",
    "Opción elegida",
    "Valor escrito",
    "AutomationId",
    "ClassName",
    "ControlType",
    "Tipo (local)",
    "Framework",
    "Tecla de acceso",
    "Interacción (patrones)",
    "Ruta del control",
}


def identification_rows(step: dict) -> list[list[str]]:
    """Subconjunto de metadata_rows relativo a la identificación del elemento."""
    return [row for row in metadata_rows(step) if row[0] in _IDENTIFICATION_KEYS]


def location_rows(step: dict) -> list[list[str]]:
    """Subconjunto de metadata_rows relativo a dónde está el elemento.

    Incluye aplicación, ventana, coordenadas y marca de registro.
    """
    return [row for row in metadata_rows(step) if row[0] not in _IDENTIFICATION_KEYS]


def selector_rows(step: dict) -> list[list[str]]:
    """Selectores listos para herramientas RPA (UIA, pywinauto, UiPath)."""
    sel = step.get("selectors") or {}
    rows: list[list[str]] = []
    if sel.get("uia_xpath"):
        rows.append(["Selector UIA (XPath)", sel["uia_xpath"]])
    pyw = sel.get("pywinauto")
    if pyw and pyw.get("child_window"):
        kwargs = ", ".join(f"{k}={v!r}" for k, v in pyw["child_window"].items())
        rows.append(["pywinauto", f"child_window({kwargs})"])
    if sel.get("uipath"):
        rows.append(["Selector UiPath", sel["uipath"]])
    return rows


def slugify(text: str, fallback: str = "proceso") -> str:
    """Nombre de archivo seguro en Windows."""
    ascii_text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug[:60] or fallback
