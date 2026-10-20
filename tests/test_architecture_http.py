"""HTTP tests for the architecture API (webapp/routes/architecture.py) and undo/redo."""
from engine import architecture as A
from tests.webapp_harness import WebAppTestCase
from webapp import core


class _ArchHttp(WebAppTestCase):

    def setUp(self):
        A.install()     # other test modules may clear the shared rule registries
        self.call("POST", "/api/new", {"name": "Avionics"})
        self.root = self.call("POST", "/api/arch/architecture", {"name": "AircraftSystem"})

    def comp(self, name=None, composition=None, **extra):
        body = {"composition": composition or self.root["id"], **extra}
        if name:
            body["name"] = name
        return self.call("POST", "/api/arch/component", body)

    def port(self, owner, name=None, direction="in", kind="data", expect=200, **extra):
        body = {"owner": owner["id"], "direction": direction, "kind": kind, **extra}
        if name:
            body["name"] = name
        return self.call("POST", "/api/arch/port", body, expect=expect)

    def connect(self, src_comp, src_port, dst_comp, dst_port, expect=200, composition=None):
        return self.call("POST", "/api/arch/connector", {
            "composition": (composition or self.root)["id"],
            "source": {"component": src_comp and src_comp["id"], "port": src_port},
            "target": {"component": dst_comp and dst_comp["id"], "port": dst_port}}, expect=expect)

    def view(self, comp=None, query=""):
        return self.call("GET", f"/api/arch/view/{(comp or self.root)['id']}{query}")

    def three(self):
        adc, fms, disp = self.comp("ADC"), self.comp("FMS"), self.comp("Display")
        self.port(adc, "airData", "out")
        self.port(fms, "airData", "in")
        self.port(fms, "route", "out")
        self.port(disp, "route", "in")
        return adc, fms, disp


class ModelTypeHttpTests(_ArchHttp):

    def test_new_with_type_and_switch(self):
        out = self.call("POST", "/api/new", {"name": "Sw", "type": "software"})
        self.assertEqual(out["type"], "software")
        self.assertEqual(self.call("GET", "/api/arch/model-type")["allowed_port_kinds"],
                         ["data", "client", "server"])
        err = self.call("POST", "/api/new", {"name": "X", "type": "quantum"}, expect=400)
        self.assertIn("model type", err["error"])
        self.assertEqual(self.call("GET", "/api/arch/model-type")["type"], "software")   # unchanged

    def test_switch_refused_when_ports_conflict(self):
        adc = self.comp("ADC")
        self.port(adc, "pwr", kind="physical")
        self.port(adc, "svc", kind="client", expect=400)
        err = self.call("POST", "/api/arch/model-type", {"type": "software"}, expect=409)
        self.assertIn("physical", err["error"])
        self.call("POST", "/api/arch/model-type", {"type": "software", "force": True})
        rules = [i["rule"] for i in self.call("GET", "/api/validate")["issues"]]
        self.assertIn("arch.port.kind", rules)


