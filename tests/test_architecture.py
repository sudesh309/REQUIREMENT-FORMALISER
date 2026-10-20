"""Engine tests for System Composer-style architecture modeling (engine/architecture.py)."""
import math
import re
import time
import unittest

from engine import Repository, Validator, from_json, parse, to_json
from engine import architecture as A
from engine import hooks
from engine.diagram import ibd
from engine.diagram_mermaid import ibd_mermaid
from engine.structure import components_of, connector_ends, connectors_of, definition_of, ports_of
from engine.undo import UndoHistory, history_for, redo, tracked, undo
from kerml.features import FeatureDirection
from kerml.stereotypes import Stereotype, stereotypes_on
from sysmlv2 import ConnectionUsage, PartDefinition, PartUsage, PortDefinition, PortUsage
from sysmlv2.state_machines import attach_state_machine


def _arch():
    """Avionics-flavoured test model: ADC -> FMS -> Display, plus a reference sensor type."""
    repo = Repository("Avionics")
    root = A.create_architecture(repo, "AircraftSystem")
    adc = A.add_component(repo, root, "ADC")
    fms = A.add_component(repo, root, "FMS")
    disp = A.add_component(repo, root, "Display")
    A.add_port(repo, adc, "airData", "out")
    A.add_port(repo, fms, "airData", "in")
    A.add_port(repo, fms, "route", "out")
    A.add_port(repo, disp, "route", "in")
    return repo, root, adc, fms, disp


def _ep(component, port_name):
    return {"component": component, "port": port_name}


def _issues(repo, prefix="arch."):
    A.install()
    return [(i.rule, i.message) for i in Validator().validate(repo) if i.rule.startswith(prefix)]


LRU_NAMES = ["ADIRU1", "ADIRU2", "ADIRU3", "FMC1", "FMC2", "DU_CPT_PFD", "DU_CPT_ND", "DU_FO_PFD",
             "DU_FO_ND", "DU_EICAS", "AFDX_SW1", "AFDX_SW2", "CPIOM_A", "CPIOM_B", "CPIOM_C",
             "RDC1", "RDC2", "GPS1", "GPS2", "RA1", "RA2", "FCC1", "FCC2", "FCC3", "TCAS",
             "WXR", "VHF1", "VHF2", "MCDU1", "MCDU2"]


def _avionics_network(n=30, seed=11):
    """The PO-1 scale fixture: n LRUs with one output each, wired to 3 random other LRUs
    (new input ports), so the network has many cycles, like bidirectional A429 / AFDX links."""
    repo = Repository("Scale")
    root = A.create_architecture(repo, "Aircraft")
    names = (LRU_NAMES + [f"LRU{i}" for i in range(n)])[:n]
    comps = []
    for name in names:
        c = A.add_component(repo, root, name)
        A.add_port(repo, c, "out", "out")
        comps.append(c)
    state = seed
    for c in comps:
        for _ in range(3):
            while True:      # small LCG: the same fixture on every Python version
                state = (state * 1103515245 + 12345) % 2147483648
                t = comps[state % n]
                if t is not c:
                    break
            A.connect_new_port(repo, root, {"component": c, "port": "out"}, t)
    return repo, root


def _frame(positions):
    """(width, height) of the bounding box of arranged component boxes."""
    boxes = list(positions.values())
    return (max(b["x"] + b["w"] for b in boxes) - min(b["x"] for b in boxes),
            max(b["y"] + b["h"] for b in boxes) - min(b["y"] for b in boxes))


def _overlaps(positions):
    boxes = list(positions.values())
    return [(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:]
            if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]]


class ModelTypeTests(unittest.TestCase):

    def test_default_system_and_persisted_software(self):
        repo = Repository("P")
        self.assertEqual(A.model_type(repo), "system")
        self.assertEqual(A.allowed_port_kinds(repo), ("data", "physical"))
        A.set_model_type(repo, "software")
        loaded = from_json(to_json(repo))
        self.assertEqual(A.model_type(loaded), "software")
        self.assertIn("client", A.allowed_port_kinds(loaded))

    def test_unknown_type_and_conflicting_ports(self):
        repo, root, adc, *_ = _arch()
        with self.assertRaises(A.ArchitectureError) as cm:
            A.set_model_type(repo, "hardware")
        self.assertEqual(cm.exception.status, 400)
        A.add_port(repo, adc, "pwr", kind="physical")
        with self.assertRaises(A.ArchitectureError) as cm:
            A.set_model_type(repo, "software")
        self.assertEqual(cm.exception.status, 409)
        A.set_model_type(repo, "software", force=True)
        self.assertIn("arch.port.kind", [r for r, _ in _issues(repo)])

    def test_port_kind_rules_follow_model_type(self):
        repo, root, adc, *_ = _arch()
        with self.assertRaises(A.ArchitectureError) as cm:
            A.add_port(repo, adc, kind="client")
        self.assertIn("software", str(cm.exception))
        A.set_model_type(repo, "software")
        p = A.add_port(repo, adc, kind="client")
        self.assertEqual((p.name, p.port_kind, p.direction), ("Client", "client", FeatureDirection.INOUT))


class PortKindAttributeTests(unittest.TestCase):

    def test_default_validation_and_round_trip(self):
        p = PortUsage(name="p")
        self.assertEqual(p.port_kind, "data")
        with self.assertRaises(ValueError):
            p.port_kind = "optical"
        repo = Repository("P")
        d = repo.add(PartDefinition(name="D"))
        q = PortUsage(name="q", port_kind="physical")
        d.own(q)
        repo.registry.register_tree(d)
        loaded = from_json(to_json(repo))
        self.assertEqual(loaded.resolve("D::q").port_kind, "physical")
        self.assertEqual(to_json(loaded), to_json(from_json(to_json(loaded))))

    def test_generic_set_property_rejects_bad_kind(self):
        from engine.properties import set_property
        p = PortUsage(name="p")
        set_property(p, "port_kind", "physical", lambda r: None)
        self.assertEqual(p.port_kind, "physical")
        with self.assertRaises(ValueError):
            set_property(p, "port_kind", "bogus", lambda r: None)


