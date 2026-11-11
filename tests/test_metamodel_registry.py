"""The metamodel registry generated from the reflective KerML / SysML models (ADR 0002).

Covers ``tools/metagen.py`` (parsing, resolution, ``--check``), ``kerml.metamodel``
(registry, redefinition-aware inheritance, Python naming, class discovery) and
the ``metamodel.*`` conformance metrics.
"""
import contextlib
import io
import time
import unittest

import sysmlv2.metamodel  # noqa: F401 - registers the SysML metaclasses
from kerml import metamodel as mm
from sysmlv2 import PartUsage, PortDefinition
from tools import metagen


def _prop(qualified: str) -> mm.PropertySpec:
    owner, name = qualified.split("::")
    prop = mm.metaclass(owner).property(name)
    assert prop is not None, qualified
    return prop


class ParsingTest(unittest.TestCase):

    def test_counts(self):
        self.assertEqual(len(mm.all_metaclasses("KerML")), 82)
        self.assertEqual(len(mm.all_metaclasses("sysml")), 93)
        self.assertEqual(len(mm.all_enums("KerML")), 2)
        self.assertEqual(len(mm.all_enums("SysML")), 5)
        self.assertEqual(sum(len(m.properties) for m in mm.all_metaclasses("KerML")), 210)
        self.assertEqual(sum(len(m.properties) for m in mm.all_metaclasses("SysML")), 218)
        self.assertEqual(mm.languages(), ["KerML", "SysML"])

    def test_packages_and_abstract_metaclasses(self):
        self.assertEqual(mm.metaclass("Element").package, "Root")
        self.assertEqual(mm.metaclass("Feature").qualified_name, "KerML::Core::Feature")
        self.assertEqual(mm.metaclass("Association").package, "Kernel")
        self.assertEqual(mm.metaclass("SysML::Systems::PartUsage").language, "SysML")
        self.assertEqual({m.name for m in mm.all_metaclasses() if m.is_abstract},
                         {"Element", "Relationship", "Import", "InstantiationExpression",
                          "ConnectorAsUsage", "ControlNode", "Expose", "LoopActionUsage"})
        with self.assertRaises(KeyError):
            mm.metaclass("NoSuchMetaclass")

    def test_feature_is_unique(self):
        p = _prop("Feature::isUnique")
        self.assertEqual((p.type, p.lower, p.upper), ("Boolean", 1, 1))
        self.assertFalse(p.derived or p.composite or p.ordered)
        self.assertTrue(p.var and p.unique)

    def test_supertypes(self):
        self.assertEqual(mm.metaclass("Subclassification").supertypes, ("Specialization",))
        self.assertEqual(mm.supertypes_closure("Subclassification"),
                         ["Specialization", "Relationship", "Element"])
        self.assertEqual(mm.metaclass("Connector").supertypes, ("Feature", "Relationship"))
        self.assertEqual(mm.metaclass("FlowUsage").supertypes,
                         ("ConnectorAsUsage", "Flow", "ActionUsage"))
        self.assertEqual(mm.metaclass("Element").supertypes, ())
        closure = mm.supertypes_closure("PartUsage")
        self.assertEqual(closure[:3], ["ItemUsage", "OccurrenceUsage", "Usage"])
        self.assertEqual(len(closure), len(set(closure)))

    def test_enum_literals(self):
        self.assertEqual(mm.enum("VisibilityKind").literals, ("private", "protected", "public"))
        self.assertEqual(mm.enum("FeatureDirectionKind").literals, ("in", "inout", "out"))
        self.assertEqual(mm.enum("PortionKind").literals, ("timeslice", "snapshot"))
        self.assertEqual(mm.enum("RequirementConstraintKind").literals,
                         ("assumption", "requirement"))
        self.assertEqual(mm.enum("StateSubactionKind").literals, ("entry", "do", "exit"))
        self.assertEqual(mm.enum("TransitionFeatureKind").literals, ("trigger", "guard", "effect"))
        self.assertEqual(mm.enum("TriggerKind").literals, ("when", "at", "after"))

    def test_property_variants(self):
        t = _prop("Feature::type")                     # quoted name 'type'
        self.assertEqual((t.lower, t.upper, t.ordered, t.derived), (0, None, True, True))
        rel = _prop("Relationship::relatedElement")    # ordered nonunique
        self.assertTrue(rel.ordered)
        self.assertFalse(rel.unique)
        self.assertTrue(_prop("Namespace::membership").abstract)   # derived abstract var
        self.assertTrue(_prop("Element::ownedRelationship").composite)
        self.assertEqual((_prop("MultiplicityRange::bound").lower,
                          _prop("MultiplicityRange::bound").upper), (1, 2))
        self.assertEqual(_prop("Flow::flowEnd").upper, 2)
        self.assertEqual((_prop("Dependency::client").lower, _prop("Dependency::client").upper),
                         (1, None))
        # SysML: `item` without `ref` is composite; `ref item` and `attribute` are not
        self.assertTrue(_prop("ActorMembership::ownedActorParameter").composite)
        self.assertFalse(_prop("PartUsage::partDefinition").composite)
        self.assertFalse(_prop("OccurrenceUsage::portionKind").composite)
        self.assertEqual(_prop("OccurrenceUsage::portionKind").type, "PortionKind")
        self.assertFalse(_prop("ConjugatedPortTyping::conjugatedPortDefinition").derived)

    def test_subsets_and_redefines_are_resolved(self):
        self.assertEqual(_prop("FeatureTyping::type").redefines, ("Specialization::general",))
        self.assertEqual(_prop("Documentation::documentedElement").subsets, ("Element::owner",))
        self.assertEqual(_prop("Documentation::documentedElement").redefines,
                         ("AnnotatingElement::annotatedElement",))
        self.assertEqual(_prop("CrossSubsetting::crossingFeature").redefines,
                         ("Subsetting::owningFeature", "Subsetting::subsettingFeature"))
        self.assertEqual(_prop("Namespace::ownedMember").subsets, ("Namespace::member",))
        self.assertEqual(_prop("AttributeUsage::isReference").redefines, ("Usage::isReference",))
        self.assertEqual(_prop("MetadataUsage::metadataDefinition").redefines,
                         ("ItemUsage::itemDefinition", "MetadataFeature::metaclass"))

    def test_plumbing_is_dropped(self):
        # Metaobjects::Metaobject::annotatedElement and Metadata::metadataItems
        self.assertEqual(_prop("Annotation::annotatedElement").redefines, ("Relationship::target",))
        self.assertEqual(_prop("AnnotatingElement::annotatedElement").redefines, ())
        # ItemUsage::itemDefinition says `subsets Metadata::metadataItems` twice
        self.assertEqual(_prop("ItemUsage::itemDefinition").subsets,
                         ("OccurrenceUsage::occurrenceDefinition",))
        self.assertEqual(_prop("ActionUsage::actionDefinition").subsets, ())

    def test_every_reference_targets_an_inherited_property(self):
        for m in mm.all_metaclasses():
            scope = {m.name, *mm.supertypes_closure(m.name)}
            for p in m.properties:
                for ref in p.subsets + p.redefines:
                    owner, name = ref.split("::")
                    self.assertIn(owner, scope, f"{p.qualified_name} -> {ref}")
                    self.assertIsNotNone(mm.metaclass(owner).property(name), ref)
                    self.assertNotEqual(ref, p.qualified_name)
            for p in m.properties:
                self.assertTrue(mm.is_metaclass(p.type) or p.type in metagen.SCALAR_TYPES
                                or p.type in {e.name for e in mm.all_enums()}, p.qualified_name)


