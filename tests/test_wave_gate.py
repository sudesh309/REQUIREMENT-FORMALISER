"""The wave gate scenario builds its model through the GUI only (PO-16).

tests/ui/scenarios/99_avionics_e2e.mjs is run by tests/test_ui_browser.py;
these checks keep it honest without a browser: it never changes the model
through the HTTP API, never emulates a gesture with studio.emit, and it
covers every wave-1 feature with real gestures (docs/EXTENDING.md, "Wave
gate").
"""
import re
import unittest
from pathlib import Path

SCENARIO = Path(__file__).resolve().parent / "ui" / "scenarios" / "99_avionics_e2e.mjs"


class WaveGateScenarioTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = SCENARIO.read_text(encoding="utf-8")
        # Code only: the header comment may mention what the scenario avoids.
        cls.code = re.sub(r"^\s*//.*$", "", cls.text, flags=re.M)

    def test_never_writes_through_the_api(self):
        writes = re.findall(r"""api\(\s*["'](POST|PATCH|PUT|DELETE)""", self.code)
        self.assertEqual(writes, [], "the gate builds the model with gestures; API calls may only read (GET)")
        self.assertNotIn("fresh(", self.code, "the project is created from the GUI (New model…)")
        self.assertNotRegex(self.code, r"studio\.(emit|api|refreshTree|selectElement)\b",
                            "no gesture is emulated through window.studio")
        self.assertNotIn("page.evaluate(() => window.studio", self.code)

    def test_uses_real_gestures(self):
        for gesture in ("page.mouse.down", "page.mouse.up", "page.keyboard.press", "page.click",
                        "page.fill", "page.selectOption", 'waitForEvent("filechooser")',
                        'waitForEvent("download")'):
            self.assertIn(gesture, self.code, gesture)

    def test_covers_every_feature(self):
        expected = {
            "functional + physical architecture on the canvas": '[data-canvas-act="add-component"]',
            "ports": "add-port-",
            "connectors drawn port to port": "connect(port(",
            "interface template": '[data-ifc="template"]',
            "interface dragged onto a port": "spring-loaded Architecture tab",
            "profile editor": '[data-pf-cmd="new-stereotype"]',
            "stereotype values in the Properties tab": '[data-section="stereotypes"]',
            "requirement set": '[data-rq="new-set"]',
            "requirements dragged onto blocks": "dragRowTo(",
            "allocation set": '[data-alloc-act="new-set"]',
            "Model Check count": ".io-tab-badge",
            "report": '[data-io="report"]',
            "save": 'header [data-cmd="save"]',
            "load": 'header [data-cmd="load"]',
            "canvas Property Inspector": ".arch-dock",
            "block badges": ".arch-pill",
            "undo labels": "undoIs(",
        }
        missing = [what for what, needle in expected.items() if needle not in self.code]
        self.assertEqual(missing, [], f"the wave gate no longer covers: {missing}")


if __name__ == "__main__":
    unittest.main()