class ComponentTests(unittest.TestCase):

    def test_auto_numbering_and_unique_names(self):
        repo = Repository("P")
        root = A.create_architecture(repo)
        names = [A.add_component(repo, root).name for _ in range(3)]
        self.assertEqual(names, ["Component", "Component1", "Component2"])
        with self.assertRaises(A.ArchitectureError) as cm:
            A.add_component(repo, root, "Component1")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(A.unique_name("Sensor2", {"Sensor2", "Sensor1"}), "Sensor3")

    def test_rename_rejects_duplicates_and_bad_names(self):
        repo, root, adc, fms, disp = _arch()
        with self.assertRaises(A.ArchitectureError) as cm:
            A.rename(repo, adc, "FMS")
        self.assertEqual(cm.exception.status, 409)
        for bad in ("", "a::b", "a.b"):
            with self.assertRaises(A.ArchitectureError):
                A.rename(repo, adc, bad)
        A.rename(repo, adc, "AirDataComputer")
        self.assertEqual(repo.resolve("AircraftSystem::AirDataComputer"), adc)

    def test_port_names_unique_and_default_names(self):
        repo, root, adc, *_ = _arch()
        self.assertEqual(A.add_port(repo, adc, None, "in").name, "In")
        self.assertEqual(A.add_port(repo, adc, None, "in").name, "In1")
        self.assertEqual(A.add_port(repo, adc, None, "out").name, "Out")
        with self.assertRaises(A.ArchitectureError) as cm:
            A.add_port(repo, adc, "airData", "in")
        self.assertEqual(cm.exception.status, 409)

    def test_reference_component_ports_appear_on_every_usage(self):
        repo, root, *_ = _arch()
        Sensor = repo.add(PartDefinition(name="AoASensor"))
        left = A.add_component(repo, root, "aoaLeft", definition=Sensor)
        right = A.add_component(repo, root, "aoaRight", definition=Sensor)
        p = A.add_port(repo, left, "angle", "out")
        self.assertIs(p.owner, Sensor)
        self.assertIn(p, ports_of(right))
        extra = A.add_port(repo, left, "test", "in", usage_only=True)
        self.assertIs(extra.owner, left)
        self.assertNotIn(extra, ports_of(right))

    def test_retype_reattaches_connectors_by_port_name(self):
        repo, root, adc, fms, disp = _arch()
        OldDef = repo.add(PartDefinition(name="AdcMk1"))
        NewDef = repo.add(PartDefinition(name="AdcMk2"))
        sensor = A.add_component(repo, root, "sensor", definition=OldDef)
        A.add_port(repo, sensor, "airData", "out")
        A.add_port(repo, sensor, "legacy", "out")
        new_air = A.add_port(repo, A.add_component(repo, root, "tmp", definition=NewDef), "airData", "out")
        A.add_port(repo, disp, "air", "in")
        A.add_port(repo, disp, "old", "in")
        c1 = A.connect(repo, root, _ep(sensor, "airData"), _ep(disp, "air"))
        c2 = A.connect(repo, root, _ep(sensor, "legacy"), _ep(disp, "old"))
        A.set_definition(repo, sensor, NewDef)
        self.assertIs(c1.ends[0], new_air)
        self.assertEqual(A.connector_problems(c1), [])
        self.assertEqual(A.connector_problems(c2)[0][0], "arch.connector.scope")   # shown as broken

    def test_reference_merges_same_named_ports_and_keeps_connectors(self):
        """SU-2: FCC-R (inline, connected) set to Reference = FlightControlComputer, which
        was saved from FCC-L and has ports of the same names."""
        repo = Repository("IMA")
        root = A.create_architecture(repo, "Aircraft")
        adc, iru, srv = (A.add_component(repo, root, n) for n in ("ADC", "IRU", "Servo"))
        A.add_port(repo, adc, "airData", "out")
        A.add_port(repo, iru, "inertial", "out")
        A.add_port(repo, srv, "cmdL", "in")
        A.add_port(repo, srv, "cmdR", "in")
        fccs = []
        for name, cmd in (("FCC-L", "cmdL"), ("FCC-R", "cmdR")):
            f = A.add_component(repo, root, name)
            A.add_port(repo, f, "airData", "in")
            A.add_port(repo, f, "inertial", "in")
            A.add_port(repo, f, "surfaceCmd", "out")
            A.add_port(repo, f, "maint", "inout")
            A.connect(repo, root, _ep(adc, "airData"), _ep(f, "airData"))
            A.connect(repo, root, _ep(iru, "inertial"), _ep(f, "inertial"))
            A.connect(repo, root, _ep(f, "surfaceCmd"), _ep(srv, cmd))
            fccs.append(f)
        left, right = fccs
        law = A.add_component(repo, right, "ControlLaw")     # inside FCC-R: boundary connector
        A.add_port(repo, law, "air", "in")
        inner = A.connect(repo, right, {"port": "airData"}, _ep(law, "air"))
        Fcc = A.save_as_reference(repo, left, "FlightControlComputer")
        debug = A.add_port(repo, right, "debug", "inout")       # FCC-R only: stays usage-only
        self.assertEqual([p.name for p, _ in A.merged_ports(right, Fcc)],
                         ["airData", "inertial", "surfaceCmd", "maint"])
        A.set_definition(repo, right, Fcc)
        names = sorted(p.name for p in ports_of(right))
        self.assertEqual(names, ["airData", "debug", "inertial", "maint", "surfaceCmd"])
        self.assertEqual([p for p in ports_of(right) if p.owner is right], [debug])
        # Every connector of FCC-R now ends on the definition's ports, through FCC-R.
        for conn in connectors_of(root):
            for ctx, p in connector_ends(conn):
                if ctx is right:
                    self.assertIs(p.owner, Fcc)
        self.assertEqual(len(connectors_of(root)), 6)
        self.assertEqual(connector_ends(inner, right)[0], (None, A.resolve_port(Fcc, "airData")))
        self.assertEqual(_issues(repo), [])                      # no arch.port.unique
        view = A.view(repo, root)
        fcc_r = [c for c in view["components"] if c["name"] == "FCC-R"][0]
        self.assertEqual(len(fcc_r["ports"]), 5)
        self.assertEqual(sorted(p["name"] for p in fcc_r["ports"] if not p["on_definition"]), ["debug"])
        self.assertTrue(all(not k["issues"] for k in view["connectors"]))
        # Saved and loaded unchanged.
        loaded = from_json(to_json(repo))
        self.assertEqual(_issues(loaded), [])

    def test_generic_creation_keeps_names_unique(self):
        repo, root, adc, *_ = _arch()
        dup = PartUsage(name="ADC")
        root.own(dup)
        hooks.notify_created(dup, repo)
        self.assertEqual(dup.name, "ADC1")
        p = PortUsage(name="airData")
        adc.own(p)
        hooks.notify_created(p, repo)
        self.assertEqual(p.name, "airData1")

    def test_reference_cycle_rejected(self):
        repo = Repository("P")
        root = A.create_architecture(repo, "Root")
        with self.assertRaises(A.ArchitectureError):
            A.add_component(repo, root, "self", definition=root)

    def test_badges(self):
        repo, root, adc, fms, _ = _arch()
        D = repo.add(PartDefinition(name="Gen"))
        g = A.add_component(repo, root, "gen", definition=D)
        A.add_component(repo, fms, "core")
        attach_state_machine(D, "Modes")
        self.assertEqual(A.component_badges(adc), ["inline", "leaf"])
        self.assertEqual(A.component_badges(fms), ["inline", "composite"])
        self.assertEqual(A.component_badges(g), ["ref", "leaf", "SM"])
        self.assertEqual(A.component_badges(root), [])

    def test_created_hook_runs_for_every_creation(self):
        seen = []
        hooks.register_created_hook(lambda e, r: seen.append(e.kind))
        try:
            repo, root, adc, fms, disp = _arch()
            A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        finally:
            hooks._CREATED_HOOKS.pop()
        self.assertEqual(seen.count("PartUsage"), 3)
        self.assertEqual(seen.count("PortUsage"), 4)
        self.assertEqual(seen.count("ConnectionUsage"), 1)
        self.assertEqual(seen.count("PartDefinition"), 1)


