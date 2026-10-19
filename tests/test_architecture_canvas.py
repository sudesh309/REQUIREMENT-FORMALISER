"""Tests for the canvas-facing architecture API: connect targets, connect-to-new-port,
locate, layout merging, view-model size, and the canvas JavaScript modules."""
import random
import shutil
import subprocess
import time
import unittest
from pathlib import Path

from engine import Repository, from_json, to_json
from engine import architecture as A
from engine.structure import components_of, connector_ends, connectors_of, ports_of
from kerml.features import FeatureDirection
from tests.webapp_harness import WebAppTestCase

ROOT = Path(__file__).resolve().parent.parent
CANVAS_JS = [ROOT / "webapp/static/plugins/10-canvas.js",
             *sorted((ROOT / "webapp/static/plugins/canvas").glob("*.js"))]


def _model():
    repo = Repository("Avionics")
    root = A.create_architecture(repo, "AircraftSystem")
    adc = A.add_component(repo, root, "ADC")
    fms = A.add_component(repo, root, "FMS")
    disp = A.add_component(repo, root, "Display")
    air_out = A.add_port(repo, adc, "airData", "out")
    air_in = A.add_port(repo, fms, "air", "in")
    A.add_port(repo, fms, "route", "out")
    A.add_port(repo, disp, "route", "in")
    return repo, root, adc, fms, disp, air_out, air_in


