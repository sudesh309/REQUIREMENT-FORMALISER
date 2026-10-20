"""Model Advisor checks and the Model Check runner."""
import unittest

from engine import Repository, Validator
from engine.interop import checks
from engine.interop.checks import RULES, run_model_check
from kerml.elements import Documentation
from kerml.features import FeatureDirection
from sysmlv2 import ConnectionUsage, PartDefinition, PartUsage, PortDefinition, PortUsage
from tests.test_interop_fixtures import avionics_repo


def _documented(e):
    e.add_annotation(Documentation(body="doc"))
    return e


def _issues(repo, rule):
    return [i for i in Validator().validate(repo) if i.rule == rule]


class AdvisorRuleTests(unittest.TestCase):

    def setUp(self):
        checks.install()        # other tests may clear the rule registries

    def test_registered_with_validator(self):
        from engine.validator import _ELEMENT_RULES, _REPO_RULES
        checks.install()
        self.assertEqual(_ELEMENT_RULES.count(checks.check_element), 1)
        self.assertEqual(_REPO_RULES.count(checks.check_unconnected_ports), 1)

    def test_empty_composition(self):
        repo = Repository("E")
        repo.add(PartDefinition(name="Empty"))
        arch = _documented(repo.add(PartDefinition(name="Arch")))
        arch.own(_documented(PartUsage(name="blank")))
        typed = _documented(PartUsage(name="typed", typed_by=arch))
        arch.own(typed)
        repo.registry.register_tree(repo.root_package)
        flagged = {i.element.name for i in _issues(repo, "advisor.empty-composition")}
        self.assertEqual(flagged, {"Empty", "blank"})

    def test_unconnected_ports(self):
        repo = avionics_repo()
        issues = _issues(repo, "advisor.unconnected-port")
        msgs = sorted(i.message for i in issues)
        self.assertEqual(msgs, ["Port ims.health is not connected in FlightDeck"])
        self.assertEqual(issues[0].severity.value, "warning")
        # Connecting it inside the component (delegation) clears the issue.
        ims = repo.resolve("FlightDeck::ims")
        part = repo.resolve("FlightDeck::ims::partition1")
        p = PortUsage(name="hb", direction=FeatureDirection.OUT)
        part.own(p)
        ims.own(ConnectionUsage(name="deleg", ends=[p, repo.resolve("FlightDeck::ims::health")]))
        repo.registry.register_tree(ims)
        self.assertEqual(_issues(repo, "advisor.unconnected-port"), [])

    def test_boundary_ports(self):
        repo = Repository("B")
        arch = repo.add(PartDefinition(name="Sys"))
        ext = PortUsage(name="ext", direction=FeatureDirection.IN)
        arch.own(ext)
        arch.own(PartUsage(name="c"))
        repo.registry.register_tree(arch)
        msgs = [i.message for i in _issues(repo, "advisor.unconnected-port")]
        self.assertIn("Boundary port Sys.ext is not connected to any component", msgs)

    def test_duplicate_names(self):
        repo = Repository("D")
        word = repo.add(PortDefinition(name="W"))
        lru = repo.add(PartDefinition(name="Lru"))
        lru.own(PortUsage(name="out", typed_by=word))
        arch = repo.add(PartDefinition(name="Arch"))
        arch.own(PartUsage(name="GPS"))
        arch.own(PartUsage(name="gps"))
        u = PartUsage(name="unit", typed_by=lru)
        arch.own(u)
        u.own(PortUsage(name="out", typed_by=word))        # repeats the definition's port
        repo.registry.register_tree(repo.root_package)
        issues = _issues(repo, "advisor.duplicate-name")
        self.assertEqual(sorted(i.element.name for i in issues), ["gps", "out"])

    def test_component_without_ports_and_missing_documentation(self):
        repo = avionics_repo()
        noports = {i.element.name for i in _issues(repo, "advisor.component-without-ports")}
        self.assertEqual(noports, set())
        arch = repo.resolve("FlightDeck")
        lonely = PartUsage(name="lonely", typed_by=repo.resolve("Components::PrimaryFlightDisplay"))
        arch.own(lonely)
        holder = PartUsage(name="holder")
        arch.own(holder)
        holder.own(PartUsage(name="inner"))
        repo.registry.register_tree(arch)
        noports = {i.element.name for i in _issues(repo, "advisor.component-without-ports")}
        self.assertEqual(noports, {"holder"})          # lonely has the definition's port
        undocumented = {i.element.name for i in _issues(repo, "advisor.missing-documentation")}
        self.assertIn("PrimaryFlightDisplay", undocumented)
        self.assertIn("navOut", undocumented)
        self.assertNotIn("FlightDeck", undocumented)
        self.assertNotIn("A429Word", undocumented)
        self.assertNotIn("LRU", undocumented)          # stereotypes are not checked


class ModelCheckRunnerTests(unittest.TestCase):

    def test_counts_filters_and_catalog(self):
        repo = avionics_repo()
        result = run_model_check(repo)
        self.assertEqual(result["total"], len(result["issues"]))
        self.assertEqual(sum(result["counts"].values()), result["total"])
        self.assertGreater(result["by_rule"]["advisor.missing-documentation"], 0)
        order = [i["severity"] for i in result["issues"]]
        self.assertEqual(order, sorted(order, key={"error": 0, "warning": 1, "info": 2}.get))
        ids = {r["id"] for r in result["rules"]}
        self.assertTrue(set(RULES) <= ids)
        self.assertIn("name.unique", ids)
        warnings = run_model_check(repo, severities=["warning"])
        self.assertTrue(all(i["severity"] == "warning" for i in warnings["issues"]))
        only = run_model_check(repo, rules=["advisor.unconnected-port"])
        self.assertEqual({i["rule"] for i in only["issues"]}, {"advisor.unconnected-port"})
        issue = only["issues"][0]
        self.assertEqual(issue["name"], "health")
        self.assertEqual(repo.by_id(issue["element_id"]).name, "health")


if __name__ == "__main__":
    unittest.main()
