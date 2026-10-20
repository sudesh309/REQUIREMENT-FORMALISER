"""Studio chrome contracts (PO-15): dialogs are styled modals, never the browser's
window.prompt / confirm / alert, and the toolstrip is organised by task."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "webapp" / "static"
NATIVE = re.compile(r"(?<![\w.$])(?:window\.)?(prompt|confirm|alert)\s*\(")


def _code(text: str) -> str:
    """JavaScript without comments and string contents (good enough for a lint)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r"(?<![:\\])//[^\n'\"`]*$", "", text, flags=re.M)
    return re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", "''", text)


class StudioChromeTests(unittest.TestCase):

    def test_no_native_browser_dialogs(self):
        offenders = []
        for path in sorted([*STATIC.glob("*.js"), *STATIC.glob("plugins/**/*.js")]):
            for n, line in enumerate(_code(path.read_text(encoding="utf-8")).splitlines(), 1):
                if NATIVE.search(line):
                    offenders.append(f"{path.relative_to(STATIC)}:{n}: {line.strip()}")
        self.assertEqual(offenders, [], "use studio.modal / studio.dialog instead")

    def test_toolstrip_sections_and_advanced_menu(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        sections = re.findall(r'class="rb-section" data-section="([a-z]+)"', html)
        self.assertEqual(sections, ["modeling", "views", "requirements", "analysis", "interop"])
        menu = html[html.index('id="advanced-menu"'):]
        menu = menu[:menu.index("</div>\n        </div>")]
        # Generic elements, state machine commands and the Links / Parser tabs are in Advanced ▾.
        for needle in ('data-kind="PartDefinition"', 'data-cmd="sm-attach"', 'data-show-tab="links"',
                       'data-show-tab="parser"', 'data-cmd="link"'):
            self.assertIn(needle, menu)
        outside = html.replace(menu, "")
        self.assertNotIn('class="btn-add"', outside, "no generic element buttons outside the menu")
        self.assertIn('data-cmd="toggle-log"', html, "the output pane is collapsible")


if __name__ == "__main__":
    unittest.main()