class ConnectorRuleTests(unittest.TestCase):

    def setUp(self):
        self.repo, self.root, self.adc, self.fms, self.disp = _arch()

    def connect(self, a, b, comp=None):
        return A.connect(self.repo, comp or self.root, a, b)

    def test_output_to_input_and_auto_orientation(self):
        c = self.connect(_ep(self.fms, "airData"), _ep(self.adc, "airData"))   # drawn backwards
        self.assertEqual([p.name for p in c.ends], ["airData", "airData"])
        self.assertEqual(c.end_contexts, (self.adc, self.fms))
        self.assertEqual(c.name, "Connector")

    def test_input_to_input_rejected(self):
        A.add_port(self.repo, self.adc, "cmd", "in")
        with self.assertRaises(A.ArchitectureError) as cm:
            self.connect(_ep(self.adc, "cmd"), _ep(self.fms, "airData"))
        self.assertIn("output", str(cm.exception))
        self.assertEqual(cm.exception.status, 400)

    def test_single_driver_and_fan_out(self):
        self.connect(_ep(self.adc, "airData"), _ep(self.fms, "airData"))
        A.add_port(self.repo, self.disp, "air", "in")
        self.connect(_ep(self.adc, "airData"), _ep(self.disp, "air"))           # branching
        src2 = A.add_component(self.repo, self.root, "ADC2")
        A.add_port(self.repo, src2, "airData", "out")
        with self.assertRaises(A.ArchitectureError) as cm:
            self.connect(_ep(src2, "airData"), _ep(self.fms, "airData"))
        self.assertEqual(cm.exception.status, 409)
        self.assertIn("one source", str(cm.exception))
        with self.assertRaises(A.ArchitectureError) as cm:
            self.connect(_ep(self.adc, "airData"), _ep(self.disp, "air"))
        self.assertIn("already connected", str(cm.exception))

    def test_self_loop_and_scope(self):
        with self.assertRaises(A.ArchitectureError) as cm:
            self.connect(_ep(self.adc, "airData"), _ep(self.adc, "airData"))
        self.assertIn("itself", str(cm.exception))
        other = A.create_architecture(self.repo, "Other")
        stranger = A.add_component(self.repo, other, "X")
        A.add_port(self.repo, stranger, "o", "out")
        with self.assertRaises(A.ArchitectureError):
            self.connect(_ep(stranger, "o"), _ep(self.fms, "airData"))
        with self.assertRaises(A.ArchitectureError) as cm:
            self.connect(_ep(self.adc, "nope"), _ep(self.fms, "airData"))
        self.assertEqual(cm.exception.status, 404)

    def test_boundary_ports_seen_from_inside(self):
        b_in = A.add_port(self.repo, self.root, "pitotIn", "in")
        b_out = A.add_port(self.repo, self.root, "routeOut", "out")
        A.add_port(self.repo, self.adc, "pitot", "in")
        self.connect({"port": b_in}, _ep(self.adc, "pitot"))                  # boundary in feeds inside
        c = self.connect(_ep(self.fms, "route"), {"port": "routeOut"})
        self.assertEqual(c.end_contexts, (self.fms, None))
        with self.assertRaises(A.ArchitectureError):
            self.connect({"port": b_out}, _ep(self.disp, "route"))            # boundary out is a sink inside

    def test_inout_both_ways_and_physical(self):
        a = A.add_port(self.repo, self.adc, "bus", "inout")
        b = A.add_port(self.repo, self.fms, "bus", "inout")
        self.connect(_ep(self.fms, b), _ep(self.adc, a))
        pa = A.add_port(self.repo, self.adc, "pwr", kind="physical")
        pf = A.add_port(self.repo, self.fms, "pwr", kind="physical")
        c = self.connect(_ep(self.adc, pa), _ep(self.fms, pf))
        self.assertEqual(A.connector_kind(self.root, c), "physical")
        with self.assertRaises(A.ArchitectureError) as cm:
            self.connect(_ep(self.adc, pa), _ep(self.disp, "route"))
        self.assertIn("physical", str(cm.exception))

    def test_client_server(self):
        A.set_model_type(self.repo, "software")
        cl = A.add_port(self.repo, self.disp, "nav", kind="client")
        sv = A.add_port(self.repo, self.fms, "nav", kind="server")
        c = self.connect(_ep(self.fms, sv), _ep(self.disp, cl))
        self.assertIs(c.ends[0], cl)                                          # client first
        cl2 = A.add_port(self.repo, self.adc, "nav", kind="client")
        with self.assertRaises(A.ArchitectureError):
            self.connect(_ep(self.adc, cl2), _ep(self.disp, cl))
        with self.assertRaises(A.ArchitectureError):
            self.connect(_ep(self.adc, cl2), _ep(self.disp, "route"))

    def test_contexts_distinguish_usages_of_one_definition(self):
        Sensor = self.repo.add(PartDefinition(name="Sensor"))
        s1 = A.add_component(self.repo, self.root, "s1", definition=Sensor)
        s2 = A.add_component(self.repo, self.root, "s2", definition=Sensor)
        A.add_port(self.repo, s1, "val", "out")
        A.add_port(self.repo, self.disp, "v1", "in")
        A.add_port(self.repo, self.disp, "v2", "in")
        c1 = self.connect(_ep(s1, "val"), _ep(self.disp, "v1"))
        c2 = self.connect(_ep(s2, "val"), _ep(self.disp, "v2"))
        self.assertIs(c1.ends[0], c2.ends[0])
        self.assertEqual((c1.end_contexts[0], c2.end_contexts[0]), (s1, s2))
        loaded = from_json(to_json(self.repo))
        lc2 = loaded.by_id(c2.element_id)
        self.assertEqual(lc2.end_contexts[0].name, "s2")
        # deleting one usage removes only its connector
        self.repo.remove(s1)
        self.assertIsNone(self.repo.by_id(c1.element_id))
        self.assertIs(self.repo.by_id(c2.element_id), c2)

    def test_cross_hierarchy_creates_boundary_ports(self):
        sub = A.add_component(self.repo, self.fms, "Guidance")
        A.add_port(self.repo, sub, "air", "in")
        c = self.connect(_ep(self.adc, "airData"), _ep(sub, "air"))
        self.assertEqual(c.end_contexts[1], self.fms)
        bp = c.ends[1]
        self.assertIs(bp.owner, self.fms)
        self.assertEqual(bp.direction, FeatureDirection.IN)
        inner = [x for x in connectors_of(self.fms)
                 if any(p is bp for p in x.ends)]
        self.assertEqual(len(inner), 1)
        self.assertEqual(_issues(self.repo, "arch.connector"), [])

    def test_cross_hierarchy_failure_rolls_back(self):
        sub = A.add_component(self.repo, self.fms, "Guidance")
        A.add_port(self.repo, sub, "cmd", "in")
        A.add_port(self.repo, self.adc, "cmd", "in")
        before = len(ports_of(self.fms))
        with self.assertRaises(A.ArchitectureError):
            self.connect(_ep(self.adc, "cmd"), _ep(sub, "cmd"))               # in -> in is invalid
        self.assertEqual(len(ports_of(self.fms)), before)

    def test_can_connect_is_side_effect_free(self):
        ok = A.can_connect(self.root, (self.fms, ports_of(self.fms)[0]), (self.adc, ports_of(self.adc)[0]))
        self.assertTrue(ok["ok"])
        self.assertTrue(ok["swapped"])
        self.assertEqual(connectors_of(self.root), [])

    def test_validator_reports_bad_stored_connectors(self):
        self.connect(_ep(self.adc, "airData"), _ep(self.fms, "airData"))
        self.assertEqual(_issues(self.repo), [])
        f_in = ports_of(self.fms)[0]
        a_out, d_out = ports_of(self.adc)[0], A.add_port(self.repo, self.disp, "o", "out")
        second = ConnectionUsage(name="second", ends=[d_out, f_in], end_contexts=(self.disp, self.fms))
        rev = ConnectionUsage(name="rev", ends=[f_in, a_out], end_contexts=(self.fms, self.adc))
        loop = ConnectionUsage(name="loop", ends=[a_out, a_out], end_contexts=(self.adc, self.adc))
        for c in (second, rev, loop):
            self.root.own(c)
        self.repo.registry.register_tree(self.root)
        rules = sorted(r for r, _ in _issues(self.repo))
        self.assertEqual(rules, ["arch.connector.direction", "arch.connector.self",
                                 "arch.port.multiple-drivers"])

    def test_update_port_guards_connectors(self):
        self.connect(_ep(self.adc, "airData"), _ep(self.fms, "airData"))
        out_port = ports_of(self.adc)[0]
        with self.assertRaises(A.ArchitectureError) as cm:
            A.update_port(self.repo, out_port, direction="in", name="renamed")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual((out_port.name, out_port.direction), ("airData", FeatureDirection.OUT))
        A.update_port(self.repo, out_port, direction="in", force=True)
        self.assertIn("arch.connector.direction", [r for r, _ in _issues(self.repo)])
        Air = self.repo.add(PortDefinition(name="AirData"))
        A.update_port(self.repo, out_port, interface=Air, direction="out")
        self.assertEqual(out_port.types, [Air])


