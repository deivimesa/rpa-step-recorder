"""Navegador predeterminado en macOS: LaunchServices y paquetes .app.

El predeterminado se pregunta a LaunchServices (NSWorkspace) y, si PyObjC no
está disponible, se lee su preferencia guardada. El ejecutable de cada
navegador está dentro de su paquete: ``<App>.app/Contents/MacOS/<CFBundleExecutable>``.
"""

from __future__ import annotations

import logging
import plistlib
from pathlib import Path

from . import DefaultBrowser

log = logging.getLogger("rpa.browser")

# Si el predeterminado no es compatible (Safari, Firefox...). macOS no trae
# ningún navegador Chromium: se prueba el más habitual primero.
FALLBACK_ORDER = ("chrome", "edge", "brave")

# Identificador del paquete -> clave del catálogo (CHROMIUM).
_BUNDLE_KEY = {
    "com.google.chrome": "chrome",
    "com.microsoft.edgemac": "edge",
    "com.brave.browser": "brave",
    "com.vivaldi.vivaldi": "vivaldi",
    "org.chromium.chromium": "chromium",
}
_KEY_BUNDLE = {key: bundle for bundle, key in _BUNDLE_KEY.items()}

# Nombre del paquete en /Applications, por si LaunchServices no responde.
_APP_NAMES = {
    "chrome": "Google Chrome.app",
    "edge": "Microsoft Edge.app",
    "brave": "Brave Browser.app",
    "vivaldi": "Vivaldi.app",
    "chromium": "Chromium.app",
}

_LS_PREFS = Path.home() / "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"


def _bundle_info(app: Path) -> dict:
    try:
        with open(app / "Contents" / "Info.plist", "rb") as handle:
            return plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}


def bundle_executable(app: Path) -> str:
    """Ejecutable de un paquete .app ("" si no se encuentra)."""
    name = _bundle_info(app).get("CFBundleExecutable") or app.stem
    exe = app / "Contents" / "MacOS" / name
    return str(exe) if exe.exists() else ""


def _app_label(app: Path) -> str:
    info = _bundle_info(app)
    return info.get("CFBundleDisplayName") or info.get("CFBundleName") or app.stem


def _default_app_appkit() -> Path | None:
    from AppKit import NSWorkspace
    from Foundation import NSURL

    url = NSWorkspace.sharedWorkspace().URLForApplicationToOpenURL_(NSURL.URLWithString_("https://example.com"))
    return Path(str(url.path())) if url is not None else None


def handler_from_prefs(prefs: dict) -> str:
    """Identificador del paquete que abre https según las preferencias de LaunchServices."""
    for handler in prefs.get("LSHandlers") or []:
        if handler.get("LSHandlerURLScheme") == "https":
            return handler.get("LSHandlerRoleAll") or ""
    return ""


def _app_for_bundle(bundle_id: str) -> Path | None:
    try:
        from AppKit import NSWorkspace

        url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(bundle_id)
        if url is not None:
            return Path(str(url.path()))
    except Exception:  # noqa: BLE001 - sin PyObjC: se buscan las rutas habituales
        pass
    key = _BUNDLE_KEY.get(bundle_id.lower())
    if key:
        for folder in (Path("/Applications"), Path.home() / "Applications"):
            app = folder / _APP_NAMES[key]
            if app.exists():
                return app
    return None


def default_browser() -> DefaultBrowser:
    app: Path | None = None
    try:
        app = _default_app_appkit()
    except Exception:  # noqa: BLE001 - PyObjC ausente o LaunchServices sin respuesta
        log.info("LaunchServices no respondió; se leen sus preferencias", exc_info=True)
    if app is None:
        try:
            with open(_LS_PREFS, "rb") as handle:
                bundle_id = handler_from_prefs(plistlib.load(handle))
        except (OSError, plistlib.InvalidFileException, ValueError):
            bundle_id = ""
        # Sin preferencia guardada, macOS abre la web con Safari.
        app = _app_for_bundle(bundle_id) if bundle_id else None
        if app is None:
            return DefaultBrowser(label="Safari" if not bundle_id else bundle_id)
    bundle_id = str(_bundle_info(app).get("CFBundleIdentifier") or "")
    return DefaultBrowser(bundle_executable(app), _BUNDLE_KEY.get(bundle_id.lower(), ""), _app_label(app))


def installed(key: str) -> str:
    """Ejecutable de ``key`` si está instalado ("" si no)."""
    app = _app_for_bundle(_KEY_BUNDLE[key]) if key in _KEY_BUNDLE else None
    return bundle_executable(app) if app else ""
