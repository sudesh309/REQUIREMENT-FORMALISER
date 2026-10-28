"""SU-7: Apply Stereotypes to Elements. The composition scope covers what the composition
contains (not the composition itself, not the internals of referenced definitions), a dry run says
how many elements an application would affect, and reference components that inherit the
stereotype from their definition are left alone (SU-15)."""
import unittest

from engine import Repository
from engine import profiles as P
from engine.hooks import notify_created
from kerml.namespaces import Package
from kerml.stereotypes import effective_applications, stereotypes_on
from mcp_server import server as M
from sysmlv2 import ConnectionUsage, PartDefinition, PartUsage, PortUsage
from tests.webapp_harness import WebAppTestCase


def _own(repo, cls, name, owner):
    e = cls(name=name)
    owner.own(e)
    notify_created(e, repo)
    return e


def _typed(repo, name, owner, definition):
    u = PartUsage(name=name)
    u.add_type(definition)
    owner.own(u)
    notify_created(u, repo)
    return u


class Model:
    """Aircraft (the composition) with an inline component ima (with a child cpu and a port),
    reference components fcc1 / fcc2 typed by FCC (whose internals are core1 / core2) and a
    connector; plus the profile with the LRU stereotype and a port stereotype."""

    def __init__(self):
        self.repo = repo = Repository("Aircraft")
        self.prof = P.create_profile(repo, "Avionics")
        self.lru = P.add_stereotype(repo, self.prof, "LRU", applies_to="Component")
        P.add_property(repo, self.lru, "mass", "double", unit="kg", default=1.5)
        P.add_property(repo, self.lru, "dal", "enumeration", literals="A,B,C", default="C")
        self.port = P.add_stereotype(repo, self.prof, "A429", applies_to="Port")
        root = repo.root_package
        self.pkg = _own(repo, Package, "Systems", root)
        self.arch = _own(repo, PartDefinition, "Aircraft", self.pkg)
        self.fcc_def = _own(repo, PartDefinition, "FCC", self.pkg)
        self.core1 = _own(repo, PartUsage, "core1", self.fcc_def)
        self.core2 = _own(repo, PartUsage, "core2", self.fcc_def)
        self.fcc_port = _own(repo, PortUsage, "bus", self.fcc_def)
        self.ima = _own(repo, PartUsage, "ima", self.arch)
        self.cpu = _own(repo, PartUsage, "cpu", self.ima)
        self.ima_port = _own(repo, PortUsage, "out", self.ima)
        self.fcc1 = _typed(repo, "fcc1", self.arch, self.fcc_def)
        self.fcc2 = _typed(repo, "fcc2", self.arch, self.fcc_def)
        self.link = _own(repo, ConnectionUsage, "link", self.arch)

    def names(self, ids):
        return sorted(self.repo.by_id(i).name for i in ids)


class CompositionScopeTests(unittest.TestCase):

    def setUp(self):
        self.m = Model()

    def apply(self, **kw):
        return P.batch_apply(self.m.repo, self.m.lru, **kw)

    def test_composition_scope_is_what_the_composition_contains(self):
        out = self.apply(scope="composition", root=self.m.arch)
        self.assertEqual(self.m.names(out["applied"]), ["cpu", "fcc1", "fcc2", "ima"])
        for untouched in (self.m.arch, self.m.fcc_def, self.m.core1, self.m.core2):
            self.assertEqual(stereotypes_on(untouched), [], untouched.name)   # not the container, not the internals
        self.assertEqual(out["count"], 4)

    def test_internals_of_referenced_definitions_only_when_selected(self):
        self.apply(scope="composition", root=self.m.arch)
        out = self.apply(scope="selection", elements=[self.m.core1.element_id, self.m.core2.element_id])
        self.assertEqual(self.m.names(out["applied"]), ["core1", "core2"])
        self.assertEqual(stereotypes_on(self.m.fcc_def), [])
        # the composition itself, likewise, when it is selected itself
        out = self.apply(scope="selection", elements=[self.m.arch.element_id])
        self.assertEqual(self.m.names(out["applied"]), ["Aircraft"])

    def test_a_reference_component_as_root_does_not_reach_its_definition(self):
        out = self.apply(scope="composition", root=self.m.fcc1)
        self.assertEqual(out["count"], 0)                     # fcc1's internals live on FCC: not part of it
        self.assertEqual(stereotypes_on(self.m.core1), [])

    def test_package_root_covers_the_definitions_it_holds(self):
        out = self.apply(scope="composition", root=self.m.pkg)
        # the package is the container; the definitions and usages in it are the elements
        # (fcc1 / fcc2 read the stereotype from FCC, which gets it in this batch)
        self.assertEqual(self.m.names(out["applied"]), sorted(["Aircraft", "FCC", "cpu", "core1", "core2", "ima"]))
        self.assertEqual(sorted(x["reason"] for x in out["skipped"]), ["inherited from FCC"] * 2)
        self.assertEqual([a.stereotype.name for a in effective_applications(self.m.fcc1)], ["LRU"])
        self.assertEqual(stereotypes_on(self.m.fcc1), [])                 # inherited, not duplicated

    def test_other_categories_inside_the_composition(self):
        out = P.batch_apply(self.m.repo, self.m.port, scope="composition", root=self.m.arch)
        self.assertEqual(self.m.names(out["applied"]), ["out"])           # ima's port, not FCC's bus
        self.assertEqual(stereotypes_on(self.m.fcc_port), [])
        anything = P.add_stereotype(self.m.repo, self.m.prof, "Tagged")
        out = P.batch_apply(self.m.repo, anything, scope="composition", root=self.m.arch, category="Connector")
        self.assertEqual(self.m.names(out["applied"]), ["link"])

    def test_model_scope_still_covers_everything_that_matches(self):
        out = self.apply(scope="model")
        self.assertEqual(self.m.names(out["applied"]), sorted(["Aircraft", "FCC", "core1", "core2", "ima", "cpu"]))
        self.assertEqual(sorted(x["reason"] for x in out["skipped"]), ["inherited from FCC"] * 2)