class EditingOperationTests(unittest.TestCase):

    def test_duplicate_deep_copies_internals(self):
        repo, root, adc, fms, disp = _arch()
        st = Stereotype(name="LRU")
        st.define_tag("dal", default="C")
        repo.add(st)
        st.apply(fms, {"dal": "A"})
        fms.tool_data["layout"] = {"x": 100, "y": 50, "w": 160, "h": 90}
        core = A.add_component(repo, fms, "core")
        A.add_port(repo, core, "air", "in")
        A.connect(repo, fms, {"port": "airData"}, _ep(core, "air"))
        A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        A.connect(repo, root, _ep(fms, "route"), _ep(disp, "route"))
        copies = A.duplicate(repo, [fms, disp])
        f2, d2 = copies
        self.assertEqual((f2.name, d2.name), ("FMS1", "Display1"))
        self.assertEqual(f2.tool_data["layout"]["x"], 130)
        self.assertEqual([a.values["dal"] for a in stereotypes_on(f2)], ["A"])
        core2 = components_of(f2)[0]
        self.assertIsNot(core2, core)
        inner = connectors_of(f2)[0]
        self.assertEqual(connector_ends(inner, f2)[1], (core2, ports_of(core2)[0]))
        # the connector between the two copied components is copied; the one from ADC is not
        copied = [c for c in connectors_of(root) if c.end_contexts and c.end_contexts[0] is f2]
        self.assertEqual(len(copied), 1)
        self.assertIs(copied[0].end_contexts[1], d2)
        self.assertEqual(_issues(repo), [])
        from_json(to_json(repo))

    def test_paste_into_another_composition(self):
        repo, root, adc, fms, disp = _arch()
        A.connect(repo, root, _ep(fms, "route"), _ep(disp, "route"))
        # Copy FMS + Display and paste them inside ADC: the connector between them comes along.
        f2, d2 = A.duplicate(repo, [fms, disp], target=adc)
        self.assertEqual((f2.owner, d2.owner), (adc, adc))
        self.assertEqual((f2.name, d2.name), ("FMS", "Display"))     # free names in ADC
        inner = connectors_of(adc)
        self.assertEqual(len(inner), 1)
        self.assertEqual(connector_ends(inner[0], adc), [(f2, ports_of(f2)[1]), (d2, ports_of(d2)[0])])
        self.assertEqual(len(connectors_of(root)), 1)                  # the original is untouched
        # Pasting into a reference component lands in its shared definition.
        Lru = A.save_as_reference(repo, adc, "Lru")
        spare = A.add_component(repo, root, "Spare", Lru)
        (f3,) = A.duplicate(repo, [fms], target=spare)
        self.assertIs(f3.owner, Lru)
        self.assertEqual(f3.name, "FMS1")
        self.assertEqual(len(components_of(adc)), 3)                   # every usage shows it
        # A copy may not contain a reference to the definition it is pasted into.
        with self.assertRaises(A.ArchitectureError):
            A.duplicate(repo, [spare], target=spare)
        self.assertEqual(_issues(repo), [])

    def test_group_and_expand(self):
        repo, root, adc, fms, disp = _arch()
        A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        A.connect(repo, root, _ep(fms, "route"), _ep(disp, "route"))
        A.add_port(repo, disp, "air", "in")
        A.connect(repo, root, _ep(adc, "airData"), _ep(disp, "air"))
        g = A.group(repo, root, [fms, disp], "NavDisplay")
        self.assertEqual(components_of(root), [adc, g])
        self.assertEqual(components_of(g), [fms, disp])
        gports = ports_of(g)
        self.assertEqual(len(gports), 1)                    # one input reused by both inner targets
        self.assertEqual(gports[0].direction, FeatureDirection.IN)
        outer = connectors_of(root)
        self.assertEqual(len(outer), 1)
        self.assertEqual(connector_ends(outer[0], root)[1], (g, gports[0]))
        self.assertEqual(len(connectors_of(g)), 3)
        self.assertEqual(_issues(repo), [])
        moved = A.expand(repo, g)
        self.assertEqual(sorted(c.name for c in moved), ["Display", "FMS"])
        self.assertIsNone(repo.by_id(g.element_id))
        pairs = sorted((connector_ends(c, root)[0][1].name + ">" + connector_ends(c, root)[1][0].name)
                       for c in connectors_of(root))
        self.assertEqual(pairs, ["airData>Display", "airData>FMS", "route>Display"])
        self.assertEqual(_issues(repo), [])

    def test_group_rejects_foreign_components(self):
        repo, root, adc, fms, disp = _arch()
        inner = A.add_component(repo, fms, "inner")
        with self.assertRaises(A.ArchitectureError):
            A.group(repo, root, [inner])
        with self.assertRaises(A.ArchitectureError):
            A.group(repo, root, [])

    def test_save_as_reference_and_inline(self):
        repo, root, adc, fms, disp = _arch()
        core = A.add_component(repo, fms, "core")
        A.add_port(repo, core, "air", "in")
        A.connect(repo, fms, {"port": "airData"}, _ep(core, "air"))
        c_out = A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        D = A.save_as_reference(repo, fms)
        self.assertEqual(D.name, "FMS")
        self.assertIs(D.owner, repo.root_package)
        self.assertIs(definition_of(fms), D)
        self.assertEqual([x for x in fms.owned_elements if not isinstance(x, ConnectionUsage)], [])
        self.assertIn(c_out.ends[1], ports_of(D))
        self.assertEqual(_issues(repo), [])
        with self.assertRaises(A.ArchitectureError):
            A.save_as_reference(repo, fms)
        # a second usage shares the definition; inlining one leaves the other referencing it
        other = A.add_component(repo, root, "FMS2", definition=D)
        A.inline_component(repo, fms)
        self.assertEqual(A.component_badges(fms)[0], "inline")
        self.assertEqual(A.component_badges(other)[0], "ref")
        self.assertIsNot(c_out.ends[1], ports_of(D)[0])
        self.assertIs(c_out.ends[1].owner, fms)
        self.assertEqual(len(connectors_of(fms)), 1)
        self.assertEqual(_issues(repo), [])
        loaded = from_json(to_json(repo))
        self.assertEqual(len(loaded.by_kind("ConnectionUsage")), 3)

    def test_delete_elements(self):
        repo, root, adc, fms, disp = _arch()
        c = A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        deleted = A.delete_elements(repo, [adc, c])
        self.assertEqual(deleted, [adc.element_id])          # connector went with the component
        self.assertEqual(connectors_of(root), [])
        with self.assertRaises(A.ArchitectureError):
            A.delete_elements(repo, [repo.root_package])


