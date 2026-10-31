"""The registry-driven derived-property installer (kerml.derived, sysmlv2.derived)."""
import unittest

import sysmlv2  # noqa: F401 - installs the SysML derived properties
from kerml import Behavior, Comment, Documentation, Feature, LiteralBoolean, Package, Succession
from kerml import derived
from kerml import metamodel as mm
from kerml.expressions import Invocation
from kerml.namespaces import ElementFilterMembership
from sysmlv2 import (
    ActionUsage, AttributeUsage, ConcernUsage, ConnectionUsage, EnumerationDefinition,
    EnumerationUsage, FlowUsage, InterfaceUsage, ItemUsage, MetadataUsage, OccurrenceDefinition,
    OccurrenceUsage, PartDefinition, PartUsage, PortDefinition, PortUsage, RequirementDefinition,
    RequirementUsage, StateDefinition, StateUsage, TransitionUsage, Usage, UseCaseUsage,
    IncludeUseCaseUsage, ViewpointUsage,
)
from sysmlv2 import variability
from sysmlv2.definitions import AnalysisCaseUsage, Definition, ViewUsage
from sysmlv2.state_machines import StateMachineDefinition


def _installed(cls, name):
    return next((i for i in derived.installed() if i.cls is cls and i.name == name), None)


class InstallerRulesTests(unittest.TestCase):

    def test_counts(self):
        sysml = derived.installed("SysML")
        kerml = derived.installed("KerML")
        self.assertGreaterEqual(len([i for i in sysml if i.rule == "filter"]), 95)
        self.assertGreaterEqual(len([i for i in sysml if i.rule == "explicit"]), 40)
        self.assertGreaterEqual(len(kerml), 10)
        specs = [i.spec for i in derived.installed()]
        self.assertEqual(len(specs), len(set(specs)))

    def test_filter_bases_follow_the_subsetting_chain(self):
        i = _installed(Definition, "owned_parts")
        self.assertEqual((i.rule, i.base, i.type), ("filter", "owned_features", "PartUsage"))
        self.assertEqual(_installed(Usage, "nested_actions").base, "owned_features")
        self.assertEqual(_installed(PartUsage, "part_definitions").base, "types")
        self.assertEqual(_installed(Usage, "owning_definition").base, "owning_type")
        self.assertEqual(_installed(Definition, "directed_usages").base, "directed_features")
        # ownedMetadata = ownedMember->selectByKind(MetadataUsage): a base override.
        self.assertEqual(_installed(Definition, "owned_metadata").base, "owned_members")
        # enumeratedValue redefines variant, an explicit derivation.
        self.assertEqual(_installed(EnumerationDefinition, "enumerated_values").base, "variants")

    def test_descriptor(self):
        prop = vars(Definition)["owned_parts"]
        self.assertIsInstance(prop, derived.DerivedProperty)
        self.assertIs(Definition.owned_parts, prop)
        self.assertEqual(prop.spec, "Definition::ownedPart")
        self.assertIn("PartUsage", prop.__doc__)
        self.assertIn("Definition::ownedPart", repr(prop))
        self.assertIn("SubjectMembership", vars(RequirementUsage)["subject_parameter"].__doc__)

    def test_hand_written_code_wins(self):
        # StateUsage carries entry_action / do_action / exit_action as class attributes.
        self.assertIsNone(vars(StateUsage)["entry_action"])
        self.assertIsNone(_installed(StateUsage, "entry_action"))
        self.assertIsNotNone(_installed(StateDefinition, "entry_action"))
        # StateMachineDefinition keeps its own `states`.
        sm = StateMachineDefinition("SM")
        s = sm.add_state("A", is_initial=True)
        self.assertEqual(sm.states, [s])
        self.assertIsInstance(vars(StateMachineDefinition)["states"], property)
        # PortDefinition.is_conjugated and the KerML properties were not replaced.
        self.assertIsInstance(vars(PortDefinition)["is_conjugated"], property)

    def test_instance_attributes_shadow_installed_properties(self):
        inv = Invocation()
        self.assertIsNone(inv.function)                       # the compatibility attribute
        req = RequirementDefinition("R")
        self.assertEqual(req.required_constraints, [])       # the compatibility list
        shadowed = {(c.__name__, n) for c, n in derived.shadowed()}
        self.assertIn(("Invocation", "function"), shadowed)
        self.assertIn(("RequirementDefinition", "required_constraints"), shadowed)
        self.assertIn(("Feature", "multiplicity"), shadowed)
        self.assertNotIn(("Definition", "owned_parts"), shadowed)

    def test_install_is_idempotent(self):
        self.assertEqual(sysmlv2.derived.install_sysml(), [])
        self.assertEqual(derived.install_kerml(), [])

    def test_class_for(self):
        self.assertIs(derived.class_for("PartUsage"), PartUsage)
        self.assertIs(derived.class_for("Membership").__name__, "Membership")
        self.assertIsNone(derived.class_for("NoSuchMetaclass"))
        self.assertTrue(derived.is_kind(PartUsage(), "ItemUsage"))
        self.assertFalse(derived.is_kind(PartUsage(), "NoSuchMetaclass"))
        self.assertEqual(derived.select_by_kind([PartUsage(), ActionUsage()], "NoSuchMetaclass"), [])
        self.assertEqual(derived.enum_value(Feature().direction), "none")

    def test_report_lists_what_is_left(self):
        report = derived.report()
        self.assertIn("Usage::mayTimeVary", report)
        self.assertIn("TransitionUsage::source", report)
        self.assertIn("Expression::isModelLevelEvaluable", report)
        self.assertNotIn("Definition::ownedPart", report)
        self.assertNotIn("Element::owner", report)            # an instance attribute
        for spec, why in report.items():
            self.assertIn(why, ("no class", "no rule", "not generated"), spec)

    def test_every_metaclass_class_still_builds(self):
        for cls in mm.python_classes():
            if (cls.__module__.split(".")[0] in ("kerml", "sysmlv2") and "kind" in vars(cls)
                    and mm.is_metaclass(cls.kind) and not cls.__name__.startswith("_")):
                with self.subTest(cls=cls.__qualname__):
                    cls()


