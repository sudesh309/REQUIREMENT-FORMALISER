"""Regression tests for defects found in the full-code review."""
import unittest

from engine import Repository, Validator, create_link, from_json, links_of, to_json
from kerml.stereotypes import Stereotype, stereotypes_on
from sysmlv2 import (
    ActionDefinition, AttributeDefinition, ParameterUsage, PartDefinition,
    RequirementDefinition,
)
from sysmlv2.state_machines import GuardError, evaluate_guard


def _project() -> Repository:
    repo = Repository("P")
    V = repo.add(PartDefinition(name="V"))
    R = repo.add(RequirementDefinition(name="R", req_id="R-1", text="be good"))
    Real = repo.add(AttributeDefinition(name="Real"))
    A = repo.add(ActionDefinition(name="A"))
    A.own(ParameterUsage(name="x", parameter_kind="return", typed_by=Real))
    create_link("satisfy", V, R)
    create_link("allocate", A, V)
    crit = repo.add(Stereotype(name="crit", applies_to=[PartDefinition]))
    crit.define_tag("lvl", default="QM")
    crit.apply(V, {"lvl": "D"})
    sm = V.attach_state_machine("SM")
    a = sm.add_state("Idle", entry="init()", is_initial=True)
    b = sm.add_state("Run", do="work()", exit="stop()")
    done = sm.add_state("Done", is_final=True)
    sm.add_transition(a, b, trigger="go", guard="speed > 0", effect="log()")
    sm.add_transition(b, done, trigger="end")
    V.add_annotation(__import__("kerml").Documentation(body="The vehicle."))
    repo.registry.register_tree(repo.root_package)
    return repo


class RoundTripTests(unittest.TestCase):

    def setUp(self):
        self.repo = from_json(to_json(_project()))
        self.V = self.repo.resolve("V")

    def test_typed_links_survive(self):
        kinds = sorted(type(l).__name__ for l in links_of(self.V, direction="both"))
        self.assertEqual(kinds, ["Allocation", "Satisfy"])
        self.assertIn(self.V, self.repo.resolve("R").satisfied_by)

    def test_stereotypes_survive(self):
        apps = stereotypes_on(self.V)
        self.assertEqual([(a.stereotype.name, a.values) for a in apps], [("crit", {"lvl": "D"})])
        crit = self.repo.resolve("crit")
        self.assertEqual(crit.applies_to, [PartDefinition])
        self.assertEqual([t.name for t in crit.tags], ["lvl"])

    def test_state_machine_survives_and_runs(self):
        sm = self.V.state_machines[0]
        self.assertEqual(sm.initial_state.name, "Idle")
        self.assertEqual([s.name for s in sm.final_states], ["Done"])
        self.assertEqual(sm.states[0].entry_action, "init()")
        r = sm.runner()
        self.assertIsNone(r.fire("go", speed=0))
        self.assertEqual(r.fire("go", speed=5).name, "Run")
        self.assertEqual(r.fire("end").name, "Done")
        self.assertTrue(r.is_in_final())

    def test_parameter_kind_and_doc_survive(self):
        self.assertEqual(self.repo.resolve("A::x").parameter_kind, "return")
        self.assertEqual(self.V.annotations[0].body, "The vehicle.")

    def test_second_round_trip_is_stable(self):
        once = to_json(self.repo)
        self.assertEqual(once, to_json(from_json(once)))


class GuardSafetyTests(unittest.TestCase):

    def test_allowed_expressions(self):
        self.assertTrue(evaluate_guard("speed == 0 and not locked", {"speed": 0, "locked": False}))
        self.assertTrue(evaluate_guard("1 < x <= 3", {"x": 2}))
        self.assertTrue(evaluate_guard("mode in ['a', 'b']", {"mode": "a"}))
        self.assertEqual(evaluate_guard("a * 2 + 1", {"a": 3}), 7)

    def test_rejects_escape_hatches(self):
        for expr in ("().__class__.__base__.__subclasses__()",
                     "__import__('os')", "x[0]", "open('f')", "lambda: 1"):
            with self.subTest(expr=expr), self.assertRaises(GuardError):
                evaluate_guard(expr, {"x": [1]})

    def test_runner_treats_bad_guard_as_false(self):
        sm = PartDefinition(name="Z").attach_state_machine("S")
        a = sm.add_state("a", is_initial=True); b = sm.add_state("b")
        sm.add_transition(a, b, trigger="t", guard="().__class__")
        self.assertIsNone(sm.runner().fire("t"))


class DeleteAndValidatorTests(unittest.TestCase):

    def test_delete_removes_incoming_links(self):
        repo = _project()
        repo.remove(repo.resolve("R"))
        V = repo.resolve("V")
        self.assertEqual([type(l).__name__ for l in links_of(V, direction="both")], ["Allocation"])
        self.assertNotIn("R-1", to_json(repo))

    def test_no_untyped_noise_for_states_and_tags(self):
        issues = Validator().validate(_project())
        noisy = [i for i in issues if i.rule == "feature.typed"]
        self.assertEqual(noisy, [])


if __name__ == "__main__":
    unittest.main()
