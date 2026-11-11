"""SysML attributes held as spec structure (ADR 0002 decision 6, Phase 1 A3)."""
import unittest

from engine import Repository
from engine.serializer import from_json, to_json
from kerml import (
    Behavior, Classifier, Connector, Documentation, EndFeatureMembership, Expression, FeatureChaining,
    Function, Membership, OwningMembership, Predicate, ReferenceSubsetting, Relationship, Step,
    Succession, TextualRepresentation, TypeFeaturing,
)
from kerml.elements import is_pure_relationship
from sysmlv2 import (
    AcceptActionUsage, ActionDefinition, ActionUsage, ActorMembership, AllocationUsage,
    CalculationDefinition, ConnectionUsage, ConnectorAsUsage, ConstraintDefinition,
    ConstraintUsage, MembershipExpose, NamespaceExpose, PartDefinition, PartUsage, PortDefinition,
    PortUsage, ReferenceUsage, RequirementConstraintMembership, RequirementDefinition,
    RequirementUsage, StakeholderMembership, StateSubactionMembership, StateUsage,
    SubjectMembership, TransitionFeatureMembership, TransitionUsage, ViewUsage,
)
from sysmlv2.definitions import is_part_definition, is_part_usage
from sysmlv2.state_machines import attach_state_machine


def _system():
    Data = PortDefinition(name="Data")
    Sensor = PartDefinition(name="Sensor")
    out = PortUsage(name="out", typed_by=Data)
    Sensor.own(out)
    Sys = PartDefinition(name="System")
    s1 = PartUsage(name="s1", typed_by=Sensor)
    Sys.own(s1)
    cpu = PartUsage(name="cpu")
    Sys.own(cpu)
    inp = PortUsage(name="in")
    cpu.own(inp)
    return Sys, s1, cpu, out, inp


class SupertypeTests(unittest.TestCase):

    def test_spec_supertypes(self):
        self.assertTrue(issubclass(ActionDefinition, Behavior))
        self.assertTrue(issubclass(ActionUsage, Step))
        self.assertTrue(issubclass(CalculationDefinition, Function))
        self.assertTrue(issubclass(ConstraintDefinition, Predicate))
        self.assertTrue(issubclass(ConstraintUsage, Expression))
        self.assertTrue(issubclass(ConnectionUsage, ConnectorAsUsage))
        self.assertTrue(issubclass(ConnectionUsage, PartUsage))
        self.assertTrue(issubclass(ConnectionUsage, Connector))
        self.assertTrue(issubclass(AllocationUsage, ConnectionUsage))
        self.assertTrue(issubclass(ViewUsage, PartUsage))

    def test_application_predicates_keep_components_apart(self):
        conn = ConnectionUsage(name="c")
        self.assertIsInstance(conn, PartUsage)
        self.assertFalse(is_part_usage(conn))
        self.assertTrue(is_part_usage(PartUsage(name="p")))
        self.assertTrue(is_part_definition(PartDefinition(name="P")))
        self.assertFalse(is_pure_relationship(conn))
        self.assertIsInstance(conn, Relationship)