class ConnectTargetsTests(unittest.TestCase):

    def test_every_view_port_with_reason(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        pitot = A.add_port(repo, root, "pitot", "in")
        pwr = A.add_port(repo, adc, "pwr", kind="physical")
        targets = {(t["component_id"], t["port_id"]): t for t in A.connect_targets(root, (adc, air_out))}
        # all other ports of the view are listed, the source itself is not
        self.assertEqual(len(targets), len(A.view_ports(root)) - 1)
        self.assertNotIn((adc.element_id, air_out.element_id), targets)
        self.assertTrue(targets[(fms.element_id, air_in.element_id)]["ok"])
        bad_dir = targets[(None, pitot.element_id)]
        self.assertFalse(bad_dir["ok"])
        self.assertIn("data connectors go", bad_dir["reason"])
        bad_kind = targets[(adc.element_id, pwr.element_id)]
        self.assertFalse(bad_kind["ok"])
        self.assertIn("physical", bad_kind["reason"])

    def test_existing_driver_and_swapped_orientation(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        A.connect(repo, root, (adc, air_out), (fms, air_in))
        other = A.add_component(repo, root, "ADC2")
        out2 = A.add_port(repo, other, "airData", "out")
        t = {(x["component_id"], x["port_id"]): x for x in A.connect_targets(root, (other, out2))}
        self.assertFalse(t[(fms.element_id, air_in.element_id)]["ok"])
        self.assertIn("already has an incoming connection", t[(fms.element_id, air_in.element_id)]["reason"])
        # dragging from an input back to an output is valid and reported as swapped
        route_in = ports_of(disp)[0]
        route_out = next(p for p in ports_of(fms) if p.name == "route")
        t = {(x["component_id"], x["port_id"]): x for x in A.connect_targets(root, (disp, route_in))}
        hit = t[(fms.element_id, route_out.element_id)]
        self.assertTrue(hit["ok"])
        self.assertTrue(hit["swapped"])

    def test_source_must_be_in_scope_and_nothing_changes(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        before = to_json(repo)
        with self.assertRaises(A.ArchitectureError):
            A.connect_targets(fms, (adc, air_out))       # ADC is not inside FMS
        A.connect_targets(root, (adc, air_out))
        self.assertEqual(before, to_json(repo))


class ConnectNewPortTests(unittest.TestCase):

    def test_new_input_on_component_mirrors_interface(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        iface = A.create_architecture(repo, "AirDataBus")       # any type will do for an interface
        A.update_port(repo, air_out, interface=iface)
        port, conn = A.connect_new_port(repo, root, (adc, air_out), disp,
                                        layout={"side": "top", "offset": 0.25})
        self.assertEqual((port.name, port.direction, port.port_kind), ("airData", FeatureDirection.IN, "data"))
        self.assertIs(port.owner, disp)
        self.assertEqual(port.types, [iface])
        self.assertEqual(port.tool_data["port_layout"], {"side": "top", "offset": 0.25})
        self.assertEqual(connector_ends(conn, root), [(adc, air_out), (disp, port)])

    def test_new_boundary_port_and_name_collision(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        port, conn = A.connect_new_port(repo, root, (adc, air_out), None)
        # a boundary output, fed from the inside
        self.assertIs(port.owner, root)
        self.assertEqual(port.direction, FeatureDirection.OUT)
        self.assertEqual(connector_ends(conn, root), [(adc, air_out), (None, port)])
        port2, _ = A.connect_new_port(repo, root, (adc, air_out), None)
        self.assertEqual(port2.name, "airData1")
        with self.assertRaises(A.ArchitectureError) as cm:
            A.connect_new_port(repo, root, (adc, air_out), fms, port_name="air")
        self.assertEqual(cm.exception.status, 409)

    def test_reference_component_gets_port_on_definition(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        sensor = A.create_architecture(repo, "Sensor")
        s1 = A.add_component(repo, root, "s1", sensor)
        s2 = A.add_component(repo, root, "s2", sensor)
        port, _ = A.connect_new_port(repo, root, (adc, air_out), s1)
        self.assertIs(port.owner, sensor)
        self.assertIn(port, ports_of(s2))

    def test_physical_and_refusals_roll_back(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        pwr = A.add_port(repo, adc, "pwr", kind="physical")
        port, _ = A.connect_new_port(repo, root, (adc, pwr), fms)
        self.assertEqual((port.port_kind, port.direction), ("physical", FeatureDirection.INOUT))
        inner = A.add_component(repo, fms, "Inner")
        before = to_json(repo)
        with self.assertRaises(A.ArchitectureError):
            A.connect_new_port(repo, root, (adc, air_out), adc)      # own component
        with self.assertRaises(A.ArchitectureError):
            A.connect_new_port(repo, root, (adc, air_out), inner)    # not a direct sub-component
        A.connect(repo, root, (adc, air_out), (fms, air_in))
        with self.assertRaises(A.ArchitectureError) as cm:            # duplicate connection
            A.connect_new_port(repo, root, (adc, air_out), fms, port_name="air")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(len(ports_of(fms)), 3)
        self.assertEqual(len(connectors_of(root)), 2)
        self.assertNotEqual(before, to_json(repo))   # only the explicit connect above changed it

    def test_cross_hierarchy_source_rolls_back_on_failure(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        inner = A.add_component(repo, fms, "Filter")
        deep_out = A.add_port(repo, inner, "clean", "out")
        n_ports = len(ports_of(fms))
        with self.assertRaises(A.ArchitectureError):
            # punches through FMS, then fails: the new port must not survive
            A.connect_new_port(repo, root, {"component": inner, "port": deep_out}, fms)
        self.assertEqual(len(ports_of(fms)), n_ports)


class LocateAndLayoutTests(unittest.TestCase):

    def test_locate(self):
        repo, root, adc, fms, disp, air_out, air_in = _model()
        conn = A.connect(repo, root, (adc, air_out), (fms, air_in))
        boundary = A.add_port(repo, root, "pitot", "in")
        inner = A.add_component(repo, fms, "Filter")
        self.assertEqual(A.locate(adc), {"composition": root, "select": adc})
        self.assertEqual(A.locate(air_out), {"composition": root, "select": air_out})
        self.assertEqual(A.locate(conn), {"composition": root, "select": conn})
        self.assertEqual(A.locate(boundary), {"composition": root, "select": boundary})
        self.assertEqual(A.locate(inner), {"composition": fms, "select": inner})
        self.assertEqual(A.locate(root), {"composition": root, "select": None})
        self.assertIsNone(A.locate(repo.root_package))

    def test_move_keeps_resized_size_and_null_resets(self):
        repo, root, adc, *_ = _model()
        A.apply_layout(repo, [{"id": adc.element_id, "x": 10, "y": 20, "w": 300, "h": 140}])
        A.apply_layout(repo, [{"id": adc.element_id, "x": 50, "y": 60}])
        self.assertEqual(adc.tool_data["layout"], {"x": 50, "y": 60, "w": 300, "h": 140})
        self.assertTrue(A.component_view(adc, root)["sized"])
        A.apply_layout(repo, [{"id": adc.element_id, "x": 50, "y": 60, "w": None, "h": None}])
        self.assertEqual(adc.tool_data["layout"], {"x": 50, "y": 60})
        v = A.component_view(adc, root)
        self.assertFalse(v["sized"])
        self.assertEqual((v["layout"]["w"], v["layout"]["h"]), (A.DEFAULT_W, A.DEFAULT_H))
        self.assertEqual(from_json(to_json(repo)).by_id(adc.element_id).tool_data["layout"],
                         {"x": 50, "y": 60})


class AutomaticPlacementTests(unittest.TestCase):

    def test_unplaced_ports_avoid_placed_ones(self):
        repo, root, adc, *_ = _model()
        pwr = A.add_port(repo, adc, "pwr", kind="physical")            # left, automatic
        pitot = A.add_port(repo, adc, "pitot", "in", layout={"side": "left", "offset": 0.3})
        lay = A.port_layouts(adc)
        self.assertEqual(lay[id(pitot)], {"side": "left", "offset": 0.3})
        self.assertGreater(abs(lay[id(pwr)]["offset"] - 0.3), 0.2)
        # without stored places the order is kept: 1/4, 2/4, 3/4
        repo2, root2, adc2, *_ = _model()
        ps = [A.add_port(repo2, adc2, f"i{i}", "in") for i in range(3)]
        self.assertEqual([A.port_layouts(adc2)[id(p)]["offset"] for p in ps], [0.25, 0.5, 0.75])

    def test_automatic_width_follows_the_name(self):
        repo, root, *_ = _model()
        short = A.add_component(repo, root, "GPS")
        long = A.add_component(repo, root, "FlightManagementSystem")
        A.add_port(repo, long, "air1", "in")
        self.assertEqual(A.default_size(short), (A.DEFAULT_W, A.DEFAULT_H))
        w, _h = A.default_size(long)
        self.assertGreater(w, A.DEFAULT_W)
        self.assertLessEqual(w, A.MAX_AUTO_W)
        self.assertEqual(w % 10, 0)
        A.apply_layout(repo, [{"id": long.element_id, "x": 0, "y": 0, "w": 200, "h": 90}])
        self.assertEqual(A.effective_box(long, root)["w"], 200)          # a user size wins


def big_model(n_components=60, n_connectors=200, seed=7):
    """60 components with 2 outputs and 4 inputs each, wired by 200 valid connectors."""
    rng = random.Random(seed)
    repo = Repository("Big")
    root = A.create_architecture(repo, "Big")
    comps = [A.add_component(repo, root, f"LRU{i}") for i in range(n_components)]
    outs = [[A.add_port(repo, c, f"o{j}", "out") for j in range(2)] for c in comps]
    free = [(c, A.add_port(repo, c, f"i{j}", "in")) for c in comps for j in range(4)]
    rng.shuffle(free)
    made = 0
    for c, p in free:
        if made >= n_connectors:
            break
        si = rng.randrange(n_components)
        if comps[si] is c:
            continue
        A.connect(repo, root, (comps[si], rng.choice(outs[si])), (c, p))
        made += 1
    return repo, root


class BigModelTests(unittest.TestCase):

    def test_view_of_60_components_and_200_connectors_is_fast(self):
        repo, root = big_model()
        self.assertEqual((len(components_of(root)), len(connectors_of(root))), (60, 200))
        t = time.perf_counter()
        v = A.view(repo, root)
        A.connect_targets(root, (components_of(root)[0], ports_of(components_of(root)[0])[0]))
        self.assertLess(time.perf_counter() - t, 2.0)
        self.assertEqual(len(v["connectors"]), 200)
        self.assertFalse(any(c["issues"] for c in v["connectors"]))


class CanvasHttpTests(WebAppTestCase):

    def setUp(self):
        A.install()
        self.call("POST", "/api/new", {"name": "Avionics"})
        self.root = self.call("POST", "/api/arch/architecture", {"name": "AircraftSystem"})
        self.adc = self.call("POST", "/api/arch/component", {"composition": self.root["id"], "name": "ADC"})
        self.fms = self.call("POST", "/api/arch/component", {"composition": self.root["id"], "name": "FMS"})
        self.out = self.call("POST", "/api/arch/port", {"owner": self.adc["id"], "name": "airData", "direction": "out"})
        self.inp = self.call("POST", "/api/arch/port", {"owner": self.fms["id"], "name": "air", "direction": "in"})

    def test_connect_targets_endpoint(self):
        q = f"composition={self.root['id']}&source_component={self.adc['id']}&source_port={self.out['id']}"
        r = self.call("GET", f"/api/arch/connect-targets?{q}")
        self.assertEqual(r["source"], {"component_id": self.adc["id"], "port_id": self.out["id"]})
        hit = next(t for t in r["targets"] if t["port_id"] == self.inp["id"])
        self.assertTrue(hit["ok"])
        # port by name, and errors are clear 4xx
        r = self.call("GET", f"/api/arch/connect-targets?composition={self.root['id']}"
                             f"&source_component={self.adc['id']}&source_port=airData")
        self.assertEqual(r["source"]["port_id"], self.out["id"])
        self.call("GET", f"/api/arch/connect-targets?composition={self.root['id']}"
                         f"&source_component={self.adc['id']}&source_port=nope", expect=404)
        self.call("GET", "/api/arch/connect-targets?source_port=x", expect=400)
        e = self.call("GET", f"/api/arch/connect-targets?composition={self.fms['id']}"
                             f"&source_component={self.adc['id']}&source_port={self.out['id']}", expect=400)
        self.assertIn("not a direct sub-component", e["error"])

    def test_connector_to_new_port(self):
        r = self.call("POST", "/api/arch/connector", {
            "composition": self.root["id"],
            "source": {"component": self.adc["id"], "port": self.out["id"]},
            "target": {"component": self.fms["id"], "new_port": {"side": "top", "offset": 0.3}}})
        self.assertEqual(r["created_port"]["direction"], "in")
        self.assertEqual((r["created_port"]["side"], r["created_port"]["offset"]), ("top", 0.3))
        self.assertEqual(r["target"], {"component_id": self.fms["id"], "port_id": r["created_port"]["id"]})
        # a new boundary port (no component), drawn from the new port's side of the connection
        r2 = self.call("POST", "/api/arch/connector", {
            "composition": self.root["id"], "source": {"new_port": True},
            "target": {"component": self.fms["id"], "port": self.inp["id"]}})
        self.assertEqual(r2["created_port"]["direction"], "in")     # a boundary input feeds the inside
        self.assertEqual(r2["source"]["component_id"], None)
        undo_depth = self.call("GET", "/api/undo/state")["undo_depth"]
        bad = self.call("POST", "/api/arch/connector", {
            "composition": self.root["id"], "source": {"new_port": True}, "target": {"new_port": True}},
            expect=400)
        self.assertIn("only one end", bad["error"])
        self.call("POST", "/api/arch/connector", {
            "composition": self.root["id"], "source": {"component": self.adc["id"], "port": self.out["id"]},
            "target": {"component": self.adc["id"], "new_port": True}}, expect=400)
        self.call("POST", "/api/arch/connector", {
            "composition": self.root["id"], "source": {"component": self.adc["id"], "port": self.out["id"]},
            "target": {"component": self.fms["id"], "new_port": {"name": 5}}}, expect=400)
        self.assertEqual(self.call("GET", "/api/undo/state")["undo_depth"], undo_depth)
        v = self.call("GET", f"/api/arch/view/{self.root['id']}")
        self.assertEqual(len(v["connectors"]), 2)
        self.assertEqual(len(v["boundary_ports"]), 1)

    def test_locate_endpoint(self):
        self.assertEqual(self.call("GET", f"/api/arch/locate/{self.out['id']}"),
                         {"composition": self.root["id"], "select": self.out["id"]})
        self.assertEqual(self.call("GET", f"/api/arch/locate/{self.root['id']}"),
                         {"composition": self.root["id"], "select": None})
        pkg = self.call("POST", "/api/element", {"kind": "Package", "name": "Lib"})
        self.assertEqual(self.call("GET", f"/api/arch/locate/{pkg['id']}"),
                         {"composition": None, "select": None})
        self.call("GET", "/api/arch/locate/missing", expect=404)

    def test_layout_merge_and_reset(self):
        cid = self.adc["id"]
        self.call("POST", "/api/arch/layout", {"items": [{"id": cid, "x": 0, "y": 0, "w": 220, "h": 120}]})
        self.call("POST", "/api/arch/layout", {"items": [{"id": cid, "x": 40, "y": 30}]})
        v = self.call("GET", f"/api/arch/view/{self.root['id']}")
        c = next(x for x in v["components"] if x["id"] == cid)
        self.assertEqual(c["layout"], {"x": 40, "y": 30, "w": 220, "h": 120})
        self.assertTrue(c["sized"])
        self.call("POST", "/api/arch/layout", {"items": [{"id": cid, "x": 40, "y": 30, "w": None, "h": None}]})
        c = next(x for x in self.call("GET", f"/api/arch/view/{self.root['id']}")["components"] if x["id"] == cid)
        self.assertFalse(c["sized"])
        self.call("POST", "/api/arch/layout", {"items": [{"id": cid, "x": 1, "y": 1, "w": -5}]}, expect=400)


class CanvasMcpTests(unittest.TestCase):

    def setUp(self):
        from mcp_server import server as m
        m.SESSION.set_repo(Repository("Mcp"))
        self.m = m

    def ok(self, tool, /, **kw):
        out = self.m.TOOL_BY_NAME[tool]["handler"](**kw)
        self.assertTrue(out["ok"], out)
        return out["result"]

    def fail(self, tool, /, **kw):
        out = self.m.TOOL_BY_NAME[tool]["handler"](**kw)
        self.assertFalse(out["ok"], out)
        return out["error"]

    def test_targets_new_port_layout_locate_and_undo(self):
        root = self.ok("sysml_new_architecture", name="Aircraft")
        adc = self.ok("sysml_add_component", composition=root["id"], name="ADC")
        fms = self.ok("sysml_add_component", composition=root["id"], name="FMS")
        out = self.ok("sysml_add_port", owner=adc["id"], name="airData", direction="out")
        self.ok("sysml_add_port", owner=fms["id"], name="cmd", direction="out")
        targets = self.ok("sysml_connect_targets", composition=root["id"], source_component=adc["id"],
                          source_port="airData")["targets"]
        self.assertEqual([(t["label"], t["ok"]) for t in targets], [("FMS.cmd", False)])
        self.assertIn("data connectors go", targets[0]["reason"])
        c = self.ok("sysml_connect_to_new_port", composition=root["id"], source_component=adc["id"],
                    source_port=out["id"], target_component=fms["id"], side="top", offset=0.25)
        self.assertEqual((c["created_port"]["name"], c["created_port"]["direction"]), ("airData", "in"))
        self.assertEqual((c["created_port"]["side"], c["created_port"]["offset"]), ("top", 0.25))
        b = self.ok("sysml_connect_to_new_port", composition=root["id"], source_component=adc["id"],
                    source_port="airData", port_name="adcOut")
        self.assertEqual((b["created_port"]["name"], b["created_port"]["direction"]), ("adcOut", "out"))
        self.assertIn("own component", self.fail("sysml_connect_to_new_port", composition=root["id"],
                                                 source_component=adc["id"], source_port="airData",
                                                 target_component=adc["id"]))
        self.assertEqual(self.ok("sysml_set_layout", items=[{"id": "Aircraft::FMS", "x": 700, "y": 80}])["updated"], 1)
        self.assertEqual(self.ok("sysml_set_layout", items=[{"id": adc["id"], "x": 400, "y": 80}])["updated"], 1)
        self.assertIn("finite number", self.fail("sysml_set_layout", items=[{"id": adc["id"], "x": "a", "y": 0}]))
        view = self.ok("sysml_arch_view", composition=root["id"])
        self.assertEqual(next(x for x in view["components"] if x["id"] == adc["id"])["layout"]["x"], 400)
        self.assertEqual(self.ok("sysml_arch_locate", element=c["created_port"]["id"]),
                         {"composition": root["id"], "select": c["created_port"]["id"]})
        self.assertTrue(self.ok("sysml_undo")["undone"])           # the move
        view = self.ok("sysml_arch_view", composition=root["id"])
        self.assertNotEqual(next(x for x in view["components"] if x["id"] == adc["id"])["layout"]["x"], 400)


@unittest.skipUnless(shutil.which("node"), "node not available")
class CanvasJavaScriptTests(unittest.TestCase):

    def test_every_canvas_module_parses(self):
        self.assertTrue(len(CANVAS_JS) >= 2)
        for f in CANVAS_JS:
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"{f.name}: {r.stderr}")

    def test_geometry_unit_tests(self):
        script = ROOT / "tests/ui/10_canvas_geometry.test.mjs"
        r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
