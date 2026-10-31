"""KerML Root and Core layers with first-class relationships (ADR 0002, Phase 1 A1/A2)."""
import unittest

from engine import Repository, register_removal_hook
from kerml import (
    AnnotatingElement, Annotation, Behavior, Classifier, Comment, Conjugation, CrossSubsetting,
    Dependency, Differencing, Disjoining, Documentation, Element, EndFeatureMembership, Feature,
    FeatureChaining, FeatureDirection, FeatureInverting, FeatureMembership, FeatureTyping,
    FeatureValue, Intersecting, LibraryPackage, MembershipImport, Membership, MultiplicityRange,
    NamespaceImport, OwningMembership, Package, ParameterMembership, Redefinition,
    ReferenceSubsetting, ReturnParameterMembership, Specialization, Subclassification, Subsetting,
    TextualRepresentation, Type, TypeFeaturing, Unioning,
)
from kerml.elements import derived_id, escape_name, split_qualified_name
from kerml.expressions import LiteralBoolean
from kerml.library import KERML_LIBRARY
from kerml.namespaces import PRIVATE, PROTECTED


def _model():
    root = Package("Root")
    p = Package("P")
    root.own(p)
    a = Classifier("A")
    p.own(a)
    x = Feature("x", direction=FeatureDirection.IN)
    a.own(x)
    return root, p, a, x


class OwnershipTests(unittest.TestCase):

    def test_owner_and_owned_elements_are_derived_from_relationships(self):
        root, p, a, x = _model()
        m = x.owning_relationship
        self.assertIsInstance(m, FeatureMembership)
        self.assertIs(m.owning_related_element, a)
        self.assertEqual(m.owned_related_elements, [x])
        self.assertEqual(m.sources, [a])
        self.assertEqual(m.targets, [x])
        self.assertIs(x.owner, a)
        self.assertIn(m, a.owned_relationships)
        self.assertEqual(a.owned_elements, [x])
        self.assertIs(x.owning_namespace, a)
        self.assertIs(x.owning_type, a)

    def test_detach_and_reown_move_the_membership(self):
        root, p, a, x = _model()
        b = Classifier("B")
        p.own(b)
        old = x.owning_relationship
        b.own(x)
        self.assertIs(x.owner, b)
        self.assertNotIn(old, a.owned_relationships)
        self.assertEqual(a.owned_elements, [])
        x.detach()
        self.assertIsNone(x.owner)
        self.assertEqual(b.owned_relationships, [])

    def test_membership_kind_is_chosen_by_own(self):
        root, p, a, x = _model()
        self.assertIsInstance(p.owning_relationship, OwningMembership)
        self.assertNotIsInstance(p.owning_relationship, FeatureMembership)
        end = Feature("e", is_end=True)
        a.own(end)
        self.assertIsInstance(end.owning_relationship, EndFeatureMembership)
        beh = Behavior("B")
        inp = Feature("in1", direction="in")
        beh.own(inp)
        self.assertIsInstance(inp.owning_relationship, ParameterMembership)
        ret = Feature("r", direction="out")
        ret.parameter_kind = "return"
        beh.own(ret)
        self.assertIsInstance(ret.owning_relationship, ReturnParameterMembership)
        plain = Feature("local")
        beh.own(plain)
        self.assertIs(type(plain.owning_relationship), FeatureMembership)
        forced = Feature("f")
        a.own(forced, membership=OwningMembership)
        self.assertIs(type(forced.owning_relationship), OwningMembership)
        self.assertIn(inp, beh.parameters)

    def test_owned_elements_assignment_reorders_tree_children(self):
        root, p, a, x = _model()
        y, z = Feature("y"), Feature("z")
        a.own(y)
        a.own(z)
        a.add_annotation(Documentation("doc"))
        a.owned_elements = [z, x, y]
        self.assertEqual([c.name for c in a.children], ["z", "x", "y"])
        self.assertEqual(len(a.documentation), 1)       # kept although not listed
        a.owned_elements = [z, y]
        self.assertIsNone(x.owner)

    def test_n_ary_relationships_and_dependency(self):
        root, p, a, x = _model()
        b = Classifier("B")
        p.own(b)
        dep = Dependency([a, b], [p, root])
        self.assertEqual(dep.clients, [a, b])
        self.assertEqual(dep.suppliers, [p, root])
        self.assertIs(dep.source, a)
        self.assertIs(dep.target, p)
        self.assertEqual(dep.related_elements, [a, b, p, root])
        a.add_relationship(dep)
        self.assertIs(dep.owning_related_element, a)
        self.assertIs(dep.owner, a)

    def test_element_identity_properties(self):
        e = Element("n", short_name="s", alias_ids=["a1", "a2"], is_implied_included=True)
        self.assertEqual((e.declared_name, e.declared_short_name), ("n", "s"))
        self.assertEqual(e.alias_ids, ["a1", "a2"])
        self.assertTrue(e.is_implied_included)
        e.name = "m"
        self.assertEqual(e.declared_name, "m")
        self.assertTrue(KERML_LIBRARY.resolve("ScalarValues::Real").is_library_element)
        self.assertIsInstance(KERML_LIBRARY, LibraryPackage)
        self.assertFalse(_model()[2].is_library_element)

    def test_effective_name_of_a_redefining_feature(self):
        root, p, a, x = _model()
        b = Classifier("B")
        p.own(b)
        b.specialize(a)
        xr = Feature()
        b.own(xr)
        xr.redefine(x)
        self.assertIsNone(xr.declared_name)
        self.assertEqual(xr.name, "x")
        self.assertEqual(xr.qualified_name, "Root::P::B::x")

    def test_qualified_names_quote_unrestricted_names(self):
        root = Package("Root")
        sp = Package("my pkg")
        root.own(sp)
        q = Classifier("it's")
        sp.own(q)
        self.assertEqual(q.qualified_name, "Root::'my pkg'::'it\\'s'")
        self.assertEqual(split_qualified_name(q.qualified_name), ["Root", "my pkg", "it's"])
        self.assertEqual(escape_name("ok_1"), "ok_1")
        self.assertIs(root.resolve("'my pkg'::'it\\'s'"), q)
        unnamed = Classifier()
        sp.own(unnamed)
        self.assertTrue(unnamed.qualified_name.startswith("<"))