class InheritanceInBatchTests(unittest.TestCase):

    def setUp(self):
        self.m = Model()

    def test_usages_of_a_definition_that_carries_it_are_skipped(self):
        P.apply_stereotype(self.m.repo, self.m.fcc_def, self.m.lru, {"mass": 3})
        out = P.batch_apply(self.m.repo, self.m.lru, scope="composition", root=self.m.arch)
        self.assertEqual(self.m.names(out["applied"]), ["cpu", "ima"])
        self.assertEqual(sorted((x["name"].rsplit("::", 1)[-1], x["reason"]) for x in out["skipped"]),
                         [("fcc1", "inherited from FCC"), ("fcc2", "inherited from FCC")])
        self.assertEqual(out["skipped_by_reason"], {"inherited from its definition": 2})
        self.assertEqual(P.get_property_value(self.m.fcc1, "Avionics.LRU.mass"), 3.0)

    def test_values_given_for_such_a_usage_are_an_override(self):
        P.apply_stereotype(self.m.repo, self.m.fcc_def, self.m.lru, {"mass": 3})
        out = P.batch_apply(self.m.repo, self.m.lru, scope="selection", values={"dal": "A"},
                            elements=[self.m.fcc1.element_id, self.m.cpu.element_id])
        self.assertEqual(self.m.names(out["applied"]), ["cpu", "fcc1"])
        self.assertEqual(out["overrides"], [self.m.fcc1.element_id])
        self.assertEqual(P.get_property_value(self.m.fcc1, "Avionics.LRU.dal"), "A")
        self.assertEqual(P.get_property_value(self.m.fcc1, "Avionics.LRU.mass"), 3.0)   # the rest inherited
        self.assertEqual(P.get_property_value(self.m.fcc2, "Avionics.LRU.dal"), "C")

    def test_a_usage_and_its_definition_in_one_batch_need_one_application(self):
        out = P.batch_apply(self.m.repo, self.m.lru, scope="selection", values={"dal": "B"},
                            elements=[self.m.fcc1.element_id, self.m.fcc_def.element_id])
        self.assertEqual(self.m.names(out["applied"]), ["FCC"])
        self.assertEqual(P.get_property_value(self.m.fcc1, "Avionics.LRU.dal"), "B")


class DryRunTests(unittest.TestCase):

    def setUp(self):
        self.m = Model()

    def test_dry_run_changes_nothing_and_matches_the_real_run(self):
        from engine import to_json
        before = to_json(self.m.repo)
        plan = P.batch_apply(self.m.repo, self.m.lru, scope="composition", root=self.m.arch, dry_run=True)
        self.assertEqual(to_json(self.m.repo), before)
        self.assertEqual((plan["dry_run"], plan["count"]), (True, 4))
        self.assertEqual(sorted(x["name"].rsplit("::", 1)[-1] for x in plan["preview"]),
                         ["cpu", "fcc1", "fcc2", "ima"])
        real = P.batch_apply(self.m.repo, self.m.lru, scope="composition", root=self.m.arch)
        self.assertFalse(real["dry_run"])
        self.assertEqual(real["applied"], plan["applied"])
        self.assertNotIn("preview", real)
        again = P.batch_apply(self.m.repo, self.m.lru, scope="composition", root=self.m.arch, dry_run=True)
        self.assertEqual((again["count"], again["skipped_by_reason"]), (0, {"already applied": 4}))

    def test_dry_run_checks_like_the_real_run(self):
        with self.assertRaises(P.ProfileError):
            P.batch_apply(self.m.repo, self.m.lru, scope="composition", dry_run=True)        # no root
        with self.assertRaises(P.ProfileError):
            P.batch_apply(self.m.repo, self.m.lru, scope="selection", elements=[], dry_run=True)
        with self.assertRaises(P.ProfileError):
            P.batch_apply(self.m.repo, self.m.lru, scope="model", values={"dal": "Z"}, dry_run=True)

    def test_preview_is_limited(self):
        for i in range(P.PREVIEW_LIMIT + 5):
            _own(self.m.repo, PartUsage, f"extra{i}", self.m.arch)
        plan = P.batch_apply(self.m.repo, self.m.lru, scope="composition", root=self.m.arch, dry_run=True)
        self.assertEqual((plan["count"], len(plan["preview"])), (P.PREVIEW_LIMIT + 9, P.PREVIEW_LIMIT))


