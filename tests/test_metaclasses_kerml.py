"""The remaining KerML Kernel metaclasses (Phase 1 B2).

Interactions (AssociationStructure, Interaction, Flow, FlowEnd, PayloadFeature,
SuccessionFlow), metadata (Metaclass, MetadataFeature), ResultExpressionMembership
and the instantiation / invocation / operator / metadata access expressions.
"""
import unittest

import sysmlv2.metamodel  # noqa: F401 - registers the SysML metaclasses
from kerml import (
    AssociationStructure, Behavior, BindingConnector, BooleanExpression, Classifier, CollectExpression,
    Connector, ConstructorExpression, Expression, Feature, FeatureChainExpression, FeatureDirection,
    FeatureMembership, FeatureReferenceExpression, FeatureValue, Flow, FlowEnd, Function,
    IndexExpression, InstantiationExpression, Interaction, InvocationExpression, LiteralInteger,
    Membership, Metaclass, MetadataAccessExpression, MetadataFeature, Multiplicity,
    OperatorExpression,
    OwningMembership, Package, ParameterMembership, PayloadFeature, Predicate,
    ResultExpressionMembership, ReturnParameterMembership, SelectExpression, Step, Structure,
    Succession, SuccessionFlow, Type,
)
from kerml import derived, interactions, metadata, functions, operator_expressions
from kerml import metamodel as mm
from kerml.elements import AnnotatingElement, Comment

NEW_MODULES = (interactions, metadata, functions, operator_expressions)


def _new_classes():
    out = []
    for mod in NEW_MODULES:
        for name in mod.__all__:
            obj = getattr(mod, name)
            if isinstance(obj, type) and "kind" in vars(obj):
                out.append(obj)
    return out


class RegistryConformanceTests(unittest.TestCase):
    """Every new class: a no-argument constructor, its spec supertypes and properties."""

    def test_every_kernel_metaclass_has_a_class(self):
        missing = [m.name for m in mm.all_metaclasses("KerML") if derived.class_for(m.name) is None]
        self.assertEqual(missing, [])

    def test_new_classes_construct_and_name_their_metaclass(self):
        classes = _new_classes()
        self.assertEqual(len(classes), 18)
        for cls in classes:
            with self.subTest(cls=cls.__name__):
                self.assertTrue(mm.is_metaclass(cls.kind))
                self.assertEqual(mm.metaclass(cls.kind).language, "KerML")
                self.assertIs(derived.class_for(cls.kind), cls)
                e = cls()
                self.assertEqual(e.metaclass_name(), cls.kind)

    def test_spec_supertypes_are_python_ancestors(self):
        for cls in _new_classes():
            kinds = {vars(a).get("kind") for a in cls.__mro__[1:]}
            for s in mm.metaclass(cls.kind).supertypes:
                with self.subTest(cls=cls.__name__, supertype=s):
                    self.assertIn(s, kinds)

    def test_owned_properties_are_present(self):
        for cls in _new_classes():
            inst = cls()
            for p in mm.properties(cls.kind, inherited=False):
                with self.subTest(prop=p.qualified_name):
                    self.assertTrue(hasattr(inst, mm.python_name(p)))

    def test_operator_defaults(self):
        self.assertIsNone(OperatorExpression().operator)
        self.assertEqual(OperatorExpression(operator="+").operator, "+")
        self.assertEqual(FeatureChainExpression().operator, ".")
        self.assertEqual(SelectExpression().operator, "select")
        self.assertEqual(CollectExpression().operator, "collect")
        self.assertEqual(IndexExpression().operator, "#")