class AnnotationTests(unittest.TestCase):

    def test_documentation_of_a_namespace_is_an_owned_member(self):
        root, p, a, x = _model()
        d = Documentation("text", locale="en_US")
        a.add_annotation(d)
        self.assertIsInstance(d, AnnotatingElement)
        self.assertIsInstance(d.owning_relationship, OwningMembership)
        self.assertEqual(a.documentation, [d])
        self.assertEqual(a.annotations, [d])
        self.assertEqual(d.annotated_elements, [a])
        self.assertIs(d.documented_element, a)
        self.assertEqual(d.locale, "en_US")
        self.assertNotIn(d, a.children)                 # the tree shows model elements only
        self.assertIn(d, a.owned_elements)

    def test_annotation_of_a_relationship_is_an_owned_annotation(self):
        root, p, a, x = _model()
        rel = x.owning_relationship
        c = Comment("on the membership")
        rel.add_annotation(c)
        self.assertIsInstance(c.owning_relationship, Annotation)
        self.assertEqual(rel.owned_annotations, [c.owning_relationship])
        self.assertIs(c.owning_relationship.annotating_element, c)
        self.assertEqual(c.annotated_elements, [rel])

    def test_comment_about_several_elements(self):
        root, p, a, x = _model()
        b = Classifier("B")
        p.own(b)
        c = Comment("shared", about=[a, b])
        p.own(c)
        self.assertEqual(c.annotated_elements, [a, b])
        self.assertEqual([r.annotated_element for r in c.annotations], [a, b])
        self.assertTrue(all(isinstance(r, Annotation) for r in c.owned_annotating_relationships))

    def test_textual_representation_and_annotation_compatibility(self):
        root, p, a, x = _model()
        rep = TextualRepresentation("classifier A;", language="kerml")
        a.add_annotation(rep)
        self.assertEqual(a.textual_representations, [rep])
        self.assertIs(rep.represented_element, a)
        a.annotations = []
        self.assertEqual(a.textual_representations, [])