class LayoutAndViewTests(unittest.TestCase):

    def test_auto_layout_layers_follow_connectors(self):
        repo, root, adc, fms, disp = _arch()
        A.connect(repo, root, _ep(fms, "route"), _ep(disp, "route"))
        A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        pos = A.auto_layout(repo, root)
        xs = [pos[c.element_id]["x"] for c in (adc, fms, disp)]
        self.assertEqual(xs, sorted(xs))
        self.assertLess(xs[0], xs[1])
        # positions are stored; sizes stay automatic unless the user resized the block
        self.assertEqual(fms.tool_data["layout"], {k: pos[fms.element_id][k] for k in ("x", "y")})
        self.assertEqual(A.effective_box(fms, root), pos[fms.element_id])
        A.apply_layout(repo, [{"id": disp.element_id, "x": 0, "y": 0, "w": 300, "h": 200}])
        pos = A.auto_layout(repo, root)
        self.assertEqual((pos[disp.element_id]["w"], disp.tool_data["layout"]["w"]), (300, 300))
        sides = {p.name: p.tool_data["port_layout"]["side"] for p in ports_of(fms)}
        self.assertEqual(sides, {"airData": "left", "route": "right"})

    def test_auto_layout_survives_cycles(self):
        repo, root, adc, fms, disp = _arch()
        A.add_port(repo, adc, "fb", "in")
        A.add_port(repo, disp, "fb", "out")
        A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        A.connect(repo, root, _ep(fms, "route"), _ep(disp, "route"))
        A.connect(repo, root, _ep(disp, "fb"), _ep(adc, "fb"))
        pos = A.auto_layout(repo, root)
        self.assertEqual(len({p["x"] for p in pos.values()}), 3)

    def test_auto_layout_honours_the_canvas_size(self):
        repo, root = _avionics_network(30)
        wide = A.auto_layout(repo, root, {"w": 1800, "h": 500})
        tall = A.auto_layout(repo, root, {"w": 700, "h": 1100})
        aspect = [_frame(p)[0] / _frame(p)[1] for p in (wide, tall)]
        self.assertGreater(aspect[0], aspect[1])          # the layout follows the window's shape
        with self.assertRaises(A.ArchitectureError):
            A.auto_layout(repo, root, {"w": "wide", "h": 3})
        self.assertEqual(A.auto_layout(repo, root, {"w": 0, "h": 0}), A.auto_layout(repo, root))

    def test_apply_layout_validates_atomically(self):
        repo, root, adc, fms, disp = _arch()
        p = ports_of(adc)[0]
        with self.assertRaises(A.ArchitectureError):
            A.apply_layout(repo, [{"id": adc.element_id, "x": 1, "y": 2},
                                  {"id": p.element_id, "side": "middle", "offset": 0.5}])
        self.assertNotIn("layout", adc.tool_data)
        n = A.apply_layout(repo, [{"id": adc.element_id, "x": 10, "y": 20, "w": 200, "h": 100},
                                  {"id": p.element_id, "side": "top", "offset": 0.25}])
        self.assertEqual(n, 2)
        loaded = from_json(to_json(repo))
        self.assertEqual(loaded.by_id(adc.element_id).tool_data["layout"],
                         {"x": 10, "y": 20, "w": 200, "h": 100})
        self.assertEqual(loaded.by_id(p.element_id).tool_data["port_layout"], {"side": "top", "offset": 0.25})

    def test_view_model(self):
        repo, root, adc, fms, disp = _arch()
        A.add_port(repo, root, "pitot", "in")
        c = A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        Sensor = repo.add(PartDefinition(name="Sensor"))
        s = A.add_component(repo, root, "aoa", definition=Sensor)
        v = A.view(repo, root)
        self.assertEqual(v["composition"]["breadcrumbs"], [{"id": root.element_id, "name": "AircraftSystem",
                                                           "kind": "PartDefinition"}])
        self.assertEqual([b["name"] for b in v["boundary_ports"]], ["pitot"])
        self.assertEqual(v["boundary_ports"][0]["side"], "left")
        comps = {x["name"]: x for x in v["components"]}
        self.assertEqual(set(comps), {"ADC", "FMS", "Display", "aoa"})
        self.assertEqual(comps["aoa"]["definition"]["name"], "Sensor")
        self.assertEqual(comps["ADC"]["ports"][0]["side"], "right")
        self.assertEqual(comps["FMS"]["badges"], ["inline", "leaf"])
        boxes = [tuple(x["layout"].values()) for x in v["components"]]
        self.assertEqual(len(set(boxes)), 4)                                   # deterministic grid
        self.assertEqual(A.view(repo, root)["components"][0]["layout"], v["components"][0]["layout"])
        conn = v["connectors"][0]
        self.assertEqual(conn["source"], {"component_id": adc.element_id,
                                          "port_id": ports_of(adc)[0].element_id})
        self.assertEqual((conn["kind"], conn["issues"], conn["label"]), ("data", [], ""))
        self.assertEqual(conn["id"], c.element_id)
        Air = repo.add(PortDefinition(name="AirData"))
        A.update_port(repo, ports_of(adc)[0], interface=Air)
        self.assertEqual(A.view(repo, root)["connectors"][0]["label"], "AirData")
        A.rename(repo, c, "airBus")                                            # a user-given name
        self.assertEqual(A.view(repo, root)["connectors"][0]["label"], "airBus : AirData")
        self.assertIn('|"airBus : AirData"|', ibd_mermaid(root))
        self.assertIn('label="airBus : AirData"', ibd(root))
        A.update_port(repo, ports_of(adc)[0], interface=None)
        self.assertEqual(A.connector_label(c), "airBus")
        A.rename(repo, c, "Connector7")                                        # auto-style names are not drawn
        self.assertEqual(A.connector_label(c), "")
        self.assertNotIn("Connector7", ibd_mermaid(root))
        self.assertFalse(comps["aoa"]["from_definition"])
        inner = A.add_component(repo, s, "core")
        self.assertTrue(A.view(repo, s)["components"][0]["from_definition"])
        self.assertIs(inner.owner, Sensor)

    def test_breadcrumbs_and_drill_path(self):
        repo, root, adc, fms, disp = _arch()
        Sensor = repo.add(PartDefinition(name="Sensor"))
        s = A.add_component(repo, root, "aoa", definition=Sensor)
        inner = A.add_component(repo, s, "adcCore")
        self.assertIs(inner.owner, Sensor)                    # reference internals live on the definition
        crumbs = A.view(repo, inner, path=[root, s, inner])["composition"]["breadcrumbs"]
        self.assertEqual([c["name"] for c in crumbs], ["AircraftSystem", "aoa", "adcCore"])
        crumbs = A.view(repo, inner)["composition"]["breadcrumbs"]
        self.assertEqual([c["name"] for c in crumbs], ["Sensor", "adcCore"])
        v = A.view(repo, s)
        self.assertTrue(v["composition"]["is_reference"])
        self.assertEqual(v["composition"]["edit_owner_id"], Sensor.element_id)

    def test_model_tree_and_roots(self):
        repo, root, adc, fms, disp = _arch()
        Sensor = repo.add(PartDefinition(name="Sensor"))
        A.add_component(repo, Sensor, "core")
        A.add_component(repo, root, "aoa", definition=Sensor)
        tree = A.model_tree(root)
        aoa = [c for c in tree["children"] if c["name"] == "aoa"][0]
        self.assertEqual(aoa["children"][0]["name"], "core")
        self.assertEqual(aoa["children"][0]["path"][0], root.element_id)
        self.assertEqual([r.name for r in A.architecture_roots(repo)], ["AircraftSystem"])


