"""HTTP tests for the Allocation Editor routes (webapp/routes/allocation.py)."""
import urllib.parse

from engine import allocation as A
from tests.webapp_harness import WebAppTestCase


class AllocationApiTests(WebAppTestCase):

    def setUp(self):
        A.install()
        self.call("POST", "/api/new", {"name": "Avionics"})
        el = lambda kind, name, parent=None: self.call(  # noqa: E731
            "POST", "/api/element", {"kind": kind, "name": name, "parent": parent})
        self.logical = el("PartDefinition", "LogicalArch")
        self.fms = el("PartUsage", "FMS", self.logical["id"])
        self.nav = el("PartUsage", "NavFn", self.fms["id"])
        self.cds = el("PartUsage", "DisplaySys", self.logical["id"])
        self.port = el("PortUsage", "arinc_out", self.fms["id"])
        self.physical = el("PartDefinition", "PhysicalArch")
        self.ima = el("PartUsage", "IMA", self.physical["id"])
        self.mfd = el("PartUsage", "MFD", self.physical["id"])
        self.req = el("RequirementDefinition", "R1")
        self.set = self.call("POST", "/api/allocation/sets", {
            "name": "L2P", "source": self.logical["id"], "target": "PhysicalArch",
            "description": "logical to physical"})
        self.sc = self.set["scenarios"][0]

    def toggle(self, src, tgt, scenario=None):
        return self.call("POST", "/api/allocation/toggle",
                         {"scenario": scenario or self.sc["id"], "source": src["id"], "target": tgt["id"]})

    def test_set_lifecycle(self):
        self.assertEqual(self.set["source_architecture"]["name"], "LogicalArch")
        self.assertEqual(self.set["target_architecture"]["name"], "PhysicalArch")
        self.assertEqual(self.set["description"], "logical to physical")
        self.assertEqual([s["name"] for s in self.set["scenarios"]], ["Scenario 1"])
        archs = [a["name"] for a in self.call("GET", "/api/allocation/architectures")]
        self.assertEqual(archs, ["LogicalArch", "PhysicalArch"])
        sets = self.call("GET", "/api/allocation/sets")
        self.assertEqual([s["name"] for s in sets], ["L2P"])
        qn = urllib.parse.quote("Allocations::L2P", safe="")
        self.assertEqual(self.call("GET", f"/api/allocation/sets/{qn}")["id"], self.set["id"])
        upd = self.call("PATCH", f"/api/allocation/sets/{self.set['id']}",
                        {"name": "Log2Phys", "require_complete_coverage": True, "description": "x"})
        self.assertEqual((upd["name"], upd["require_complete_coverage"], upd["description"]),
                         ("Log2Phys", True, "x"))
        tree = self.call("GET", "/api/tree")
        alloc_pkg = next(c for c in tree["children"] if c["name"] == "Allocations")
        self.assertEqual(alloc_pkg["children"][0]["kind"], "AllocationSet")
        self.assertEqual(alloc_pkg["children"][0]["badges"], ["LogicalArch → PhysicalArch"])
        self.call("DELETE", f"/api/allocation/sets/{self.set['id']}")
        self.assertEqual(self.call("GET", "/api/allocation/sets"), [])

    def test_set_errors_are_clear(self):
        e = self.call("POST", "/api/allocation/sets",
                      {"name": "L2P", "source": "LogicalArch", "target": "PhysicalArch"}, expect=409)
        self.assertIn("already exists", e["error"])
        e = self.call("POST", "/api/allocation/sets",
                      {"name": "X", "source": "Nope", "target": "PhysicalArch"}, expect=404)
        self.assertIn("not found", e["error"])
        e = self.call("POST", "/api/allocation/sets",
                      {"name": "X", "source": self.fms["id"], "target": "PhysicalArch"}, expect=400)
        self.assertIn("must be an architecture", e["error"])
        e = self.call("POST", "/api/allocation/sets", {"source": "LogicalArch", "target": "PhysicalArch"},
                      expect=400)
        self.assertIn("name", e["error"])

    def test_scenarios(self):
        s2 = self.call("POST", f"/api/allocation/sets/{self.set['id']}/scenarios", {})
        self.assertEqual(s2["name"], "Scenario 2")
        s3 = self.call("POST", "/api/allocation/scenarios", {"set": "Allocations::L2P", "name": "Alt"})
        self.assertEqual(s3["name"], "Alt")
        self.call("POST", "/api/allocation/scenarios", {"set": self.set["id"], "name": "Alt"}, expect=409)
        ren = self.call("PATCH", f"/api/allocation/scenarios/{s2['id']}", {"name": "Dual"})
        self.assertEqual(ren["name"], "Dual")
        self.toggle(self.nav, self.ima, s3["id"])
        dup = self.call("POST", f"/api/allocation/scenarios/{s3['id']}/duplicate", {"name": "Alt B"})
        self.assertEqual((dup["name"], dup["allocation_count"]), ("Alt B", 1))
        for sc in (s2, s3, dup):
            self.call("DELETE", f"/api/allocation/scenarios/{sc['id']}")
        e = self.call("DELETE", f"/api/allocation/scenarios/{self.sc['id']}", expect=409)
        self.assertIn("at least one scenario", e["error"])
        # Generic inspector rename goes through the same uniqueness check.
        self.call("PATCH", f"/api/element/{self.sc['id']}", {"props": {"name": ""}}, expect=400)
        self.call("PATCH", f"/api/element/{self.sc['id']}", {"props": {"name": "Baseline"}})
        self.assertEqual(self.call("GET", "/api/allocation/sets")[0]["scenarios"][0]["name"], "Baseline")

    def test_matrix_toggle_and_queries(self):
        r = self.toggle(self.nav, self.ima)
        self.assertTrue(r["allocated"])
        self.assertEqual(r["allocation"]["label"], "NavFn → IMA")
        self.toggle(self.cds, self.mfd)
        self.toggle(self.cds, self.ima)
        self.assertFalse(self.toggle(self.cds, self.ima)["allocated"])
        mx = self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/matrix")
        self.assertEqual([r["name"] for r in mx["rows"]], ["FMS", "NavFn", "DisplaySys"])
        self.assertEqual([c["name"] for c in mx["columns"]], ["IMA", "MFD"])
        self.assertEqual(sorted(a["label"] for a in mx["allocations"]), ["DisplaySys → MFD", "NavFn → IMA"])
        un = self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/matrix?show=unallocated")
        self.assertEqual([r["name"] for r in un["rows"]], ["FMS"])
        ports = self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/matrix?rows=port&q=arinc")
        self.assertEqual([(r["name"], r["context"]) for r in ports["rows"]],
                         [("FMS", True), ("arinc_out", False)])
        self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/matrix?rows=bogus", expect=400)
        to = self.call("GET", f"/api/allocation/allocated_to/{self.nav['id']}")
        self.assertEqual([x["name"] for x in to], ["IMA"])
        frm = self.call("GET", f"/api/allocation/allocated_from/{self.mfd['id']}?scenario={self.sc['id']}")
        self.assertEqual([x["name"] for x in frm], ["DisplaySys"])
        amap = self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/map")
        self.assertEqual(amap, {self.ima["id"]: [self.nav["id"]], self.mfd["id"]: [self.cds["id"]]})
        lst = self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/allocations")
        self.assertEqual(len(lst), 2)
        info = self.call("GET", f"/api/allocation/element/{self.nav['id']}")
        self.assertEqual((info["category"], len(info["to"]), info["from"]), ("component", 1, []))
        cov = self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/coverage")
        self.assertEqual((cov["total"], cov["allocated"], cov["unallocated"]), (2, 2, []))
        cov = self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/coverage?leaves=0")
        self.assertEqual([u["name"] for u in cov["unallocated"]], ["FMS"])

    def test_allocate_errors(self):
        body = {"scenario": self.sc["id"], "source": self.nav["id"], "target": self.ima["id"]}
        a = self.call("POST", "/api/allocation/allocate", body)
        self.assertEqual(a["kind"], "Allocation")
        e = self.call("POST", "/api/allocation/allocate", body, expect=409)
        self.assertIn("already allocated", e["error"])
        e = self.call("POST", "/api/allocation/allocate",
                      {**body, "source": self.ima["id"]}, expect=400)
        self.assertIn("not part of source architecture", e["error"])
        e = self.call("POST", "/api/allocation/allocate", {**body, "source": self.req["id"]}, expect=400)
        self.assertIn("cannot be allocated", e["error"])
        e = self.call("POST", "/api/allocation/allocate", {**body, "scenario": self.nav["id"]}, expect=400)
        self.assertIn("not an allocation scenario", e["error"])
        self.call("POST", "/api/allocation/allocate", {**body, "target": "missing"}, expect=404)
        self.call("POST", "/api/allocation/deallocate", body)
        self.call("POST", "/api/allocation/deallocate", body, expect=404)
        a = self.call("POST", "/api/allocation/allocate", {**body, "scenario": self.set["id"]})
        self.call("POST", "/api/allocation/deallocate", {"allocation": a["id"]})

    def test_element_json_delete_sync_and_validation(self):
        a = self.toggle(self.nav, self.ima)["allocation"]
        el = self.call("GET", f"/api/element/{a['id']}")
        self.assertEqual(el["kind"], "Allocation")
        self.assertIn("NavFn → IMA", el["badges"])
        self.assertEqual(el["allocation"]["source"]["name"], "NavFn")
        self.assertEqual(self.call("GET", f"/api/element/{self.port['id']}")["allocation_category"], "port")
        self.call("PATCH", f"/api/element/{self.nav['id']}", {"props": {"name": "Navigation"}})
        mx = self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/matrix")
        self.assertEqual(mx["allocations"][0]["label"], "Navigation → IMA")
        self.call("PATCH", f"/api/allocation/sets/{self.set['id']}", {"require_complete_coverage": True})
        issues = self.call("GET", "/api/validate")["issues"]
        cov = [i for i in issues if i["rule"] == "allocation.coverage"]
        self.assertEqual([i["qualified_name"] for i in cov], ["Avionics::LogicalArch::DisplaySys"])
        self.call("DELETE", f"/api/element/{self.ima['id']}")
        self.call("GET", f"/api/element/{a['id']}", expect=404)
        self.assertEqual(self.call("GET", f"/api/allocation/scenarios/{self.sc['id']}/allocations"), [])

    def test_set_architecture_change_needs_force(self):
        self.toggle(self.nav, self.ima)
        other = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "OtherArch"})
        e = self.call("PATCH", f"/api/allocation/sets/{self.set['id']}", {"target": other["id"]}, expect=409)
        self.assertIn("force", e["error"])
        s = self.call("PATCH", f"/api/allocation/sets/{self.set['id']}", {"target": other["id"], "force": True})
        self.assertEqual(s["target_architecture"]["name"], "OtherArch")
        self.assertEqual(s["scenarios"][0]["allocation_count"], 0)

    def test_save_load_round_trip_and_export(self):
        self.toggle(self.nav, self.ima)
        self.toggle(self.cds, self.mfd)
        text = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/new", {"name": "Other"})
        self.assertEqual(self.call("GET", "/api/allocation/sets"), [])
        self.call("POST", "/api/load", {"text": text})
        sets = self.call("GET", "/api/allocation/sets")
        self.assertEqual(sets[0]["scenarios"][0]["allocation_count"], 2)
        mx = self.call("GET", f"/api/allocation/scenarios/{sets[0]['scenarios'][0]['id']}/matrix")
        self.assertEqual(sorted(a["label"] for a in mx["allocations"]), ["DisplaySys → MFD", "NavFn → IMA"])
        ttl = self.call("GET", "/api/export/turtle")["text"]
        self.assertIn("sysml:allocatedTo", ttl)

    def test_stereotype_restricted_to_allocations(self):
        a = self.toggle(self.nav, self.ima)["allocation"]
        self.call("POST", "/api/stereotype/define",
                  {"name": "Binding", "applies_to": ["Allocation"], "tags": [{"name": "latency_ms"}]})
        self.call("POST", "/api/stereotype/apply",
                  {"stereotype": "Binding", "target": a["id"], "values": {"latency_ms": 2}})
        e = self.call("POST", "/api/stereotype/apply", {"stereotype": "Binding", "target": self.nav["id"]},
                      expect=400)
        self.assertIn("cannot be applied", e["error"])
        el = self.call("GET", f"/api/element/{a['id']}")
        # Other features may add keys to stereotype entries (profiles adds id, style, ...).
        self.assertEqual([(st["name"], st["values"]) for st in el["stereotypes"]],
                         [("Binding", {"latency_ms": 2})])

    def test_chain_endpoint(self):
        func = self.call("POST", "/api/element", {"kind": "Package", "name": "Functions"})
        fn = self.call("POST", "/api/element", {"kind": "ActionUsage", "name": "ComputeNav",
                                                "parent": func["id"]})
        f2l = self.call("POST", "/api/allocation/sets",
                        {"name": "F2L", "source": "Functions", "target": "LogicalArch"})
        self.toggle(fn, self.nav, f2l["scenarios"][0]["id"])
        self.toggle(self.nav, self.ima)
        chain = self.call("GET", f"/api/allocation/chain/{fn['id']}")
        self.assertEqual([n["name"] for n in chain["nodes"]], ["ComputeNav", "NavFn", "IMA"])
        self.assertIn("flowchart LR", chain["mermaid"])
        tb = self.call("GET", f"/api/allocation/chain/{fn['id']}?direction=TB")
        self.assertTrue(tb["mermaid"].startswith("flowchart TB"))
        self.call("GET", f"/api/allocation/chain/{fn['id']}?direction=XY", expect=400)