class FilterTests(unittest.TestCase):

    def _definition(self):
        d = PartDefinition("Vehicle")
        engine = PartUsage("engine")
        mass = AttributeUsage("mass")
        port = PortUsage("fuel")
        drive = ActionUsage("drive")
        state = StateUsage("on")
        conn = ConnectionUsage("c")
        plain = Feature("plain")
        for x in (engine, mass, port, drive, state, conn, plain):
            d.own(x)
        return d, engine, mass, port, drive, state, conn, plain

    def test_definition_filters(self):
        d, engine, mass, port, drive, state, conn, plain = self._definition()
        self.assertEqual(d.owned_usages, [engine, mass, port, drive, state, conn])
        self.assertEqual(d.owned_parts, [engine])
        self.assertEqual(d.owned_items, [engine])
        self.assertEqual(d.owned_occurrences, [engine, port, drive, state])
        self.assertEqual(d.owned_attributes, [mass])
        self.assertEqual(d.owned_ports, [port])
        self.assertEqual(d.owned_actions, [drive, state])
        self.assertEqual(d.owned_states, [state])
        self.assertEqual(d.owned_flows, [])
        self.assertEqual(d.owned_references, [])              # no ReferenceUsage class yet
        self.assertEqual(d.usages, [engine, mass, port, drive, state, conn])
        sub = PartDefinition("Car")
        sub.specialize(d)
        self.assertEqual(sub.owned_usages, [])
        self.assertEqual(sub.usages, [engine, mass, port, drive, state, conn])   # inherited

    def test_usage_filters_and_owners(self):
        vehicle = PartUsage("vehicle")
        wheel = PartUsage("wheel")
        flow = FlowUsage("f")
        vehicle.own(wheel)
        vehicle.own(flow)
        self.assertEqual(vehicle.nested_usages, [wheel, flow])
        self.assertEqual(vehicle.nested_parts, [wheel])
        self.assertEqual(vehicle.nested_flows, [flow])
        self.assertEqual(vehicle.nested_actions, [flow])
        self.assertIs(wheel.owning_usage, vehicle)
        self.assertIsNone(wheel.owning_definition)
        d = PartDefinition("D")
        d.own(vehicle)
        self.assertIs(vehicle.owning_definition, d)
        self.assertIsNone(vehicle.owning_usage)

    def test_definitions_of_usages(self):
        engine_def = PartDefinition("Engine")
        occ_def = OccurrenceDefinition("O", is_individual=True)
        u = PartUsage("e", typed_by=engine_def)
        u.add_type(occ_def)
        self.assertEqual(u.definitions, [engine_def, occ_def])
        self.assertEqual(u.part_definitions, [engine_def])
        # itemDefinition: the types that are Structures (PartDefinition becomes one with A3).
        self.assertEqual(_installed(ItemUsage, "item_definitions").type, "Structure")
        self.assertIs(u.individual_definition, occ_def)
        self.assertIsNone(PartUsage(typed_by=engine_def).individual_definition)
        behavior = Behavior("B")        # (ActionDefinition becomes a Behavior with A3)
        a = ActionUsage("a", typed_by=behavior)
        self.assertEqual(a.action_definitions, [behavior])
        self.assertEqual(InterfaceUsage().interface_definitions, [])

    def test_owned_metadata_filters_owned_members(self):
        d = PartDefinition("D")
        md = MetadataUsage("m")
        d.own(md)
        self.assertEqual(d.owned_metadata, [md])
        self.assertEqual(ItemUsage("i").nested_metadata, [])

    def test_variants_and_enumerations(self):
        colors = EnumerationDefinition("Color")
        red, green = EnumerationUsage("red"), EnumerationUsage("green")
        variability.add_variant(colors, red)
        variability.add_variant(colors, green)
        colors.own(AttributeUsage("other"))
        self.assertEqual(colors.variants, [red, green])
        self.assertEqual(colors.enumerated_values, [red, green])
        self.assertEqual(EnumerationUsage(typed_by=colors).enumeration_definition, colors)
        usage = PartUsage("u")
        self.assertEqual(usage.variants, [])

    def test_conjugated_port_definition_is_a_single_filter(self):
        port = PortDefinition("P")
        self.assertIsNone(port.conjugated_port_definition)

    def test_transition_succession(self):
        t = TransitionUsage("t")
        self.assertIsNone(t.succession)
        s = Succession()
        t.own(s)
        self.assertIs(t.succession, s)