class ArrangeScaleTests(unittest.TestCase):
    """PO-1 / SU-12b: Arrange on realistic, cyclic avionics networks stays compact and readable."""

    def assert_readable(self, positions, n, min_zoom=0.40):
        cap = math.ceil(math.sqrt(n)) + 2
        columns = {b["x"] + b["w"] / 2 for b in positions.values()}
        self.assertLessEqual(len(columns), cap, "at most ceil(sqrt(n)) + 2 layers side by side")
        w, h = _frame(positions)
        self.assertTrue(1 / 3 <= w / h <= 3, f"aspect ratio {w}x{h}")
        self.assertEqual(_overlaps(positions), [])
        # Fit zoom in the canvas of a 1400 x 900 window (Property Inspector open).
        self.assertGreaterEqual(A.fit_zoom(w, h), min_zoom)

    def test_thirty_lrus_with_ninety_cyclic_connectors(self):
        repo, root = _avionics_network(30)
        self.assertEqual(len(connectors_of(root)), 90)
        t = time.perf_counter()
        pos = A.auto_layout(repo, root)
        self.assertLess(time.perf_counter() - t, 1.0)
        self.assertEqual(len(pos), 30)
        self.assert_readable(pos, 30)
        # Deterministic: again on the same model, and on an identical model built afresh.
        self.assertEqual(A.auto_layout(repo, root), pos)
        repo2, root2 = _avionics_network(30)
        names = {c.element_id: c.name for c in components_of(root)}
        names2 = {c.element_id: c.name for c in components_of(root2)}
        again = {names2[k]: v for k, v in A.auto_layout(repo2, root2).items()}
        self.assertEqual(again, {names[k]: v for k, v in pos.items()})

    def test_forty_eight_lrus_and_unconnected_blocks_wrap(self):
        # 48 LRUs with ~190 ports need about 35% to fit (it was a 15% strip before).
        repo, root = _avionics_network(48)
        self.assert_readable(A.auto_layout(repo, root), 48, min_zoom=0.32)
        repo = Repository("P")
        root = A.create_architecture(repo, "R")
        for i in range(48):
            A.add_component(repo, root, f"C{i}")
        self.assert_readable(A.auto_layout(repo, root), 48)

    def test_small_chains_keep_the_signal_flow_left_to_right(self):
        repo, root, adc, fms, disp = _arch()
        A.connect(repo, root, _ep(adc, "airData"), _ep(fms, "airData"))
        A.connect(repo, root, _ep(fms, "route"), _ep(disp, "route"))
        pos = A.auto_layout(repo, root)
        self.assertEqual(len({pos[c.element_id]["y"] for c in (adc, fms, disp)}), 1)    # one row
        xs = [pos[c.element_id]["x"] for c in (adc, fms, disp)]
        self.assertEqual(xs, sorted(xs))

    def test_cycles_do_not_make_a_layer_per_block(self):
        repo = Repository("P")
        root = A.create_architecture(repo, "Ring")
        ring = []
        for i in range(12):
            c = A.add_component(repo, root, f"N{i}")
            A.add_port(repo, c, "i", "in")
            A.add_port(repo, c, "o", "out")
            ring.append(c)
        for a, b in zip(ring, ring[1:] + ring[:1]):
            A.connect(repo, root, _ep(a, "o"), _ep(b, "i"))
        self.assert_readable(A.auto_layout(repo, root), 12)


