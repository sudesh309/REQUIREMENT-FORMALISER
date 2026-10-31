"""The remaining SysML metaclasses (Phase 1 B2).

Ports (conjugation), flows and connectors as usages, action usages and control
nodes, asserted / satisfied / included usages, the objective, framed concern,
requirement verification, variant and view rendering memberships, renderings.
"""
import unittest

from kerml import (
    BindingConnector, Feature, FeatureDirection, FeatureTyping, Interaction, Invariant,
    LiteralBoolean, LiteralInteger, Succession, SuccessionFlow,
)
from kerml import Flow, FlowEnd, derived
from kerml import metamodel as mm
from kerml.features import ReferenceSubsetting
from sysmlv2 import (
    ActionDefinition, ActionUsage, AssertConstraintUsage, AssignmentActionUsage,
    BindingConnectorAsUsage, ConcernUsage, ConjugatedPortDefinition, ConjugatedPortTyping,
    ConstraintUsage, ControlNode, DecisionNode, EventOccurrenceUsage, ExhibitStateUsage,
    FlowDefinition, FlowUsage, ForLoopActionUsage, ForkNode, FramedConcernMembership,
    IfActionUsage, IncludeUseCaseUsage, JoinNode, LoopActionUsage, MergeNode, ObjectiveMembership,
    OccurrenceUsage, PartDefinition, PartUsage, PerformActionUsage, PortConjugation, PortDefinition,
    PortUsage, RenderingDefinition, RenderingUsage, RequirementUsage, RequirementVerificationMembership,
    SatisfyRequirementUsage, SendActionUsage, StateUsage, SuccessionAsUsage, SuccessionFlowUsage,
    TerminateActionUsage, Usage, UseCaseUsage, VariantMembership, ViewRenderingMembership,
    WhileLoopActionUsage,
)
from sysmlv2 import actions, cases, flows, ports, variability, views

NEW_MODULES = (actions, cases, flows, ports, variability, views)

#: Spec supertypes that are stream A3 metaclasses (ConnectorAsUsage, RequirementConstraintMembership):
#: allowed to be missing from the Python ancestors only while their class does not exist.
A3_SUPERTYPES = {"ConnectorAsUsage", "RequirementConstraintMembership"}


def _new_classes():
    out = []
    for mod in NEW_MODULES:
        for name in mod.__all__:
            obj = getattr(mod, name)
            if isinstance(obj, type) and "kind" in vars(obj):
                out.append(obj)
    return out


class RegistryConformanceTests(unittest.TestCase):

    def test_new_classes_construct_and_name_their_metaclass(self):
        classes = _new_classes()
        self.assertEqual(len(classes), 33)
        for cls in classes:
            with self.subTest(cls=cls.__name__):
                self.assertEqual(mm.metaclass(cls.kind).language, "SysML")
                self.assertIs(derived.class_for(cls.kind), cls)
                self.assertEqual(cls().metaclass_name(), cls.kind)

    def test_spec_supertypes_are_python_ancestors(self):
        for cls in _new_classes():
            kinds = {vars(a).get("kind") for a in cls.__mro__[1:]}
            for s in mm.metaclass(cls.kind).supertypes:
                with self.subTest(cls=cls.__name__, supertype=s):
                    if s in A3_SUPERTYPES and derived.class_for(s) is None:
                        continue   # TODO(A3 merge): the base is added when the class exists
                    self.assertIn(s, kinds)

    def test_owned_properties_are_present(self):
        for cls in _new_classes():
            inst = cls()
            for p in mm.properties(cls.kind, inherited=False):
                with self.subTest(prop=p.qualified_name):
                    self.assertTrue(hasattr(inst, mm.python_name(p)))

    def test_only_a3_metaclasses_are_missing(self):
        missing = {m.name for m in mm.all_metaclasses("SysML") if derived.class_for(m.name) is None}
        a3 = {"SubjectMembership", "ActorMembership", "StakeholderMembership",
              "RequirementConstraintMembership", "TransitionFeatureMembership",
              "StateSubactionMembership", "Expose", "MembershipExpose", "NamespaceExpose",
              "ConnectorAsUsage", "ReferenceUsage", "AcceptActionUsage",
              "TriggerInvocationExpression"}
        self.assertLessEqual(missing, a3)