class ComponentHttpTests(_ArchHttp):

    def test_auto_numbering_rename_and_duplicates(self):
        names = [self.comp()["name"] for _ in range(3)]
        self.assertEqual(names, ["Component", "Component1", "Component2"])
        dup = self.call("POST", "/api/arch/component",
                        {"composition": self.root["id"], "name": "Component1"}, expect=409)
        self.assertIn("already has", dup["error"])
        c = self.comp("ADC")
        self.call("PATCH", f"/api/arch/component/{c['id']}", {"name": "Component"}, expect=409)
        out = self.call("PATCH", f"/api/arch/component/{c['id']}", {"name": "AirDataComputer"})
        self.assertEqual(out["name"], "AirDataComputer")
        # the generic properties PATCH applies the same rule
        self.call("PATCH", f"/api/element/{c['id']}", {"props": {"name": "Component2"}}, expect=400)
        self.call("PATCH", f"/api/element/{c['id']}", {"props": {"name": "AirDataComputer"}})

    def test_unknown_ids_and_bad_bodies(self):
        self.call("POST", "/api/arch/component", {"composition": "nope"}, expect=404)
        self.call("POST", "/api/arch/component", {}, expect=400)
        self.call("POST", "/api/arch/component", ["x"], expect=400)
        pkg = self.call("POST", "/api/element", {"kind": "Package", "name": "Lib"})
        self.call("POST", "/api/arch/component", {"composition": pkg["id"]}, expect=400)

    def test_summary_badges_and_reference_retype(self):
        sensor = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "Sensor"})
        c = self.comp("aoa", definition=sensor["id"])
        self.assertTrue(c["is_reference"])
        self.assertEqual(c["definition"]["name"], "Sensor")
        el = self.call("GET", f"/api/element/{c['id']}")
        self.assertEqual(el["badges"][:2], ["ref", "leaf"])
        out = self.call("PATCH", f"/api/arch/component/{c['id']}", {"definition": None})
        self.assertFalse(out["is_reference"])
        self.call("PATCH", f"/api/arch/component/{c['id']}", {"definition": self.root["id"]},
                  expect=400)                                 # would contain itself

    def test_reference_merges_same_named_ports(self):
        adc, fms, disp = self.three()
        self.connect(adc, "airData", fms, "airData")
        self.connect(fms, "route", disp, "route")
        fmc = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "FmcType"})
        self.port({"id": fmc["id"]}, "airData", "in")
        self.port({"id": fmc["id"]}, "route", "out")
        out = self.call("PATCH", f"/api/arch/component/{fms['id']}", {"definition": fmc["id"]})
        self.assertEqual(out["merged_ports"], ["airData", "route"])
        self.assertEqual([(p["name"], p["on_definition"]) for p in out["ports"]],
                         [("airData", True), ("route", True)])
        conns = self.view()["connectors"]
        self.assertEqual([k["issues"] for k in conns], [[], []])
        port_ids = {p["id"] for p in out["ports"]}
        self.assertTrue(all({k["source"]["port_id"], k["target"]["port_id"]} & port_ids for k in conns))
        issues = self.call("GET", "/api/validate")["issues"]
        self.assertFalse([i for i in issues if i["rule"] == "arch.port.unique"])
        self.call("POST", "/api/undo")                        # one step
        self.assertEqual([p["on_definition"] for p in self.view()["components"][1]["ports"]], [False, False])

    def test_ports_and_port_kind_props(self):
        adc = self.comp("ADC")
        p = self.port(adc, None, "out")
        self.assertEqual((p["name"], p["side"], p["kind"]), ("Out", "right", "data"))
        self.port(adc, "Out", "in", expect=409)
        el = self.call("GET", f"/api/element/{p['id']}")
        self.assertEqual((el["port_kind"], el["badges"]), ("data", ["out"]))
        self.call("PATCH", f"/api/element/{p['id']}", {"props": {"port_kind": "bogus"}}, expect=400)
        self.call("PATCH", f"/api/element/{p['id']}", {"props": {"port_kind": "server"}}, expect=400)
        out = self.call("PATCH", f"/api/element/{p['id']}", {"props": {"port_kind": "physical"}})
        self.assertEqual((out["port_kind"], out["direction"]), ("physical", "inout"))
        q = self.call("PATCH", f"/api/arch/port/{p['id']}", {"kind": "data", "direction": "in",
                                                             "name": "pitot"})
        self.assertEqual((q["kind"], q["direction"], q["name"], q["side"]), ("data", "in", "pitot", "left"))
        iface = self.call("POST", "/api/element", {"kind": "PortDefinition", "name": "AirData"})
        q = self.call("PATCH", f"/api/arch/port/{p['id']}", {"interface": iface["id"]})
        self.assertEqual(q["interface"]["name"], "AirData")
        q = self.call("PATCH", f"/api/arch/port/{p['id']}", {"interface": None})
        self.assertIsNone(q["interface"])

    def test_reference_port_on_every_usage(self):
        sensor = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "Sensor"})
        a = self.comp("left", definition=sensor["id"])
        b = self.comp("right", definition=sensor["id"])
        p = self.port(a, "angle", "out")
        self.assertTrue(p["on_definition"])
        comps = {c["name"]: c for c in self.view()["components"]}
        self.assertEqual([x["name"] for x in comps["right"]["ports"]], ["angle"])


