"""Engine tests for SU-15: stereotype values are inherited by usages from their definition.

A reference component (a PartUsage typed by a PartDefinition) reads the values of the
stereotypes applied to its definition unless it overrides them; resetting an override
inherits the definition's value again.
"""
import json
import unittest

from engine import Repository, Validator, from_json, to_json
from engine import profiles as P
from engine.hooks import notify_created
from kerml.stereotypes import (
    InheritedApplication, effective_applications, inheritance_source, stereotypes_on,
)
from sysmlv2 import PartDefinition, PartUsage


def _own(repo, cls, name, owner):
    e = cls(name=name)
    owner.own(e)
    notify_created(e, repo)
    return e


def _typed(repo, name, owner, definition):
    u = PartUsage(name=name)
    u.add_type(definition)
    owner.own(u)
    notify_created(u, repo)
    return u


class Base(unittest.TestCase):

    def setUp(self):
        self.repo = Repository("Aircraft")
        self.prof = P.create_profile(self.repo, "Avionics", version="1.0")
        self.lru = P.add_stereotype(self.repo, self.prof, "LRU", applies_to="Component")
        P.add_property(self.repo, self.lru, "mass", "double", unit="kg", default="1.5", minimum=0)
        P.add_property(self.repo, self.lru, "power", "double", unit="W", default=10)
        P.add_property(self.repo, self.lru, "dal", "enumeration", literals="A,B,C,D,E", default="C")
        self.root = self.repo.root_package
        self.arch = _own(self.repo, PartDefinition, "Aircraft", self.root)
        self.fcc_def = _own(self.repo, PartDefinition, "FCC", self.root)
        self.fcc1 = _typed(self.repo, "fcc1", self.arch, self.fcc_def)
        self.fcc2 = _typed(self.repo, "fcc2", self.arch, self.fcc_def)
        self.inline = _own(self.repo, PartUsage, "inline", self.arch)
        P.apply_stereotype(self.repo, self.fcc_def, self.lru, {"mass": "3 kg", "dal": "A"})


