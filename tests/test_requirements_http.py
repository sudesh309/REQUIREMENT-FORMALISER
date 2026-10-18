"""HTTP tests for the requirements and traceability API (webapp/routes/requirements.py)."""
import engine.requirements as rq
from tests.webapp_harness import WebAppTestCase


class RequirementsApiTests(WebAppTestCase):

    def setUp(self):
        rq.install()
        self.call("POST", "/api/new", {"name": "Avionics"})
        self.arch = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "Aircraft"})
        self.fcc = self.call("POST", "/api/element", {"kind": "PartUsage", "name": "FCC",
                                                      "parent": self.arch["id"]})
        self.set = self.call("POST", "/api/req/sets", {"name": "FCS", "prefix": "FCS-"})

    def add(self, parent, **fields):
        return self.call("POST", "/api/req/requirements", {"parent": parent, **fields})

    def table(self):
        return self.call("GET", f"/api/req/table?set={self.set['id']}")

    def test_meta_and_sets(self):
        meta = self.call("GET", "/api/req/meta")
        self.assertIn("design-constraint", meta["types"])
        self.assertEqual(meta["link_types"][0]["name"], "implement")
        sets = self.call("GET", "/api/req/sets")
        self.assertEqual([s["name"] for s in sets], ["FCS"])
        out = self.call("PATCH", f"/api/req/sets/{self.set['id']}",
                        {"name": "Flight Controls", "prefix": "FC-", "description": "System reqs"})
        self.assertEqual((out["name"], out["prefix"], out["description"]),
                         ("Flight Controls", "FC-", "System reqs"))
        err = self.call("POST", "/api/req/sets", {"name": "Flight Controls"}, expect=400)
        self.assertIn("already contains", err["error"])
        self.call("POST", "/api/req/sets", {"name": ""}, expect=400)

    def test_authoring_flow(self):
        r1 = self.add(self.set["id"], summary="Pitch control", type="Functional")
        r2 = self.add(self.set["id"], summary="Roll control")
        child = self.add(r1["id"], summary="Pitch rate")
        self.assertEqual((r1["req_id"], r2["req_id"], child["req_id"]), ("FCS-1", "FCS-2", "FCS-3"))
        self.assertEqual(child["parent_id"], r1["id"])
        self.assertEqual(r1["type"], "functional")
        sib = self.add(self.set["id"], summary="Yaw", after=r1["id"])
        rows = self.table()["rows"]
        self.assertEqual([(r["index"], r["summary"]) for r in rows],
                         [("1", "Pitch control"), ("1.1", "Pitch rate"), ("2", "Yaw"), ("3", "Roll control")])
        upd = self.call("PATCH", f"/api/req/requirements/{r2['id']}",
                        {"description": "Roll within 30 deg/s", "priority": "high", "id": "FCS-20"})
        self.assertEqual((upd["description"], upd["priority"], upd["req_id"]),
                         ("Roll within 30 deg/s", "high", "FCS-20"))
        e = self.call("PATCH", f"/api/req/requirements/{r2['id']}", {"type": "banana"}, expect=400)
        self.assertIn("Invalid type 'banana'", e["error"])
        e = self.call("PATCH", f"/api/req/requirements/{r2['id']}", {"id": "FCS-1"}, expect=400)
        self.assertIn("already used", e["error"])
        moved = self.call("POST", f"/api/req/requirements/{sib['id']}/move", {"direction": "indent"})
        self.assertEqual(moved["parent_id"], r1["id"])
        self.call("POST", f"/api/req/requirements/{r1['id']}/move", {"direction": "up"}, expect=400)
        self.call("DELETE", f"/api/req/requirements/{r1['id']}")
        self.assertEqual([r["summary"] for r in self.table()["rows"]], ["Roll control"])
        self.call("PATCH", "/api/req/requirements/nope", {"summary": "x"}, expect=404)
        self.call("POST", "/api/req/requirements", {"parent": self.arch["id"], "summary": "x"}, expect=400)

    def test_links_status_and_suspect(self):
        r1 = self.add(self.set["id"], summary="Pitch control")
        r2 = self.add(self.set["id"], summary="Roll control")
        link = self.call("POST", "/api/req/links", {"type": "implement", "source": self.fcc["id"],
                                                    "target": r1["id"]})
        self.assertEqual((link["type"], link["suspect"]), ("implement", False))
        e = self.call("POST", "/api/req/links", {"type": "implement", "source": r1["id"],
                                                 "target": r2["id"]}, expect=400)
        self.assertIn("Derive or Refine", e["error"])
        self.call("POST", "/api/req/links", {"type": "implement", "source": "missing",
                                             "target": r2["id"]}, expect=404)
        st = self.table()
        self.assertEqual(st["sets"][0]["implementation"], {"done": 1, "total": 2, "pct": 50})
        row = next(r for r in st["rows"] if r["id"] == r1["id"])
        self.assertTrue(row["implementation"]["implemented"])
        # Editing the text makes the link suspect; clearing it resets the baseline.
        self.call("PATCH", f"/api/req/requirements/{r1['id']}", {"description": "Pitch within 2 deg"})
        links = self.call("GET", f"/api/req/links?element={r1['id']}")["links"]
        self.assertTrue(links[0]["suspect"])
        self.assertEqual(links[0]["direction"], "incoming")
        issues = self.call("GET", "/api/validate")["issues"]
        self.assertIn("requirements.suspect-link", [i["rule"] for i in issues])
        cleared = self.call("POST", f"/api/req/links/{link['id']}/clear-suspect")
        self.assertFalse(cleared["suspect"])
        # Generic link created through the core API, then edited through the Properties form.
        core_link = self.call("POST", "/api/link", {"kind": "satisfy", "source": self.fcc["id"],
                                                    "target": r2["id"]})
        self.call("PATCH", f"/api/element/{r2['id']}", {"props": {"text": "Roll rate 30 deg/s"}})
        links = self.call("GET", f"/api/req/links?element={r2['id']}")["links"]
        self.assertEqual([(l["id"], l["suspect"]) for l in links], [(core_link["id"], True)])
        self.assertEqual(self.call("POST", "/api/req/clear-suspect", {})["cleared"], 1)
        self.call("DELETE", f"/api/req/links/{link['id']}")
        self.call("DELETE", f"/api/req/links/{link['id']}", expect=404)
        self.assertEqual(len(self.call("GET", f"/api/req/links?element={self.fcc['id']}")["links"]), 1)

    def test_batch_links_and_test_cases(self):
        r1 = self.add(self.set["id"], summary="Pitch control")
        adc = self.call("POST", "/api/element", {"kind": "PartUsage", "name": "ADC", "parent": self.arch["id"]})
        out = self.call("POST", "/api/req/links/batch", {"type": "implement", "sources": [self.fcc["id"], adc["id"], r1["id"]],
                                                         "target": r1["id"]})
        self.assertEqual(len(out["created"]), 2)
        self.assertEqual(len(out["errors"]), 1)
        tc = self.call("POST", "/api/req/test-cases", {"parent": self.set["id"], "name": "Pitch step"})
        self.assertEqual(tc["result"], "unexecuted")
        self.call("POST", "/api/req/links", {"type": "verify", "source": tc["id"], "target": r1["id"]})
        tc = self.call("PATCH", f"/api/req/test-cases/{tc['id']}", {"result": "passed"})
        self.assertEqual(tc["verifies"][0]["req_id"], "FCS-1")
        self.call("PATCH", f"/api/req/test-cases/{tc['id']}", {"result": "great"}, expect=400)
        row = self.table()["rows"][0]
        self.assertEqual(row["verification"]["state"], "passed")
        self.assertEqual(self.table()["test_cases"][0]["name"], "Pitch step")
        status = self.call("GET", f"/api/req/status?target={self.set['id']}")
        self.assertEqual(status["set"]["verification"]["pct"], 100)
        self.call("DELETE", f"/api/req/test-cases/{tc['id']}")
        self.assertEqual(self.table()["rows"][0]["verification"]["state"], "missing")

    def test_matrix_diagram_and_exports(self):
        r1 = self.add(self.set["id"], summary="Pitch control")
        r2 = self.add(self.set["id"], summary="Derived pitch")
        self.call("POST", "/api/req/links", {"type": "derive", "source": r2["id"], "target": r1["id"]})
        self.call("POST", "/api/req/links", {"type": "implement", "source": self.fcc["id"], "target": r2["id"]})
        m = self.call("GET", f"/api/req/matrix?set={self.set['id']}&columns=components")
        self.assertEqual([c["name"] for c in m["columns"]], ["Aircraft", "FCC"])
        self.assertEqual(m["unlinked_rows"], [r1["id"]])
        m2 = self.call("GET", f"/api/req/matrix?set={self.set['id']}&columns=requirements&column_set={self.set['id']}")
        self.assertEqual(len(m2["cells"]), 2)
        self.call("GET", "/api/req/matrix?columns=gizmos", expect=400)
        d = self.call("GET", f"/api/req/diagram?element={r1['id']}&depth=2")
        self.assertIn("FCC", d["text"])
        for fmt in ("csv", "reqif", "report-html", "report-csv", "matrix-csv"):
            out = self.call("GET", f"/api/req/export?format={fmt}&set={self.set['id']}")
            self.assertTrue(out["text"] and out["filename"])
        self.call("GET", "/api/req/export?format=docx", expect=400)

    def test_import(self):
        csv_text = "id,summary,description,type,priority,parent_id\nA-1,Top,,safety,high,\nA-2,Sub,,,,A-1\n"
        rep = self.call("POST", "/api/req/import", {"format": "csv", "text": csv_text, "new_set": "Imported"})
        self.assertEqual((rep["created"], rep["set"]), (2, "Imported"))
        rows = self.call("GET", f"/api/req/table?set={rep['set_id']}")["rows"]
        self.assertEqual([(r["req_id"], r["depth"]) for r in rows], [("A-1", 0), ("A-2", 1)])
        rep2 = self.call("POST", "/api/req/import", {"format": "csv", "set": rep["set_id"],
                                                    "text": "id,summary\nA-2,Sub renamed\n"})
        self.assertEqual(rep2["updated"], 1)
        xml = self.call("GET", f"/api/req/export?format=reqif&set={rep['set_id']}")["text"]
        rep3 = self.call("POST", "/api/req/import", {"format": "reqif", "text": xml, "new_set": "FromReqIF"})
        self.assertEqual(rep3["created"], 2)
        e = self.call("POST", "/api/req/import", {"format": "reqif", "new_set": "Bad",
                                                 "text": '<!DOCTYPE x [<!ENTITY a "b">]><REQ-IF/>'}, expect=400)
        self.assertIn("DOCTYPE or ENTITY", e["error"])
        self.assertNotIn("Bad", [s["name"] for s in self.call("GET", "/api/req/sets")])
        self.call("POST", "/api/req/import", {"format": "xlsx", "text": "x"}, expect=400)
        self.call("POST", "/api/req/import", {"format": "csv", "path": "/etc/passwd"}, expect=400)

    def test_core_integration(self):
        r1 = self.add(self.set["id"], summary="Pitch control")
        el = self.call("GET", f"/api/element/{r1['id']}")
        self.assertIn("FCS-1", el["badges"])
        self.assertTrue(el["traceable"])
        self.assertEqual(el["requirement"]["set_id"], self.set["id"])
        self.call("POST", "/api/req/links", {"type": "implement", "source": self.fcc["id"], "target": r1["id"]})
        fcc = self.call("GET", f"/api/element/{self.fcc['id']}")
        self.assertIn("1 req", fcc["badges"])
        # Generic Properties form edits are validated by the prop hook.
        e = self.call("PATCH", f"/api/element/{r1['id']}", {"props": {"req_type": "bogus"}}, expect=400)
        self.assertIn("Invalid type", e["error"])
        self.call("PATCH", f"/api/element/{r1['id']}", {"props": {"req_type": "Safety", "rationale": "AC 25.1309"}})
        self.assertEqual(self.table()["rows"][0]["type"], "safety")
        # Requirement sets and test cases are creatable through the generic element API too.
        s2 = self.call("POST", "/api/element", {"kind": "RequirementSet", "name": "SRS"})
        self.assertIn("req set", s2["badges"])
        self.call("POST", "/api/element", {"kind": "VerificationCaseDefinition", "name": "TC",
                                           "parent": s2["id"]})
        # Saved projects keep fields, links and suspect state.
        self.call("PATCH", f"/api/req/requirements/{r1['id']}", {"description": "edited"})
        saved = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/load", {"text": saved})
        links = self.call("GET", f"/api/req/links?element={r1['id']}")["links"]
        self.assertTrue(links[0]["suspect"])
        self.assertEqual(self.table()["rows"][0]["rationale"], "AC 25.1309")

    def test_plugin_shipped(self):
        self.assertIn("/static/plugins/40-requirements.js", self.call("GET", "/api/plugins"))
        js = self.get_text("/static/plugins/40-requirements.js")
        for needle in ('id: "requirements"', 'id: "traceability"', "drop-on-element",
                       "application/x-sysml-element", "Link to Selection", "Requirements links"):
            self.assertIn(needle, js)