class NamespaceTests(unittest.TestCase):

    def setUp(self):
        self.root = Package("Root")
        self.lib = Package("Lib")
        self.root.own(self.lib)
        self.pub = Classifier("Pub")
        self.lib.own(self.pub)
        self.priv = Classifier("Priv")
        self.lib.own(self.priv, visibility=PRIVATE)
        self.sub = Package("Sub")
        self.lib.own(self.sub)
        self.deep = Classifier("Deep", short_name="D1")
        self.sub.own(self.deep)
        self.user = Package("User")
        self.root.own(self.user)

    def test_visibility_and_namespace_imports(self):
        self.user.add_import(self.lib)
        members = self.user.members
        self.assertIn(self.pub, members)
        self.assertNotIn(self.priv, members)
        self.assertNotIn(self.deep, members)
        self.assertIsInstance(self.user.owned_imports[0], NamespaceImport)
        self.assertEqual(self.user.members(include_imports=False), [])

    def test_recursive_and_import_all(self):
        self.user.add_import(self.lib, recursive=True)
        self.assertIn(self.deep, self.user.members)
        other = Package("Other")
        self.root.own(other)
        other.add_import(self.lib, import_all=True)
        self.assertIn(self.priv, other.members)

    def test_membership_import_and_alias(self):
        m = self.pub.owning_relationship
        imp = self.user.add_import(m)
        self.assertIsInstance(imp, MembershipImport)
        self.assertEqual(self.user.members, [self.pub])
        alias = self.user.add_member(self.deep, owned=False, alias="Alias")
        self.assertIsInstance(alias, Membership)
        self.assertIs(self.user.resolve("Alias"), self.deep)
        self.assertIs(self.deep.owner, self.sub)

    def test_filtered_import_stores_conditions(self):
        cond = LiteralBoolean(True)
        imp = self.user.add_import(self.lib, filter_conditions=[cond])
        fp = imp.imported_namespace
        self.assertIsInstance(fp, Package)
        self.assertEqual(fp.filter_conditions, [cond])
        self.assertIn(self.pub, self.user.members)

    def test_spec_name_resolution(self):
        r = self.user.resolve_membership
        self.assertIs(r("Lib::Pub").member_element, self.pub)             # outer scope, then visible
        self.assertIsNone(r("Lib::Priv"))                                  # private is not visible
        self.assertIs(self.lib.resolve_membership("Priv").member_element, self.priv)  # locally it is
        self.assertIs(r("Lib::Sub::D1").member_element, self.deep)         # short name
        self.assertIs(r("ScalarValues::Real").member_element,              # global scope (libraries)
                      KERML_LIBRARY.resolve("ScalarValues::Real"))
        self.assertIs(r("$::KerML::ScalarValues::Real").member_element,
                      KERML_LIBRARY.resolve("ScalarValues::Real"))
        self.assertIsNone(self.user.resolve("Pub"))                        # compat lookup: local only

    def test_inherited_members_resolve(self):
        a = Classifier("A")
        self.lib.own(a)
        f = Feature("f")
        a.own(f)
        hidden = Feature("hidden")
        a.own(hidden, visibility=PRIVATE)
        prot = Feature("prot")
        a.own(prot, visibility=PROTECTED)
        b = Classifier("B")
        self.lib.own(b)
        b.specialize(a)
        self.assertIs(b.resolve("f"), f)
        self.assertIs(b.resolve_membership("f").member_element, f)
        self.assertEqual(b.inherited_features, [f, prot])
        self.assertEqual(b.inherited_features(), [f, prot])        # still callable
        self.assertIsNone(b.resolve("hidden"))