class ConnectionTests(unittest.TestCase):

    def test_ends_are_end_features_with_reference_subsetting(self):
        Sys, s1, cpu, out, inp = _system()
        conn = ConnectionUsage(name="c", ends=[out, inp], end_contexts=(s1, cpu))
        Sys.own(conn)
        ends = conn.connector_ends
        self.assertEqual(len(ends), 2)
        for end in ends:
            self.assertIsInstance(end, ReferenceUsage)
            self.assertTrue(end.is_end)
            self.assertIsInstance(end.owning_relationship, EndFeatureMembership)
            self.assertIsInstance(end.owned_reference_subsetting, ReferenceSubsetting)
        chain = ends[0].owned_reference_subsetting.referenced_feature
        self.assertEqual(chain.chaining_features, [s1, out])
        self.assertTrue(all(isinstance(r, FeatureChaining) for r in chain.owned_feature_chainings))
        self.assertIs(chain.owner, ends[0])
        self.assertEqual(conn.ends, [out, inp])
        self.assertEqual(conn.end_contexts, (s1, cpu))
        self.assertEqual(conn.related_features, [chain, ends[1].owned_reference_subsetting.referenced_feature])
        self.assertIs(conn.source_feature, chain)
        self.assertEqual(ends[0].types, [out.types[0]])          # typed through the chain
        self.assertEqual(conn.children, [])                         # ends are structure
        self.assertNotIn(conn, [c for c in Sys.children if is_part_usage(c)])

    def test_ends_and_contexts_are_assignable(self):
        Sys, s1, cpu, out, inp = _system()
        conn = ConnectionUsage(name="c", ends=[out, inp])
        Sys.own(conn)
        self.assertEqual(conn.end_contexts, ())
        conn.end_contexts = (s1, None)
        self.assertEqual(conn.end_contexts, (s1, None))
        self.assertEqual(conn.ends, [out, inp])
        conn.ends = [inp, out]
        self.assertEqual(conn.ends, [inp, out])
        conn.end_contexts = ()
        self.assertEqual(conn.end_contexts, ())
        ids = [e.element_id for e in conn.connector_ends]
        conn.ends = [inp, out]
        self.assertEqual([e.element_id for e in conn.connector_ends], ids)     # deterministic

    def test_allocation_ends(self):
        a, b = PartUsage(name="a"), PartUsage(name="b")
        alloc = AllocationUsage(name="al", allocate_from=a, allocate_to=b)
        self.assertEqual((alloc.allocate_from, alloc.allocate_to), (a, b))
        self.assertEqual(alloc.ends, [a, b])
        alloc.allocate_to = a
        self.assertEqual(alloc.ends, [a, a])

    def test_saved_connectors_keep_their_contexts(self):
        repo = Repository("R")
        Sys, s1, cpu, out, inp = _system()
        repo.add(s1.types[0])
        repo.add(Sys)
        conn = ConnectionUsage(name="c", ends=[out, inp], end_contexts=(s1, cpu))
        Sys.own(conn)
        import engine.architecture  # noqa: F401 - registers the connector codec
        loaded = from_json(to_json(repo))
        lc = loaded.by_id(conn.element_id)
        self.assertEqual([e.name for e in lc.ends], ["out", "in"])
        self.assertEqual([c.name for c in lc.end_contexts], ["s1", "cpu"])
        self.assertEqual([e.element_id for e in lc.connector_ends],
                         [e.element_id for e in conn.connector_ends])


class TransitionTests(unittest.TestCase):

    def setUp(self):
        self.sm = attach_state_machine(PartDefinition(name="V"), "SM")
        self.a = self.sm.add_state("A", entry="lock()", is_initial=True)
        self.b = self.sm.add_state("B", do="run()", exit="stop()")
        self.t = self.sm.add_transition(self.a, self.b, trigger="go", guard="speed > 0",
                                        effect="log()")

    def test_source_target_and_features_are_spec_structure(self):
        t = self.t
        self.assertIs(type(t.owned_relationships[0]), Membership)
        self.assertIs(t.source, self.a)
        self.assertIs(t.target, self.b)
        self.assertIsInstance(t.succession, Succession)
        self.assertIs(t.succession.connector_ends[1].owned_reference_subsetting.referenced_feature, self.b)
        trig, = t.trigger_actions
        self.assertIsInstance(trig, AcceptActionUsage)
        self.assertEqual(trig.payload_parameter.name, "go")
        guard, = t.guard_expressions
        self.assertIsInstance(guard, Expression)
        self.assertIsInstance(guard.textual_representations[0], TextualRepresentation)
        self.assertEqual(guard.textual_representations[0].body, "speed > 0")
        effect, = t.effect_actions
        self.assertIsInstance(effect, ActionUsage)
        kinds = [m.transition_feature_kind for m in t.owned_relationships
                 if isinstance(m, TransitionFeatureMembership)]
        self.assertEqual(kinds, ["trigger", "guard", "effect"])
        self.assertEqual(t.children, [])
        self.assertEqual((t.transition_source, t.transition_target, t.trigger_event, t.guard, t.effect),
                         (self.a, self.b, "go", "speed > 0", "log()"))

    def test_state_actions_and_runtime_callables(self):
        m = self.a.subaction("entry").owning_relationship
        self.assertIsInstance(m, StateSubactionMembership)
        self.assertEqual(m.state_subaction_kind, "entry")
        self.assertEqual((self.a.entry_action, self.b.do_action, self.b.exit_action),
                         ("lock()", "run()", "stop()"))
        seen = []
        self.t.effect = lambda ctx: seen.append(ctx)
        self.assertEqual(self.t.effect_actions, [])                 # callables are not model
        runner = self.sm.runner()
        runner.fire("go", speed=1)
        self.assertEqual(seen, [{"speed": 1}])
        self.t.guard = None
        self.assertEqual(self.t.guard_expressions, [])

    def test_round_trip(self):
        repo = Repository("R")
        repo.add(self.sm.owner)
        loaded = from_json(to_json(repo))
        t = loaded.by_id(self.t.element_id)
        self.assertEqual((t.transition_source.name, t.transition_target.name, t.trigger_event,
                          t.guard, t.effect), ("A", "B", "go", "speed > 0", "log()"))
        self.assertEqual(loaded.by_id(self.a.element_id).entry_action, "lock()")