class InheritanceTests(Base):

    def test_usage_reads_the_definition_values(self):
        self.assertIs(inheritance_source(self.fcc1), self.fcc_def)
        self.assertIsNone(inheritance_source(self.inline))           # untyped: nothing to inherit
        self.assertIsNone(inheritance_source(self.fcc_def))
        self.assertEqual(stereotypes_on(self.fcc1), [])               # nothing stored on the usage
        apps = effective_applications(self.fcc1)
        self.assertEqual([(type(a), a.inherited) for a in apps], [(InheritedApplication, True)])
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 3.0)
        self.assertEqual(P.get_property_value(self.fcc2, "mass"), 3.0)
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.dal"), "A")
        self.assertEqual(P.get_property_value(self.fcc1, "power"), 10.0)   # the definition's default
        with self.assertRaises(P.ProfileError):
            P.get_property_value(self.inline, "Avionics.LRU.mass")        # no stereotype, no value

    def test_follows_the_definition(self):
        P.set_property_value(self.repo, self.fcc_def, "Avionics.LRU.mass", "4 kg")
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 4.0)
        self.assertEqual(P.get_property_value(self.fcc2, "Avionics.LRU.mass"), 4.0)
        P.remove_stereotype(self.repo, self.fcc_def, self.lru)
        with self.assertRaises(P.ProfileError):
            P.get_property_value(self.fcc1, "Avionics.LRU.mass")          # nothing inherited any more

    def test_element_view_marks_inherited_values(self):
        (view,) = P.element_stereotypes(self.fcc1)
        self.assertEqual((view["qualified_name"], view["inherited"], view["overridden"]),
                         ("Avionics.LRU", True, False))
        self.assertEqual(view["inherited_from"]["name"], "FCC")
        props = {p["name"]: p for g in view["groups"] for p in g["properties"]}
        self.assertEqual((props["mass"]["value"], props["mass"]["origin"], props["mass"]["inherited"]),
                         (3.0, "inherited", True))
        self.assertEqual(props["mass"]["display"], "3 kg")
        self.assertEqual((props["mass"]["overridden"], props["mass"]["inherited_value"]), (False, 3.0))
        self.assertEqual(view["values"], {"mass": 3.0, "power": 10.0, "dal": "A"})
        # the definition itself is not "inherited"
        (own,) = P.element_stereotypes(self.fcc_def)
        self.assertEqual((own["inherited"], own["overridden"], own["inherited_from"]), (False, False, None))

    def test_badges_and_style_follow(self):
        P.update_stereotype(self.repo, self.lru, style={"fill": "#ffeeaa", "icon": "computer"})
        badges, style = P.display_fields(self.fcc1)
        self.assertEqual((badges, style["fill"], style["icon"]), (["«LRU»"], "#ffeeaa", "computer"))
        self.assertEqual(P.display_fields(self.inline), ([], {}))

    def test_inherited_stereotype_is_not_offered_again(self):
        self.assertNotIn(self.lru, P.applicable_stereotypes(self.repo, self.fcc1))
        self.assertIn(self.lru, P.applicable_stereotypes(self.repo, self.inline))

    def test_only_applicable_stereotypes_are_inherited(self):
        arch_only = P.add_stereotype(self.repo, self.prof, "Root", applies_to="Architecture")
        P.apply_stereotype(self.repo, self.fcc_def, arch_only)      # a definition outside any component
        self.assertEqual([a.stereotype.name for a in effective_applications(self.fcc1)], ["LRU"])
        anything = P.add_stereotype(self.repo, self.prof, "Tagged")
        P.add_property(self.repo, anything, "note", "string", default="n")
        P.apply_stereotype(self.repo, self.fcc_def, anything, {"note": "hello"})
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.Tagged.note"), "hello")

    def test_inheriting_works_for_a_definition_used_in_a_definition_in_a_definition(self):
        """Nested references: a usage typed by a definition whose own parts are typed usages."""
        rack = _own(self.repo, PartDefinition, "Rack", self.root)
        slot = _typed(self.repo, "slot", rack, self.fcc_def)             # Rack.slot : FCC
        rack1 = _typed(self.repo, "rack1", self.arch, rack)              # Aircraft.rack1 : Rack
        P.apply_stereotype(self.repo, rack, self.lru, {"mass": 20})      # Rack carries LRU too
        self.assertEqual(P.get_property_value(slot, "Avionics.LRU.mass"), 3.0)    # from FCC
        self.assertEqual(P.get_property_value(rack1, "Avionics.LRU.mass"), 20.0)  # from Rack
        P.set_property_value(self.repo, self.fcc_def, "Avionics.LRU.mass", "5 kg")
        self.assertEqual(P.get_property_value(slot, "Avionics.LRU.mass"), 5.0)
        self.assertEqual(P.get_property_value(rack1, "Avionics.LRU.mass"), 20.0)
        # a part inside a usage's definition can be overridden on its own
        P.set_property_value(self.repo, slot, "Avionics.LRU.mass", "6 kg")
        self.assertEqual(P.get_property_value(slot, "Avionics.LRU.mass"), 6.0)
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 5.0)


    def test_own_stereotypes_win_over_inherited_ones_for_a_shared_base_property(self):
        """Inheritance must not make a path ambiguous that was not (the avionics roll-up reads
        ``Avionics.Equipment.dal`` on usages that carry another Equipment stereotype)."""
        base = P.add_stereotype(self.repo, self.prof, "Equipment", applies_to="Component", abstract=True)
        P.add_property(self.repo, base, "tier", "enumeration", literals="X,Y,Z", default="Z")
        comp = P.add_stereotype(self.repo, self.prof, "Computer", base=base)
        item = P.add_stereotype(self.repo, self.prof, "LogicalItem", base=base)
        d = _own(self.repo, PartDefinition, "Adc", self.root)
        P.apply_stereotype(self.repo, d, comp, {"tier": "Y"})
        u1, u2 = _typed(self.repo, "adc1", self.arch, d), _typed(self.repo, "adc2", self.arch, d)
        P.apply_stereotype(self.repo, u2, item, {"tier": "X"})
        self.assertEqual(P.get_property_value(u1, "Avionics.Equipment.tier"), "Y")        # inherited
        self.assertEqual(P.get_property_value(u2, "Avionics.Equipment.tier"), "X")        # its own wins
        self.assertEqual(P.get_property_value(u2, "Avionics.Computer.tier"), "Y")         # still reachable
        self.assertEqual(P.get_property_value(u2, "Avionics.LogicalItem.tier"), "X")
        # two own stereotypes sharing the base property are still ambiguous
        P.apply_stereotype(self.repo, u2, comp)
        with self.assertRaises(P.ProfileError) as cm:
            P.get_property_value(u2, "Avionics.Equipment.tier")
        self.assertIn("ambiguous", str(cm.exception))