class UndoHistoryTests(unittest.TestCase):

    class _Session:
        def __init__(self, repo):
            self.repo, self.plugin_state = repo, {}

        def set_repo(self, repo):
            self.repo = repo
            self.plugin_state.clear()

    def test_undo_redo_round_trip_keeps_ids(self):
        repo, root, *_ = _arch()
        s = self._Session(repo)
        with tracked(s, "add"):
            c = A.add_component(repo, root, "New")
        self.assertTrue(undo(s))
        self.assertIsNone(s.repo.by_id(c.element_id))
        self.assertTrue(redo(s))
        self.assertEqual(s.repo.by_id(c.element_id).name, "New")
        self.assertEqual(history_for(s).state()["undo_depth"], 1)

    def test_no_step_for_unchanged_model_and_cap(self):
        repo, root, *_ = _arch()
        s = self._Session(repo)
        with tracked(s, "noop"):
            pass
        self.assertFalse(history_for(s).state()["can_undo"])
        h = UndoHistory(limit=3)
        for i in range(5):
            before = h.begin(s.repo)
            A.add_component(s.repo, s.repo.resolve("AircraftSystem"))
            h.commit(s.repo, before, f"step{i}")
        self.assertEqual(h.state()["undo_depth"], 3)

    def test_dirty_until_saved(self):
        """SU-13: New / Load warn about changes made since the last save."""
        repo, root, *_ = _arch()
        s = self._Session(repo)
        self.assertFalse(history_for(s).state()["dirty"])           # a new or loaded project
        with tracked(s, "noop"):
            pass
        self.assertFalse(history_for(s).state()["dirty"])           # nothing changed
        with tracked(s, "add"):
            A.add_component(repo, root, "New")
        self.assertTrue(history_for(s).state()["dirty"])
        history_for(s).mark_saved(s.repo)
        self.assertFalse(history_for(s).state()["dirty"])
        self.assertTrue(undo(s))                                    # differs from the saved file
        self.assertTrue(history_for(s).state()["dirty"])
        history_for(s).mark_saved(s.repo)
        A.add_component(s.repo, s.repo.resolve("AircraftSystem"), "Untracked")
        history_for(s).mark_saved(s.repo)                           # catches the change up first
        self.assertFalse(history_for(s).state()["dirty"])
        self.assertTrue(undo(s))
        self.assertIsNone(s.repo.resolve("AircraftSystem::Untracked"))

    def test_untracked_change_becomes_its_own_step(self):
        repo, root, *_ = _arch()
        s = self._Session(repo)
        with tracked(s, "a"):
            A.add_component(repo, root, "A1")
        A.add_component(repo, root, "Untracked")              # e.g. a tool without tracking
        self.assertTrue(undo(s))
        names = [c.name for c in components_of(s.repo.resolve("AircraftSystem"))]
        self.assertIn("A1", names)
        self.assertNotIn("Untracked", names)
        self.assertTrue(undo(s))
        self.assertNotIn("A1", [c.name for c in components_of(s.repo.resolve("AircraftSystem"))])
        self.assertFalse(undo(s))


