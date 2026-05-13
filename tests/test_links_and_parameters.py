import json
import unittest

from engine import (
    Repository, create_link, describe_link, link_kind, links_of, list_link_kinds,
)
from engine.graph_export import export_knowledge_graph
from kerml.features import FeatureDirection
from sysmlv2 import (
    ActionDefinition, CalculationDefinition,
    ConstraintDefinition, PartDefinition,
    ParameterDefinition, ParameterUsage,
    RequirementDefinition,
    AttributeDefinition,
    VerificationCaseDefinition,
)
from sysmlv2.relationships import (
    ActorOf, Allocation, AssumeConstraint, RequireConstraint, Satisfy, StakeholderOf, SubjectOf, Verify,
)


class ParameterTests(unittest.TestCase):

    def test_parameter_directions(self):
        a = ActionDefinition(name="A")
        a.own(ParameterUsage(name="in_p",     parameter_kind="in"))
        a.own(ParameterUsage(name="out_p",    parameter_kind="out"))
        a.own(ParameterUsage(name="io_p",     parameter_kind="inout"))
        a.own(ParameterUsage(name="ret_p",    parameter_kind="return"))
        dirs = {p.name: p.direction for p in a.owned_features}
        self.assertEqual(dirs["in_p"],  FeatureDirection.IN)
        self.assertEqual(dirs["out_p"], FeatureDirection.OUT)
        self.assertEqual(dirs["io_p"],  FeatureDirection.INOUT)
        self.assertEqual(dirs["ret_p"], FeatureDirection.OUT)

    def test_parameter_typed(self):
        Real = AttributeDefinition(name="Real")
        a = CalculationDefinition(name="Speed")
        p = ParameterUsage(name="v", parameter_kind="in", typed_by=Real)
        a.own(p)
        self.assertIn(Real, p.types)
        self.assertEqual(p.parameter_kind, "in")


class LinkRegistryTests(unittest.TestCase):

    def test_all_kinds_registered(self):
        names = set(list_link_kinds())
        for expected in ("satisfy", "verify", "refine", "trace", "derive",
                         "allocate", "subject", "stakeholder", "actor",
                         "assume", "require", "expose", "parameter_binding"):
            self.assertIn(expected, names)

    def test_aliases_resolve(self):
        self.assertIs(link_kind("satisfies").cls, Satisfy)
        self.assertIs(link_kind("derives_from").cls.__name__,
                      link_kind("derive").cls.__name__)

    def test_create_typed_links(self):
        repo = Repository("Demo")
        V = PartDefinition(name="Vehicle"); repo.add(V)
        R = RequirementDefinition(name="Req", req_id="R-1"); repo.add(R)
        rel = create_link("satisfy", V, R)
        self.assertIsInstance(rel, Satisfy)
        # target_list side-effect populates R.satisfied_by with the source.
        self.assertIn(V, R.satisfied_by)

        alloc = create_link("allocate", V, R)
        self.assertIsInstance(alloc, Allocation)

    def test_list_links_directionality(self):
        repo = Repository("Demo")
        V = PartDefinition(name="V"); repo.add(V)
        R = RequirementDefinition(name="R", req_id="R-1"); repo.add(R)
        create_link("satisfy", V, R)
        create_link("trace",   V, R)
        out_v = links_of(V, direction="outgoing")
        self.assertEqual({type(r).__name__ for r in out_v}, {"Satisfy", "Trace"})
        in_r = links_of(R, direction="incoming")
        self.assertEqual({type(r).__name__ for r in in_r}, {"Satisfy", "Trace"})

    def test_unknown_kind_raises(self):
        repo = Repository("D")
        V = PartDefinition(name="V"); repo.add(V)
        R = RequirementDefinition(name="R"); repo.add(R)
        with self.assertRaises(ValueError):
            create_link("not_a_kind", V, R)


class RequirementWiringTests(unittest.TestCase):

    def test_subject_stakeholder_actor(self):
        repo = Repository("Demo")
        V = PartDefinition(name="V"); repo.add(V)
        Eng = PartDefinition(name="Engineer"); repo.add(Eng)
        User = PartDefinition(name="Driver"); repo.add(User)
        R = RequirementDefinition(name="R"); repo.add(R)

        s_rel = create_link("subject",     R, V)
        st_rel = create_link("stakeholder", R, Eng)
        a_rel = create_link("actor",       R, User)

        self.assertIsInstance(s_rel, SubjectOf)
        self.assertIsInstance(st_rel, StakeholderOf)
        self.assertIsInstance(a_rel, ActorOf)

    def test_assume_and_require_constraints(self):
        repo = Repository("Demo")
        R = RequirementDefinition(name="R"); repo.add(R)
        C1 = ConstraintDefinition(name="C1"); repo.add(C1)
        C2 = ConstraintDefinition(name="C2"); repo.add(C2)
        a = create_link("assume",  R, C1)
        r = create_link("require", R, C2)
        self.assertIsInstance(a, AssumeConstraint)
        self.assertIsInstance(r, RequireConstraint)


class KnowledgeGraphLinkExportTests(unittest.TestCase):

    def test_typed_links_serialize_in_turtle_and_cypher(self):
        repo = Repository("Demo")
        V = PartDefinition(name="V"); repo.add(V)
        R = RequirementDefinition(name="R", req_id="R-1"); repo.add(R)
        VC = VerificationCaseDefinition(name="VC"); repo.add(VC)
        create_link("satisfy",  V, R)
        create_link("verify",   VC, R)
        create_link("allocate", V, R)

        ttl = export_knowledge_graph(repo.root_package, "turtle")
        self.assertIn("sysml:satisfies", ttl)
        self.assertIn("sysml:verifies",  ttl)

        cy = export_knowledge_graph(repo.root_package, "cypher")
        self.assertIn("-[:SATISFIES]->", cy.upper())
        self.assertIn("-[:VERIFIES]->",  cy.upper())


if __name__ == "__main__":
    unittest.main()