class RequirementTests(unittest.TestCase):

    def test_id_and_text(self):
        r = RequirementDefinition(name="Range", req_id="R1", text="Range >= 400 km")
        self.assertEqual(r.declared_short_name, "R1")
        self.assertEqual(r.short_name, "R1")
        doc, = r.documentation
        self.assertIsInstance(doc, Documentation)
        self.assertEqual(doc.body, "Range >= 400 km")
        self.assertEqual(r.texts, ["Range >= 400 km"])
        self.assertEqual(r.annotations, [])                           # text is not "doc"
        r.add_annotation(Documentation("rationale-like note"))
        self.assertEqual(r.text, "Range >= 400 km")
        self.assertEqual(len(r.documentation), 2)
        r.annotations = []
        self.assertEqual(r.text, "Range >= 400 km")
        r.text = None
        self.assertEqual(r.documentation, [])

    def test_subject_actors_stakeholders_constraints(self):
        Vehicle = PartDefinition(name="Vehicle")
        driver, owner = PartUsage(name="driver"), PartUsage(name="owner")
        r = RequirementUsage(name="r")
        r.subject = Vehicle
        r.add_actor(driver)
        r.add_stakeholder(owner)
        self.assertIsInstance(r.subject_parameter.owning_relationship, SubjectMembership)
        self.assertIs(r.subject, Vehicle)
        self.assertEqual(r.subject_parameter.types, [Vehicle])
        self.assertIsInstance(r.actor_parameters[0].owning_relationship, ActorMembership)
        self.assertEqual(r.actors, [driver])
        self.assertIsInstance(r.stakeholder_parameters[0].owning_relationship, StakeholderMembership)
        self.assertEqual(r.stakeholders, [owner])
        free = ConstraintUsage(name="c1")
        elsewhere = ConstraintUsage(name="c2")
        PartDefinition(name="Holder").own(elsewhere)
        r.required_constraints = [free, elsewhere]
        self.assertIs(r.required_constraints[0], free)
        ref = r.required_constraints[1]
        m = ref.owning_relationship
        self.assertIsInstance(m, RequirementConstraintMembership)
        self.assertEqual(m.requirement_constraint_kind, "requirement")
        self.assertIs(m.referenced_constraint, elsewhere)
        r.add_constraint(ConstraintUsage(name="a1"), "assumption")
        self.assertEqual([c.name for c in r.assumed_constraints], ["a1"])
        self.assertEqual(r.children, [])


class ViewAndFeaturingTests(unittest.TestCase):

    def test_view_exposes(self):
        pkg = PartDefinition(name="P")
        a = PartUsage(name="a")
        pkg.own(a)
        v = ViewUsage(name="v")
        v.exposed = [a, pkg]
        self.assertIsInstance(v.owned_exposes[0], MembershipExpose)
        self.assertIsInstance(v.owned_exposes[1], NamespaceExpose)
        self.assertEqual(v.exposed, [a, pkg])
        self.assertIn(a, v.exposed_elements)
        self.assertEqual(v.owned_exposes[0].visibility, "protected")

    def test_featuring_type(self):
        T, U = Classifier("T"), Classifier("U")
        u = PartUsage(name="u")
        T.own(u)
        self.assertIs(u.featuring_type, T)
        free = PartUsage(name="free")
        free.featuring_type = U
        self.assertIsInstance(free.owned_type_featurings[0], TypeFeaturing)
        self.assertIs(free.featuring_type, U)
        self.assertEqual(free.featuring_types, [U])
        free.featuring_type = None
        self.assertEqual(free.owned_type_featurings, [])
        self.assertIsInstance(u.owning_relationship, OwningMembership)


if __name__ == "__main__":
    unittest.main()