class PortTests(unittest.TestCase):

    def test_conjugated_port_definition(self):
        port = PortDefinition("FuelPort")
        self.assertIsNone(port.conjugated_port_definition)
        cpd = ports.conjugated_port_definition(port)
        self.assertIsInstance(cpd, ConjugatedPortDefinition)
        self.assertIs(ports.conjugated_port_definition(port), cpd)           # created once
        self.assertIs(port.conjugated_port_definition, cpd)                  # derived
        self.assertIs(cpd.original_port_definition, port)
        self.assertIsInstance(cpd.owned_port_conjugator, PortConjugation)
        self.assertIs(cpd.owned_port_conjugator.original_port_definition, port)
        self.assertIs(cpd.owned_port_conjugator.conjugated_port_definition, cpd)
        self.assertTrue(cpd.is_conjugated)
        self.assertEqual(cpd.name, "~FuelPort")
        self.assertEqual(cpd.qualified_name, "FuelPort::'~FuelPort'")
        cpd.name = "Reversed"
        self.assertEqual(cpd.name, "Reversed")
        self.assertIsNone(ConjugatedPortDefinition().name)
        with self.assertRaises(ValueError):
            ports.conjugated_port_definition(cpd)
        self.assertIsNone(ports.conjugated_port_definition(PortDefinition(), create=False))

    def test_conjugated_port_typing(self):
        port = PortDefinition("P")
        p = PortUsage("p")
        typing = ports.type_by_conjugate(p, port)
        self.assertIsInstance(typing, ConjugatedPortTyping)
        self.assertIsInstance(typing, FeatureTyping)
        self.assertIs(typing.conjugated_port_definition, port.conjugated_port_definition)
        self.assertIs(typing.port_definition, port)
        self.assertEqual(p.types, [port.conjugated_port_definition])
        typing.conjugated_port_definition = None
        self.assertIsNone(typing.port_definition)

    def test_port_usage_definitions(self):
        port = PortDefinition("P")
        self.assertEqual(PortUsage("p", typed_by=port).port_definitions, [port])


class FlowTests(unittest.TestCase):

    def test_flow_usage_is_a_flow_and_an_action(self):
        fd = FlowDefinition("FuelFlow")
        self.assertIsInstance(fd, Interaction)
        self.assertIsInstance(fd, ActionDefinition)
        fu = FlowUsage("f", typed_by=fd)
        self.assertIsInstance(fu, Flow)
        self.assertIsInstance(fu, ActionUsage)
        self.assertEqual(fu.flow_definitions, [fd])
        self.assertEqual(fu.interactions, [fd])
        a, b = PartUsage("a"), PartUsage("b")
        end = fu.add_flow_end(a)
        fu.add_flow_end(b)
        self.assertIsInstance(end, FlowEnd)
        self.assertEqual(fu.related_features, [a, b])

    def test_flow_definition_ends(self):
        fd = FlowDefinition("F")
        e1 = Usage("source", is_end=True)
        e2 = Usage("target", is_end=True)
        fd.own(e1)
        fd.own(e2)
        fd.own(Usage("other"))
        self.assertEqual(fd.flow_ends, [e1, e2])

    def test_connectors_as_usages(self):
        sfu = SuccessionFlowUsage()
        self.assertIsInstance(sfu, SuccessionFlow)
        self.assertIsInstance(sfu, FlowUsage)
        bind = BindingConnectorAsUsage(related_features=[Feature("x"), Feature("y")])
        self.assertIsInstance(bind, BindingConnector)
        self.assertIsInstance(bind, Usage)
        self.assertEqual([f.name for f in bind.related_features], ["x", "y"])
        first = SuccessionAsUsage()
        self.assertIsInstance(first, Succession)
        self.assertIsInstance(first, Usage)
        owner = PartDefinition("P")
        owner.own(first)
        self.assertIn(first, owner.owned_usages)


