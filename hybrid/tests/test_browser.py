"""Detección del navegador: elección, Windows (registro) y macOS (paquetes .app)."""

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hybrid.web import browser
from hybrid.web.browser import macos, windows


class PickTest(unittest.TestCase):
    def setUp(self):
        browser.pick.cache_clear()
        self.addCleanup(browser.pick.cache_clear)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exe = Path(self.tmp.name) / "chrome"
        self.exe.touch()

    def system(self, default, installed=None):
        fake = mock.Mock(FALLBACK_ORDER=("chrome", "edge"))
        fake.default_browser.return_value = default
        fake.installed.side_effect = lambda key: (installed or {}).get(key, "")
        return mock.patch.object(browser, "_platform", return_value=fake)

    def test_predeterminado_compatible(self):
        with self.system(browser.DefaultBrowser(str(self.exe), "chrome", "Google Chrome")):
            info = browser.pick()
        self.assertTrue(info.is_default)
        self.assertEqual((info.key, info.process, info.note), ("chrome", "chrome.exe", ""))

    def test_predeterminado_no_compatible_usa_otro(self):
        with self.system(browser.DefaultBrowser("/x/Safari", "", "Safari"), {"edge": "/x/Edge"}):
            info = browser.pick()
        self.assertFalse(info.is_default)
        self.assertEqual((info.key, info.process), ("edge", "msedge.exe"))
        self.assertIn("(Safari) no admite", info.note)
        self.assertIn("Microsoft Edge", info.note)

    def test_sin_ninguno(self):
        with self.system(browser.DefaultBrowser()), self.assertRaises(browser.BrowserError) as ctx:
            browser.pick()
        self.assertIn("Google Chrome o Microsoft Edge", str(ctx.exception))


class WindowsTest(unittest.TestCase):
    def test_ejecutable_del_comando(self):
        cmd = r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --single-argument %1'
        self.assertEqual(windows.exe_from_command(cmd), r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        self.assertEqual(windows.exe_from_command(r"C:\Edge\msedge.exe -- %1"), r"C:\Edge\msedge.exe")

    def test_nombre_visible(self):
        self.assertEqual(windows.friendly_name(r"C:\Mozilla Firefox\firefox.exe", "FirefoxURL-308046B"), "Firefox")
        self.assertEqual(windows.friendly_name("", "OperaStable"), "Opera")


class MacTest(unittest.TestCase):
    def make_app(self, folder, name, bundle_id, executable):
        app = Path(folder) / f"{name}.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        (app / "Contents" / "MacOS" / executable).touch()
        with open(app / "Contents" / "Info.plist", "wb") as handle:
            plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleExecutable": executable,
                           "CFBundleName": name}, handle)
        return app

    def test_ejecutable_del_paquete(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, "Google Chrome", "com.google.Chrome", "Google Chrome")
            self.assertEqual(macos.bundle_executable(app), str(app / "Contents/MacOS/Google Chrome"))
            self.assertEqual(macos.bundle_executable(Path(tmp) / "No existe.app"), "")

    def test_predeterminado_desde_launchservices(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, "Brave Browser", "com.brave.Browser", "Brave Browser")
            with mock.patch.object(macos, "_default_app_appkit", return_value=app):
                found = macos.default_browser()
        self.assertEqual((found.key, found.label), ("brave", "Brave Browser"))
        self.assertTrue(found.exe.endswith("Contents/MacOS/Brave Browser"))

    def test_safari_no_es_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, "Safari", "com.apple.Safari", "Safari")
            with mock.patch.object(macos, "_default_app_appkit", return_value=app):
                found = macos.default_browser()
        self.assertEqual((found.key, found.label), ("", "Safari"))

    def test_preferencias_de_launchservices(self):
        prefs = {"LSHandlers": [
            {"LSHandlerURLScheme": "mailto", "LSHandlerRoleAll": "com.apple.mail"},
            {"LSHandlerURLScheme": "https", "LSHandlerRoleAll": "com.google.chrome"},
        ]}
        self.assertEqual(macos.handler_from_prefs(prefs), "com.google.chrome")
        self.assertEqual(macos.handler_from_prefs({}), "")


if __name__ == "__main__":
    unittest.main()
