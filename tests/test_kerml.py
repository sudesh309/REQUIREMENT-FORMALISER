import unittest

from kerml.features import Feature, FeatureDirection, MultiplicityRange
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Package
from kerml.types import Classifier


class KerMLTests(unittest.TestCase):

    def test_qualified_name(self):
        root = Package(name="Root")
        child = Package(name="Child"); root.own(child)
        cls = Classifier(name="C"); child.own(cls)
        self.assertEqual(cls.qualified_name, "Root::Child::C")

    def test_specialization_conformance(self):
        a = Classifier(name="A")
        b = Classifier(name="B"); b.specialize(a)
        c = Classifier(name="C"); c.specialize(b)
        self.assertTrue(c.conforms_to(a))
        self.assertTrue(c.conforms_to(b))
        self.assertFalse(a.conforms_to(b))

    def test_multiplicity(self):
        m = MultiplicityRange.parse("0..*")
        self.assertEqual(m.lower, 0); self.assertIsNone(m.upper)
        self.assertTrue(m.includes(0)); self.assertTrue(m.includes(1_000_000))
        m2 = MultiplicityRange(1, 3)
        self.assertFalse(m2.includes(0)); self.assertTrue(m2.includes(2))

    def test_feature_typing(self):
        Real = KERML_LIBRARY.resolve("ScalarValues::Real")
        self.assertIsNotNone(Real)
        f = Feature(name="x", typed_by=Real, direction=FeatureDirection.IN)
        self.assertIn(Real, f.types)
        self.assertEqual(f.direction, FeatureDirection.IN)

    def test_namespace_resolution_and_imports(self):
        a = Package(name="A")
        b = Package(name="B"); a.own(b)
        x = Classifier(name="X"); b.own(x)
        self.assertIs(a.resolve("B::X"), x)

        c = Package(name="C")
        c.add_import(a, recursive=True)
        self.assertIn(b, c.members(include_imports=True))


if __name__ == "__main__":
    unittest.main()
