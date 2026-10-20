"""Engine tests for the Allocation Editor (engine/allocation.py)."""
import json
import unittest

from engine import Repository, Validator, export_knowledge_graph, from_json, to_json
from engine import allocation as A
from engine.allocation import AllocationError
from kerml.namespaces import Package
from kerml.stereotypes import Stereotype, stereotypes_on
from sysmlv2 import (
    ActionUsage, ConnectionUsage, PartDefinition, PartUsage, PortUsage, RequirementDefinition,
    StateUsage,
)


def build_model():
    """Functional (Package of actions) -> Logical -> Physical avionics architectures."""
    repo = Repository("Avionics")
    func = Package(name="Functions")
    navigate = ActionUsage(name="Navigate"); func.own(navigate)
    compute = ActionUsage(name="ComputePosition"); navigate.own(compute)
    plan = ActionUsage(name="PlanRoute"); navigate.own(plan)
    show = ActionUsage(name="DisplayData"); func.own(show)

    logical = PartDefinition(name="LogicalArch")
    fms = PartUsage(name="FMS"); logical.own(fms)
    nav = PartUsage(name="NavFn"); fms.own(nav)
    guid = PartUsage(name="GuidanceFn"); fms.own(guid)
    fms_out = PortUsage(name="arinc_out"); fms.own(fms_out)
    cds = PartUsage(name="DisplaySys"); logical.own(cds)
    cds_in = PortUsage(name="arinc_in"); cds.own(cds_in)
    bus = ConnectionUsage(name="a429", ends=[fms_out, cds_in]); logical.own(bus)
    monitor = ActionUsage(name="MonitorHealth"); cds.own(monitor)
    mode = StateUsage(name="Normal"); cds.own(mode)          # states are not functions

    physical = PartDefinition(name="PhysicalArch")
    ima = PartUsage(name="IMA_Cabinet"); physical.own(ima)
    cpm1 = PartUsage(name="CPM1"); ima.own(cpm1)
    cpm2 = PartUsage(name="CPM2"); ima.own(cpm2)
    mfd = PartUsage(name="MFD"); physical.own(mfd)
    afdx = PortUsage(name="afdx"); mfd.own(afdx)

    req = RequirementDefinition(name="R1")
    for top in (func, logical, physical, req):
        repo.add(top)
    m = dict(repo=repo, func=func, navigate=navigate, compute=compute, plan=plan, show=show,
             logical=logical, fms=fms, nav=nav, guid=guid, fms_out=fms_out, cds=cds, cds_in=cds_in,
             bus=bus, monitor=monitor, mode=mode, physical=physical, ima=ima, cpm1=cpm1,
             cpm2=cpm2, mfd=mfd, afdx=afdx, req=req)
    return type("Model", (), m)


class AllocationTestCase(unittest.TestCase):

    def setUp(self):
        A.install()          # other test modules may clear the global rule/edge registries
        self.m = build_model()
        self.repo = self.m.repo
        self.l2p = A.create_allocation_set(self.repo, "L2P", self.m.logical, self.m.physical,
                                           description="logical to physical")
        self.sc = self.l2p.scenarios[0]