class InheritanceTest(unittest.TestCase):

    def names(self, metaclass, **kw):
        return [p.qualified_name for p in mm.properties(metaclass, **kw)]

    def test_redefined_properties_are_replaced(self):
        names = self.names("FeatureTyping")
        self.assertIn("FeatureTyping::type", names)
        self.assertIn("FeatureTyping::owningFeature", names)
        for hidden in ("Specialization::general", "Specialization::specific",
                       "Specialization::owningType", "Relationship::target", "Relationship::source"):
            self.assertNotIn(hidden, names)
        self.assertIn("Element::elementId", names)

    def test_same_named_redefinition(self):
        names = self.names("AttributeUsage")
        self.assertIn("AttributeUsage::isReference", names)
        self.assertNotIn("Usage::isReference", names)
        usage = self.names("Usage")
        self.assertIn("Usage::definition", usage)
        self.assertNotIn("Feature::type", usage)          # redefined by Usage::definition
        self.assertNotIn("Feature::isVariable", usage)    # redefined by Usage::mayTimeVary

    def test_redefinition_through_a_diamond(self):
        names = self.names("CalculationUsage")
        self.assertIn("CalculationUsage::calculationDefinition", names)
        for hidden in ("Expression::function", "ActionUsage::actionDefinition", "Step::behavior",
                       "OccurrenceUsage::occurrenceDefinition", "Usage::definition",
                       "Feature::type"):
            self.assertNotIn(hidden, names)
        self.assertIn("Expression::result", names)
        self.assertIn("Step::parameter", names)

    def test_order_and_filters(self):
        own = mm.properties("Feature", inherited=False)
        self.assertEqual(own, list(mm.metaclass("Feature").properties))
        self.assertEqual(self.names("Feature")[:len(own)], [p.qualified_name for p in own])
        self.assertTrue(all(p.derived for p in mm.properties("Feature", derived=True)))
        self.assertFalse(any(p.derived for p in mm.properties("Feature", derived=False)))
        self.assertIn("Feature::isUnique", self.names("Feature", inherited=False, derived=False))

    def test_no_duplicates(self):
        for m in mm.all_metaclasses():
            names = self.names(m.name)
            self.assertEqual(len(names), len(set(names)), m.name)


