"""Interop HTTP API (webapp/routes/interop.py) over real HTTP."""
import base64
import json

from engine import to_json
from engine.interop import write_csv_zip, write_xlsx
from engine.interop.tables import export_tables
from tests.test_interop_fixtures import XMI_FIXTURE, avionics_repo
from tests.webapp_harness import WebAppTestCase
from webapp import core


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class InteropHttpTests(WebAppTestCase):

    def load_avionics(self):
        self.call("POST", "/api/load", {"text": to_json(avionics_repo())})

    def test_export_tables_formats(self):
        self.load_avionics()
        x = self.call("GET", "/api/interop/tables?format=xlsx")
        self.assertEqual(x["filename"], "FlightDeck.xlsx")
        self.assertEqual(base64.b64decode(x["base64"])[:2], b"PK")
        c = self.call("GET", "/api/interop/tables?format=csv")
        self.assertEqual(c["filename"], "FlightDeck_tables.zip")
        j = self.call("GET", "/api/interop/tables?format=json")
        self.assertIn("Components", j["tables"])
        self.assertIn("unknown table format", self.call("GET", "/api/interop/tables?format=ods",
                                                         expect=400)["error"])

    def test_import_tables_new_and_merge(self):
        self.load_avionics()
        x = self.call("GET", "/api/interop/tables?format=xlsx")
        saved = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/new", {"name": "Blank"})
        r = self.call("POST", "/api/interop/tables/import",
                      {"base64": x["base64"], "filename": x["filename"], "mode": "new"})
        self.assertEqual(r["project"]["name"], "FlightDeck")
        self.assertGreater(r["report"]["created"], 20)
        diff = self.call("POST", "/api/interop/compare", {"text": saved})
        self.assertTrue(diff["identical"], diff["changes"][:3])
        diff = self.call("POST", "/api/interop/compare",
                         {"base64": x["base64"], "filename": "FlightDeck.xlsx"})
        self.assertTrue(diff["identical"])
        # Merge an edited CSV export into the current project.
        tables = export_tables(core.session().repo)
        header = tables["Components"][0]
        row = next(r for r in tables["Components"][1:] if r[header.index("Name")] == "gps")
        row[header.index("Name")] = "gnss"
        r = self.call("POST", "/api/interop/tables/import",
                      {"base64": _b64(write_csv_zip(tables)), "filename": "t.zip"})
        self.assertEqual((r["mode"], r["report"]["updated"], r["report"]["created"]),
                         ("merge", 1, 0))
        self.assertIsNotNone(core.session().find("FlightDeck::gnss"))

    def test_import_errors_are_400_and_atomic(self):
        self.load_avionics()
        before = self.call("GET", "/api/save")["text"]
        bad = {"Components": [["Name", "Parent"], ["X", "FlightDeck"]],
               "Ports": [["Name", "Component", "Direction"], ["p", "FlightDeck::X", "up"]]}
        r = self.call("POST", "/api/interop/tables/import", {"tables": bad}, expect=400)
        self.assertIn("invalid direction 'up'", r["error"])
        self.assertEqual(self.call("GET", "/api/save")["text"], before)
        r = self.call("POST", "/api/interop/tables/import", {"base64": "%%%"}, expect=400)
        self.assertIn("base64", r["error"])
        r = self.call("POST", "/api/interop/tables/import",
                      {"base64": _b64(b"plain"), "filename": "x.xlsx"}, expect=400)
        self.assertIn("ZIP", r["error"])
        self.call("POST", "/api/interop/tables/import", {"tables": {}, "mode": "sideways"},
                  expect=400)
        self.call("POST", "/api/interop/tables/import", {}, expect=400)

    def test_report(self):
        self.load_avionics()
        r = self.call("GET", "/api/interop/report?title=SAR&author=Me&sections=summary,diagrams")
        self.assertEqual(r["filename"], "FlightDeck_report.html")
        self.assertIn("<title>SAR</title>", r["html"])
        self.assertIn('id="sec-diagrams"', r["html"])
        self.assertNotIn('id="sec-validation"', r["html"])
        self.assertIn("unknown report section", self.call(
            "GET", "/api/interop/report?sections=bogus", expect=400)["error"])

    def test_sysml_export_and_import(self):
        self.load_avionics()
        r = self.call("GET", "/api/interop/sysml")
        self.assertEqual(r["filename"], "FlightDeck.sysml")
        self.assertIn("part def FlightDeck", r["text"])
        n = self.call("POST", "/api/interop/sysml/import",
                      {"text": r["text"], "mode": "new", "name": "FromText"})
        self.assertEqual(n["project"]["name"], "FromText")
        self.assertIsNotNone(core.session().find("Components::GPSReceiver::navOut"))
        m = self.call("POST", "/api/interop/sysml/import", {"text": "package Extra { part def X; }"})
        self.assertEqual(m["created"], 2)
        before = self.call("GET", "/api/save")["text"]
        e = self.call("POST", "/api/interop/sysml/import",
                      {"text": "package Bad { part def Y; part def }"}, expect=400)
        self.assertIn("Expected", e["error"])
        self.assertEqual(self.call("GET", "/api/save")["text"], before)
        self.call("POST", "/api/interop/sysml/import", {"text": "  "}, expect=400)

    def test_xmi_import(self):
        self.call("POST", "/api/new", {"name": "Host"})
        r = self.call("POST", "/api/interop/xmi/import",
                      {"base64": _b64(XMI_FIXTURE.read_bytes()), "mode": "merge"})
        self.assertEqual(r["report"]["model_name"], "FlightDeckModel")
        self.assertIsNotNone(core.session().find("FlightDeckModel::Structure::FlightDeck"))
        r = self.call("POST", "/api/interop/xmi/import",
                      {"text": XMI_FIXTURE.read_text(), "mode": "new"})
        self.assertEqual(r["project"]["name"], "FlightDeckModel")
        r = self.call("POST", "/api/interop/xmi/import",
                      {"text": '<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'}, expect=400)
        self.assertIn("DOCTYPE", r["error"])

    def test_snapshot_compare(self):
        self.load_avionics()
        self.assertIn("no snapshot", self.call("POST", "/api/interop/compare",
                                               {"against": "snapshot"}, expect=400)["error"])
        snap = self.call("POST", "/api/interop/snapshot", {"label": "Last saved"})
        self.assertEqual(snap["label"], "Last saved")
        self.assertEqual(self.call("GET", "/api/interop/snapshot")["name"], "FlightDeck")
        gps = core.session().find("FlightDeck::gps")
        self.call("PATCH", f"/api/element/{gps.element_id}", {"props": {"name": "gnss"}})
        diff = self.call("POST", "/api/interop/compare", {"against": "snapshot"})
        self.assertEqual(diff["summary"]["modified"], 1)
        self.assertEqual(diff["old"]["label"], "Last saved")
        self.assertEqual(diff["changes"][0]["properties"][0]["new"], "gnss")
        self.call("POST", "/api/new", {"name": "Other"})
        self.assertEqual(self.call("GET", "/api/interop/snapshot"), {"exists": False})
        self.call("POST", "/api/interop/compare", {"text": "{bad"}, expect=400)

    def test_three_way_merge_flow(self):
        base = to_json(avionics_repo())
        theirs = json.loads(base)
        mine = json.loads(base)
        for data, name in ((theirs, "gnssTheirs"), (mine, "gnssMine")):
            next(e for e in data["elements"] if e["name"] == "gps")["name"] = name
        next(e for e in theirs["elements"] if e["name"] == "pfd")["name"] = "display"
        self.call("POST", "/api/load", {"text": json.dumps(mine)})
        r = self.call("POST", "/api/interop/merge", {"base": base, "theirs": json.dumps(theirs)})
        self.assertEqual(len(r["conflicts"]), 1)
        c = r["conflicts"][0]
        self.assertEqual((c["property"], c["mine"], c["theirs"]), ("name", "gnssMine", "gnssTheirs"))
        self.assertTrue(any(a["from"] == "theirs" for a in r["auto"]))
        bad = self.call("POST", "/api/interop/merge/resolve",
                        {"token": r["token"], "choices": {c["id"]: "both"}}, expect=400)
        self.assertIn("choose", bad["error"])
        done = self.call("POST", "/api/interop/merge/resolve",
                         {"token": r["token"], "choices": {c["id"]: "theirs"}})
        self.assertEqual(done["conflicts_resolved"], 1)
        self.assertIsNotNone(core.session().find("FlightDeck::gnssTheirs"))
        self.assertIsNotNone(core.session().find("FlightDeck::display"))
        self.call("POST", "/api/interop/merge/resolve", {"token": r["token"]}, expect=400)
        self.call("POST", "/api/interop/merge", {"base": base}, expect=400)

    def test_merge_accepts_uploaded_files(self):
        base = to_json(avionics_repo())
        self.call("POST", "/api/load", {"text": base})
        tables = write_xlsx(export_tables(avionics_repo()))
        r = self.call("POST", "/api/interop/merge",
                      {"base": {"base64": _b64(base.encode()), "filename": "base.json"},
                       "theirs": {"base64": _b64(tables), "filename": "t.xlsx"}})
        self.assertEqual(r["conflicts"], [])

    def test_model_check_and_info(self):
        self.load_avionics()
        r = self.call("GET", "/api/interop/check")
        self.assertEqual(r["total"], len(r["issues"]))
        self.assertIn("advisor.unconnected-port", r["by_rule"])
        w = self.call("GET", "/api/interop/check?severity=warning&rule=advisor.unconnected-port")
        self.assertEqual({i["rule"] for i in w["issues"]}, {"advisor.unconnected-port"})
        v = self.call("GET", "/api/validate")
        self.assertTrue(any(i["rule"].startswith("advisor.") for i in v["issues"]))
        info = self.call("GET", "/api/interop/info")
        self.assertIn("diagrams", info["report_sections"])
        self.assertIn("direction", info["parser_capabilities"])

    def test_save_is_deterministic_over_http(self):
        self.load_avionics()
        a = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/load", {"text": a})
        self.assertEqual(self.call("GET", "/api/save")["text"], a)
        self.assertTrue(a.endswith("\n"))