class SetAndScenarioTests(AllocationTestCase):

    def test_set_lives_in_allocations_package_with_default_scenario(self):
        pkg = A.allocations_package(self.repo)
        self.assertIsNotNone(pkg)
        self.assertIs(self.l2p.owner, pkg)
        self.assertEqual([s.name for s in self.l2p.scenarios], ["Scenario 1"])
        self.assertEqual(self.l2p.description, "logical to physical")
        self.assertIs(self.repo.resolve("Allocations::L2P::Scenario 1"), self.sc)
        self.assertIs(self.repo.by_id(self.sc.element_id), self.sc)
        f2l = A.create_allocation_set(self.repo, "F2L", self.m.func, self.m.logical)
        self.assertEqual([s.name for s in A.allocation_sets(self.repo)], ["L2P", "F2L"])
        self.assertIs(f2l.owner, pkg)

    def test_set_creation_is_validated(self):
        with self.assertRaises(AllocationError) as cm:
            A.create_allocation_set(self.repo, "L2P", self.m.logical, self.m.physical)
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaisesRegex(AllocationError, "non-empty"):
            A.create_allocation_set(self.repo, "  ", self.m.logical, self.m.physical)
        with self.assertRaisesRegex(AllocationError, "must be an architecture"):
            A.create_allocation_set(self.repo, "X", self.m.fms, self.m.physical)
        with self.assertRaises(AllocationError) as cm:
            A.create_allocation_set(self.repo, "X", None, self.m.physical)
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaisesRegex(AllocationError, "not part of this project"):
            A.create_allocation_set(self.repo, "X", PartDefinition(name="Loose"), self.m.physical)
        with self.assertRaisesRegex(AllocationError, "true or false"):
            A.create_allocation_set(self.repo, "X", self.m.logical, self.m.physical,
                                    require_complete_coverage="yes")

    def test_scenarios_create_rename_delete(self):
        s2 = A.create_scenario(self.repo, self.l2p)
        self.assertEqual(s2.name, "Scenario 2")
        with self.assertRaises(AllocationError) as cm:
            A.create_scenario(self.repo, self.l2p, "Scenario 2")
        self.assertEqual(cm.exception.status, 409)
        A.rename_scenario(s2, "Dual CPM")
        self.assertEqual(s2.name, "Dual CPM")
        with self.assertRaises(AllocationError):
            A.rename_scenario(s2, "Scenario 1")
        A.delete_scenario(self.repo, s2)
        self.assertEqual([s.name for s in self.l2p.scenarios], ["Scenario 1"])
        with self.assertRaises(AllocationError) as cm:
            A.delete_scenario(self.repo, self.sc)
        self.assertEqual(cm.exception.status, 409)

    def test_duplicate_scenario_copies_allocations_and_stereotypes(self):
        st = Stereotype(name="Binding", applies_to=[A.ArchitectureAllocation])
        st.define_tag("latency_ms", default=1)
        self.repo.add(st)
        a = A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        st.apply(a, {"latency_ms": 5})
        A.allocate(self.repo, self.sc, self.m.cds, self.m.mfd)
        copy = A.duplicate_scenario(self.repo, self.sc)
        self.assertEqual(copy.name, "Scenario 1 copy")
        self.assertEqual([x.label for x in copy.allocations], ["NavFn → CPM1", "DisplaySys → MFD"])
        self.assertIsNot(copy.allocations[0], a)
        self.assertEqual(stereotypes_on(copy.allocations[0])[0].values, {"latency_ms": 5})
        self.assertEqual(A.duplicate_scenario(self.repo, self.sc).name, "Scenario 1 copy 2")

    def test_update_set_and_stale_allocations(self):
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        A.update_allocation_set(self.repo, self.l2p, name="Logical2Physical", description="d",
                                require_complete_coverage=True)
        self.assertEqual((self.l2p.name, self.l2p.description, self.l2p.require_complete_coverage),
                         ("Logical2Physical", "d", True))
        other = self.repo.add(PartDefinition(name="OtherArch"))
        with self.assertRaises(AllocationError) as cm:
            A.update_allocation_set(self.repo, self.l2p, target=other)
        self.assertEqual(cm.exception.status, 409)
        self.assertIs(self.l2p.target_architecture, self.m.physical)
        A.update_allocation_set(self.repo, self.l2p, target=other, force=True)
        self.assertIs(self.l2p.target_architecture, other)
        self.assertEqual(self.sc.allocations, [])

    def test_architecture_candidates(self):
        names = [c["name"] for c in A.architecture_candidates(self.repo)]
        self.assertEqual(names, ["Functions", "LogicalArch", "PhysicalArch"])


