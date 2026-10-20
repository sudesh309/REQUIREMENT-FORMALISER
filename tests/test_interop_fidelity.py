"""Fidelity of the tables round trip and of the report on a real studio project.

The fixture ``tests/data/interop_ima_avionics_demo.json`` is the System User's wave-1
acceptance model (IMA avionics: functional and physical architectures, FCC-L / FCC-R
reference components of FlightControlComputer, ARINC 429 / AFDX interfaces, a profile,
requirements with suspect links, an allocation set F2L, canvas layout).
"""
from __future__ import annotations

import json
import re
import unittest
from html import unescape

import engine.interop  # noqa: F401  (loads every feature module first)
from engine import allocation as A
from engine import from_json, to_json
from engine import requirements as R
from engine.interop import export_tables, export_tables_file, import_tables, read_tables_file
from engine.interop.diff import compare
from engine.interop.report import generate_report
from engine.interop.tables import NULL_CELL, PROJECT_DATA_PREFIX, TOOL_DATA, tables_to_project
from tests.test_interop_fixtures import DATA
from tests.webapp_harness import WebAppTestCase
from webapp import core

FIXTURE = DATA / "interop_ima_avionics_demo.json"


def load_fixture():
    A.install()          # other test modules may clear the global rule / codec registries
    return from_json(FIXTURE.read_text(encoding="utf-8"))


def suspects(repo) -> list:
    return sorted((rel.element_id, tuple(R.suspect_ends(rel))) for rel in R.trace_links(repo)
                  if R.suspect_ends(rel))


def allocations(repo) -> list:
    out = []
    for s in A.allocation_sets(repo):
        for sc in s.scenarios:
            out.append((s.name, getattr(s.source_architecture, "element_id", None),
                        getattr(s.target_architecture, "element_id", None), sc.name,
                        sorted((getattr(a.source, "element_id", None),
                                getattr(a.target, "element_id", None)) for a in sc.allocations)))
    return out