class ActionTests(unittest.TestCase):

    def test_operations(self):
        act = ActionUsage("a")
        p1 = actions.add_parameter(act, value=1)
        p2 = actions.add_parameter(act)
        act.own(Feature("local"))
        self.assertEqual(actions.input_parameters(act), [p1, p2])
        self.assertIs(actions.input_parameter(act, 2), p2)
        self.assertIsNone(actions.input_parameter(act, 3))
        self.assertIsNone(actions.input_parameter(act, 0))
        self.assertEqual(actions.argument(act, 1).value, 1)
        self.assertIsNone(actions.argument(act, 2))
        self.assertIsNone(actions.argument(act, 3))
        self.assertIs(p1.direction, FeatureDirection.IN)

    def test_send(self):
        payload = LiteralInteger(42)
        send = SendActionUsage(payload=payload, receiver="bus")
        self.assertIs(send.payload_argument, payload)
        self.assertIsNone(send.sender_argument)
        self.assertEqual(send.receiver_argument.value, "bus")
        self.assertEqual([p.name for p in actions.input_parameters(send)],
                         ["payload", "sender", "receiver"])
        self.assertIsNone(SendActionUsage().payload_argument)

    def test_assignment(self):
        speed = Feature("speed")
        assign = AssignmentActionUsage(referent=speed, target="vehicle", value=LiteralInteger(3))
        self.assertIs(assign.referent, speed)
        self.assertEqual(assign.target_argument.value, "vehicle")
        self.assertEqual(assign.value_expression.value, 3)
        self.assertIsNone(speed.owner)                     # referenced, not owned
        self.assertIsNone(AssignmentActionUsage().referent)

    def test_terminate(self):
        t = TerminateActionUsage(terminated_occurrence=LiteralInteger(1))
        self.assertEqual(t.terminated_occurrence_argument.value, 1)

    def test_if(self):
        cond = LiteralBoolean(True)
        then, other = ActionUsage("then"), ActionUsage("other")
        if_ = IfActionUsage(if_argument=cond, then_action=then, else_action=other)
        self.assertIs(if_.if_argument, cond)
        self.assertIs(if_.then_action, then)
        self.assertIs(if_.else_action, other)
        self.assertIs(then.owner, if_)
        no_else = IfActionUsage(if_argument=cond, then_action=ActionUsage())
        self.assertIsNone(no_else.else_action)

    def test_loops(self):
        cond, until = LiteralBoolean(True), LiteralBoolean(False)
        body = ActionUsage("body")
        w = WhileLoopActionUsage(while_argument=cond, body_action=body, until_argument=until)
        self.assertIsInstance(w, LoopActionUsage)
        self.assertIs(w.while_argument, cond)
        self.assertIs(w.body_action, body)
        self.assertIs(w.until_argument, until)
        var = Usage("i", is_reference=True)
        body2 = ActionUsage("b")
        f = ForLoopActionUsage(loop_variable=var, seq=LiteralInteger(3), body_action=body2)
        self.assertIs(f.loop_variable, var)
        self.assertEqual(f.seq_argument.value, 3)
        self.assertIs(f.body_action, body2)
        self.assertIsNone(ForLoopActionUsage().loop_variable)

    def test_control_nodes(self):
        for cls in (DecisionNode, ForkNode, JoinNode, MergeNode):
            self.assertIsInstance(cls(), ControlNode)
            self.assertIsInstance(cls(), ActionUsage)

    def test_event_occurrence(self):
        e = EventOccurrenceUsage("e")
        self.assertIs(e.event_occurrence, e)
        self.assertTrue(e.is_reference)
        e.is_reference = False                             # ignored: always referential
        self.assertTrue(e.is_reference)
        occ = OccurrenceUsage("occ")
        ref = EventOccurrenceUsage(event_occurrence=occ)
        self.assertIs(ref.event_occurrence, occ)
        self.assertIsInstance(ref.owned_reference_subsetting, ReferenceSubsetting)
        self.assertIsNone(EventOccurrenceUsage(event_occurrence=Feature("plain")).event_occurrence)

    def test_perform_exhibit(self):
        act = ActionUsage("drive")
        perform = PerformActionUsage(performed_action=act)
        self.assertIs(perform.performed_action, act)
        self.assertIs(perform.event_occurrence, act)
        own = PerformActionUsage("p")
        self.assertIs(own.performed_action, own)
        state = StateUsage("on")
        exhibit = ExhibitStateUsage(exhibited_state=state)
        self.assertIs(exhibit.exhibited_state, state)
        self.assertIsNone(ExhibitStateUsage(exhibited_state=act).exhibited_state)
        self.assertIsInstance(exhibit, StateUsage)
        self.assertIsInstance(exhibit, PerformActionUsage)

    def test_perform_chain_reference(self):
        part = PartUsage("vehicle")
        drive = ActionUsage("drive")
        part.own(drive)
        chain = Feature()
        chain.chain(part, drive)
        perform = PerformActionUsage()
        perform.reference_subset(chain)
        self.assertIs(perform.performed_action, drive)     # the feature target of the chain