class AllocateTests(AllocationTestCase):

    def test_allocate_and_query(self):
        a1 = A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        A.allocate(self.repo, self.sc, self.m.guid, self.m.cpm1)
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm2)
        self.assertEqual(a1.kind, "Allocation")
        self.assertIs(a1.scenario, self.sc)
        self.assertEqual(A.allocated_to(self.m.nav, self.sc), [self.m.cpm1, self.m.cpm2])
        self.assertEqual(A.allocated_from(self.m.cpm1, self.sc), [self.m.nav, self.m.guid])
        self.assertEqual(len(A.allocations(self.sc)), 3)
        other = A.create_scenario(self.repo, self.l2p)
        A.allocate(self.repo, other, self.m.nav, self.m.mfd)
        self.assertEqual(A.allocated_to(self.m.nav), [self.m.cpm1, self.m.cpm2, self.m.mfd])
        self.assertEqual(A.allocated_to(self.m.nav, other), [self.m.mfd])
        self.assertEqual(A.allocation_map(self.sc), {
            self.m.cpm1.element_id: [self.m.nav.element_id, self.m.guid.element_id],
            self.m.cpm2.element_id: [self.m.nav.element_id]})

    def test_one_allocation_per_pair_and_scope(self):
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        with self.assertRaises(AllocationError) as cm:
            A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaisesRegex(AllocationError, "not part of source architecture"):
            A.allocate(self.repo, self.sc, self.m.cpm2, self.m.cpm1)
        with self.assertRaisesRegex(AllocationError, "not part of target architecture"):
            A.allocate(self.repo, self.sc, self.m.nav, self.m.fms)
        with self.assertRaisesRegex(AllocationError, "cannot be allocated"):
            A.allocate(self.repo, self.sc, self.m.req, self.m.cpm1)
        with self.assertRaisesRegex(AllocationError, "cannot be allocated"):
            A.allocate(self.repo, self.sc, self.m.mode, self.m.cpm1)
        with self.assertRaises(AllocationError) as cm:
            A.deallocate(self.repo, self.sc, self.m.guid, self.m.cpm1)
        self.assertEqual(cm.exception.status, 404)

    def test_ports_connectors_and_functions_are_allocatable(self):
        self.assertEqual([A.category_of(x) for x in (self.m.fms, self.m.fms_out, self.m.bus,
                                                     self.m.monitor, self.m.mode, self.m.req)],
                         ["component", "port", "connector", "function", None, None])
        A.allocate(self.repo, self.sc, self.m.fms_out, self.m.afdx)
        A.allocate(self.repo, self.sc, self.m.bus, self.m.ima)
        A.allocate(self.repo, self.sc, self.m.monitor, self.m.cpm2)
        f2l = A.create_allocation_set(self.repo, "F2L", self.m.func, self.m.logical)
        A.allocate(self.repo, f2l.scenarios[0], self.m.compute, self.m.nav)
        self.assertEqual(A.allocated_to(self.m.compute), [self.m.nav])

    def test_toggle(self):
        a = A.toggle_allocation(self.repo, self.sc, self.m.nav, self.m.cpm1)
        self.assertIsNotNone(a)
        self.assertIsNone(A.toggle_allocation(self.repo, self.sc, self.m.nav, self.m.cpm1))
        self.assertEqual(self.sc.allocations, [])
        self.assertIsNone(self.repo.by_id(a.element_id))

    def test_reference_component_internals(self):
        cpm_def = self.repo.add(PartDefinition(name="CPM"))
        core = PartUsage(name="Core0"); cpm_def.own(core)
        self.repo.registry.register_tree(core)
        cpm3 = PartUsage(name="CPM3", typed_by=cpm_def); self.m.ima.own(cpm3)
        self.repo.registry.register_tree(cpm3)
        rows = A.architecture_rows(self.m.physical)
        self.assertIn(("Core0", 2), [(r["name"], r["depth"]) for r in rows])
        A.allocate(self.repo, self.sc, self.m.nav, core)
        self.assertEqual(A.allocated_from(core), [self.m.nav])