class OverrideTests(Base):

    def test_setting_a_value_overrides_it_on_that_usage_only(self):
        stored = P.set_property_value(self.repo, self.fcc1, "Avionics.LRU.mass", "2 lb")
        self.assertAlmostEqual(stored, 0.90718474)                      # converted like any value
        self.assertAlmostEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 0.90718474)
        self.assertEqual(P.get_property_value(self.fcc2, "Avionics.LRU.mass"), 3.0)
        self.assertEqual(P.get_property_value(self.fcc_def, "Avionics.LRU.mass"), 3.0)
        (app,) = stereotypes_on(self.fcc1)                                # one application: the override
        self.assertEqual([t.name for t in app.explicit_tags()], ["mass"])
        self.assertEqual(app.origin("mass"), "own")
        self.assertEqual(app.origin("dal"), "inherited")
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.dal"), "A")   # still inherited
        P.set_property_value(self.repo, self.fcc_def, "Avionics.LRU.dal", "B")
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.dal"), "B")   # follows the definition
        P.set_property_value(self.repo, self.fcc_def, "Avionics.LRU.mass", "9 kg")
        self.assertAlmostEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 0.90718474)  # not this one

    def test_view_of_an_override(self):
        P.set_property_value(self.repo, self.fcc1, "mass", 4)
        (view,) = P.element_stereotypes(self.fcc1)
        self.assertEqual((view["inherited"], view["overridden"]), (False, True))
        props = {p["name"]: p for g in view["groups"] for p in g["properties"]}
        self.assertEqual((props["mass"]["origin"], props["mass"]["overridden"], props["mass"]["inherited_value"],
                          props["mass"]["inherited_display"]), ("own", True, 3.0, "3 kg"))
        self.assertEqual((props["dal"]["origin"], props["dal"]["overridden"]), ("inherited", False))

    def test_all_or_nothing(self):
        before = P.get_property_value(self.fcc1, "Avionics.LRU.mass")
        with self.assertRaises(P.ProfileError):
            P.set_property_values(self.repo, self.fcc1, {"Avionics.LRU.mass": 7, "Avionics.LRU.dal": "Z"})
        self.assertEqual(stereotypes_on(self.fcc1), [])                   # no override application either
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), before)
        P.set_property_values(self.repo, self.fcc1, {"Avionics.LRU.mass": 7, "Avionics.LRU.dal": "D"})
        self.assertEqual(len(stereotypes_on(self.fcc1)), 1)               # one override, two values
        self.assertEqual([t.name for t in stereotypes_on(self.fcc1)[0].explicit_tags()], ["mass", "dal"])

    def test_applying_the_stereotype_to_a_usage_is_an_override_not_a_duplicate(self):
        app = P.apply_stereotype(self.repo, self.fcc1, self.lru, {"dal": "B"})
        self.assertEqual(app.values, {"mass": 3.0, "power": 10.0, "dal": "B"})   # the rest is inherited
        self.assertEqual(P.get_property_value(self.fcc2, "Avionics.LRU.dal"), "A")
        with self.assertRaises(P.ProfileError) as cm:                      # a second own one still is
            P.apply_stereotype(self.repo, self.fcc1, self.lru)
        self.assertEqual(cm.exception.status, 409)
        # one stereotype shown once, as an override
        self.assertEqual([(v["qualified_name"], v["overridden"]) for v in P.element_stereotypes(self.fcc1)],
                         [("Avionics.LRU", True)])
        issues = [i for i in Validator().validate(self.repo) if i.rule.startswith("profile.")]
        self.assertEqual(issues, [])                                       # no duplicate / invalid finding

    def test_applying_without_values_keeps_inheriting(self):
        P.apply_stereotype(self.repo, self.fcc1, self.lru)
        P.set_property_value(self.repo, self.fcc_def, "Avionics.LRU.mass", "8 kg")
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 8.0)

    def test_reset_inherits_again(self):
        P.set_property_values(self.repo, self.fcc1, {"Avionics.LRU.mass": 4, "Avionics.LRU.dal": "D"})
        out = P.reset_property_values(self.repo, self.fcc1, ["Avionics.LRU.mass"])
        self.assertEqual(out, {"reset": ["Avionics.LRU.mass"], "unchanged": [], "removed": []})
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 3.0)
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.dal"), "D")   # the other stays
        out = P.reset_property_value(self.repo, self.fcc1, "Avionics.LRU.dal")
        self.assertEqual(out["removed"], ["Avionics.LRU"])                  # an empty override goes away
        self.assertEqual(stereotypes_on(self.fcc1), [])
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.dal"), "A")
        again = P.reset_property_values(self.repo, self.fcc1, ["Avionics.LRU.dal"])
        self.assertEqual(again, {"reset": [], "unchanged": ["Avionics.LRU.dal"], "removed": []})
        with self.assertRaises(P.ProfileError):
            P.reset_property_values(self.repo, self.fcc1, [])
        with self.assertRaises(P.ProfileError):
            P.reset_property_values(self.repo, self.fcc1, ["Avionics.LRU.nope"])

    def test_reset_without_a_definition_goes_back_to_the_default(self):
        P.apply_stereotype(self.repo, self.inline, self.lru, {"mass": 9})
        P.reset_property_value(self.repo, self.inline, "mass")
        self.assertEqual(P.get_property_value(self.inline, "mass"), 1.5)
        self.assertEqual(len(stereotypes_on(self.inline)), 1)              # the application stays

    def test_remove_and_remove_all(self):
        with self.assertRaises(P.ProfileError) as cm:
            P.remove_stereotype(self.repo, self.fcc1, self.lru)            # inherited only
        self.assertEqual(cm.exception.status, 409)
        self.assertIn("inherited from", str(cm.exception))
        P.set_property_value(self.repo, self.fcc1, "mass", 4)
        P.remove_stereotype(self.repo, self.fcc1, self.lru)                # drops the override
        self.assertEqual(P.get_property_value(self.fcc1, "mass"), 3.0)
        self.assertEqual(P.remove_all_stereotypes(self.repo, self.fcc1), 0)
        self.assertEqual(P.get_property_value(self.fcc1, "mass"), 3.0)     # inherited ones stay

    def test_units_follow_property_changes(self):
        P.set_property_value(self.repo, self.fcc1, "mass", "4 kg")
        mass = self.lru.find_tag("mass")
        P.update_property(self.repo, mass, unit="g")
        self.assertEqual(P.get_property_value(self.fcc1, "mass"), 4000.0)  # the override is converted
        self.assertEqual(P.get_property_value(self.fcc2, "mass"), 3000.0)  # and so is the inherited one
        P.set_property_value(self.repo, self.fcc2, "mass", "1 kg")          # unit-aware entry
        self.assertEqual(P.get_property_value(self.fcc2, "mass"), 1000.0)

    def test_deleting_a_property_or_the_stereotype(self):
        P.set_property_values(self.repo, self.fcc1, {"mass": 4, "dal": "D"})
        P.delete_property(self.repo, self.lru.find_tag("mass"))
        (app,) = stereotypes_on(self.fcc1)
        self.assertEqual([t.name for t in app.explicit_tags()], ["dal"])
        P.delete_stereotype(self.repo, self.lru)
        self.assertEqual(effective_applications(self.fcc1), [])
        self.assertEqual(effective_applications(self.fcc_def), [])

    def test_validator(self):
        self.assertEqual([i for i in Validator().validate(self.repo) if i.rule.startswith("profile.")], [])
        P.set_property_value(self.repo, self.fcc1, "mass", 5)
        app = stereotypes_on(self.fcc1)[0]
        app.raw_slots()[self.lru.find_tag("mass")] = -5                    # corrupt the override by hand
        rules = [(i.rule, i.element) for i in Validator().validate(self.repo) if i.rule.startswith("profile.")]
        self.assertEqual(rules, [("profile.value.invalid", self.fcc1)])
        app.raw_slots()[self.lru.find_tag("mass")] = 5
        # a corrupt inherited value is reported once, on the definition
        stereotypes_on(self.fcc_def)[0].raw_slots()[self.lru.find_tag("power")] = "lots"
        rules = [(i.rule, i.element) for i in Validator().validate(self.repo) if i.rule.startswith("profile.")]
        self.assertEqual(rules, [("profile.value.invalid", self.fcc_def)])

    def test_copying_an_application_carries_only_what_was_set(self):
        P.set_property_value(self.repo, self.fcc1, "mass", 4)
        app = stereotypes_on(self.fcc1)[0]
        self.assertEqual(app.own_values(), {"mass": 4.0})
        self.assertEqual(effective_applications(self.fcc2)[0].own_values(), {})