class ConnectorHttpTests(_ArchHttp):

    def test_rules_and_status_codes(self):
        adc, fms, disp = self.three()
        c = self.connect(fms, "airData", adc, "airData")          # drawn backwards: oriented
        self.assertEqual(c["source"]["component_id"], adc["id"])
        err = self.connect(fms, "airData", disp, "route", expect=400)
        self.assertIn("output", err["error"])
        adc2 = self.comp("ADC2")
        self.port(adc2, "airData", "out")
        err = self.connect(adc2, "airData", fms, "airData", expect=409)
        self.assertIn("one source", err["error"])
        self.connect(adc, "airData", disp, "nope", expect=404)
        self.connect(adc, "airData", adc, "airData", expect=400)
        pwr = self.port(adc, "pwr", kind="physical")
        err = self.connect(adc, pwr["id"], fms, "airData", expect=400)
        self.assertIn("physical", err["error"])
        self.call("POST", "/api/arch/connector", {"composition": self.root["id"]}, expect=400)

    def test_fan_out_boundary_and_can_connect(self):
        adc, fms, disp = self.three()
        self.port(disp, "air", "in")
        self.connect(adc, "airData", fms, "airData")
        self.connect(adc, "airData", disp, "air")
        b = self.port(self.root, "status", "out")
        self.connect(fms, "route", None, b["id"])
        q = (f"/api/arch/can-connect?composition={self.root['id']}&source_component={disp['id']}"
             f"&source_port=route&target_component={fms['id']}&target_port=route")
        r = self.call("GET", q)
        self.assertEqual((r["ok"], r["swapped"]), (True, True))
        q2 = (f"/api/arch/can-connect?composition={self.root['id']}&source_component={adc['id']}"
              f"&source_port=airData&target_component={fms['id']}&target_port=airData")
        self.assertFalse(self.call("GET", q2)["ok"])
        v = self.view()
        self.assertEqual(len(v["connectors"]), 3)
        self.assertEqual(v["boundary_ports"][0]["side"], "right")

    def test_cross_hierarchy_and_points(self):
        adc, fms, disp = self.three()
        guid = self.comp("Guidance", composition=fms["id"])
        self.port(guid, "air", "in")
        c = self.connect(adc, "airData", guid, "air")
        self.assertEqual(c["target"]["component_id"], fms["id"])
        inner = self.view(fms, f"?path={self.root['id']},{fms['id']}")
        self.assertEqual([b["name"] for b in inner["composition"]["breadcrumbs"]], ["AircraftSystem", "FMS"])
        self.assertEqual(len(inner["connectors"]), 1)
        out = self.call("PATCH", f"/api/arch/connector/{c['id']}", {"points": [[1, 2], [3, 4]],
                                                                    "name": "air_bus"})
        self.assertEqual((out["points"], out["name"]), ([[1, 2], [3, 4]], "air_bus"))
        self.call("PATCH", f"/api/arch/connector/{c['id']}", {"points": "bad"}, expect=400)
        self.call("PATCH", f"/api/arch/connector/{adc['id']}", {"name": "x"}, expect=400)

    def test_client_server_in_software_model(self):
        self.call("POST", "/api/arch/model-type", {"type": "software"})
        nav, ui = self.comp("NavService"), self.comp("Ui")
        s = self.port(nav, "api", kind="server")
        c = self.port(ui, "api", kind="client")
        out = self.connect(nav, s["id"], ui, c["id"])
        self.assertEqual((out["kind"], out["source"]["port_id"]), ("client-server", c["id"]))