class FlowTests(unittest.TestCase):

    def _model(self):
        root = Package("M")
        system = Structure("System")
        root.own(system)
        out_port = Feature("out1", direction=FeatureDirection.OUT)
        in_port = Feature("in1", direction=FeatureDirection.IN)
        a, b = Feature("a"), Feature("b")
        for f in (a, b):
            system.own(f)
        flow = Flow("f")
        system.own(flow)
        return root, system, a, b, out_port, in_port, flow

    def test_flow_ends_and_io_features(self):
        root, system, a, b, out1, in1, flow = self._model()
        src = flow.add_flow_end(a, out1)
        tgt = flow.add_flow_end(b, in1)
        self.assertIsInstance(src, FlowEnd)
        self.assertTrue(src.is_end)
        self.assertEqual(flow.flow_ends, [src, tgt])
        self.assertEqual(flow.connector_ends, [src, tgt])
        self.assertEqual(flow.related_features, [a, b])
        self.assertIs(flow.source, a)
        self.assertIs(flow.target, b)
        self.assertTrue(flow.source_output_feature.redefines(out1))
        self.assertTrue(flow.target_input_feature.redefines(in1))
        # Connector ends (and so flow ends) stay out of the application tree.
        self.assertNotIn(src, flow.children)

    def test_flow_without_io_features(self):
        flow = Flow()
        self.assertEqual(flow.flow_ends, [])
        self.assertIsNone(flow.source_output_feature)
        self.assertIsNone(flow.target_input_feature)
        flow.add_flow_end(Feature("x"))
        self.assertIsNone(flow.source_output_feature)
        self.assertIsNone(flow.target_input_feature)

    def test_payload(self):
        flow = Flow()
        self.assertIsNone(flow.payload_feature)
        self.assertEqual(flow.payload_types, [])
        fuel = Classifier("Fuel")
        payload = flow.set_payload(fuel)
        self.assertIsInstance(payload, PayloadFeature)
        self.assertIs(flow.payload_feature, payload)
        self.assertEqual(flow.payload_types, [fuel])
        water = Classifier("Water")
        flow.set_payload(water)
        self.assertEqual(flow.payload_types, [water])
        self.assertEqual(len([f for f in flow.owned_features if isinstance(f, PayloadFeature)]), 1)

    def test_interactions_type_flows(self):
        transfer = Interaction("Transfer")
        flow = Flow(typed_by=transfer)
        self.assertEqual(flow.interactions, [transfer])
        self.assertEqual(flow.behaviors, [transfer])
        self.assertEqual(flow.associations, [transfer])
        self.assertIsInstance(transfer, Behavior)

    def test_flow_is_a_step_and_a_connector(self):
        flow = Flow()
        self.assertIsInstance(flow, Connector)
        self.assertIsInstance(flow, Step)
        p = Feature("p", direction=FeatureDirection.IN)
        flow.own(p)
        self.assertIsInstance(p.owning_relationship, ParameterMembership)

    def test_succession_flow(self):
        sf = SuccessionFlow()
        self.assertIsInstance(sf, Succession)
        self.assertIsInstance(sf, Flow)
        end = sf.add_flow_end(Feature("x"))
        self.assertIsInstance(end, FlowEnd)

    def test_association_structure_related_types(self):
        link = AssociationStructure("Link")
        a_type, b_type = Classifier("A"), Classifier("B")
        e1 = Feature("e1", typed_by=a_type, is_end=True)
        e2 = Feature("e2", typed_by=b_type, is_end=True)
        link.own(e1)
        link.own(e2)
        self.assertIsInstance(link, Structure)
        self.assertEqual(link.association_ends, [e1, e2])
        self.assertEqual(link.related_types, [a_type, b_type])
        self.assertIs(link.source_type, a_type)
        self.assertEqual(link.target_types, [b_type])
        self.assertIsNone(AssociationStructure().source_type)
        self.assertEqual(AssociationStructure().target_types, [])


class MetadataTests(unittest.TestCase):

    def test_metaclass_of_a_metadata_feature(self):
        level = Metaclass("SecurityLevel")
        other = Classifier("Other")
        mf = MetadataFeature(typed_by=other)
        self.assertIsNone(mf.metaclass)
        mf.add_type(level)
        self.assertIs(mf.metaclass, level)

    def test_annotate_a_namespace_and_another_element(self):
        pkg = Package("P")
        part = Structure("S")
        pkg.own(part)
        mf = MetadataFeature(typed_by=Metaclass("M"))
        metadata.annotate(part, mf)
        self.assertIs(type(mf.owning_relationship), OwningMembership)
        self.assertEqual(mf.annotated_elements, [part])
        self.assertIn(mf, part.owned_members)
        self.assertNotIn(mf, part.children)          # annotating elements are not tree children
        self.assertIn(mf, part.annotations)
        rel_target = Feature("x")
        mf2 = MetadataFeature()
        metadata.annotate(rel_target, mf2)
        self.assertEqual(mf2.annotated_elements, [rel_target])

    def test_about(self):
        a, b = Structure("A"), Structure("B")
        mf = MetadataFeature(about=[a, b])
        self.assertEqual(mf.annotated_elements, [a, b])


def _library_root():
    """A model whose own root holds BaseFunctions::'+' (found by global resolution)."""
    root = Package("Model")
    base = Package("BaseFunctions")
    root.own(base)
    plus = Function("+")
    base.own(plus)
    x = Feature("x", direction=FeatureDirection.IN)
    y = Feature("y", direction=FeatureDirection.IN)
    plus.own(x)
    plus.own(y)
    ret = Feature("result", direction=FeatureDirection.OUT)
    ret.parameter_kind = "return"
    plus.own(ret)
    return root, plus, x, y, ret