class InteropTests(Base):

    def test_tables_round_trip_into_a_new_project(self):
        from engine.interop import export_tables, tables_to_project
        from engine.interop.diff import compare
        P.set_property_value(self.repo, self.fcc1, "mass", 4)              # an override; dal stays inherited
        P.apply_stereotype(self.repo, self.fcc2, self.lru)                 # an override without values
        repo2, _report = tables_to_project(export_tables(self.repo))
        find = lambda n: next(e for e in repo2.root_package.walk() if e.name == n)    # noqa: E731
        fcc1, fcc2, fdef = find("fcc1"), find("fcc2"), find("FCC")
        self.assertEqual([t.name for t in stereotypes_on(fcc1)[0].explicit_tags()], ["mass"])
        self.assertEqual(stereotypes_on(fcc2), [])          # an override that sets nothing reads the same
        P.set_property_values(repo2, fdef, {"Avionics.LRU.mass": 9, "Avionics.LRU.dal": "E"})
        self.assertEqual(P.get_property_value(fcc1, "Avionics.LRU.mass"), 4.0)       # still an override
        self.assertEqual(P.get_property_value(fcc1, "Avionics.LRU.dal"), "E")        # still inherited
        self.assertEqual(P.get_property_value(fcc2, "Avionics.LRU.mass"), 9.0)
        self.assertTrue(compare(self.repo, tables_to_project(export_tables(self.repo))[0])["identical"])

    def test_inherited_values_in_the_report_and_sysml(self):
        from engine.interop.report import generate_report
        from engine.interop.sysml_export import export_sysml
        P.set_property_value(self.repo, self.fcc1, "mass", 4)
        html = generate_report(self.repo).replace("\n", "")
        self.assertIn("<td>Avionics.LRU</td><td>mass</td><td>3 kg</td><td>inherited from FCC</td>", html)
        self.assertIn("<td>Avionics.LRU</td><td>dal</td><td>A</td><td>inherited from FCC</td>", html)
        self.assertIn("<td>Avionics.LRU</td><td>mass</td><td>4 kg</td><td>set here (the definition has 3 kg)</td>", html)
        text = export_sysml(self.repo)
        self.assertIn("(inherited from FCC)", text)
        self.assertEqual(text.count("#Avionics.LRU"), 3)                    # FCC, fcc1 (override), fcc2 (inherited)

    def test_legacy_stereotypes_keep_their_values_per_element(self):
        """The pre-profile API (a stereotype in a plain package, untyped tags) is not inherited."""
        from kerml.namespaces import Package
        from kerml.stereotypes import Stereotype
        pkg = Package(name="Legacy")
        self.root.own(pkg)
        old = Stereotype("Old", applies_to=[PartDefinition, PartUsage])
        pkg.own(old)
        old.define_tag("mass", default=0.0)
        old.apply(self.fcc_def, {"mass": 4.2})
        self.assertEqual([a.stereotype.name for a in effective_applications(self.fcc1)], ["LRU"])   # not «Old»
        old.apply(self.fcc1)
        self.assertEqual(stereotypes_on(self.fcc1)[0].values, {"mass": 0.0})      # the default, not 4.2