class NamingTest(unittest.TestCase):

    def test_rule(self):
        self.assertEqual(mm.python_name(_prop("Element::ownedRelationship")), "owned_relationships")
        self.assertEqual(mm.python_name(_prop("Feature::type")), "types")
        self.assertEqual(mm.python_name(_prop("FeatureTyping::type")), "type")
        self.assertEqual(mm.python_name(_prop("Type::isAbstract")), "is_abstract")
        self.assertEqual(mm.python_name(_prop("Element::elementId")), "element_id")
        self.assertEqual(mm.python_name(_prop("Element::isImpliedIncluded")), "is_implied_included")
        self.assertEqual(mm.python_name(_prop("MultiplicityRange::bound")), "bounds")      # [1..2]
        self.assertEqual(mm.python_name(_prop("Relationship::target")), "targets")
        self.assertEqual(mm.python_name(_prop("Annotation::annotatedElement")), "annotated_element")
        self.assertEqual(mm.python_name(_prop("AnnotatingElement::annotatedElement")),
                         "annotated_elements")
        self.assertEqual(mm.python_name(_prop("RequirementDefinition::text")), "texts")

    def test_plural_forms(self):
        cases = {"ownedEntity": "owned_entities", "box": "boxes", "ownedBranch": "owned_branches",
                 "status": "statuses", "ownedDay": "owned_days", "isFlag": "is_flag",
                 "parameter": "parameters"}
        for name, expected in cases.items():
            self.assertEqual(mm.python_name(name, True), expected, name)
        self.assertEqual(mm.python_name("ownedRelationship"), "owned_relationship")
        self.assertEqual(mm.python_name("ownedRelationship", multi_valued=True),
                         "owned_relationships")

    def test_overrides(self):
        self.assertEqual(mm.python_name(_prop("Element::aliasIds")), "alias_ids")
        self.assertEqual(mm.python_name(_prop("Element::documentation")), "documentation")
        self.assertEqual(mm.python_name(_prop("Definition::ownedMetadata")), "owned_metadata")
        self.assertEqual(mm.python_name(_prop("Usage::nestedMetadata")), "nested_metadata")
        self.assertEqual(mm.python_name(_prop("FramedConcernMembership::kind")),
                         "requirement_constraint_kind")
        self.assertEqual(mm.python_name("TriggerInvocationExpression::kind"), "trigger_kind")
        with self.assertRaises(ValueError):
            mm.python_name("kind")

    def test_override_keys_name_real_properties(self):
        names = {p.name for m in mm.all_metaclasses() for p in m.properties}
        for key in mm.PYTHON_NAME_OVERRIDES:
            if "::" in key:
                self.assertIsNotNone(_prop(key), key)
            else:
                self.assertIn(key, names)

    def test_names_are_unique_and_not_reserved(self):
        for m in mm.all_metaclasses():
            seen = {}
            for p in mm.properties(m.name):
                name = mm.python_name(p)
                self.assertNotIn(name, mm.RESERVED_PYTHON_NAMES, p.qualified_name)
                self.assertNotIn(name, seen, f"{m.name}: {p.qualified_name} and {seen.get(name)}")
                seen[name] = p.qualified_name


