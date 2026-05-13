import unittest

from engine import state_machine as sm_dot
from sysmlv2 import PartDefinition
from sysmlv2.state_machines import (
    StateMachineDefinition, attach_state_machine, state_machines_of,
)


class StateMachineBuildTests(unittest.TestCase):

    def test_attach_and_query(self):
        v = PartDefinition(name="Vehicle")
        sm = v.attach_state_machine("VehicleSM")
        self.assertIsInstance(sm, StateMachineDefinition)
        self.assertIn(sm, state_machines_of(v))
        self.assertEqual([s.name for s in v.state_machines], ["VehicleSM"])

    def test_states_and_transitions(self):
        sm = PartDefinition(name="V").attach_state_machine("SM")
        a = sm.add_state("A", entry="onA()", is_initial=True)
        b = sm.add_state("B")
        c = sm.add_state("Done", is_final=True)
        sm.add_transition(a, b, trigger="go")
        sm.add_transition(b, c, trigger="end")
        self.assertEqual([s.name for s in sm.states], ["A", "B", "Done"])
        self.assertEqual(len(sm.transitions), 2)
        self.assertIs(sm.initial_state, a)
        self.assertIn(c, sm.final_states)


class StateMachineRunnerTests(unittest.TestCase):

    def _three_state(self):
        sm = PartDefinition(name="V").attach_state_machine("SM")
        parked  = sm.add_state("Parked",  entry="lock", is_initial=True)
        driving = sm.add_state("Driving", entry="unlock", do="monitor",
                               exit="brake")
        off     = sm.add_state("Off", is_final=True)
        sm.add_transition(parked,  driving, trigger="start", effect="releaseBrake")
        sm.add_transition(driving, parked,  trigger="park",
                          guard=lambda ctx: ctx.get("speed", 0) == 0)
        sm.add_transition(parked,  off,     trigger="shutdown")
        return sm, parked, driving, off

    def test_happy_path(self):
        sm, parked, driving, off = self._three_state()
        r = sm.runner()
        self.assertIs(r.current, parked)
        self.assertIs(r.fire("start"), driving)
        self.assertIs(r.fire("park", speed=0), parked)
        self.assertIs(r.fire("shutdown"), off)
        self.assertTrue(r.is_in_final())

    def test_guard_blocks_transition(self):
        sm, parked, driving, _ = self._three_state()
        r = sm.runner()
        r.fire("start")
        # guard says only park when speed==0
        self.assertIsNone(r.fire("park", speed=10))
        self.assertIs(r.current, driving)
        self.assertIs(r.fire("park", speed=0), parked)

    def test_unknown_event_records_trace(self):
        sm, *_ = self._three_state()
        r = sm.runner()
        self.assertIsNone(r.fire("nope"))
        self.assertIn("unhandled:nope", r.trace())

    def test_string_guard_evaluated(self):
        sm = PartDefinition(name="V").attach_state_machine("SM")
        a = sm.add_state("A", is_initial=True)
        b = sm.add_state("B")
        sm.add_transition(a, b, trigger="go", guard="ok == True")
        r = sm.runner()
        self.assertIsNone(r.fire("go", ok=False))
        self.assertIs(r.fire("go", ok=True), b)

    def test_callable_effect_invoked(self):
        sm = PartDefinition(name="V").attach_state_machine("SM")
        a = sm.add_state("A", is_initial=True)
        b = sm.add_state("B")
        seen: list[dict] = []
        sm.add_transition(a, b, trigger="go", effect=lambda ctx: seen.append(dict(ctx)))
        sm.runner().fire("go", x=42)
        self.assertEqual(seen, [{"x": 42}])


class StateMachineDiagramTests(unittest.TestCase):

    def test_dot_includes_states_and_transitions(self):
        sm = PartDefinition(name="V").attach_state_machine("SM")
        a = sm.add_state("A", is_initial=True)
        b = sm.add_state("B")
        c = sm.add_state("Done", is_final=True)
        sm.add_transition(a, b, trigger="go")
        sm.add_transition(b, c, trigger="finish", effect="cleanup()")
        dot = sm_dot(sm)
        self.assertIn("StateMachine: SM", dot)
        self.assertIn("go", dot)
        self.assertIn("finish", dot)
        self.assertIn("cleanup()", dot)
        self.assertIn("start -> ", dot)


if __name__ == "__main__":
    unittest.main()