class RowsMatrixCoverageTests(AllocationTestCase):

    def test_architecture_rows_hierarchy(self):
        rows = [(r["name"], r["category"], r["depth"]) for r in A.architecture_rows(self.m.logical)]
        self.assertEqual(rows, [
            ("FMS", "component", 0), ("arinc_out", "port", 1), ("NavFn", "component", 1),
            ("GuidanceFn", "component", 1), ("DisplaySys", "component", 0),
            ("MonitorHealth", "function", 1), ("arinc_in", "port", 1), ("a429", "connector", 0)])
        frows = [(r["name"], r["depth"], r["leaf"]) for r in A.architecture_rows(self.m.func)]
        self.assertEqual(frows, [("Navigate", 0, False), ("ComputePosition", 1, True),
                                 ("PlanRoute", 1, True), ("DisplayData", 0, True)])

    def test_matrix_filters(self):
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        mx = A.matrix(self.sc)
        self.assertEqual([r["name"] for r in mx["rows"]],
                         ["FMS", "NavFn", "GuidanceFn", "DisplaySys", "MonitorHealth"])
        self.assertEqual([c["name"] for c in mx["columns"]], ["IMA_Cabinet", "CPM1", "CPM2", "MFD"])
        self.assertEqual(len(mx["allocations"]), 1)
        nav_row = next(r for r in mx["rows"] if r["name"] == "NavFn")
        self.assertEqual(nav_row["count"], 1)
        un = A.matrix(self.sc, rows="component", show="unallocated")
        self.assertEqual([(r["name"], r["context"]) for r in un["rows"]],
                         [("FMS", False), ("GuidanceFn", False), ("DisplaySys", False)])
        al = A.matrix(self.sc, rows=["component"], show="allocated")
        self.assertEqual([(r["name"], r["context"]) for r in al["rows"]], [("FMS", True), ("NavFn", False)])
        ports = A.matrix(self.sc, rows="ports,connectors", cols="port", text="arinc")
        self.assertEqual([(r["name"], r["context"]) for r in ports["rows"]],
                         [("FMS", True), ("arinc_out", False), ("DisplaySys", True), ("arinc_in", False)])
        self.assertEqual([c["name"] for c in ports["columns"] if not c["context"]], ["afdx"])
        with self.assertRaisesRegex(AllocationError, "unknown element kind"):
            A.matrix(self.sc, rows="widgets")
        with self.assertRaisesRegex(AllocationError, "show must be"):
            A.matrix(self.sc, show="some")

    def test_coverage(self):
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        A.allocate(self.repo, self.sc, self.m.guid, self.m.cpm1)
        cov = A.coverage(self.sc)
        self.assertEqual((cov["total"], cov["allocated"]), (4, 2))
        self.assertEqual([u["name"] for u in cov["unallocated"]], ["DisplaySys", "MonitorHealth"])
        per = {t["name"]: t["count"] for t in cov["per_target"]}
        self.assertEqual(per, {"IMA_Cabinet": 0, "CPM1": 2, "CPM2": 0, "MFD": 0})
        cov_all = A.coverage(self.sc, kinds=["component"], leaves_only=False)
        self.assertEqual([u["name"] for u in cov_all["unallocated"]], ["FMS", "DisplaySys"])


class SynchronizationAndPersistenceTests(AllocationTestCase):

    def test_deleting_an_end_removes_its_allocations(self):
        a = A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        keep = A.allocate(self.repo, self.sc, self.m.guid, self.m.cpm2)
        self.repo.remove(self.m.cpm1)
        self.assertEqual(self.sc.allocations, [keep])
        self.assertIsNone(self.repo.by_id(a.element_id))
        self.repo.remove(self.m.fms)            # removes guid (child of FMS) too
        self.assertEqual(self.sc.allocations, [])

    def test_deleting_an_architecture_keeps_the_set_and_flags_it(self):
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        self.repo.remove(self.m.physical)
        self.assertIsNone(self.l2p.target_architecture)
        self.assertEqual(self.sc.allocations, [])
        rules = {i.rule for i in Validator().validate(self.repo)}
        self.assertIn("allocation.set.target", rules)

    def test_renames_are_live(self):
        a = A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        self.m.cpm1.name = "CPM_A"
        self.assertEqual(a.label, "NavFn → CPM_A")
        self.assertEqual(A.allocation_summary(a)["target"]["name"], "CPM_A")

    def test_round_trip(self):
        st = Stereotype(name="Binding", applies_to=[A.ArchitectureAllocation])
        st.define_tag("latency_ms", default=1)
        self.repo.add(st)
        a = A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        st.apply(a, {"latency_ms": 3})
        A.allocate(self.repo, self.sc, self.m.fms_out, self.m.afdx)
        s2 = A.create_scenario(self.repo, self.l2p, "Alt")
        A.allocate(self.repo, s2, self.m.cds, self.m.mfd)
        A.update_allocation_set(self.repo, self.l2p, require_complete_coverage=True)
        text = to_json(self.repo)
        loaded = from_json(text)
        again = to_json(loaded)
        self.assertEqual(again, to_json(from_json(again)))
        by_id = lambda t: sorted(json.loads(t)["elements"], key=lambda r: r["id"])  # noqa: E731
        self.assertEqual(by_id(text), by_id(again))
        s = A.find_set(loaded, "L2P")
        self.assertEqual(s.source_architecture.name, "LogicalArch")
        self.assertEqual(s.target_architecture.name, "PhysicalArch")
        self.assertTrue(s.require_complete_coverage)
        self.assertEqual(s.description, "logical to physical")
        self.assertEqual([sc.name for sc in s.scenarios], ["Scenario 1", "Alt"])
        labels = [x.label for x in s.scenarios[0].allocations]
        self.assertEqual(labels, ["NavFn → CPM1", "arinc_out → afdx"])
        loaded_a = loaded.by_id(a.element_id)
        self.assertIs(loaded_a.source, loaded.resolve("LogicalArch::FMS::NavFn"))
        self.assertEqual(stereotypes_on(loaded_a)[0].values, {"latency_ms": 3})
        # The loaded model stays live: deleting an end still cleans up.
        loaded.remove(loaded.resolve("PhysicalArch::IMA_Cabinet::CPM1"))
        self.assertEqual([x.label for x in s.scenarios[0].allocations], ["arinc_out → afdx"])


