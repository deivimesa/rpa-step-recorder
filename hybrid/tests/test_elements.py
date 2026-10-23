"""Del evento del agente web al paso: elemento, fiabilidad, selectores y descripción."""

import unittest

from hybrid.web import elements


def event(**dom):
    base = {"tag": "button", "role": "button", "text": "Guardar", "css": "button.primary", "xpath": "/html/body/button[1]"}
    base.update(dom)
    return {"kind": "click", "url": "https://portal/alta", "title": "Alta", "element": base,
            "rect": {"x": 10.4, "y": 20.6, "width": 80, "height": 30}}


class BuildElementTest(unittest.TestCase):
    def test_normaliza_al_vocabulario_de_escritorio(self):
        el = elements.build_element(event(id="guardar", id_unique=True), "Google Chrome")
        self.assertEqual(el["platform"], "web")
        self.assertEqual(el["control_type"], "Button")
        self.assertEqual(el["name"], "Guardar")
        self.assertEqual(el["rect"], {"x": 10, "y": 21, "width": 80, "height": 30})
        self.assertEqual(el["app"], "Google Chrome")
        self.assertEqual(el["window"], "Alta")

    def test_sin_elemento(self):
        self.assertIsNone(elements.build_element({"kind": "click"}, "Chrome"))

    def test_rect_vacio(self):
        data = event()
        data["rect"] = {"x": 0, "y": 0, "width": 0, "height": 0}
        self.assertIsNone(elements.build_element(data, "Chrome")["rect"])


class ReliabilityTest(unittest.TestCase):
    def level(self, **dom):
        return elements.build_element(event(**dom), "Chrome")["reliability"]

    def test_id_estable_es_alta(self):
        rel = self.level(id="guardar", id_unique=True)
        self.assertEqual((rel["level"], rel["best_selector"]), ("alta", "id"))

    def test_id_generado_no_cuenta(self):
        rel = self.level(id=":r1a:", id_unique=True, xpath_text="//button[normalize-space()='Guardar']")
        self.assertEqual(rel["best_selector"], "texto+rol")
        self.assertTrue(any("generado" in r for r in rel["reasons"]))

    def test_shadow_dom_baja(self):
        rel = self.level(text="", role="div", tag="div", in_shadow=True)
        self.assertEqual(rel["level"], "baja")

    def test_ids_volatiles(self):
        for ident in (":r5:", "ember123", "mat-input-12", "ext-gen1234", "campo_123456"):
            self.assertTrue(elements.web_volatile(ident), ident)
        for ident in ("guardar", "txtNombre", "user-email"):
            self.assertFalse(elements.web_volatile(ident), ident)


class SelectorsTest(unittest.TestCase):
    def test_iframe_en_todos_los_formatos(self):
        data = event(name="pagar", name_unique=True)
        data["frame_path"] = ["#pago"]
        sel = elements.build_selectors(elements.build_element(data, "Chrome"), "chrome.exe")
        self.assertEqual(sel["playwright"], 'page.frame_locator("#pago").get_by_role("button", name="Guardar")')
        self.assertTrue(sel["selenium"].startswith('driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "#pago"))'))
        self.assertIn("<webctrl css-selector='#pago' tag='IFRAME' />", sel["uipath"])
        self.assertIn("<html app='chrome.exe' title='Alta' />", sel["uipath"])

    def test_escapa_comillas(self):
        sel = elements.build_selectors(elements.build_element(event(text='Pulsa "aquí"'), "Chrome"), "msedge.exe")
        self.assertIn('name="Pulsa \\"aquí\\""', sel["playwright"])
        self.assertIn("aaname='Pulsa &quot;aquí&quot;'", sel["uipath"])


class DescribeTest(unittest.TestCase):
    def test_contrasena_no_se_guarda(self):
        data = {"kind": "input", "value": "secreta", "element": {"tag": "input", "type": "password", "role": "textbox"}}
        kind, text, value, secret = elements.describe(data, elements.build_element(data, "Chrome"))
        self.assertEqual((kind, value, secret), ("input", "", "password"))
        self.assertNotIn("secreta", text)

    def test_campo_sensible_por_nombre(self):
        data = {"kind": "input", "value": "4111", "element": {"tag": "input", "role": "textbox", "name": "cvv"}}
        self.assertEqual(elements.describe(data, elements.build_element(data, "Chrome"))[3], "sensitive")

    def test_seleccion(self):
        data = {"kind": "select", "value": "Medellín", "element": {"tag": "select", "role": "combobox", "label": "Ciudad"}}
        kind, text, value, _ = elements.describe(data, elements.build_element(data, "Chrome"))
        self.assertEqual((kind, value), ("select", "Medellín"))
        self.assertIn("Ciudad", text)


if __name__ == "__main__":
    unittest.main()
