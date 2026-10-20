"""Human-readable undo step labels (PO-5, SU-8): every feature names its steps, creating and
naming an element in place is one step, and no label shows an HTTP method, a route or an id."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from tests.webapp_harness import WebAppTestCase
from webapp import core
from webapp.core import Mutation, register_undo_label, undo_label
from webapp.routes.undo import label_for

RAW = re.compile(r"/api/|\b(GET|POST|PATCH|PUT|DELETE)\b|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-")


class UndoLabelTests(WebAppTestCase):

    def send(self, method: str, path: str, body=None, headers=None, expect: int = 200):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        h = {"Content-Type": "application/json"} if data else {}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        self.assertEqual(status, expect, raw[:300])
        return json.loads(raw or b"null")

    def state(self) -> dict:
        return self.call("GET", "/api/undo/state")

    def top(self) -> str:
        label = self.state()["undo_label"]
        self.assertIsNone(RAW.search(label or ""), f"raw route or id in label {label!r}")
        return label

    def setUp(self):
        self.call("POST", "/api/new", {"name": "Labels"})
        self.root = self.call("POST", "/api/arch/architecture", {"name": "AircraftAvionics"})

    def comp(self, name, composition=None):
        return self.call("POST", "/api/arch/component",
                         {"composition": composition or self.root["id"], "name": name})

    # --- labels per feature ---------------------------------------------------------

    def test_profile_value_label(self):
        prof = self.call("POST", "/api/profiles", {"name": "Avionics"})
        lru = self.call("POST", f"/api/profiles/{prof['id']}/stereotypes", {"name": "LRU", "applies_to": "Component"})
        self.assertEqual(self.top(), "Add stereotype Avionics.LRU")
        self.call("POST", f"/api/stereotypes/{lru['id']}/properties", {"name": "mass", "type": "double", "unit": "kg"})
        self.assertEqual(self.top(), "Add property Avionics.LRU.mass")
        fms = self.comp("FMS")
        self.call("POST", f"/api/elements/{fms['id']}/stereotypes", {"stereotype": lru["id"]})
        self.assertEqual(self.top(), "Apply «Avionics.LRU» to FMS")
        self.call("PATCH", f"/api/elements/{fms['id']}/stereotypes", {"property": "Avionics.LRU.mass", "value": "7"})
        self.assertEqual(self.top(), "Set Avionics.LRU.mass of FMS")
        self.call("PATCH", f"/api/element/{fms['id']}", {"props": {"Avionics.LRU.mass": 8}})
        self.assertEqual(self.top(), "Set Avionics.LRU.mass of FMS")
        self.call("DELETE", f"/api/elements/{fms['id']}/stereotypes/{lru['id']}")
        self.assertEqual(self.top(), "Remove «Avionics.LRU» from FMS")

    def test_allocation_labels(self):
        func = self.call("POST", "/api/arch/architecture", {"name": "Functions"})
        nav = self.comp("ComputeNavigation", func["id"])
        cpm = self.comp("CPM1")
        s = self.call("POST", "/api/allocation/sets", {"name": "FunctionsToHardware",
                                                       "source": func["id"], "target": self.root["id"]})
        self.assertEqual(self.top(), "Add allocation set FunctionsToHardware")
        body = {"scenario": s["id"], "source": nav["id"], "target": cpm["id"]}
        self.call("POST", "/api/allocation/toggle", body)
        self.assertEqual(self.top(), "Allocate ComputeNavigation → CPM1")
        self.call("POST", "/api/allocation/toggle", body)
        self.assertEqual(self.top(), "Remove allocation ComputeNavigation → CPM1")

    def test_requirement_labels(self):
        rset = self.call("POST", "/api/req/sets", {"name": "System", "prefix": "SYS"})
        r = self.call("POST", "/api/req/requirements", {"parent": rset["id"], "summary": "Navigate"})
        self.assertEqual(self.top(), f"Add requirement {r['req_id']}")
        self.call("PATCH", f"/api/req/requirements/{r['id']}", {"summary": "Compute the position"})
        self.assertEqual(self.top(), f"Edit {r['req_id']} summary")
        fms = self.comp("FMS")
        self.call("POST", "/api/req/links", {"type": "implement", "source": fms["id"], "target": r["id"]})
        self.assertEqual(self.top(), f"Add link FMS implements {r['req_id']}")
        self.call("DELETE", f"/api/req/requirements/{r['id']}")
        self.assertEqual(self.top(), f"Delete requirement {r['req_id']}")

    def test_interface_labels(self):
        item = self.call("POST", "/api/interfaces", {"kind": "DataInterface", "name": "A429Word"})
        self.assertEqual(self.top(), "Add data interface A429Word")
        adiru = self.comp("ADIRU")
        port = self.call("POST", "/api/arch/port", {"owner": adiru["id"], "name": "airData", "direction": "out"})
        self.assertEqual(self.top(), "Add port ADIRU.airData")
        self.call("POST", "/api/interfaces/assign", {"port": port["id"], "interface": item["id"]})
        self.assertEqual(self.top(), "Assign A429Word to ADIRU.airData")
        self.call("POST", "/api/interfaces/assign", {"port": port["id"], "interface": None})
        self.assertEqual(self.top(), "Remove interface from ADIRU.airData")

    def test_architecture_and_core_labels(self):
        adc, fms = self.comp("ADC"), self.comp("FMS")
        self.call("POST", "/api/arch/port", {"owner": adc["id"], "name": "airData", "direction": "out"})
        self.call("POST", "/api/arch/port", {"owner": fms["id"], "name": "air", "direction": "in"})
        self.call("POST", "/api/arch/connector", {"composition": self.root["id"],
                                                  "source": {"component": adc["id"], "port": "airData"},
                                                  "target": {"component": fms["id"], "port": "air"}})
        self.assertEqual(self.top(), "Connect ADC.airData → FMS.air")
        self.call("PATCH", f"/api/arch/component/{fms['id']}", {"name": "FMS1"})
        self.assertEqual(self.top(), "Rename FMS to FMS1")
        self.call("POST", "/api/arch/delete", {"ids": [adc["id"]]})
        self.assertEqual(self.top(), "Delete ADC")
        el = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "Gen"})
        self.assertEqual(self.top(), "Add part definition Gen")
        self.call("DELETE", f"/api/element/{el['id']}")
        self.assertEqual(self.top(), "Delete Gen")
        st = self.call("POST", "/api/undo")
        self.assertEqual(st["redo_label"], "Delete Gen")

    def test_unlabelled_routes_get_a_generic_label(self):
        self.assertEqual(label_for("POST", "/api/variants/1a2b3c4d-0000-0000-0000-000000000000/activate"),
                         "Change variants")
        self.assertEqual(label_for("PATCH", "/api/arch/whatever/x"), "Edit architecture")
        # A failing label function falls back to the generic label instead of breaking the edit.
        register_undo_label("POST", r"^/api/broken$", lambda c: 1 / 0)
        try:
            self.assertEqual(undo_label(Mutation("POST", "/api/broken", None))[0], "Change broken")
        finally:
            core._UNDO_LABELS.pop(0)

    # --- create + name in place is one step -------------------------------------------

    def test_add_component_then_name_in_place_is_one_step(self):
        depth = self.state()["undo_depth"]
        c = self.call("POST", "/api/arch/component", {"composition": self.root["id"]})
        self.send("PATCH", f"/api/arch/component/{c['id']}", {"name": "CPM_A"}, {"X-Undo-Merge": c["id"]})
        st = self.state()
        self.assertEqual((st["undo_depth"], st["undo_label"]), (depth + 1, "Add component CPM_A"))
        self.call("POST", "/api/undo")
        self.call("GET", f"/api/element/{c['id']}", expect=404)
        self.assertEqual(self.state()["redo_label"], "Add component CPM_A")
        self.call("POST", "/api/redo")
        self.assertEqual(self.call("GET", f"/api/element/{c['id']}")["name"], "CPM_A")

    def test_group_then_name_in_place_is_one_step(self):
        a, b = self.comp("CPM1"), self.comp("CPM2")
        depth = self.state()["undo_depth"]
        g = self.call("POST", "/api/arch/group", {"composition": self.root["id"], "component_ids": [a["id"], b["id"]]})
        self.send("PATCH", f"/api/arch/component/{g['id']}", {"name": "CPM_Pair"}, {"X-Undo-Merge": g["id"]})
        st = self.state()
        self.assertEqual((st["undo_depth"], st["undo_label"]), (depth + 1, "Group CPM1, CPM2 into CPM_Pair"))
        self.call("POST", "/api/undo")
        names = sorted(c["name"] for c in self.call("GET", f"/api/arch/view/{self.root['id']}")["components"])
        self.assertEqual(names, ["CPM1", "CPM2"], "one undo removes the group, no 'Component' left behind")

    def test_merge_only_into_the_creation_just_made(self):
        c = self.comp("Box")
        # Without the hint a rename is its own step.
        self.call("PATCH", f"/api/arch/component/{c['id']}", {"name": "Box2"})
        self.assertEqual(self.top(), "Rename Box to Box2")
        # The hint is ignored when the last step did not create the element.
        depth = self.state()["undo_depth"]
        self.send("PATCH", f"/api/arch/component/{c['id']}", {"name": "Box3"}, {"X-Undo-Merge": c["id"]})
        self.assertEqual((self.state()["undo_depth"], self.top()), (depth + 1, "Rename Box2 to Box3"))
        # ... and when something else happened after the creation.
        d = self.call("POST", "/api/arch/component", {"composition": self.root["id"]})
        self.comp("Other")
        depth = self.state()["undo_depth"]
        self.send("PATCH", f"/api/arch/component/{d['id']}", {"name": "Late"}, {"X-Undo-Merge": d["id"]})
        self.assertEqual(self.state()["undo_depth"], depth + 1)

    def test_new_architecture_then_name_in_place_is_one_step(self):
        depth = self.state()["undo_depth"]
        a = self.call("POST", "/api/arch/architecture", {})
        self.send("PATCH", f"/api/element/{a['id']}", {"props": {"name": "Physical"}}, {"X-Undo-Merge": a["id"]})
        st = self.state()
        self.assertEqual((st["undo_depth"], st["undo_label"]), (depth + 1, "New architecture"))