class TypeAndFeatureTests(unittest.TestCase):

    def test_specialization_kinds(self):
        a, b = Classifier("A"), Classifier("B")
        s = b.specialize(a)
        self.assertIsInstance(s, Subclassification)
        self.assertEqual((s.subclassifier, s.superclassifier), (b, a))
        self.assertIs(s.specific, b)
        self.assertIs(s.general, a)
        self.assertEqual(b.owned_specializations, [s])
        self.assertEqual(b.specializations, [s])
        t = Type("T")
        self.assertIs(type(t.specialize(a)), Specialization)
        self.assertEqual(b.all_supertypes(), [b, a])
        self.assertTrue(b.specializes(a) and b.conforms_to(a) and b.conforms_to(b))
        with self.assertRaises(AttributeError):
            b.specializations = []

    def test_feature_relationship_kinds_and_views(self):
        a = Classifier("A")
        f, g, h = Feature("f"), Feature("g"), Feature("h")
        for x in (f, g, h):
            a.own(x)
        ft = f.add_type(a)
        self.assertIsInstance(ft, FeatureTyping)
        self.assertEqual(f.owned_typings, [ft])
        self.assertEqual(f.feature_typings, [ft])
        self.assertIs(ft.typed_feature, f)
        self.assertIs(ft.type, a)
        s = g.subset(f)
        r = h.redefine(f)
        rs = h.reference_subset(g)
        cs = g.cross_subset(h)
        self.assertIsInstance(s, Subsetting)
        self.assertIsInstance(r, Redefinition)
        self.assertIsInstance(rs, ReferenceSubsetting)
        self.assertIsInstance(cs, CrossSubsetting)
        self.assertEqual(h.owned_redefinitions, [r])
        self.assertEqual(h.redefinitions, [r])
        self.assertIs(h.owned_reference_subsetting, rs)
        self.assertIs(g.owned_cross_subsetting, cs)
        self.assertEqual(set(map(id, h.subsettings)), {id(r), id(rs)})
        self.assertEqual(g.types, [a])                    # through the subsetted feature
        with self.assertRaises(AttributeError):
            f.feature_typings = []
        f.remove_types()
        self.assertEqual(f.types, [])

    def test_chaining_inverting_featuring(self):
        a = Classifier("A")
        p, q = Feature("p"), Feature("q")
        a.own(p)
        a.own(q)
        chain = Feature()
        chain.chain(p, q)
        self.assertEqual(chain.chaining_features, [p, q])
        self.assertIs(chain.feature_target, q)
        self.assertTrue(all(isinstance(r, FeatureChaining) for r in chain.owned_feature_chainings))
        inv = p.invert(q)
        self.assertIsInstance(inv, FeatureInverting)
        self.assertEqual(p.owned_feature_invertings, [inv])
        b = Classifier("B")
        tf = q.add_featuring_type(b)
        self.assertIsInstance(tf, TypeFeaturing)
        self.assertEqual(q.featuring_types, [a, b])
        self.assertEqual(chain.featuring_types, [a])              # those of its first link

    def test_type_algebra_relationships(self):
        a, b, c = Classifier("A"), Classifier("B"), Classifier("C")
        self.assertIsInstance(a.disjoin(b), Disjoining)
        self.assertIsInstance(c.add_unioning(a), Unioning)
        self.assertIsInstance(c.add_intersecting(b), Intersecting)
        self.assertIsInstance(c.add_differencing(a), Differencing)
        self.assertEqual(c.unioning_types, [a])
        self.assertEqual(c.intersecting_types, [b])
        self.assertEqual(c.differencing_types, [a])
        self.assertEqual(len(a.owned_disjoinings), 1)

    def test_inherited_features_hide_redefined_and_private(self):
        a = Classifier("A")
        x, secret = Feature("x"), Feature("secret")
        a.own(x)
        a.own(secret, visibility=PRIVATE)
        b = Classifier("B")
        b.specialize(a)
        xr = Feature("x")
        b.own(xr)
        xr.redefine(x)
        self.assertEqual(b.inherited_features, [])
        self.assertEqual(b.features, [xr])
        c = Classifier("C")
        c.specialize(b)
        self.assertEqual(c.inherited_features, [xr])

    def test_feature_flags(self):
        f = Feature("f")
        self.assertTrue(f.is_unique)
        self.assertFalse(f.is_ordered or f.is_variable or f.is_constant)
        f.is_readonly = True
        self.assertTrue(f.is_constant)
        g = Feature("g", is_ordered=True, is_unique=False, is_variable=True, is_constant=True)
        self.assertTrue(g.is_ordered and g.is_variable and g.is_readonly)
        self.assertFalse(g.is_unique)

    def test_conjugated_type_flips_directions(self):
        port = Classifier("Port")
        i, o, io = (Feature("i", direction="in"), Feature("o", direction="out"),
                    Feature("io", direction="inout"))
        for f in (i, o, io):
            port.own(f)
        conj = Classifier("~Port")
        cj = conj.conjugate(port)
        self.assertIsInstance(cj, Conjugation)
        self.assertTrue(conj.is_conjugated)
        self.assertIs(conj.owned_conjugator, cj)
        self.assertEqual(conj.direction_of(i), "out")
        self.assertEqual(conj.direction_of(o), "in")
        self.assertEqual(conj.direction_of(io), "inout")
        self.assertEqual(port.inputs, [i, io])
        self.assertEqual(conj.inputs, [o, io])

    def test_values_are_materialized_with_deterministic_ids(self):
        f = Feature("f", multiplicity=MultiplicityRange(1, 4), default_value=2.5)
        m1, m2 = f.multiplicity_element(), f.multiplicity_element()
        self.assertEqual(m1.element_id, m2.element_id)
        mult = m1.member_element
        self.assertEqual(mult.element_id, derived_id(f.element_id, "multiplicity"))
        self.assertEqual(mult.as_range(), MultiplicityRange(1, 4))
        self.assertEqual([b.value for b in mult.bounds], [1, 4])
        fv = f.value_membership()
        self.assertIsInstance(fv, FeatureValue)
        self.assertEqual(fv.value.value, 2.5)
        self.assertEqual(f.owned_relationships, [])               # the live tree stays free of them
        self.assertIsNone(Feature("g").value_membership())


class RepositoryRemovalTests(unittest.TestCase):

    def test_remove_deletes_relationships_that_reference_removed_elements(self):
        repo = Repository("R")
        pkg = repo.add(Package("P"))
        a, b = Classifier("A"), Classifier("B")
        pkg.own(a)
        pkg.own(b)
        b.specialize(a)
        f = Feature("f")
        b.own(f)
        f.add_type(a)
        dep = Dependency([b], [a])
        b.add_relationship(dep)
        alias = pkg.add_member(a, owned=False, alias="Alias")
        seen = []
        register_removal_hook(lambda r, ids: seen.append(id(a) in ids))
        repo.registry.register_tree(pkg)
        repo.remove(a)
        self.assertIsNone(a.owner)
        self.assertEqual(b.owned_specializations, [])
        self.assertEqual(f.types, [])
        self.assertNotIn(dep, b.owned_relationships)
        self.assertNotIn(alias, pkg.owned_relationships)
        self.assertIsNone(repo.by_id(a.element_id))
        self.assertIn(True, seen)


if __name__ == "__main__":
    unittest.main()