class GeneratorTest(unittest.TestCase):

    def test_check_passes_in_process(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(metagen.main(["--check"]), 0, out.getvalue())

    def test_generation_is_deterministic(self):
        first, second = metagen.generate(), metagen.generate()
        self.assertEqual(first, second)
        for path, text in first.items():
            self.assertEqual(path.read_text(encoding="utf-8"), text, path)
            self.assertIn("do not edit", text)
            self.assertIn("2026-09.1", text)

    def _model(self, body: str, language: str = "KerML"):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "M.kerml"
            path.write_text(f"standard library package {language} {{ package Root {{ {body} }} }}")
            return metagen.parse(language, path)

    def test_parser_handles_variants(self):
        model = self._model("""
            doc /* text */
            private import ScalarValues::*;
            abstract metaclass A { derived abstract var feature 'x' : A[*] ordered nonunique; }
            metaclass B specializes A {
                composite feature y : B[1] subsets x redefines x;
                feature z : B[0..2] :> x :>> x;
            }
            metaclass C specializes A, B;
            datatype K { member feature 'in' : K[1]; member feature out : K[1]; }
        """)
        a, b, c = model.metaclasses
        self.assertTrue(a.abstract and a.properties[0].abstract)
        self.assertEqual((a.properties[0].lower, a.properties[0].upper), (0, None))
        self.assertFalse(a.properties[0].unique)
        self.assertEqual((b.properties[0].lower, b.properties[0].upper), (1, 1))
        self.assertTrue(b.properties[0].composite)
        self.assertEqual((b.properties[1].subsets, b.properties[1].redefines), (["x"], ["x"]))
        self.assertEqual(c.supertypes, ["A", "B"])
        self.assertEqual(model.enums[0].literals, ["in", "out"])
        metagen.resolve([model])
        self.assertEqual(b.properties[0].subsets, ["A::x"])

    def test_parser_rejects_unknown_constructs(self):
        with self.assertRaises(metagen.MetagenError):
            self._model("metaclass A { operation f(); }")
        with self.assertRaises(metagen.MetagenError):
            self._model("connector c;")
        with self.assertRaises(metagen.MetagenError):
            metagen.resolve([self._model("metaclass A { feature x : A[1] subsets nothing; }")])
        with self.assertRaises(metagen.MetagenError):
            metagen.resolve([self._model("metaclass A specializes Missing;")])


class PythonClassesTest(unittest.TestCase):

    def test_discovery(self):
        classes = mm.python_classes()
        import kerml
        self.assertIn(kerml.Element, classes)
        self.assertIn(PartUsage, classes)
        from engine.requirements import RequirementSet
        self.assertIn(RequirementSet, classes)
        self.assertEqual(mm.discovery_errors(), {})

        class LocalUsage(PartUsage):        # defined outside the discovery packages
            kind = "LocalUsage"
        refreshed = mm.python_classes(refresh=True)
        self.assertNotIn(LocalUsage, refreshed)
        self.assertEqual(refreshed, classes)

    def test_spec_metaclass_of(self):
        self.assertEqual(mm.spec_metaclass_of(PartUsage), "PartUsage")

        class AppPort(PortDefinition):
            kind = "AppPort"
        self.assertIsNone(mm.spec_metaclass_of(AppPort))

        class MappedPort(PortDefinition):
            kind = "MappedPort"
            spec_metaclass = "PortDefinition"
        self.assertEqual(mm.spec_metaclass_of(MappedPort), "PortDefinition")

        class SameKind(MappedPort):          # shares the kind, so the mapping too
            pass
        self.assertEqual(mm.spec_metaclass_of(SameKind), "PortDefinition")

        class NewKind(MappedPort):           # a new kind needs its own mapping
            kind = "NewKind"
        self.assertIsNone(mm.spec_metaclass_of(NewKind))

        class Bogus(PortDefinition):
            kind = "PortDefinition"
            spec_metaclass = "NotAMetaclass"
        self.assertIsNone(mm.spec_metaclass_of(Bogus))


class MetricsTest(unittest.TestCase):

    NAMES = {"metamodel.kerml.metaclasses_present", "metamodel.sysml.metaclasses_present",
             "metamodel.supertypes_consistent", "metamodel.kerml.attributes_present",
             "metamodel.sysml.attributes_present", "metamodel.kerml.derived_present",
             "metamodel.sysml.derived_present", "metamodel.nonstandard_kinds"}

    def test_collector(self):
        from tools.conformance.metrics import metamodel as metric
        started = time.perf_counter()
        results = metric.collect()
        self.assertLess(time.perf_counter() - started, 5.0)
        by_name = {m["name"]: m for m in results}
        self.assertEqual(set(by_name), self.NAMES)
        self.assertEqual(len(results), len(self.NAMES))
        for name, m in by_name.items():
            self.assertIsInstance(m["detail"], list, name)
            if name == "metamodel.nonstandard_kinds":
                self.assertEqual(m["better"], "lower")
                self.assertIsInstance(m["value"], int)
                self.assertGreaterEqual(m["value"], 0)
                self.assertEqual(m["value"], len(m["detail"]))
            else:
                self.assertEqual(m["better"], "higher")
                self.assertGreaterEqual(m["value"], 0.0, name)
                self.assertLessEqual(m["value"], 1.0, name)
            self.assertTrue(all(isinstance(d, str) for d in m["detail"]), name)
        self.assertGreater(by_name["metamodel.kerml.metaclasses_present"]["value"], 0)
        self.assertTrue(by_name["metamodel.kerml.attributes_present"]["detail"][0]
                        .startswith("construction:"))

    def test_presence_rules(self):
        from tools.conformance.metrics.metamodel import _presence

        class Probe:
            declared = None
            def method(self): ...
            @property
            def prop(self): raise RuntimeError("fails on an empty element")
        probe = Probe()
        probe.assigned = 1
        self.assertEqual(_presence(Probe, probe, "assigned"), "yes")
        self.assertEqual(_presence(Probe, probe, "declared"), "yes")
        self.assertEqual(_presence(Probe, probe, "prop"), "yes")
        self.assertEqual(_presence(Probe, probe, "method"), "method")
        self.assertEqual(_presence(Probe, probe, "absent"), "no")
        self.assertEqual(_presence(Probe, None, "assigned"), "no")


if __name__ == "__main__":
    unittest.main()
