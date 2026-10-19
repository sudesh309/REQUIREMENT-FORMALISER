"""HTML system architecture report."""
import re
import unittest

from engine.interop.report import SECTIONS, generate_report, root_architectures
from sysmlv2 import PartDefinition
from tests.test_interop_fixtures import avionics_repo


class ReportTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo = avionics_repo()
        cls.html = generate_report(cls.repo, title="Flight Deck SAR", author="J. Doe",
                                   date="2026-10-18")

    def test_title_page_and_sections(self):
        h = self.html
        self.assertTrue(h.startswith("<!doctype html>"))
        self.assertIn("<title>Flight Deck SAR</title>", h)
        self.assertIn("System Architecture Report", h)
        self.assertIn("J. Doe", h)
        self.assertIn("2026-10-18", h)
        for s in SECTIONS:
            self.assertIn(f'id="sec-{s}"', h)
            self.assertIn(f'href="#sec-{s}"', h)

    def test_content(self):
        h = self.html
        self.assertIn("FlightManagementComputer", h)
        self.assertIn("navOut", h)
        self.assertIn("Interfaces::A429Word", h)
        self.assertIn("SRS-001", h)
        self.assertIn("RNP 0.3", h)
        self.assertIn("advisor.unconnected-port", h)
        # Stereotype name as engine.profiles reports it (plain package: no profile prefix).
        self.assertIn("<span class=stereo>«LRU»</span>", h)
        self.assertIn("<td>LRU</td><td>mass</td><td>4.2</td>", h)   # stereotype property value
        self.assertIn("2 of 3 requirements are implemented", h)
        # Hierarchy lists the architecture with nested components.
        hier = h[h.index('id="sec-hierarchy"'):h.index('id="sec-components"')]
        self.assertLess(hier.index(">FlightDeck<"), hier.index(">partition1<"))

    def test_mermaid_diagrams(self):
        blocks = re.findall(r'<pre class="mermaid"[^>]*>(.*?)</pre>', self.html, re.S)
        self.assertEqual(len(blocks), 2)               # architecture + traceability
        self.assertTrue(blocks[0].startswith("flowchart LR"))
        self.assertIn("gps : GPSReceiver", blocks[0])
        self.assertIn("navOut to navIn", blocks[0])
        self.assertIn('src="/static/vendor/mermaid-10.9.8.min.js"', self.html)
        self.assertEqual([r.name for r in root_architectures(self.repo)], ["FlightDeck"])

    def test_mermaid_modes_and_sections(self):
        none = generate_report(self.repo, mermaid="none", date="x")
        self.assertNotIn("<script", none)
        self.assertIn('class="mermaid-source"', none)
        inline = generate_report(self.repo, mermaid="inline", sections=["diagrams"], date="x")
        self.assertGreater(len(inline), 1_000_000)
        self.assertNotIn("/static/vendor/", inline)
        self.assertNotIn('id="sec-validation"', inline)
        with self.assertRaises(ValueError):
            generate_report(self.repo, sections=["nope"])
        with self.assertRaises(ValueError):
            generate_report(self.repo, mermaid="cdn")

    def test_escaping(self):
        repo = avionics_repo()
        repo.resolve("FlightDeck::gps").name = '<script>alert("x")</script>'
        html = generate_report(repo, date="x")
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIn("&lt;script&gt;", html)
        block = re.findall(r'<pre class="mermaid"[^>]*>(.*?)</pre>', html, re.S)[0]
        self.assertNotIn("&lt;script", block.replace("#lt;script", ""))

    def test_empty_model(self):
        from engine import Repository
        html = generate_report(Repository("Empty"), date="x")
        self.assertIn("No architecture with components.", html)
        self.assertIn("No requirements.", html)
        self.assertNotIn("<script", html)            # no diagrams, no script

    def test_reference_component_without_architecture_root(self):
        from engine import Repository
        repo = Repository("Lib")
        repo.add(PartDefinition(name="Only"))
        html = generate_report(repo, date="x")
        self.assertIn(">Only <span", html)


if __name__ == "__main__":
    unittest.main()