class RetypingTests(Base):
    """What a component reads must not change silently when its typing goes away."""

    def test_inlining_a_component_keeps_what_it_read(self):
        from engine import architecture as A
        P.set_property_value(self.repo, self.fcc1, "mass", 4)                # an override; dal inherited
        A.inline_component(self.repo, self.fcc1)
        A.inline_component(self.repo, self.fcc2)
        self.assertIsNone(inheritance_source(self.fcc1))
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 4.0)
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.dal"), "A")      # was inherited
        self.assertEqual(P.get_property_value(self.fcc2, "Avionics.LRU.mass"), 3.0)     # was inherited
        P.set_property_value(self.repo, self.fcc_def, "Avionics.LRU.mass", 9)           # no longer follows
        self.assertEqual(P.get_property_value(self.fcc2, "Avionics.LRU.mass"), 3.0)
        self.assertEqual([a.inherited for a in effective_applications(self.fcc2)], [False])

    def test_retyping_follows_the_new_definition(self):
        from engine import architecture as A
        other = _own(self.repo, PartDefinition, "Other", self.root)
        P.apply_stereotype(self.repo, other, self.lru, {"mass": 20})
        A.set_definition(self.repo, self.fcc2, other)
        self.assertEqual(P.get_property_value(self.fcc2, "Avionics.LRU.mass"), 20.0)
        self.assertEqual(P.get_property_value(self.fcc1, "Avionics.LRU.mass"), 3.0)

    def test_copies_do_not_freeze_inherited_values(self):
        from engine import architecture as A
        P.set_property_value(self.repo, self.fcc1, "mass", 4)
        copies, _mapping, apps = A.clone_forest([self.fcc1, self.fcc2])
        self.assertEqual([(c.name, st.name, vals) for c, st, vals in apps],
                         [("fcc1", "LRU", {"mass": 4.0})])                # fcc2 inherits: nothing to copy


