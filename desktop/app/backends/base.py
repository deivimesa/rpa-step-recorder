"""Interfaz común de los backends de plataforma y utilidades compartidas.

Un backend sabe tres cosas de su sistema operativo:
  1. Inspeccionar el elemento de la interfaz en un punto o con el foco
     (UI Automation en Windows, Accesibilidad en macOS).
  2. Escuchar el ratón y el teclado de forma global.
  3. Integrarse con el sistema: permisos, ocultar nuestras ventanas de las
     capturas, abrir archivos, avisos del entorno...

El resto de la app (grabador, documentos, interfaz) trabaja con el dict
``element`` normalizado y no necesita saber en qué sistema corre.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable


class HookError(Exception):
    """No se pudieron activar los hooks globales (permiso denegado, etc.)."""


@dataclass
class Permission:
    key: str
    title: str
    description: str
    granted: bool | None          # None = no se puede saber
    restart_needed: bool = False  # el SO exige reabrir la app tras concederlo


# ── heurística de campos confidenciales ─────────────────────

# Palabras largas: basta con que aparezcan como subcadena.
_SECRET_SUBSTRINGS = (
    "password", "passwd", "passcode", "passphrase", "contraseña", "contrasena",
    "contraseña", "senha", "secret", "secreto", "token", "clave",
    "card number", "cardnumber", "card_number", "ccnumber", "cc-number",
    "credit card", "número de tarjeta", "numero de tarjeta", "nº de tarjeta",
    "tarjeta de crédito", "tarjeta de credito", "security code",
    "código de seguridad", "codigo de seguridad",
)
# Palabras cortas: solo como palabra completa ("pin" no debe casar con "Shipping").
_SECRET_WORDS = re.compile(r"\b(pin|cvv2?|cvc2?|nip|otp|pwd|pass|iban)\b", re.IGNORECASE)


def secret_hint(*texts: str) -> bool:
    """¿Algún texto del control sugiere un dato confidencial?"""
    joined = " ".join(str(t or "") for t in texts).lower()
    if not joined.strip():
        return False
    if any(word in joined for word in _SECRET_SUBSTRINGS):
        return True
    # Identificadores tipo "txtPin" / "user_pwd": se separan las palabras.
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", " ".join(str(t or "") for t in texts))
    spaced = re.sub(r"[_\-.:/]+", " ", spaced)
    return bool(_SECRET_WORDS.search(spaced))


# ── fiabilidad del selector ─────────────────────────────────

_GUIDISH = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}")
_NUMBERED = re.compile(r"^[A-Za-z_:\-]*\d{4,}$")


def looks_volatile(identifier: str) -> bool:
    """¿El identificador parece generado y cambiante entre ejecuciones?"""
    if not identifier:
        return True
    if identifier.isdigit():
        return True
    if identifier.startswith("_NS:"):  # ids automáticos de Interface Builder (macOS)
        return True
    if _GUIDISH.search(identifier):
        return True
    if _NUMBERED.match(identifier):
        return True
    return len(identifier) > 64


def compute_reliability(element: dict) -> dict:
    """Heurística de fiabilidad del mejor selector disponible.

    Devuelve {level, score, reasons, best_selector}: un identificador estable
    vale más que el texto visible, y este más que una ruta por índices. El
    elemento fuera de pantalla o deshabilitado penaliza.
    """
    reasons: list[str] = []
    control_type = element.get("control_type") or ""
    identifier = element.get("automation_id") or ""
    name = element.get("name") or ""
    class_name = element.get("class_name") or ""
    mac = element.get("platform") == "macos"
    id_label = "identificador AX" if mac else "AutomationId"
    has_indexed = any(isinstance(a, dict) and a.get("index") for a in element.get("ancestors") or [])
    significant = bool(control_type) and control_type not in {"Text", "Custom", "Pane", "Group"}

    if identifier and not looks_volatile(identifier):
        score, best = 95, "AutomationId"
        reasons.append(f"Tiene {id_label} estable")
    elif name and significant:
        score, best = 80, "Name+ControlType"
        reasons.append(f"Sin {id_label}; se identifica por su texto visible y su tipo")
    elif (class_name or mac) and has_indexed:
        score, best = 60, "ruta"
        reasons.append("Sin texto ni identificador fuertes; se usa la ruta de controles")
    else:
        score, best = 40, "ruta"
        reasons.append("Elemento genérico sin identificadores fuertes; solo ruta por posición")

    if identifier and looks_volatile(identifier):
        reasons.append(f"El {id_label} parece generado automáticamente (puede cambiar)")
    if element.get("is_offscreen"):
        score = min(score, 45)
        reasons.append("El elemento estaba fuera de pantalla")
    if element.get("is_enabled") is False:
        score = min(score, 45)
        reasons.append("El elemento estaba deshabilitado")
    if element.get("path_truncated"):
        reasons.append("La ruta es muy profunda; el selector usa un salto (//)")

    level = "alta" if score >= 90 else "media" if score >= 50 else "baja"
    return {"level": level, "score": score, "reasons": reasons, "best_selector": best}


# ── backend base ────────────────────────────────────────────


class Backend:
    """Backend mínimo: sin inspección de elementos (solo coordenadas)."""

    name = "generic"
    label = "Genérico"
    inspection = False

    # proceso / hilos
    def prepare_process(self) -> None:
        """Se llama antes de crear la ventana principal (p. ej. DPI en Windows)."""

    def thread_init(self) -> None:
        """Se llama al arrancar el hilo de inspección (p. ej. COM en Windows)."""

    def thread_exit(self) -> None:
        pass

    # inspección (solo desde el hilo de inspección)
    def inspect_point(self, x: int, y: int) -> tuple[dict | None, Any]:
        return None, None

    def inspect_focused(self) -> tuple[dict | None, Any]:
        return None, None

    def focused_handle(self) -> Any:
        return None

    def same_element(self, a: Any, b: Any) -> bool:
        return False

    def read_value(self, handle: Any) -> str | None:
        return None

    def is_editable(self, element: dict | None) -> bool:
        return False

    def secret_kind(self, element: dict | None) -> str:
        """"password" si es un campo de contraseña, "sensitive" si lo parece, "" si no."""
        if not element:
            return ""
        if element.get("is_password"):
            return "password"
        hint = secret_hint(
            element.get("name", ""),
            element.get("automation_id", ""),
            element.get("help_text", ""),
            element.get("placeholder", ""),
        )
        return "sensitive" if hint else ""

    def is_own_point(self, x: int, y: int) -> bool | None:
        """¿El punto cae sobre una ventana del propio grabador? None = no se sabe."""
        return None

    def is_own_element(self, element: dict | None) -> bool:
        return bool(element) and element.get("process_id") == os.getpid()

    def build_selectors(self, element: dict | None) -> dict:
        return {}

    # entrada global
    def start_hooks(self, on_mouse: Callable, on_key: Callable) -> None:
        raise HookError("Este sistema no admite la escucha global de ratón y teclado.")

    def stop_hooks(self) -> None:
        pass

    def hooks_alive(self) -> bool:
        return False

    def cursor_position(self) -> tuple[int, int]:
        return (0, 0)

    def double_click_time(self) -> float:
        return 0.5

    def double_click_slop(self) -> int:
        return 6

    # sistema
    def set_capture_excluded(self, window, excluded: bool) -> bool:
        """Oculta (o vuelve a mostrar) una ventana Tk en las capturas de pantalla."""
        return False

    def open_path(self, path: str) -> None:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def reveal_path(self, path: str) -> None:
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        self.open_path(folder)

    def permissions(self) -> list[Permission]:
        return []

    def request_permission(self, key: str) -> None:
        pass

    def open_permission_settings(self, key: str) -> None:
        pass

    def environment_warnings(self) -> list[str]:
        """Avisos puntuales del entorno (entrada segura, ventanas elevadas...)."""
        return []

    def window_screen_rect(self, window) -> tuple[int, int, int, int] | None:
        """Rectángulo (x, y, w, h) de una ventana Tk en coordenadas de pantalla."""
        try:
            return (window.winfo_rootx(), window.winfo_rooty(), window.winfo_width(), window.winfo_height())
        except Exception:
            return None
