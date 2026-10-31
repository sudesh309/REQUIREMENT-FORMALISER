"""Projects saved by the engine before Phase 1 (``sysmlv2-core/1``) still load and round-trip.

The fixtures in ``tests/data/v1`` were written by the pre-Phase-1 engine (commit 83d812e):
the avionics example and a small model with the core constructs it saved.
"""
import json
import unittest
from pathlib import Path

from engine.interop.checks import run_model_check
from engine.serializer import from_json, to_json
from engine.structure import component_tree, connector_ends
from sysmlv2 import ConnectionUsage, PartDefinition, RequirementDefinition, TransitionUsage
from sysmlv2.state_machines import StateMachineDefinition

DATA = Path(__file__).parent / "data" / "v1"


def _load(name: str):
    text = (DATA / name).read_text(encoding="utf-8")
    assert json.loads(text)["format"] == "sysmlv2-core/1"
    return from_json(text)


class AvionicsExampleV1Tests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo = _load("v1_avionics_example.json")

    def test_loads_with_its_structure(self):
        arch = self.repo.resolve("PhysicalArchitecture")
        self.assertIsInstance(arch, PartDefinition)
        self.assertGreater(len(list(component_tree(arch))), 10)
        conns = [e for e in self.repo.root_package.walk() if isinstance(e, ConnectionUsage)]
        self.assertGreater(len(conns), 50)
        for c in conns:
            self.assertEqual(len(c.ends), 2, c.qualified_name)
            self.assertEqual(len(connector_ends(c)), 2)
        self.assertTrue(any(c.end_contexts for c in conns))
        sms = [e for e in self.repo.root_package.walk() if isinstance(e, StateMachineDefinition)]
        self.assertTrue(sms and sms[0].initial_state is not None)
        self.assertTrue(any(t.trigger_event for t in self.repo.root_package.walk()
                            if isinstance(t, TransitionUsage)))

    def test_model_check_and_round_trip(self):
        issues = run_model_check(self.repo)
        text = to_json(self.repo)
        again = from_json(text)
        self.assertEqual(to_json(again), text)
        self.assertEqual(json.dumps(run_model_check(again), sort_keys=True, default=str),
                         json.dumps(issues, sort_keys=True, default=str))


class CoreModelV1Tests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo = _load("v1_core_model.json")

    def test_core_constructs(self):
        r = self.repo
        sensor = r.resolve("Structure::Sensor")
        self.assertTrue(sensor.conforms_to(r.resolve("Structure::Base")))
        mass = next(f for f in sensor.owned_features if f.name == "mass")
        self.assertEqual(mass.default_value, 2.5)
        self.assertEqual([x.redefined_feature.name for x in mass.owned_redefinitions], ["mass"])
        self.assertEqual(sensor.inherited_features, [])          # Base::mass is redefined
        out = r.resolve("Structure::Sensor::out")
        self.assertEqual(out.direction.value, "out")
        req = r.resolve("Requirements::Accuracy")
        self.assertIsInstance(req, RequirementDefinition)
        self.assertEqual((req.req_id, req.text), ("SRS-001", "Error below 1 %."))
        self.assertEqual([a.body for a in req.annotations], ["From the customer specification."])
        sm = r.resolve("Structure::Sensor::Modes")
        on = sm.resolve("On")
        self.assertEqual((on.entry_action, on.do_action, on.exit_action),
                         ("selfTest()", "measure()", "flush()"))
        t = next(t for t in sm.transitions if t.trigger_event == "powerOff")
        self.assertEqual(t.guard, "load < 10")
        self.assertEqual([s.name for s in sm.final_states], ["Failed"])
        system = r.resolve("System")
        conns = [c for c in system.children if isinstance(c, ConnectionUsage)]
        self.assertEqual([[x.name for x in c.end_contexts] for c in conns], [["s1", "cpu"], ["s2", "cpu"]])
        cpu = r.resolve("System::cpu")
        self.assertEqual(cpu.tool_data["note"], {"color": "#ffcc00"})
        self.assertIn("layout", cpu.tool_data)

    def test_round_trip(self):
        text = to_json(self.repo)
        self.assertEqual(to_json(from_json(text)), text)


if __name__ == "__main__":
    unittest.main()