class PersistenceTests(Base):

    def _reload(self):
        return from_json(to_json(self.repo))

    def _find(self, repo, name):
        return next(e for e in repo.root_package.walk() if e.name == name)

    def test_overrides_round_trip(self):
        P.set_property_values(self.repo, self.fcc1, {"mass": "2 lb", "dal": "E"})
        P.apply_stereotype(self.repo, self.fcc2, self.lru)                  # an override without values
        repo2 = self._reload()
        fcc1, fcc2, fdef = (self._find(repo2, n) for n in ("fcc1", "fcc2", "FCC"))
        self.assertAlmostEqual(P.get_property_value(fcc1, "Avionics.LRU.mass"), 0.90718474)
        self.assertEqual(P.get_property_value(fcc1, "Avionics.LRU.dal"), "E")
        self.assertEqual(P.get_property_value(fcc1, "Avionics.LRU.power"), 10.0)
        self.assertEqual([t.name for t in stereotypes_on(fcc1)[0].explicit_tags()], ["mass", "dal"])
        self.assertEqual(stereotypes_on(fcc2)[0].explicit_tags(), [])
        # the override is still an override after the load: the definition's changes reach fcc2 only
        P.set_property_values(repo2, fdef, {"Avionics.LRU.mass": "7 kg", "Avionics.LRU.power": 70})
        self.assertEqual(P.get_property_value(fcc2, "Avionics.LRU.mass"), 7.0)
        self.assertEqual(P.get_property_value(fcc2, "Avionics.LRU.power"), 70.0)
        self.assertAlmostEqual(P.get_property_value(fcc1, "Avionics.LRU.mass"), 0.90718474)
        self.assertEqual(P.get_property_value(fcc1, "Avionics.LRU.power"), 70.0)
        # saving again is stable
        self.assertEqual(json.loads(to_json(self._reload()))["elements"].__len__(),
                         json.loads(to_json(self.repo))["elements"].__len__())

    def test_override_equal_to_default_survives(self):
        """An override that equals the property default is still an override (it is recorded)."""
        P.set_property_value(self.repo, self.fcc1, "mass", 1.5)             # = the default
        repo2 = self._reload()
        P.set_property_value(repo2, self._find(repo2, "FCC"), "mass", 8)
        self.assertEqual(P.get_property_value(self._find(repo2, "fcc1"), "mass"), 1.5)

    def test_inherited_values_in_the_file_do_not_become_overrides(self):
        """`values` of the saved application holds what is read; only the recorded set is own."""
        P.apply_stereotype(self.repo, self.fcc1, self.lru)
        data = json.loads(to_json(self.repo))
        el = next(e for e in data["elements"] if e["name"] == "fcc1")
        self.assertEqual(el["stereotypes"][0]["values"]["mass"], 3.0)
        repo2 = from_json(json.dumps(data))
        P.set_property_value(repo2, self._find(repo2, "FCC"), "mass", 6)
        self.assertEqual(P.get_property_value(self._find(repo2, "fcc1"), "mass"), 6.0)

    def test_files_from_before_inheritance_load(self):
        """No override record: a value that differs from the default counts as set."""
        P.apply_stereotype(self.repo, self.fcc1, self.lru, {"mass": 4})
        data = json.loads(to_json(self.repo))
        for e in data["elements"]:
            if e["name"] == "fcc1":                    # what a version without inheritance wrote
                (e.get("ext") or {}).pop("profiles", None)
                e["stereotypes"][0]["values"] = {"mass": 4.0, "power": 10.0, "dal": "C"}
        repo2 = from_json(json.dumps(data))
        fcc1 = self._find(repo2, "fcc1")
        self.assertEqual(P.get_property_value(fcc1, "mass"), 4.0)
        self.assertEqual([t.name for t in stereotypes_on(fcc1)[0].explicit_tags()], ["mass"])


if __name__ == "__main__":
    unittest.main()
