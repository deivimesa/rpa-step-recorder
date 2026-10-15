"""Captura de pantalla del escritorio con mss.

Reemplaza chrome.tabs.captureVisibleTab. Captura el monitor donde ocurrió el
clic y traslada el rectángulo del elemento al origen de esa captura, para que
annotate.py dibuje el recuadro en el sitio correcto.
"""

from __future__ import annotations

import mss
from PIL import Image


def grab_for_point(x: int, y: int, rect: dict | None):
    """Captura el monitor que contiene (x, y).

    Devuelve una tupla de tres: (imagen_PIL, rect_trasladado_o_None,
    monitor_info). El rect de entrada está en coordenadas globales de
    escritorio; el de salida, relativo a la imagen. monitor_info describe el
    monitor usado: {"index" (1-based), "left", "top", "width", "height"}.
    """
    with mss.mss() as sct:
        index, monitor = _monitor_for(sct, x, y)
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    # En macOS (Retina) la captura tiene más píxeles que puntos tiene el
    # monitor: el rectángulo del elemento (en puntos) se escala al de la imagen.
    scale = image.width / monitor["width"] if monitor.get("width") else 1.0

    local_rect = None
    if rect and rect.get("width", 0) > 0:
        local_rect = {
            "x": round((rect["x"] - monitor["left"]) * scale),
            "y": round((rect["y"] - monitor["top"]) * scale),
            "width": round(rect["width"] * scale),
            "height": round(rect["height"] * scale),
        }

    monitor_info = {
        "index": index,
        "left": monitor["left"],
        "top": monitor["top"],
        "width": monitor["width"],
        "height": monitor["height"],
        "scale": round(scale, 3),
    }
    return image, local_rect, monitor_info


def _monitor_for(sct, x: int, y: int) -> tuple[int, dict]:
    """Devuelve (índice_1based, monitor) del monitor que contiene (x, y).

    monitors[0] es el escritorio virtual completo; 1..n son cada pantalla.
    El índice devuelto es 1-based respecto a esas pantallas (1 = primera).
    """
    for i, monitor in enumerate(sct.monitors[1:], start=1):
        if (
            monitor["left"] <= x < monitor["left"] + monitor["width"]
            and monitor["top"] <= y < monitor["top"] + monitor["height"]
        ):
            return i, monitor
    if len(sct.monitors) > 1:
        return 1, sct.monitors[1]
    return 0, sct.monitors[0]