class ExplicitDerivationTests(unittest.TestCase):

    def test_requirement_navigation_without_a3_memberships(self):
        r = RequirementUsage("r")
        self.assertIsNone(r.subject_parameter)
        self.assertEqual(r.actor_parameters, [])
        self.assertEqual(r.stakeholder_parameters, [])
        self.assertEqual(r.assumed_constraints, [])
        self.assertEqual(r.required_constraints, [])
        self.assertEqual(TransitionUsage().trigger_actions, [])
        self.assertIsNone(StateDefinition().entry_action)

    def test_requirement_texts(self):
        r = RequirementUsage("r")
        doc = Documentation("The vehicle shall stop.")
        r.add_annotation(doc)
        r.add_annotation(Comment("not a doc"))
        self.assertEqual(r.texts, ["The vehicle shall stop."])

    def test_included_use_cases(self):
        fly = UseCaseUsage("fly")
        mission = UseCaseUsage("mission")
        mission.own(IncludeUseCaseUsage(use_case_included=fly))
        mission.own(UseCaseUsage("other"))
        self.assertEqual(mission.included_use_cases, [fly])

    def test_views(self):
        view = ViewUsage("v")
        cond = LiteralBoolean(True)
        view.add_relationship(ElementFilterMembership(view, cond))
        self.assertEqual(view.view_conditions, [cond])
        vp = ViewpointUsage("vp", is_composite=True)
        ref_vp = ViewpointUsage("ref")
        view.own(vp)
        view.own(ref_vp)
        self.assertEqual(view.satisfied_viewpoints, [vp])
        self.assertIsNone(view.view_rendering)
        self.assertEqual(ViewpointUsage().viewpoint_stakeholders, [])

    def test_analysis_case_result_expression(self):
        from kerml import ResultExpressionMembership
        case = AnalysisCaseUsage("a")
        self.assertIsNone(case.result_expression)
        body = LiteralBoolean(True)
        case.own(body, membership=ResultExpressionMembership)
        self.assertIs(case.result_expression, body)

    def test_framed_concerns_of_definitions(self):
        from sysmlv2 import FramedConcernMembership
        req = RequirementDefinition("R")
        c = ConcernUsage("c")
        req.own(c, membership=FramedConcernMembership)
        self.assertEqual(req.framed_concerns, [c])

    def test_package_has_no_installed_properties(self):
        self.assertFalse(any(isinstance(v, derived.DerivedProperty) for v in vars(Package).values()))


if __name__ == "__main__":
    unittest.main()