class EditingHttpTests(_ArchHttp):

    def test_duplicate_group_expand_reference_inline_delete(self):
        adc, fms, disp = self.three()
        self.connect(adc, "airData", fms, "airData")
        self.connect(fms, "route", disp, "route")
        dup = self.call("POST", "/api/arch/duplicate", {"ids": [fms["id"], disp["id"]]})["components"]
        self.assertEqual([c["name"] for c in dup], ["FMS1", "Display1"])
        self.assertEqual(len(self.view()["connectors"]), 3)       # the FMS->Display copy came along
        self.call("POST", "/api/arch/delete", {"ids": [c["id"] for c in dup]})
        g = self.call("POST", "/api/arch/group", {"composition": self.root["id"],
                                                  "component_ids": [fms["id"], disp["id"]],
                                                  "name": "NavDisplay"})
        self.assertEqual(g["badges"][:2], ["inline", "composite"])
        self.assertEqual([p["name"] for p in g["ports"]], ["airData"])
        v = self.view()
        self.assertEqual(sorted(c["name"] for c in v["components"]), ["ADC", "NavDisplay"])
        self.assertEqual(self.call("GET", "/api/validate")["errors"], 0)
        ref = self.call("POST", "/api/arch/save-as-reference", {"component": g["id"]})
        self.assertEqual(ref["definition"]["name"], "NavDisplay")
        self.assertTrue(ref["component"]["is_reference"])
        self.call("POST", "/api/arch/save-as-reference", {"component": g["id"]}, expect=400)
        roots = self.call("GET", "/api/arch/roots")
        self.assertEqual([r["name"] for r in roots["roots"]], ["AircraftSystem"])
        inl = self.call("POST", "/api/arch/inline", {"component": g["id"]})
        self.assertFalse(inl["is_reference"])
        moved = self.call("POST", "/api/arch/expand", {"component": g["id"]})["components"]
        self.assertEqual(len(moved), 2)
        v = self.view()
        self.assertEqual(sorted(c["name"] for c in v["components"]), ["ADC", "Display", "FMS"])
        self.assertEqual(len(v["connectors"]), 2)
        self.assertEqual(self.call("GET", "/api/validate")["errors"], 0)
        self.call("POST", "/api/arch/delete", {"ids": []}, expect=400)
        self.call("POST", "/api/arch/delete", {"ids": ["missing"]}, expect=404)

    def test_copy_paste_into_another_composition(self):
        adc, fms, disp = self.three()
        self.connect(fms, "route", disp, "route")
        pasted = self.call("POST", "/api/arch/duplicate", {"ids": [fms["id"], disp["id"]],
                                                           "target": adc["id"]})["components"]
        self.assertEqual([c["owner_id"] for c in pasted], [adc["id"], adc["id"]])
        inside = self.view(adc)
        self.assertEqual(sorted(c["name"] for c in inside["components"]), ["Display", "FMS"])
        self.assertEqual(len(inside["connectors"]), 1)
        self.assertEqual(inside["connectors"][0]["issues"], [])
        self.assertIn("composite", self.call("GET", f"/api/element/{adc['id']}")["badges"])
        # One undo step removes the whole paste.
        self.call("POST", "/api/undo")
        self.assertEqual(self.view(adc)["components"], [])
        self.call("POST", "/api/arch/duplicate", {"ids": [fms["id"]], "target": "missing"}, expect=404)

    def test_layout_auto_layout_and_tree(self):
        adc, fms, disp = self.three()
        self.connect(fms, "route", disp, "route")
        self.connect(adc, "airData", fms, "airData")
        pos = self.call("POST", "/api/arch/auto-layout", {"composition": self.root["id"]})["positions"]
        self.assertLess(pos[adc["id"]]["x"], pos[fms["id"]]["x"])
        self.assertLess(pos[fms["id"]]["x"], pos[disp["id"]]["x"])
        p = self.view()["components"][0]["ports"][0]
        self.call("POST", "/api/arch/layout", {"items": [
            {"id": adc["id"], "x": 5, "y": 6, "w": 170, "h": 95},
            {"id": p["id"], "side": "bottom", "offset": 0.3}]})
        comp = [c for c in self.view()["components"] if c["id"] == adc["id"]][0]
        self.assertEqual(comp["layout"], {"x": 5, "y": 6, "w": 170, "h": 95})
        self.assertEqual((comp["ports"][0]["side"], comp["ports"][0]["offset"]), ("bottom", 0.3))
        self.call("POST", "/api/arch/layout", {"items": [{"id": adc["id"], "x": "a", "y": 1}]}, expect=400)
        tree = self.call("GET", f"/api/arch/tree/{self.root['id']}")
        self.assertEqual([c["name"] for c in tree["children"]], ["ADC", "FMS", "Display"])

    def test_arrange_packs_a_cyclic_avionics_network_for_the_canvas(self):
        """PO-1 repro: 30 LRUs, 3 outputs each to other LRUs (new ports), then Arrange."""
        names = ["ADIRU1", "ADIRU2", "ADIRU3", "FMC1", "FMC2", "DU_CPT", "DU_FO", "DU_EICAS",
                 "AFDX_SW1", "AFDX_SW2", "CPIOM_A", "CPIOM_B", "CPIOM_C", "RDC1", "RDC2", "GPS1",
                 "GPS2", "RA1", "RA2", "FCC1", "FCC2", "FCC3", "TCAS", "WXR", "VHF1", "VHF2",
                 "MCDU1", "MCDU2", "EGPWS", "SATCOM"]
        comps = [self.comp(n) for n in names]
        for c in comps:
            self.port(c, "out", "out")
        for i, c in enumerate(comps):
            for k in (7, 11, 19):
                self.call("POST", "/api/arch/connector", {
                    "composition": self.root["id"], "source": {"component": c["id"], "port": "out"},
                    "target": {"component": comps[(i * 3 + k) % 30]["id"], "new_port": True}})
        body = {"composition": self.root["id"], "view": {"w": 874, "h": 480}}
        pos = self.call("POST", "/api/arch/auto-layout", body)["positions"]
        self.assertEqual(self.call("GET", "/api/undo/state")["undo_label"], "Arrange")
        boxes = list(pos.values())
        w = max(b["x"] + b["w"] for b in boxes) - min(b["x"] for b in boxes)
        h = max(b["y"] + b["h"] for b in boxes) - min(b["y"] for b in boxes)
        self.assertTrue(1 / 3 <= w / h <= 3, (w, h))
        self.assertLessEqual(len({b["x"] + b["w"] / 2 for b in boxes}), 30 ** 0.5 + 3)
        self.assertGreaterEqual(A.fit_zoom(w, h, (874, 480)), 0.4)
        self.assertEqual(self.call("POST", "/api/arch/auto-layout", body)["positions"], pos)
        self.assertEqual({c["id"]: c["layout"] for c in self.view()["components"]}, pos)
        body["view"] = {"w": "big"}
        self.call("POST", "/api/arch/auto-layout", body, expect=400)

    def test_everything_survives_save_and_load(self):
        self.call("POST", "/api/arch/model-type", {"type": "software"})
        adc, fms, disp = self.three()
        sensor = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "Sensor"})
        s1 = self.comp("s1", definition=sensor["id"])
        self.comp("s2", definition=sensor["id"])
        self.port(s1, "val", "out")
        self.port(disp, "v", "in")
        self.port(fms, "svc", kind="server")
        self.connect(s1, "val", disp, "v")
        self.call("POST", "/api/arch/auto-layout", {"composition": self.root["id"]})
        before = self.view()
        text = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/new", {"name": "Other"})
        self.call("POST", "/api/load", {"text": text})
        after = self.view()
        self.assertEqual(after, before)
        self.assertEqual(self.call("GET", "/api/arch/model-type")["type"], "software")

    def test_ibd_diagram_endpoint(self):
        adc, fms, disp = self.three()
        self.connect(adc, "airData", fms, "airData")
        out = self.call("GET", f"/api/diagram/mermaid?kind=ibd&target={self.root['id']}")
        self.assertIn("-->", out["text"])