class TablesRoundTripFidelityTests(unittest.TestCase):
    """SU-4: XLSX export -> import as a new project keeps allocations, suspect links, layout."""

    def setUp(self):
        self.repo = load_fixture()

    def round_trip(self, fmt="xlsx"):
        data, filename, _mime = export_tables_file(self.repo, fmt)
        new, report = tables_to_project(read_tables_file(data, filename))
        return new, report

    def test_xlsx_round_trip_is_identical_including_layout(self):
        new, report = self.round_trip("xlsx")
        self.assertEqual(report.warnings, [])
        for layout in (False, True):
            diff = compare(self.repo, new, include_layout=layout)
            self.assertTrue(diff["identical"], (layout, diff["summary"], diff["changes"][:3]))

    def test_allocation_sets_keep_their_architectures_and_ends(self):
        before = allocations(self.repo)
        self.assertTrue(before and all(None not in pair for *_, pairs in before for pair in pairs))
        new, _report = self.round_trip()
        self.assertEqual(allocations(new), before)
        f2l = A.allocation_sets(new)[0]
        cov = A.coverage(f2l.scenarios[0])
        self.assertEqual((cov["total"], cov["allocated"], cov["ratio"]), (4, 4, 1.0))
        self.assertEqual([a.label for a in f2l.scenarios[0].allocations],
                         [a.label for a in A.allocation_sets(self.repo)[0].scenarios[0].allocations])

    def test_suspect_links_survive(self):
        before = suspects(self.repo)
        self.assertEqual(len(before), 2)              # REQ-002's two links are suspect
        new, _report = self.round_trip()
        self.assertEqual(suspects(new), before)

    def test_layout_and_tool_data_are_carried(self):
        sheets = export_tables(self.repo)
        header, *rows = sheets[TOOL_DATA]
        keys = {r[header.index("Key")] for r in rows}
        self.assertEqual(keys, {"layout", "port_layout", "default_literal"})
        new, _report = self.round_trip()
        for e in self.repo.root_package.walk():
            self.assertEqual(new.by_id(e.element_id).tool_data, e.tool_data, e.qualified_name)

    def test_project_data_rows_in_the_model_sheet(self):
        model = dict((r[0], r[1]) for r in export_tables(self.repo)["Model"][1:])
        self.assertIn(f"{PROJECT_DATA_PREFIX}requirements-links", model)
        self.assertEqual(json.loads(model[f"{PROJECT_DATA_PREFIX}requirements-links"]),
                         json.loads(to_json(self.repo))["ext"]["requirements-links"]["data"])

    def test_long_project_data_is_split_over_cells(self):
        # A spreadsheet cell holds 32767 characters; longer data continues on the next rows
        # (simulated here with a 40-character cell).
        from unittest import mock
        with mock.patch("engine.interop.tables._CELL_CHUNK", 40):
            rows = [r for r in export_tables(self.repo)["Model"][1:]
                    if r[0] == f"{PROJECT_DATA_PREFIX}requirements-links"]
            self.assertGreater(len(rows), 5)
            self.assertTrue(all(len(r[1]) <= 40 for r in rows))
            new, _report = self.round_trip()
        self.assertEqual(json.loads(to_json(new))["ext"]["requirements-links"],
                         json.loads(to_json(self.repo))["ext"]["requirements-links"])
        self.assertEqual(suspects(new), suspects(self.repo))

    def test_architecture_type_survives(self):
        from engine.architecture import model_type, set_model_type
        set_model_type(self.repo, "software", force=True)
        new, _report = self.round_trip()
        self.assertEqual(model_type(new), "software")

    def test_value_without_default_is_written_as_null(self):
        sheets = export_tables(self.repo)
        header, *rows = sheets["Interfaces"]
        alt = next(r for r in rows if r[header.index("Name")] == "altitude")
        self.assertEqual(alt[header.index("primitive_type")], NULL_CELL)
        new, _report = self.round_trip()
        self.assertIsNone(new.by_id(alt[header.index("ID")]).primitive_type)

    def test_merge_import_gives_layout_only_to_created_elements(self):
        sheets = export_tables(self.repo)
        fcc = next(e for e in self.repo.root_package.walk() if e.name == "FCC-L")
        fcc.tool_data["layout"] = {"x": 999, "y": 999}            # moved after the export
        header = sheets["Components"][0]
        new_row = [""] * len(header)
        new_row[header.index("ID")] = "spare-lru"
        new_row[header.index("Name")] = "SpareLRU"
        new_row[header.index("Kind")] = "PartUsage"
        new_row[header.index("Parent ID")] = fcc.owner.element_id
        sheets["Components"].append(new_row)
        sheets[TOOL_DATA].append(["spare-lru", "SpareLRU", "PartUsage", "layout",
                                  '{"x": 10, "y": 20}'])
        report = import_tables(self.repo, sheets)
        self.assertEqual(report.created, ["spare-lru"])
        self.assertEqual(fcc.tool_data["layout"], {"x": 999, "y": 999})
        self.assertEqual(self.repo.by_id("spare-lru").tool_data, {"layout": {"x": 10, "y": 20}})

    def test_bad_tool_data_is_refused_and_changes_nothing(self):
        sheets = export_tables(self.repo)
        sheets[TOOL_DATA].append([self.repo.root_package.element_id, "", "Package", "layout",
                                  "{not json"])
        before = to_json(self.repo)
        with self.assertRaises(engine.interop.InteropError) as cm:
            import_tables(self.repo, sheets)
        self.assertIn("Tool Data row", str(cm.exception))
        self.assertEqual(to_json(self.repo), before)

    def test_set_without_source_reports_coverage_not_applicable(self):
        s = A.allocation_sets(self.repo)[0]
        s.source_architecture = None
        cov = A.coverage(s.scenarios[0])
        self.assertIsNone(cov["ratio"])
        self.assertTrue(cov["source_missing"])
        self.assertEqual(cov["total"], 0)