class BatchHttpTests(WebAppTestCase):

    def setUp(self):
        self.call("POST", "/api/new", {"name": "Aircraft"})
        prof = self.call("POST", "/api/profiles", {"name": "Avionics"})
        self.lru = self.call("POST", f"/api/profiles/{prof['id']}/stereotypes", {"name": "LRU", "applies_to": "Component"})
        self.any = self.call("POST", f"/api/profiles/{prof['id']}/stereotypes", {"name": "Tagged"})
        self.root = self.call("POST", "/api/arch/architecture", {"name": "Aircraft"})
        self.fcc_def = self.call("POST", "/api/arch/architecture", {"name": "FCC"})
        self.core = self.call("POST", "/api/arch/component", {"composition": self.fcc_def["id"], "name": "core"})
        self.ima = self.call("POST", "/api/arch/component", {"composition": self.root["id"], "name": "ima"})
        self.fcc = self.call("POST", "/api/arch/component",
                             {"composition": self.root["id"], "name": "fcc", "definition": self.fcc_def["id"]})

    def depth(self):
        return self.call("GET", "/api/undo/state")["undo_depth"]

    def test_dry_run_then_apply(self):
        d = self.depth()
        body = {"scope": "composition", "root": self.root["id"]}
        plan = self.call("POST", f"/api/stereotypes/{self.lru['id']}/batch", {**body, "dry_run": True})
        self.assertEqual((plan["dry_run"], plan["count"]), (True, 2))
        self.assertEqual(sorted(x["name"].rsplit("::", 1)[-1] for x in plan["preview"]), ["fcc", "ima"])
        self.assertEqual(self.depth(), d)                                     # a preview is not an undo step
        out = self.call("POST", f"/api/stereotypes/{self.lru['id']}/batch", body)
        self.assertEqual((out["count"], out["applied"]), (2, plan["applied"]))
        self.assertEqual(self.depth(), d + 1)
        self.assertEqual(self.call("GET", "/api/undo/state")["undo_label"], "Apply «Avionics.LRU» to 2 element(s)")
        for e in (self.root, self.fcc_def, self.core):
            self.assertEqual(self.call("GET", f"/api/elements/{e['id']}/stereotypes")["applied"], [], e["name"])

    def test_a_preview_of_an_impossible_choice_is_an_answer(self):
        plan = self.call("POST", f"/api/stereotypes/{self.any['id']}/batch", {"scope": "model", "dry_run": True})
        self.assertEqual(plan["count"], 0)
        self.assertIn("choose an element category", plan["problem"])
        self.call("POST", f"/api/stereotypes/{self.any['id']}/batch", {"scope": "model"}, expect=400)
        plan = self.call("POST", f"/api/stereotypes/{self.lru['id']}/batch", {"scope": "selection", "ids": [], "dry_run": True})
        self.assertIn("nothing is selected", plan["problem"])


class BatchMcpTests(unittest.TestCase):

    def test_dry_run_and_composition_scope(self):
        def ok(tool, /, **args):
            out = M.TOOL_BY_NAME[tool]["handler"](**args)
            assert out["ok"], out
            return out["result"]
        ok("sysml_new_project", name="Aircraft")
        ok("sysml_create_profile", name="Avionics")
        ok("sysml_add_stereotype", profile="Avionics", name="LRU", applies_to="Component")
        arch = ok("sysml_new_architecture", name="Aircraft")
        fcc_def = ok("sysml_new_architecture", name="FCC")
        ok("sysml_add_component", composition=fcc_def["id"], name="core")
        ok("sysml_add_component", composition=arch["id"], name="ima")
        ok("sysml_add_component", composition=arch["id"], name="fcc", definition=fcc_def["id"])
        plan = ok("sysml_batch_apply_stereotype", stereotype="Avionics.LRU", scope="composition", root=arch["id"],
                  dry_run=True)
        self.assertEqual((plan["dry_run"], plan["count"]), (True, 2))
        out = ok("sysml_batch_apply_stereotype", stereotype="Avionics.LRU", scope="composition", root=arch["id"])
        self.assertEqual(out["applied"], plan["applied"])
        again = ok("sysml_batch_apply_stereotype", stereotype="Avionics.LRU", scope="composition", root=arch["id"],
                   dry_run=True)
        self.assertEqual(again["count"], 0)
        bad = M.TOOL_BY_NAME["sysml_batch_apply_stereotype"]["handler"](stereotype="Avionics.LRU", scope="composition",
                                                                       dry_run=True)
        self.assertFalse(bad["ok"])
        self.assertIn("dry_run", M.TOOL_BY_NAME["sysml_batch_apply_stereotype"]["description"])


if __name__ == "__main__":
    unittest.main()