class ParserAndDiagramTests(unittest.TestCase):

    SRC = """
    package Avionics {
        part def AircraftSystem {
            in port pitot : AirData;
            out port status;
            part adc : ADC;
            part fms : FMS;
            part dau { in port raw; out port cooked : AirData; }
            connect pitot to adc.pitot;
            connect adc.airData to fms.air;
            connect dau.cooked to fms.aux;
            connect fms.st to status;
        }
        part def ADC { in port pitot : AirData; out port airData : AirData; }
        part def FMS { in port air : AirData; in port aux : AirData; out port st; }
        port def AirData;
    }
    """

    def _parsed(self):
        repo = Repository("P")
        parse(self.SRC, into=repo.root_package, repo=repo)
        return repo, repo.resolve("Avionics::AircraftSystem")

    def test_directions_forward_refs_and_connect_inside_def(self):
        repo, sysdef = self._parsed()
        pitot = repo.resolve("Avionics::AircraftSystem::pitot")
        self.assertEqual(pitot.direction, FeatureDirection.IN)
        self.assertEqual(pitot.types[0].name, "AirData")                  # declared later
        self.assertEqual(repo.resolve("Avionics::AircraftSystem::adc").types[0].name, "ADC")
        dau = repo.resolve("Avionics::AircraftSystem::dau")
        self.assertEqual([p.name for p in ports_of(dau)], ["raw", "cooked"])
        conns = connectors_of(sysdef)
        self.assertEqual(len(conns), 4)
        ends = [[(c.name if c else None, p.name) for c, p in connector_ends(x)] for x in conns]
        self.assertIn([(None, "pitot"), ("adc", "pitot")], ends)
        self.assertIn([("adc", "airData"), ("fms", "air")], ends)
        self.assertEqual(_issues(repo), [])

    def test_parse_notifies_created_hooks(self):
        seen = []
        hooks.register_created_hook(lambda e, r: seen.append(e.name))
        try:
            self._parsed()
        finally:
            hooks._CREATED_HOOKS.pop()
        self.assertIn("AircraftSystem", seen)
        self.assertIn("cooked", seen)

    def test_direction_keywords_usable_as_names(self):
        repo = Repository("P")
        parse("part def A { in port in; out port out; } part def S { part a : A; part b : A; "
              "connect a.out to b.in; }", into=repo.root_package, repo=repo)
        c = connectors_of(repo.resolve("S"))[0]
        self.assertEqual([p.name for p in c.ends], ["out", "in"])

    def _node_ids(self, text):
        return set(re.findall(r"^\s+(n[0-9a-f_n]+(?:_anchor)?)\s*[\[(>]", text, re.M))

    def test_ibd_edges_connect_drawn_port_nodes(self):
        repo, sysdef = self._parsed()
        dot = ibd(sysdef)
        nodes = set(re.findall(r"^\s+(n[\w]+) \[", dot, re.M))
        edges = re.findall(r"^\s+(n\w+) -> (n\w+) ", dot, re.M)
        self.assertEqual(len(edges), 4)
        for a, b in edges:
            self.assertIn(a, nodes)
            self.assertIn(b, nodes)
        mer = ibd_mermaid(sysdef)
        mnodes = set(re.findall(r"^\s+(n\w+?)(?:\(\(|>|\(\[|\[)", mer, re.M))
        medges = re.findall(r"^\s+(n\w+) --[->]\S* (n\w+)$", mer, re.M)
        self.assertEqual(len(medges), 4)
        for a, b in medges:
            self.assertIn(a, mnodes)
            self.assertIn(b, mnodes)
        self.assertIn('>"▸ pitot"]', mer)                                    # boundary port on the frame


if __name__ == "__main__":
    unittest.main()