class StudioRoundTripHttpTests(WebAppTestCase):
    """SU-4 and PO-12 through the studio's HTTP API."""

    def setUp(self):
        A.install()
        self.text = FIXTURE.read_text(encoding="utf-8")

    def compare_saved(self, **extra):
        return self.call("POST", "/api/interop/compare", {"against": "snapshot", **extra})

    def test_xlsx_export_import_compares_equal_with_the_saved_file(self):
        self.call("POST", "/api/load", {"text": self.text})
        saved = self.call("GET", "/api/save")["text"]
        x = self.call("GET", "/api/interop/tables?format=xlsx")
        self.call("POST", "/api/new", {"name": "Blank"})
        r = self.call("POST", "/api/interop/tables/import",
                      {"base64": x["base64"], "filename": x["filename"], "mode": "new"})
        self.assertEqual(r["report"]["warnings"], [])
        diff = self.call("POST", "/api/interop/compare", {"text": saved, "include_layout": True})
        self.assertTrue(diff["identical"], (diff["summary"], diff["changes"][:3]))
        (f2l,) = self.call("GET", "/api/allocation/sets")
        self.assertEqual((f2l["source_architecture"]["name"], f2l["target_architecture"]["name"],
                          f2l["scenarios"][0]["allocation_count"]),
                         ("AvionicsFunctions", "AircraftAvionics", 4))

    def test_load_json_sets_the_baseline(self):
        self.call("POST", "/api/new", {"name": "Blank"})
        self.assertEqual(self.call("GET", "/api/interop/snapshot"), {"exists": False})
        self.call("POST", "/api/load", {"text": self.text})
        snap = self.call("GET", "/api/interop/snapshot")
        self.assertEqual(snap["label"], "Last saved (loaded file)")
        self.assertTrue(self.compare_saved()["identical"])
        self.assertTrue(self.compare_saved(include_layout=True)["identical"])
        # An edit shows up; undo keeps the baseline (the same project) and is clean again.
        fcc = next(e for e in core.session().repo.root_package.walk() if e.name == "FCC-R")
        self.call("PATCH", f"/api/element/{fcc.element_id}", {"props": {"name": "FCC-R2"}})
        self.assertEqual(self.compare_saved()["summary"]["modified"], 1)
        self.call("POST", "/api/undo")
        self.assertTrue(self.compare_saved()["identical"])
        self.call("POST", "/api/redo")
        self.assertEqual(self.compare_saved()["summary"]["modified"], 1)
        # New clears it.
        self.call("POST", "/api/new", {"name": "Other"})
        self.assertEqual(self.call("GET", "/api/interop/snapshot"), {"exists": False})

    def test_imports_as_a_new_project_set_the_baseline(self):
        from tests.test_interop_fixtures import XMI_FIXTURE
        self.call("POST", "/api/load", {"text": self.text})
        x = self.call("GET", "/api/interop/tables?format=xlsx")
        self.call("POST", "/api/new", {"name": "Blank"})
        self.call("POST", "/api/interop/tables/import",
                  {"base64": x["base64"], "filename": x["filename"], "mode": "new"})
        self.assertEqual(self.call("GET", "/api/interop/snapshot")["label"],
                         f"Imported {x['filename']}")
        self.assertTrue(self.compare_saved()["identical"])
        self.call("POST", "/api/new", {"name": "Blank"})
        self.call("POST", "/api/interop/xmi/import",
                  {"text": XMI_FIXTURE.read_text(encoding="utf-8"), "mode": "new"})
        self.assertTrue(self.compare_saved()["identical"])
        self.call("POST", "/api/new", {"name": "Blank"})
        self.call("POST", "/api/interop/sysml/import",
                  {"text": "package P { part def A; }", "mode": "new"})
        self.assertTrue(self.compare_saved()["identical"])
        # Merging into the current project does not move the baseline.
        self.call("POST", "/api/interop/sysml/import", {"text": "package Q { part def B; }"})
        self.assertEqual(self.compare_saved()["summary"]["added"], 2)


class ReportOnStudioModelTests(unittest.TestCase):
    """SU-3 on the System User's model: FCC-R gets its own two incoming edges."""

    def test_fcc_l_and_fcc_r_each_have_their_edges(self):
        html = generate_report(load_fixture(), sections=["diagrams"], mermaid="none", date="x")
        block = unescape(re.findall(r'<pre class="mermaid-source"[^>]*>(.*?)</pre>', html, re.S)[0])
        nodes = {name: nid for nid, name in re.findall(r'(n\d+)\["([^ "]+)', block)}
        edges = re.findall(r'(n\d+) --> ?(?:\|"([^"]*)"\| )?(n\d+)', block)
        into = lambda n: sorted((a, label) for a, label, b in edges if b == nodes[n])  # noqa: E731
        expected = sorted([(nodes["ADC"], "AirDataWord"), (nodes["IRU"], "InertialData")])
        self.assertEqual(into("FCC-L"), expected)
        self.assertEqual(into("FCC-R"), expected)
        self.assertNotIn(" to ", block)


if __name__ == "__main__":
    unittest.main()