class CaseTests(unittest.TestCase):

    def test_assert_constraint(self):
        c = ConstraintUsage("c")
        a = AssertConstraintUsage(asserted_constraint=c, is_negated=True)
        self.assertIsInstance(a, Invariant)
        self.assertTrue(a.is_negated)
        self.assertIs(a.asserted_constraint, c)
        own = AssertConstraintUsage()
        self.assertIs(own.asserted_constraint, own)
        self.assertIsNone(AssertConstraintUsage(asserted_constraint=Feature("f")).asserted_constraint)

    def test_satisfy_requirement(self):
        r = RequirementUsage("r")
        s = SatisfyRequirementUsage(satisfied_requirement=r)
        self.assertIs(s.satisfied_requirement, r)
        self.assertIs(s.asserted_constraint, r)
        self.assertIsInstance(s, AssertConstraintUsage)
        self.assertIsNone(s.satisfying_feature)        # no subject parameter yet

    def test_include_use_case(self):
        uc = UseCaseUsage("fly")
        inc = IncludeUseCaseUsage(use_case_included=uc)
        self.assertIs(inc.use_case_included, uc)
        self.assertIs(inc.performed_action, uc)
        self.assertIsInstance(inc, PerformActionUsage)

    def test_framed_concern_membership(self):
        req = RequirementUsage("r")
        concern = ConcernUsage("c")
        req.own(concern, membership=FramedConcernMembership)
        m = concern.owning_relationship
        self.assertEqual(m.requirement_constraint_kind, "requirement")
        m.requirement_constraint_kind = "requirement"
        with self.assertRaises(ValueError):
            m.requirement_constraint_kind = "assumption"
        self.assertIs(m.owned_concern, concern)
        self.assertIs(m.referenced_concern, concern)
        shared = ConcernUsage("shared")
        ref = ConcernUsage()
        ref.reference_subset(shared)
        req.own(ref, membership=FramedConcernMembership)
        self.assertIs(ref.owning_relationship.referenced_concern, shared)
        self.assertEqual(req.framed_concerns, [concern, ref])

    def test_verification_and_objective(self):
        from sysmlv2.definitions import VerificationCaseUsage
        case = VerificationCaseUsage("vc")
        objective = RequirementUsage("obj")
        case.own(objective, membership=ObjectiveMembership)
        self.assertIs(objective.owning_relationship.owned_objective_requirement, objective)
        self.assertIs(case.objective_requirement, objective)
        target = RequirementUsage("target")
        verified = RequirementUsage()
        verified.reference_subset(target)
        objective.own(verified, membership=RequirementVerificationMembership)
        m = verified.owning_relationship
        self.assertIs(m.owned_requirement, verified)
        self.assertIs(m.verified_requirement, target)
        self.assertEqual(case.verified_requirements, [target])


class MembershipTests(unittest.TestCase):

    def test_variant_membership(self):
        variation = PartDefinition("Engine", is_variation=True)
        v6 = PartUsage("v6")
        m = variability.add_variant(variation, v6)
        self.assertIsInstance(m, VariantMembership)
        self.assertIs(m.owned_variant_usage, v6)
        self.assertEqual(variation.variants, [v6])
        self.assertEqual(variation.variant_memberships, [m])
        self.assertTrue(v6.is_variant)

    def test_view_rendering_membership(self):
        from sysmlv2.definitions import ViewDefinition
        view = ViewDefinition("V")
        rendering = RenderingUsage("asTree")
        view.own(rendering, membership=ViewRenderingMembership)
        m = rendering.owning_relationship
        self.assertIs(m.owned_rendering, rendering)
        self.assertIs(m.referenced_rendering, rendering)
        self.assertIs(view.view_rendering, rendering)
        shared = RenderingUsage("shared")
        ref = RenderingUsage()
        ref.reference_subset(shared)
        view2 = ViewDefinition("W")
        view2.own(ref, membership=ViewRenderingMembership)
        self.assertIs(view2.view_rendering, shared)

    def test_rendering_definition(self):
        rd = RenderingDefinition("R")
        self.assertIsInstance(rd, PartDefinition)
        ru = RenderingUsage("r", typed_by=rd)
        self.assertIs(ru.rendering_definition, rd)
        self.assertEqual(ru.part_definitions, [rd])
        holder = RenderingDefinition("H")
        holder.own(ru)
        self.assertEqual(holder.renderings, [ru])
        self.assertEqual(holder.owned_renderings, [ru])
        self.assertEqual(holder.owned_parts, [ru])


if __name__ == "__main__":
    unittest.main()