class ValidationGraphChainTests(AllocationTestCase):

    def _issues(self, prefix="allocation"):
        return [i for i in Validator().validate(self.repo) if i.rule.startswith(prefix)]

    def test_coverage_rule_only_when_required(self):
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        self.assertEqual(self._issues(), [])
        A.update_allocation_set(self.repo, self.l2p, require_complete_coverage=True)
        issues = self._issues("allocation.coverage")
        self.assertEqual(sorted(i.element.name for i in issues), ["DisplaySys", "GuidanceFn"])
        self.assertTrue(all(i.severity.value == "warning" for i in issues))
        self.assertIn("L2P/Scenario 1", issues[0].message)

    def test_integrity_rules(self):
        a = A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        dup = A.ArchitectureAllocation(source=self.m.nav, target=self.m.cpm1)
        self.sc.own(dup)
        stray = A.ArchitectureAllocation(source=self.m.cpm1, target=self.m.nav)
        self.sc.own(stray)
        loose = A.ArchitectureAllocation(source=self.m.nav, target=self.m.cpm1)
        self.repo.add(loose)
        rules = sorted(i.rule for i in self._issues())
        self.assertEqual(rules, ["allocation.duplicate", "allocation.owner",
                                 "allocation.scope", "allocation.scope"])
        self.assertTrue(a)

    def test_knowledge_graph_edges(self):
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        ttl = export_knowledge_graph(self.repo.root_package, "turtle")
        self.assertIn(f"sysml:{self.m.nav.element_id} sysml:allocatedTo sysml:{self.m.cpm1.element_id}", ttl)
        self.assertIn("ALLOCATEDTO", export_knowledge_graph(self.repo.root_package, "cypher"))

    def test_multi_level_chain(self):
        f2l = A.create_allocation_set(self.repo, "F2L", self.m.func, self.m.logical)
        A.allocate(self.repo, f2l.scenarios[0], self.m.compute, self.m.nav)
        A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        chain = A.allocation_chain(self.m.nav)
        self.assertEqual([(n["name"], n["level"], n["architecture"]["name"]) for n in chain["nodes"]],
                         [("NavFn", 0, "LogicalArch"), ("CPM1", 1, "PhysicalArch"),
                          ("ComputePosition", -1, "Functions")])
        self.assertEqual({(e["set"], e["scenario"]) for e in chain["edges"]},
                         {("F2L", "Scenario 1"), ("L2P", "Scenario 1")})
        mm = chain["mermaid"]
        self.assertTrue(mm.startswith("flowchart LR"))
        self.assertIn('subgraph g0["Functions"]', mm)
        self.assertIn("-->|F2L / Scenario 1|", mm)
        self.assertIn("class n0 focus", mm)
        # From the function, the chain reaches the physical module.
        far = A.allocation_chain(self.m.compute)
        self.assertEqual([n["name"] for n in far["nodes"]], ["ComputePosition", "NavFn", "CPM1"])
        alone = A.allocation_chain(self.m.mfd)
        self.assertEqual((len(alone["nodes"]), alone["edges"]), (1, []))

    def test_stereotype_applies_only_to_allocations(self):
        st = Stereotype(name="Binding", applies_to=[A.ArchitectureAllocation])
        a = A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        st.apply(a)
        with self.assertRaises(TypeError):
            st.apply(self.m.nav)

    def test_summary_annotation(self):
        a = A.allocate(self.repo, self.sc, self.m.nav, self.m.cpm1)
        d = {"badges": [], "style": {}}
        A.annotate_summary(a, d)
        self.assertEqual(d["badges"], ["NavFn → CPM1"])
        self.assertEqual(d["allocation"]["scenario"], "Scenario 1")
        d = {}
        A.annotate_summary(self.m.fms_out, d)
        self.assertEqual(d, {"allocation_category": "port"})


if __name__ == "__main__":
    unittest.main()