class UndoHttpTests(_ArchHttp):

    def test_undo_redo_any_mutation(self):
        el = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "Gen"})
        self.call("PATCH", f"/api/element/{el['id']}", {"props": {"name": "Generator"}})
        self.call("DELETE", f"/api/element/{el['id']}")
        self.call("GET", f"/api/element/{el['id']}", expect=404)
        st = self.call("POST", "/api/undo")
        self.assertTrue(st["ok"])
        self.assertEqual(self.call("GET", f"/api/element/{el['id']}")["name"], "Generator")
        self.call("POST", "/api/undo")
        self.assertEqual(self.call("GET", f"/api/element/{el['id']}")["name"], "Gen")
        st = self.call("POST", "/api/redo")
        self.assertEqual((st["ok"], st["redo_label"]), (True, "Delete element"))
        self.assertEqual(self.call("GET", f"/api/element/{el['id']}")["name"], "Generator")
        # a new edit clears redo
        self.comp("X")
        self.assertFalse(self.call("GET", "/api/undo/state")["can_redo"])

    def test_failed_and_readonly_requests_leave_no_step(self):
        depth = self.call("GET", "/api/undo/state")["undo_depth"]
        self.call("POST", "/api/arch/component", {"composition": "missing"}, expect=404)
        self.call("PATCH", f"/api/element/{self.root['id']}", {"props": {"bogus": 1}}, expect=400)
        self.call("POST", "/api/arch/layout", {"items": []})
        self.call("GET", "/api/save")
        self.assertEqual(self.call("GET", "/api/undo/state")["undo_depth"], depth)

    def test_nothing_to_undo_new_and_load_clear(self):
        self.comp("A")
        self.call("POST", "/api/new", {"name": "Fresh"})
        st = self.call("POST", "/api/undo")
        self.assertEqual((st["ok"], st["reason"]), (False, "nothing to undo"))
        self.assertFalse(self.call("POST", "/api/redo")["ok"])
        text = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "Z"})
        self.call("POST", "/api/load", {"text": text})
        self.assertFalse(self.call("GET", "/api/undo/state")["can_undo"])

    def test_unsaved_changes_state(self):
        """SU-13: the studio warns on New / Load while the project is dirty."""
        self.assertTrue(self.call("GET", "/api/undo/state")["dirty"])     # architecture created
        st = self.call("POST", "/api/undo/saved")
        self.assertFalse(st["dirty"])
        self.assertEqual(self.call("GET", "/api/undo/state")["undo_label"], st["undo_label"])   # no step
        self.call("POST", "/api/arch/auto-layout", {"composition": self.root["id"]})   # changes nothing
        self.call("POST", "/api/arch/component", {"composition": "missing"}, expect=404)
        self.assertFalse(self.call("GET", "/api/undo/state")["dirty"])
        self.comp("FMS")
        self.assertTrue(self.call("GET", "/api/undo/state")["dirty"])
        self.call("POST", "/api/new", {"name": "Fresh"})
        self.assertFalse(self.call("GET", "/api/undo/state")["dirty"])

    def test_history_is_capped_at_50(self):
        for i in range(55):
            self.call("PATCH", f"/api/element/{self.root['id']}", {"props": {"short_name": f"s{i}"}})
        st = self.call("GET", "/api/undo/state")
        self.assertEqual(st["undo_depth"], 50)
        self.assertEqual(st["limit"], 50)

    def test_undo_restores_architecture_edits(self):
        adc, fms, disp = self.three()
        c = self.connect(adc, "airData", fms, "airData")
        self.call("POST", "/api/arch/group", {"composition": self.root["id"],
                                              "component_ids": [adc["id"], fms["id"]]})
        self.assertEqual(len(self.view()["components"]), 2)
        self.call("POST", "/api/undo")
        v = self.view()
        self.assertEqual(sorted(x["name"] for x in v["components"]), ["ADC", "Display", "FMS"])
        self.assertEqual([x["id"] for x in v["connectors"]], [c["id"]])
        self.assertIs(core.session().find(c["id"]).owner, core.session().find(self.root["id"]))