class ExpressionTests(unittest.TestCase):

    def test_result_expression_membership(self):
        fn = Function("f")
        body = LiteralInteger(1)
        fn.own(body, membership=ResultExpressionMembership)
        m = body.owning_relationship
        self.assertIsInstance(m, ResultExpressionMembership)
        self.assertIs(m.owned_result_expression, body)
        self.assertIs(m.owned_member_feature, body)

    def test_instantiated_type_is_first_non_feature_membership(self):
        t = Classifier("T")
        e = InvocationExpression(instantiated_type=t)
        self.assertIs(e.instantiated_type, t)
        self.assertIs(type(e.owned_memberships[0]), Membership)     # not owning the type
        self.assertIsNone(t.owner)
        self.assertIsNone(InvocationExpression().instantiated_type)
        self.assertEqual(InstantiationExpression().arguments, [])

    def test_invocation_arguments_follow_the_inputs_of_the_type(self):
        root, plus, x, y, _ret = _library_root()
        inv = InvocationExpression(instantiated_type=plus)
        root.own(inv)
        a2 = inv.add_argument(2, parameter=y)
        a1 = inv.add_argument(1)                 # takes the next free input: x
        self.assertTrue(a1.redefines(x))
        self.assertTrue(a2.redefines(y))
        self.assertIsInstance(a1.owning_relationship, ParameterMembership)
        self.assertEqual([v.value for v in inv.arguments], [1, 2])   # in the order of the inputs
        fv = next(r for r in a1.owned_relationships if isinstance(r, FeatureValue))
        self.assertIs(inv.arguments[0], fv.value)

    def test_invocation_arguments_without_a_type(self):
        inv = InvocationExpression()
        inv.add_argument(5)
        inv.add_argument(LiteralInteger(6))
        self.assertEqual([v.value for v in inv.arguments], [5, 6])
        p = Feature("p", direction=FeatureDirection.IN)
        p.default_value = 7                      # a literal value is materialized
        inv.own(p)
        self.assertEqual([v.value for v in inv.arguments], [5, 6, 7])

    def test_operator_expression_resolves_its_operator(self):
        root, plus, *_ = _library_root()
        op = OperatorExpression(operator="+")
        root.own(op)
        self.assertIs(op.instantiated_type, plus)
        self.assertIsNone(OperatorExpression(operator="-").instantiated_type)
        op.add_argument(1)
        op.add_argument(2)
        self.assertEqual([v.value for v in op.arguments], [1, 2])

    def test_constructor_expression(self):
        point = Classifier("Point")
        px, py = Feature("x"), Feature("y")
        point.own(px)
        point.own(py)
        ctor = ConstructorExpression(instantiated_type=point)
        self.assertIsNone(operator_expressions.result_parameter(ctor))
        ctor.add_argument(4, feature=py)
        ctor.add_argument(3, feature=px)
        result = ctor.result
        self.assertIsInstance(result.owning_relationship, ReturnParameterMembership)
        self.assertIs(ctor.ensure_result(), result)
        self.assertEqual([v.value for v in ctor.arguments], [3, 4])

    def test_feature_chain_expression(self):
        target = Feature("speed")
        chain = FeatureChainExpression(target_feature=target)
        self.assertIs(chain.target_feature, target)
        self.assertIsNone(chain.source_target_feature())
        source = Feature("source", direction=FeatureDirection.IN)
        inner = Feature("target")
        source.own(inner)
        chain.own(source)
        self.assertIs(chain.source_target_feature(), inner)
        self.assertIs(chain.target_feature, target)       # parameters are skipped
        self.assertIsNone(FeatureChainExpression().target_feature)

    def test_metadata_access_expression(self):
        el = Structure("S")
        mae = MetadataAccessExpression(referenced_element=el)
        self.assertIs(mae.referenced_element, el)
        self.assertIsNone(MetadataAccessExpression().referenced_element)
        mae2 = MetadataAccessExpression()
        mae2.own(Feature("f"))                            # a FeatureMembership is skipped
        self.assertIsNone(mae2.referenced_element)


class KermlDerivedTests(unittest.TestCase):
    """Derived properties of existing KerML classes installed by kerml.derived."""

    def test_expression_function_result_and_predicate(self):
        fn = Function("F")
        pred = Predicate("P")
        e = Expression("e", typed_by=fn)
        self.assertIs(e.function, fn)
        self.assertIsNone(Expression().function)
        self.assertIsNone(e.result)
        r = Feature("r", direction=FeatureDirection.OUT)
        e.own(r, membership=ReturnParameterMembership)
        self.assertIs(e.result, r)
        b = BooleanExpression(typed_by=pred)
        self.assertIs(b.predicate, pred)
        self.assertIs(b.function, pred)
        self.assertIsNone(BooleanExpression(typed_by=fn).predicate)

    def test_feature_reference_expression_referent(self):
        f = Feature("f")
        ref = FeatureReferenceExpression(f)
        self.assertIs(ref.referent, f)           # the compatibility attribute
        self.assertIs(FeatureReferenceExpression.referent.rule, "explicit")

    def test_connector_associations(self):
        assoc = AssociationStructure("A")
        c = BindingConnector(typed_by=assoc)
        self.assertEqual(c.associations, [assoc])
        self.assertEqual(Connector().associations, [])

    def test_type_multiplicity(self):
        t = Type("T")
        self.assertIsNone(t.multiplicity)
        m = Multiplicity()
        t.own(m)
        self.assertIs(t.multiplicity, m)
        # A feature keeps its multiplicity value (ADR 0002 decision 5).
        f = Feature("f")
        self.assertEqual((f.multiplicity.lower, f.multiplicity.upper), (0, None))

    def test_metadata_feature_is_an_annotating_element(self):
        self.assertNotIsInstance(Comment("x"), MetadataFeature)
        self.assertIsInstance(MetadataFeature(), AnnotatingElement)

    def test_feature_membership_of_result_expression_is_a_feature_membership(self):
        self.assertTrue(issubclass(ResultExpressionMembership, FeatureMembership))


if __name__ == "__main__":
    unittest.main()
