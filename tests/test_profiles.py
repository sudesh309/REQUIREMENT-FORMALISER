"""Engine tests for profiles, stereotypes and typed stereotype properties."""
import json
import unittest

from engine import Repository, Validator, from_json, to_json
from engine import profiles as P
from engine.hooks import notify_created
from kerml.elements import Element
from kerml.namespaces import Package
from kerml.stereotypes import (
    CATEGORIES, Profile, Stereotype, StereotypeError, matches_category, categories_of, stereotypes_on,
)
from sysmlv2 import (
    ActionDefinition, AttributeUsage, ConnectionUsage, InterfaceDefinition, PartDefinition,
    PartUsage, PortDefinition, PortUsage, RequirementDefinition, StateDefinition,
)
from sysmlv2.definitions import AllocationUsage


def _avionics(repo=None):
    """Avionics profile: abstract Equipment (Component, mass) <- LRU (dal) + ports."""
    repo = repo or Repository("Aircraft")
    prof = P.create_profile(repo, "Avionics", description="Avionics profile", version="2.1")
    eq = P.add_stereotype(repo, prof, "Equipment", applies_to="Component", abstract=True,
                          style={"fill": "#dbeafe", "stroke": "#1d4ed8"})
    P.add_property(repo, eq, "mass", "double", unit="kg", default="1.5", minimum=0)
    P.add_property(repo, eq, "power", "double", unit="W", default=10)
    lru = P.add_stereotype(repo, prof, "LRU", base=eq, style={"icon": "computer"})
    P.add_property(repo, lru, "dal", "enumeration", literals="A,B,C,D,E", default="C")
    P.add_property(repo, lru, "ata", "uint8", default=31, maximum=99)
    port = P.add_stereotype(repo, prof, "A429Port", applies_to="Port")
    P.add_property(repo, port, "rate", "double", unit="kbit/s", default="100 kbit/s")
    bus = P.add_stereotype(repo, prof, "A429Bus", applies_to="Connector", style={"line": "dashed"})
    P.add_property(repo, bus, "labels", "int32", default=0)
    return repo, prof, eq, lru, port, bus


def _system(repo):
    arch = PartDefinition(name="AvSystem")
    repo.root_package.own(arch)
    notify_created(arch, repo)
    fmc = PartUsage(name="FMC")
    arch.own(fmc)
    notify_created(fmc, repo)
    adc = PartUsage(name="ADC")
    arch.own(adc)
    notify_created(adc, repo)
    return arch, fmc, adc


def _new(repo, cls, name, owner):
    e = cls(name=name)
    owner.own(e)
    notify_created(e, repo)
    return e


class DefinitionTests(unittest.TestCase):

    def setUp(self):
        self.repo, self.prof, self.eq, self.lru, self.port, self.bus = _avionics()

    def test_profile_and_names(self):
        self.assertIsInstance(self.prof, Package)
        self.assertEqual([s.name for s in self.prof.stereotypes], ["Equipment", "LRU", "A429Port", "A429Bus"])
        self.assertEqual(self.lru.full_name, "Avionics.LRU")
        self.assertIs(P.find_stereotype(self.repo, "Avionics.LRU"), self.lru)
        self.assertIs(P.find_stereotype(self.repo, "LRU"), self.lru)
        self.assertIs(P.find_stereotype(self.repo, "Avionics::LRU"), self.lru)
        self.assertIs(P.find_stereotype(self.repo, self.lru.element_id), self.lru)
        self.assertIs(P.find_property(self.repo, "Avionics.LRU.mass"), self.eq.tags[0])
        with self.assertRaises(P.ProfileError) as cm:
            P.find_stereotype(self.repo, "Nope.X")
        self.assertEqual(cm.exception.status, 404)

    def test_ambiguous_bare_name(self):
        other = P.create_profile(self.repo, "Other")
        P.add_stereotype(self.repo, other, "LRU")
        with self.assertRaises(P.ProfileError) as cm:
            P.find_stereotype(self.repo, "LRU")
        self.assertIn("ambiguous", str(cm.exception))
        self.assertIs(P.find_stereotype(self.repo, "Other.LRU").profile, other)

    def test_names_are_checked(self):
        for bad in ("", "has space", "a.b", "1x"):
            with self.subTest(bad=bad), self.assertRaises(P.ProfileError):
                P.add_stereotype(self.repo, self.prof, bad)
        with self.assertRaises(P.ProfileError) as cm:
            P.add_stereotype(self.repo, self.prof, "LRU")
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(P.ProfileError) as cm:
            P.create_profile(self.repo, "Avionics")
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(P.ProfileError):
            P.add_property(self.repo, self.lru, "mass")        # inherited from Equipment
        with self.assertRaises(P.ProfileError):
            P.add_property(self.repo, self.eq, "dal")          # defined by derived LRU

    def test_property_definitions_are_checked(self):
        bad = [dict(prop_type="float"), dict(prop_type="string", unit="kg"), dict(unit="parsec"),
               dict(prop_type="enumeration"), dict(minimum=5, maximum=1), dict(default="abc"),
               dict(prop_type="int8", default=300), dict(default="3 psi", unit="kg"),
               dict(prop_type="boolean", minimum=0)]
        for kw in bad:
            with self.subTest(kw=kw), self.assertRaises(P.ProfileError):
                P.add_property(self.repo, self.port, "x", kw.pop("prop_type", "double"), **kw)
        self.assertEqual([t.name for t in self.port.tags], ["rate"])

    def test_defaults_are_coerced(self):
        mass, power = self.eq.tags
        self.assertEqual((mass.default_value, mass.unit, mass.minimum), (1.5, "kg", 0.0))
        self.assertEqual(power.default_value, 10.0)
        self.assertEqual(self.port.tags[0].default_value, 100.0)
        t = P.add_property(self.repo, self.port, "latency", "double", unit="ms", default="2*0.75 ms")
        self.assertEqual(t.default_value, 1.5)
        b = P.add_property(self.repo, self.port, "redundant", "boolean")
        self.assertIs(b.default_value, False)
        s = P.add_property(self.repo, self.port, "label", "string")
        self.assertEqual(s.default_value, "")

    def test_inheritance_groups_and_style(self):
        self.assertEqual([t.name for t in self.lru.all_tags()], ["dal", "ata", "mass", "power"])
        groups = [(s.name, [t.name for t in props]) for s, props in self.lru.property_groups()]
        self.assertEqual(groups, [("Equipment", ["mass", "power"]), ("LRU", ["dal", "ata"])])
        self.assertEqual(self.lru.effective_category(), "Component")
        self.assertEqual(self.lru.effective_style(),
                         {"fill": "#dbeafe", "stroke": "#1d4ed8", "icon": "computer"})

    def test_base_cycles_and_conflicts_rejected(self):
        with self.assertRaises(P.ProfileError) as cm:
            P.update_stereotype(self.repo, self.eq, base=self.lru)
        self.assertIn("cycle", str(cm.exception))
        with self.assertRaises(P.ProfileError):
            P.update_stereotype(self.repo, self.eq, base=self.eq)
        with self.assertRaises(P.ProfileError):
            P.update_stereotype(self.repo, self.port, base=self.eq)   # Port vs Component
        with self.assertRaises(P.ProfileError):
            P.update_stereotype(self.repo, self.lru, applies_to="Port")
        other = P.add_stereotype(self.repo, self.prof, "Box")
        P.add_property(self.repo, other, "mass", "double")
        with self.assertRaises(P.ProfileError) as cm:
            P.update_stereotype(self.repo, other, base=self.eq)
        self.assertEqual(cm.exception.status, 409)

    def test_style_and_categories_validated(self):
        for kw in (dict(style={"fill": "red"}), dict(style={"icon": "rocket"}),
                   dict(style={"line": "wavy"}), dict(style={"glow": "#fff"}), dict(applies_to="Widget")):
            with self.subTest(kw=kw), self.assertRaises(P.ProfileError):
                P.update_stereotype(self.repo, self.port, **kw)
        out = P.update_stereotype(self.repo, self.port, style={"fill": "#ABCDEF", "icon": ""})
        self.assertEqual(out["stereotype"].style, {"fill": "#abcdef"})

    def test_default_stereotypes_validated(self):
        with self.assertRaises(P.ProfileError):
            P.update_stereotype(self.repo, self.lru, defaults={"port": "Avionics.A429Bus"})
        with self.assertRaises(P.ProfileError):
            P.update_stereotype(self.repo, self.lru, defaults={"component": "Avionics.Equipment"})
        with self.assertRaises(P.ProfileError):
            P.update_stereotype(self.repo, self.port, defaults={"port": "Avionics.A429Port"})
        P.update_stereotype(self.repo, self.lru, defaults={"port": "Avionics.A429Port"})
        self.assertIs(self.lru.effective_default("port"), self.port)


class CategoryTests(unittest.TestCase):

    def test_categories_by_kind(self):
        root = Package(name="P")
        arch = PartDefinition(name="Arch"); root.own(arch)
        comp = PartUsage(name="c"); arch.own(comp)
        port = PortUsage(name="p"); comp.own(port)
        conn = ConnectionUsage(name="k"); arch.own(conn)
        pdef = PortDefinition(name="PD"); root.own(pdef)
        idef = InterfaceDefinition(name="ID"); root.own(idef)
        attr = AttributeUsage(name="a"); pdef.own(attr)
        req = RequirementDefinition(name="R"); root.own(req)
        act = ActionDefinition(name="F"); root.own(act)
        state = StateDefinition(name="S"); root.own(state)
        alloc = AllocationUsage(name="al"); root.own(alloc)
        self.assertEqual(categories_of(arch), ["Component", "Architecture"])
        self.assertEqual(categories_of(comp), ["Component"])
        self.assertEqual(categories_of(port), ["Port"])
        self.assertEqual(categories_of(conn), ["Connector"])
        self.assertEqual(categories_of(pdef), ["Interface"])
        self.assertEqual(categories_of(idef), ["Interface"])
        self.assertEqual(categories_of(attr), ["InterfaceElement"])
        self.assertEqual(categories_of(req), ["Requirement"])
        self.assertEqual(categories_of(act), ["Function"])
        self.assertEqual(categories_of(state), [])
        self.assertEqual(categories_of(alloc), ["Allocation"])

    def test_allocation_categories_are_separate(self):
        """PO-13: Allocation matches allocations only, AllocationSet allocation sets only."""
        from engine.allocation import AllocationScenario, AllocationSet, ArchitectureAllocation
        from sysmlv2.definitions import AllocationDefinition
        aset, scen, alloc = AllocationSet(name="S"), AllocationScenario(name="Sc"), ArchitectureAllocation(name="a")
        self.assertEqual(categories_of(aset), ["AllocationSet"])
        self.assertEqual(categories_of(alloc), ["Allocation"])
        self.assertEqual(categories_of(scen), [])              # a scenario is neither
        self.assertEqual(categories_of(AllocationDefinition(name="AD")), ["Allocation"])
        self.assertEqual(categories_of(AllocationUsage(name="au")), ["Allocation"])
        self.assertIn("AllocationSet", CATEGORIES)
        self.assertEqual(CATEGORIES.index("AllocationSet"), CATEGORIES.index("Allocation") + 1)

    def test_allocation_stereotypes_apply_only_to_allocations(self):
        from engine.allocation import AllocationSet, ArchitectureAllocation
        repo = Repository("A")
        prof = P.create_profile(repo, "Alloc")
        on_alloc = P.add_stereotype(repo, prof, "Binding", applies_to="Allocation")
        on_set = P.add_stereotype(repo, prof, "Plan", applies_to="AllocationSet")
        anything = P.add_stereotype(repo, prof, "Tagged")
        aset = _new(repo, AllocationSet, "Set", repo.root_package)
        alloc = _new(repo, ArchitectureAllocation, "al", repo.root_package)
        offered = lambda e: {s.name for s in P.applicable_stereotypes(repo, e)}
        self.assertEqual(offered(alloc), {"Binding", "Tagged"})
        self.assertEqual(offered(aset), {"Plan", "Tagged"})
        P.apply_stereotype(repo, alloc, on_alloc)
        P.apply_stereotype(repo, aset, on_set)
        with self.assertRaises(P.ProfileError):
            P.apply_stereotype(repo, aset, on_alloc)             # the old category let this through
        with self.assertRaises(P.ProfileError):
            P.apply_stereotype(repo, alloc, on_set)
        # a batch over the model skips what is already stereotyped and tags nothing else
        out = P.batch_apply(repo, on_alloc, scope="model")
        self.assertEqual((out["count"], [x["reason"] for x in out["skipped"]]), (0, ["already applied"]))
        out = P.batch_apply(repo, on_set, scope="model")
        self.assertEqual((out["count"], [x["reason"] for x in out["skipped"]]), (0, ["already applied"]))
        reloaded = from_json(to_json(repo))
        self.assertEqual(sum(1 for e in P.model_elements(reloaded) if stereotypes_on(e)), 2)

    def test_kinds_from_parallel_features_match_by_name(self):
        class DataInterface(PortDefinition):
            kind = "DataInterface"

        class DataElement(AttributeUsage):
            kind = "DataElement"

        class InterfaceDictionary(Package):
            kind = "InterfaceDictionary"

        class AllocationSet(Element):
            kind = "AllocationSet"

        class FunctionDefinition(Element):
            kind = "FunctionDefinition"

        self.assertTrue(matches_category(DataInterface(name="d"), "Interface"))
        self.assertTrue(matches_category(DataElement(name="e"), "InterfaceElement"))
        self.assertFalse(matches_category(InterfaceDictionary(name="x"), "Interface"))
        # PO-13: an Allocation stereotype applies to allocations only; sets have their own category.
        self.assertFalse(matches_category(AllocationSet(name="s"), "Allocation"))
        self.assertTrue(matches_category(AllocationSet(name="s"), "AllocationSet"))
        self.assertTrue(matches_category(FunctionDefinition(name="f"), "Function"))

        class ServiceInterface(PortDefinition):
            kind = "ServiceInterface"

        class FunctionElement(AttributeUsage):
            kind = "FunctionElement"

        class Adapter(PartUsage):
            kind = "Adapter"

        self.assertEqual(categories_of(ServiceInterface(name="s")), ["Interface"])
        self.assertEqual(categories_of(FunctionElement(name="f")), ["InterfaceElement"])
        self.assertEqual(categories_of(Adapter(name="a")), ["Component"])


class ApplicationTests(unittest.TestCase):

    def setUp(self):
        self.repo, self.prof, self.eq, self.lru, self.port, self.bus = _avionics()
        self.arch, self.fmc, self.adc = _system(self.repo)

    def test_apply_with_defaults_and_values(self):
        app = P.apply_stereotype(self.repo, self.fmc, self.lru, {"mass": "3 lb", "Avionics.LRU.dal": "a"})
        self.assertEqual(app.values, {"dal": "A", "ata": 31, "mass": 1.36077711, "power": 10.0})
        self.assertEqual(P.get_property_value(self.fmc, "Avionics.LRU.mass"), 1.36077711)
        self.assertEqual(P.get_property_value(self.fmc, "Avionics.Equipment.power"), 10.0)

    def test_value_checks(self):
        P.apply_stereotype(self.repo, self.fmc, self.lru)
        cases = {"Avionics.LRU.mass": ["3 psi", "-1", "abc", True],
                 "Avionics.LRU.dal": ["F", 3],
                 "Avionics.LRU.ata": ["100", "1.5", "-1"]}
        for path, values in cases.items():
            for v in values:
                with self.subTest(path=path, v=v), self.assertRaises(P.ProfileError) as cm:
                    P.set_property_value(self.repo, self.fmc, path, v)
                self.assertIn(path.rsplit(".", 1)[1], str(cm.exception))
        self.assertEqual(P.set_property_value(self.repo, self.fmc, "LRU.ata", "4*10"), 40)
        self.assertEqual(P.set_property_value(self.repo, self.fmc, "mass", "500 g"), 0.5)
        self.assertEqual(P.set_property_value(self.repo, self.fmc, "mass", ""), None)

    def test_set_values_is_all_or_nothing(self):
        P.apply_stereotype(self.repo, self.fmc, self.lru)
        with self.assertRaises(P.ProfileError):
            P.set_property_values(self.repo, self.fmc, {"Avionics.LRU.dal": "B", "Avionics.LRU.mass": "x"})
        self.assertEqual(P.get_property_value(self.fmc, "Avionics.LRU.dal"), "C")
        out = P.set_property_values(self.repo, self.fmc, {"Avionics.LRU.dal": "B", "Avionics.LRU.mass": 2})
        self.assertEqual(out, {"Avionics.LRU.dal": "B", "Avionics.LRU.mass": 2.0})

    def test_typed_values_by_type(self):
        st = P.add_stereotype(self.repo, self.prof, "Typed")
        for name, t in (("b", "boolean"), ("s", "string"), ("i8", "int8"), ("u16", "uint16"),
                        ("f", "single"), ("i64", "int64")):
            P.add_property(self.repo, st, name, t)
        P.apply_stereotype(self.repo, self.fmc, st)
        for path, given, stored in (("Typed.b", "yes", True), ("Typed.b", "0", False), ("Typed.s", 42, "42"),
                                    ("Typed.i8", "-128", -128), ("Typed.u16", 65535, 65535),
                                    ("Typed.f", "1e3", 1000.0), ("Typed.i64", "2**40", 2 ** 40)):
            with self.subTest(path=path, given=given):
                self.assertEqual(P.set_property_value(self.repo, self.fmc, path, given), stored)
        for path, bad in (("Typed.b", "maybe"), ("Typed.i8", 128), ("Typed.u16", -1), ("Typed.f", "1e39"),
                          ("Typed.s", [1])):
            with self.subTest(path=path, bad=bad), self.assertRaises(P.ProfileError):
                P.set_property_value(self.repo, self.fmc, path, bad)

    def test_abstract_duplicate_and_applicability(self):
        with self.assertRaises(P.ProfileError) as cm:
            P.apply_stereotype(self.repo, self.fmc, self.eq)
        self.assertIn("abstract", str(cm.exception))
        P.apply_stereotype(self.repo, self.fmc, self.lru)
        with self.assertRaises(P.ProfileError) as cm:
            P.apply_stereotype(self.repo, self.fmc, self.lru)
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(P.ProfileError):
            P.apply_stereotype(self.repo, self.fmc, self.port)
        # The legacy entry point enforces the same rules (TypeError for old callers).
        with self.assertRaises(TypeError):
            self.lru.apply(self.fmc)
        with self.assertRaises(TypeError):
            self.eq.apply(self.adc)
        with self.assertRaises(P.ProfileError):
            P.apply_stereotype(self.repo, self.lru, self.lru)       # profile definitions are not targets

    def test_multiple_stereotypes(self):
        extra = P.add_stereotype(self.repo, self.prof, "Cots")
        P.add_property(self.repo, extra, "vendor", "string", default="ACME")
        P.apply_stereotype(self.repo, self.fmc, self.lru)
        P.apply_stereotype(self.repo, self.fmc, extra)
        self.assertEqual([a.stereotype.full_name for a in stereotypes_on(self.fmc)],
                         ["Avionics.LRU", "Avionics.Cots"])
        self.assertEqual(P.get_property_value(self.fmc, "vendor"), "ACME")
        self.assertEqual([s.full_name for s in P.applicable_stereotypes(self.repo, self.fmc)], [])
        self.assertEqual(P.remove_all_stereotypes(self.repo, self.fmc), 2)
        self.assertEqual(stereotypes_on(self.fmc), [])

    def test_abstract_guard(self):
        P.apply_stereotype(self.repo, self.fmc, self.lru)
        with self.assertRaises(StereotypeError):
            self.lru.is_abstract = True                  # any path (e.g. a generic property edit)
        with self.assertRaises(P.ProfileError) as cm:
            P.update_stereotype(self.repo, self.lru, abstract=True)
        self.assertEqual(cm.exception.status, 409)
        out = P.update_stereotype(self.repo, self.lru, abstract=True, force=True)
        self.assertEqual(len(out["stripped"]), 1)
        self.assertEqual(stereotypes_on(self.fmc), [])

    def test_category_change_guard(self):
        P.apply_stereotype(self.repo, self.fmc, self.lru)
        with self.assertRaises(P.ProfileError) as cm:
            P.update_stereotype(self.repo, self.eq, applies_to="Port")
        self.assertEqual(cm.exception.status, 409)
        P.update_stereotype(self.repo, self.eq, applies_to="")     # loosening is fine
        self.assertEqual(self.lru.effective_category(), "")

    def test_display_fields(self):
        P.apply_stereotype(self.repo, self.fmc, self.lru)
        self.assertEqual(P.display_fields(self.fmc),
                         (["«LRU»"], {"fill": "#dbeafe", "stroke": "#1d4ed8", "icon": "computer"}))
        conn = _new(self.repo, ConnectionUsage, "bus1", self.arch)
        P.apply_stereotype(self.repo, conn, self.bus)
        self.assertEqual(P.display_fields(conn)[1], {"dash": "6 4"})

    def test_inherited_addressing(self):
        P.apply_stereotype(self.repo, self.fmc, self.lru)
        P.set_property_value(self.repo, self.fmc, "Avionics.Equipment.mass", 2)
        self.assertEqual(P.get_property_value(self.fmc, "Avionics.LRU.mass"), 2.0)
        with self.assertRaises(P.ProfileError):
            P.get_property_value(self.fmc, "Avionics.Equipment.dal")   # dal is LRU's, not Equipment's
        with self.assertRaises(P.ProfileError) as cm:
            P.get_property_value(self.adc, "Avionics.LRU.mass")
        self.assertEqual(cm.exception.status, 404)


class DefaultStereotypeTests(unittest.TestCase):

    def setUp(self):
        self.repo, self.prof, self.eq, self.lru, self.port, self.bus = _avionics()
        sub = P.add_stereotype(self.repo, self.prof, "Module", applies_to="Component")
        P.update_stereotype(self.repo, self.lru, defaults={"port": "Avionics.A429Port",
                                                           "connector": self.bus, "component": sub})
        self.sub = sub

    def test_defaults_applied_on_creation(self):
        arch, fmc, _adc = _system(self.repo)
        P.apply_stereotype(self.repo, fmc, self.lru)
        p = _new(self.repo, PortUsage, "a429_out", fmc)
        c = _new(self.repo, PartUsage, "cpu", fmc)
        k = _new(self.repo, ConnectionUsage, "link", fmc)
        loose = _new(self.repo, PortUsage, "free", arch)
        self.assertEqual([a.stereotype.name for a in stereotypes_on(p)], ["A429Port"])
        self.assertEqual(stereotypes_on(p)[0].values, {"rate": 100.0})
        self.assertEqual([a.stereotype.name for a in stereotypes_on(c)], ["Module"])
        self.assertEqual([a.stereotype.name for a in stereotypes_on(k)], ["A429Bus"])
        self.assertEqual(stereotypes_on(loose), [])

    def test_defaults_reach_the_definition_of_a_reference_component(self):
        """Ports of a reference component live on its definition (engine/structure.py)."""
        arch, _fmc, _adc = _system(self.repo)
        fcc_def = _new(self.repo, PartDefinition, "FCCDef", self.repo.root_package)
        fcc = PartUsage(name="FCC")
        fcc.add_type(fcc_def)
        arch.own(fcc)
        notify_created(fcc, self.repo)
        P.apply_stereotype(self.repo, fcc, self.lru)          # on the usage, as on the canvas
        p = _new(self.repo, PortUsage, "a429_in", fcc_def)
        self.assertEqual([a.stereotype.name for a in stereotypes_on(p)], ["A429Port"])
        other = _new(self.repo, PartDefinition, "Unused", self.repo.root_package)
        self.assertEqual(stereotypes_on(_new(self.repo, PortUsage, "q", other)), [])

    def test_defaults_are_inherited_from_base(self):
        P.update_stereotype(self.repo, self.lru, defaults={"port": None})
        P.update_stereotype(self.repo, self.eq, defaults={"port": self.port})
        _arch, fmc, _adc = _system(self.repo)
        P.apply_stereotype(self.repo, fmc, self.lru)
        p = _new(self.repo, PortUsage, "p", fmc)
        self.assertEqual([a.stereotype.name for a in stereotypes_on(p)], ["A429Port"])

    def test_model_root_stereotype(self):
        sysst = P.add_stereotype(self.repo, self.prof, "AircraftSystem", applies_to="Architecture")
        existing = PartDefinition(name="Existing")
        self.repo.root_package.own(existing)
        notify_created(existing, self.repo)
        out = P.update_profile(self.repo, self.prof, root_stereotype="Avionics.AircraftSystem")
        self.assertEqual(out["root_applied"], ["Aircraft::Existing"])
        arch, fmc, _ = _system(self.repo)
        self.assertEqual([a.stereotype for a in stereotypes_on(arch)], [sysst])
        self.assertEqual(stereotypes_on(fmc), [])
        with self.assertRaises(P.ProfileError):
            P.update_profile(self.repo, self.prof, root_stereotype="Avionics.A429Port")
        with self.assertRaises(P.ProfileError):
            P.update_profile(self.repo, self.prof, root_stereotype="Avionics.Equipment")


class PropagationTests(unittest.TestCase):

    def setUp(self):
        self.repo, self.prof, self.eq, self.lru, self.port, self.bus = _avionics()
        self.arch, self.fmc, self.adc = _system(self.repo)
        P.apply_stereotype(self.repo, self.fmc, self.lru, {"mass": 2, "dal": "A"})
        P.apply_stereotype(self.repo, self.adc, self.lru, {"mass": 4})

    def test_rename_property_keeps_values(self):
        mass = self.eq.tags[0]
        P.update_property(self.repo, mass, name="weight")
        self.assertEqual(P.get_property_value(self.fmc, "Avionics.LRU.weight"), 2.0)
        self.assertNotIn("mass", stereotypes_on(self.fmc)[0].values)
        mass.name = "m"      # a generic rename (any front end) also keeps the value
        self.assertEqual(stereotypes_on(self.fmc)[0].values["m"], 2.0)

    def test_rename_stereotype_and_profile(self):
        P.update_stereotype(self.repo, self.lru, name="Lru")
        P.update_profile(self.repo, self.prof, name="Avio")
        self.assertEqual(P.get_property_value(self.fmc, "Avio.Lru.mass"), 2.0)
        self.assertEqual(P.display_fields(self.fmc)[0], ["«Lru»"])

    def test_unit_change_converts_values(self):
        mass = self.eq.tags[0]
        out = P.update_property(self.repo, mass, unit="g")
        self.assertEqual(out["converted"], 2)
        self.assertEqual(P.get_property_value(self.fmc, "mass"), 2000.0)
        self.assertEqual((mass.default_value, mass.minimum), (1500.0, 0.0))
        P.update_property(self.repo, mass, unit="W")      # incompatible: numbers are kept
        self.assertEqual(P.get_property_value(self.fmc, "mass"), 2000.0)

    def test_type_change_coerces_or_resets(self):
        dal = self.lru.tags[0]
        out = P.update_property(self.repo, dal, literals="DAL_A,DAL_B,DAL_C,DAL_D,DAL_E")
        self.assertEqual(P.get_property_value(self.fmc, "dal"), "DAL_A")     # renamed in place
        self.assertEqual(dal.default_value, "DAL_C")
        out = P.update_property(self.repo, dal, prop_type="string")
        self.assertEqual(P.get_property_value(self.fmc, "dal"), "DAL_A")
        out = P.update_property(self.repo, dal, prop_type="int32")
        self.assertEqual(len(out["reset"]), 2)
        self.assertIsNone(P.get_property_value(self.fmc, "dal"))
        ata = self.lru.tags[1]
        P.update_property(self.repo, ata, maximum=30)
        self.assertIsNone(P.get_property_value(self.fmc, "ata"))   # 31 no longer fits: reset

    def test_delete_property_and_stereotype(self):
        mass = self.eq.tags[0]
        out = P.delete_property(self.repo, mass)
        self.assertEqual(out["values_removed"], 2)
        self.assertNotIn("mass", stereotypes_on(self.fmc)[0].values)
        out = P.delete_stereotype(self.repo, self.eq)
        self.assertEqual(out["rebased"], ["Avionics.LRU"])
        self.assertIsNone(self.lru.base)
        self.assertEqual(set(stereotypes_on(self.fmc)[0].values), {"dal", "ata"})
        out = P.delete_stereotype(self.repo, self.lru)
        self.assertEqual(out["applications_removed"], 2)
        self.assertEqual(stereotypes_on(self.fmc), [])

    def test_delete_profile_strips_everything(self):
        other = P.create_profile(self.repo, "Ext")
        derived = P.add_stereotype(self.repo, other, "Special", base=self.lru)
        p = _new(self.repo, PortUsage, "p", self.fmc)
        P.apply_stereotype(self.repo, p, self.port)
        P.apply_stereotype(self.repo, self.arch, derived)
        out = P.delete_profile(self.repo, self.prof)
        self.assertEqual(out["applications_removed"], 3)
        self.assertEqual(out["rebased"], ["Ext.Special"])
        for e in (self.fmc, self.adc, p):
            self.assertEqual(stereotypes_on(e), [])
        self.assertEqual(stereotypes_on(self.arch)[0].values, {})
        self.assertNotIn("Avionics", to_json(self.repo).replace('"name": "Avionics"', ""))

    def test_move_property_order_persists(self):
        P.move_property(self.repo, self.lru.tags[1], 0)
        self.assertEqual([t.name for t in self.lru.tags], ["ata", "dal"])
        loaded = from_json(to_json(self.repo))
        lru = P.find_stereotype(loaded, "Avionics.LRU")
        self.assertEqual([t.name for t in lru.tags], ["ata", "dal"])


class BatchTests(unittest.TestCase):

    def setUp(self):
        self.repo, self.prof, self.eq, self.lru, self.port, self.bus = _avionics()
        self.arch, self.fmc, self.adc = _system(self.repo)
        self.p = _new(self.repo, PortUsage, "p", self.fmc)
        other = PartDefinition(name="Other")
        self.repo.root_package.own(other)
        notify_created(other, self.repo)
        self.other_c = _new(self.repo, PartUsage, "x", other)

    def test_model_scope(self):
        out = P.batch_apply(self.repo, self.lru, scope="model", values={"dal": "B"})
        names = {self.repo.by_id(i).name for i in out["applied"]}
        self.assertEqual(names, {"AvSystem", "FMC", "ADC", "Other", "x"})
        self.assertEqual(P.get_property_value(self.adc, "dal"), "B")
        again = P.batch_apply(self.repo, self.lru, scope="model")
        self.assertEqual(again["count"], 0)
        self.assertEqual(len(again["skipped"]), 5)

    def test_composition_and_selection_scopes(self):
        out = P.batch_apply(self.repo, self.lru, scope="composition", root=self.arch.element_id)
        self.assertEqual({self.repo.by_id(i).name for i in out["applied"]}, {"AvSystem", "FMC", "ADC"})
        out = P.batch_apply(self.repo, self.port, scope="selection",
                            elements=[self.p.element_id, self.other_c.element_id])
        self.assertEqual(out["applied"], [self.p.element_id])
        self.assertEqual(out["skipped"][0]["reason"], "not a Port")

    def test_batch_checks(self):
        with self.assertRaises(P.ProfileError):
            P.batch_apply(self.repo, self.eq, scope="model")                 # abstract
        with self.assertRaises(P.ProfileError):
            P.batch_apply(self.repo, self.lru, scope="model", values={"dal": "Z"})
        self.assertEqual(stereotypes_on(self.fmc), [])
        anything = P.add_stereotype(self.repo, self.prof, "Tagged")
        with self.assertRaises(P.ProfileError):
            P.batch_apply(self.repo, anything, scope="model")                # needs a category
        out = P.batch_apply(self.repo, anything, scope="model", category="Port")
        self.assertEqual(out["applied"], [self.p.element_id])
        with self.assertRaises(P.ProfileError):
            P.batch_apply(self.repo, self.lru, scope="selection", elements=[])
        with self.assertRaises(P.ProfileError):
            P.batch_apply(self.repo, self.lru, scope="galaxy")


class PersistenceTests(unittest.TestCase):

    def _project(self):
        repo, prof, eq, lru, port, bus = _avionics()
        arch, fmc, adc = _system(repo)
        P.update_stereotype(repo, lru, defaults={"port": port}, description="Line replaceable unit")
        P.update_profile(repo, prof, root_stereotype=None)
        P.apply_stereotype(repo, fmc, lru, {"mass": "3 lb", "dal": "A"})
        p = _new(repo, PortUsage, "out", fmc)
        P.set_property_value(repo, p, "rate", "12.5 kbit/s")
        return repo

    def test_round_trip(self):
        repo = self._project()
        loaded = from_json(to_json(repo))
        once = to_json(loaded)
        self.assertEqual(once, to_json(from_json(once)))
        prof = P.find_profile(loaded, "Avionics")
        self.assertEqual((prof.description, prof.version), ("Avionics profile", "2.1"))
        lru = P.find_stereotype(loaded, "Avionics.LRU")
        eq = P.find_stereotype(loaded, "Avionics.Equipment")
        self.assertIs(lru.base, eq)
        self.assertTrue(eq.is_abstract)
        self.assertEqual(lru.description, "Line replaceable unit")
        self.assertEqual(lru.effective_style()["icon"], "computer")
        self.assertIs(lru.default_port_stereotype, P.find_stereotype(loaded, "A429Port"))
        mass = eq.tags[0]
        self.assertEqual((mass.prop_type, mass.unit, mass.minimum, mass.default_value), ("double", "kg", 0.0, 1.5))
        self.assertEqual(lru.tags[0].literals, ["A", "B", "C", "D", "E"])
        fmc = loaded.resolve("AvSystem::FMC")
        self.assertEqual(stereotypes_on(fmc)[0].values,
                         {"dal": "A", "ata": 31, "mass": 1.36077711, "power": 10.0})
        self.assertEqual(P.get_property_value(loaded.resolve("AvSystem::FMC::out"), "rate"), 12.5)
        # Behaviour survives too: checks and defaults still work after loading.
        with self.assertRaises(P.ProfileError):
            P.set_property_value(loaded, fmc, "mass", "1 psi")
        q = _new(loaded, PortUsage, "in", fmc)
        self.assertEqual([a.stereotype.name for a in stereotypes_on(q)], ["A429Port"])
        self.assertEqual([i for i in Validator().validate(loaded) if i.rule.startswith("profile")], [])

    def test_legacy_project_loads(self):
        legacy = {
            "format": "sysmlv2-core/1", "name": "Old", "root": "root", "links": [], "ext": {},
            "elements": [
                {"id": "root", "class": "kerml.namespaces.Package", "kind": "Package", "name": "Old",
                 "short_name": None, "is_abstract": False, "owner": None},
                {"id": "st", "class": "kerml.stereotypes.Stereotype", "kind": "Stereotype", "name": "crit",
                 "short_name": None, "is_abstract": False, "owner": "root",
                 "applies_to": ["sysmlv2.definitions.PartDefinition"], "base": None},
                {"id": "tag", "class": "kerml.stereotypes.StereotypeTag", "kind": "StereotypeTag",
                 "name": "lvl", "short_name": None, "is_abstract": False, "owner": "st",
                 "multiplicity": [0, 1], "direction": "none", "is_composite": False,
                 "is_readonly": False, "is_derived": False, "is_end": False, "default_value": "QM",
                 "typed_by": [], "subsets": [], "redefines": [], "specializes": []},
                {"id": "v", "class": "sysmlv2.definitions.PartDefinition", "kind": "PartDefinition",
                 "name": "V", "short_name": None, "is_abstract": False, "owner": "root",
                 "specializes": [], "is_variation": False, "is_individual": False,
                 "stereotypes": [{"stereotype": "st", "values": {"lvl": {"any": ["json"]}}}]},
            ],
        }
        repo = from_json(json.dumps(legacy))
        v = repo.resolve("V")
        self.assertEqual(stereotypes_on(v)[0].values, {"lvl": {"any": ["json"]}})
        crit = repo.resolve("crit")
        self.assertEqual(crit.full_name, "crit")
        self.assertEqual(crit.tags[0].prop_type, "")
        self.assertEqual(P.set_property_value(repo, v, "crit.lvl", 7), 7)   # untyped: any value
        P.update_property(repo, crit.tags[0], prop_type="string")          # typed later: coerced
        self.assertEqual(P.get_property_value(v, "lvl"), "7")
        self.assertEqual(to_json(from_json(to_json(repo))), to_json(repo))

    def test_invalid_saved_state_still_loads(self):
        """A file with state the editing APIs refuse opens; the validator reports it."""
        from kerml.stereotypes import StereotypeApplication
        repo, prof, eq, lru, port, bus = _avionics()
        arch, fmc, adc = _system(repo)
        app = P.apply_stereotype(repo, fmc, lru, {"mass": 2})
        app.raw_slots()[eq.tags[0]] = -5.0                       # below the minimum 0 kg
        adc.add_annotation(StereotypeApplication(port, {}))       # wrong kind ...
        adc.add_annotation(StereotypeApplication(port, {}))       # ... and applied twice
        arch.add_annotation(StereotypeApplication(eq, {}))        # abstract
        data = json.loads(to_json(repo))
        for r in data["elements"]:                                # a property deleted by hand
            for a in r.get("stereotypes", []):
                a["values"]["gone"] = 1
        loaded = from_json(json.dumps(data))
        fmc2 = loaded.resolve("AvSystem::FMC")
        self.assertEqual(P.get_property_value(fmc2, "Avionics.LRU.mass"), -5.0)
        self.assertEqual(len(stereotypes_on(loaded.resolve("AvSystem::ADC"))), 2)
        rules = {i.rule for i in Validator().validate(loaded) if i.rule.startswith("profile")}
        for rule in ("profile.value.invalid", "profile.application.duplicate",
                     "profile.application.applies_to", "profile.application.abstract"):
            self.assertIn(rule, rules)
        # The editing API stays strict after loading.
        with self.assertRaises(P.ProfileError):
            P.apply_stereotype(loaded, fmc2, P.find_stereotype(loaded, "Avionics.LRU"))
        with self.assertRaises(P.ProfileError):
            P.set_property_value(loaded, fmc2, "Avionics.LRU.mass", -1)

    def test_import_log_round_trip(self):
        repo = self._project()
        text = P.export_profile_json(P.find_profile(repo, "Avionics"))
        target = Repository("Other")
        P.import_profile(target, text, file_name="Avionics.profile.json")
        loaded = from_json(to_json(target))
        self.assertEqual([x["file"] for x in P.import_log(loaded)], ["Avionics.profile.json"])
        P.delete_profile(loaded, P.find_profile(loaded, "Avionics"))
        self.assertEqual(P.import_log(loaded), [])


class ImportExportTests(unittest.TestCase):

    def setUp(self):
        self.repo, self.prof, self.eq, self.lru, self.port, self.bus = _avionics()
        P.update_stereotype(self.repo, self.lru, defaults={"port": self.port})
        self.text = P.export_profile_json(self.prof)

    def test_export_shape(self):
        data = json.loads(self.text)
        self.assertEqual(data["format"], P.PROFILE_FORMAT)
        st = {s["name"]: s for s in data["profile"]["stereotypes"]}
        self.assertEqual(st["LRU"]["base"], "Equipment")
        self.assertEqual(st["LRU"]["defaults"], {"port": "A429Port"})
        self.assertEqual(st["Equipment"]["properties"][0],
                         {"id": self.eq.tags[0].element_id, "name": "mass", "type": "double", "unit": "kg",
                          "default": 1.5, "min": 0.0, "max": None, "literals": [], "description": ""})

    def test_import_into_new_project(self):
        target = Repository("Target")
        out = P.import_profile(target, self.text)
        self.assertTrue(out["created"])
        lru = P.find_stereotype(target, "Avionics.LRU")
        self.assertEqual(lru.element_id, self.lru.element_id)          # ids kept when free
        self.assertEqual([t.name for t in lru.all_tags()], ["dal", "ata", "mass", "power"])
        self.assertIs(lru.default_port_stereotype, P.find_stereotype(target, "Avionics.A429Port"))
        self.assertEqual(P.export_profile(out["profile"])["profile"],
                         json.loads(self.text)["profile"])

    def test_import_conflict_and_replace(self):
        arch, fmc, adc = _system(self.repo)
        P.apply_stereotype(self.repo, fmc, self.lru, {"mass": 2})
        p = _new(self.repo, PortUsage, "p", fmc)       # gets A429Port by default
        with self.assertRaises(P.ProfileError) as cm:
            P.import_profile(self.repo, self.text)
        self.assertEqual(cm.exception.status, 409)
        data = json.loads(self.text)
        prof = data["profile"]
        prof["version"] = "3.0"
        sts = {s["name"]: s for s in prof["stereotypes"]}
        sts["Equipment"]["properties"][0]["unit"] = "g"            # converts stored values
        sts["Equipment"]["properties"][0]["name"] = "weight"       # rename matched by id
        sts["LRU"]["name"] = "Unit"
        sts["LRU"]["defaults"] = {}
        prof["stereotypes"] = [s for s in prof["stereotypes"] if s["name"] != "A429Port"]
        prof["stereotypes"].append({"name": "Sensor", "applies_to": "Component", "base": "Equipment",
                                    "properties": [{"name": "range", "type": "double", "unit": "nmi"}]})
        out = P.import_profile(self.repo, json.dumps(data), replace=True, file_name="v3.json")
        self.assertFalse(out["created"])
        self.assertIs(out["profile"], self.prof)
        self.assertEqual(self.prof.version, "3.0")
        self.assertEqual(self.lru.name, "Unit")
        self.assertEqual(P.get_property_value(fmc, "Avionics.Unit.weight"), 2000.0)
        self.assertEqual(stereotypes_on(p), [])                     # A429Port removed
        self.assertTrue(any("A429Port" in r for r in out["report"]))
        sensor = P.find_stereotype(self.repo, "Avionics.Sensor")
        self.assertIs(sensor.base, self.eq)
        self.assertEqual(self.prof.source["file"], "v3.json")

    def test_invalid_files_change_nothing(self):
        before = to_json(self.repo)
        target = Repository("T")
        base = json.loads(self.text)

        def variant(fn):
            d = json.loads(json.dumps(base))
            fn(d["profile"])
            return json.dumps(d)

        def sts(p):
            return {s["name"]: s for s in p["stereotypes"]}

        bad = [
            "not json", json.dumps({"format": "other/9", "profile": {}}), json.dumps([1]),
            variant(lambda p: sts(p)["LRU"].update(base="Missing.X")),
            variant(lambda p: sts(p)["Equipment"].update(base="LRU")),
            variant(lambda p: sts(p)["LRU"]["properties"].append({"name": "mass", "type": "double"})),
            variant(lambda p: sts(p)["LRU"]["properties"].append({"name": "x", "type": "float"})),
            variant(lambda p: sts(p)["LRU"]["properties"].append({"name": "x", "unit": "parsec", "type": "double"})),
            variant(lambda p: sts(p)["LRU"].update(applies_to="Port")),
            variant(lambda p: sts(p)["LRU"].update(defaults={"port": "A429Bus"})),
            variant(lambda p: p.update(root_stereotype="Equipment")),
            variant(lambda p: p["stereotypes"].append({"name": "LRU"})),
            variant(lambda p: p.update(name="bad name")),
        ]
        for text in bad:
            with self.subTest(text=text[:80]), self.assertRaises(P.ProfileError):
                P.import_profile(target, text)
            with self.subTest(text=text[:80]), self.assertRaises(P.ProfileError):
                P.import_profile(self.repo, text, replace=True)
        self.assertEqual(P.profiles_of(target), [])
        self.assertEqual(before, to_json(self.repo))


class ValidatorTests(unittest.TestCase):

    def _issues(self, repo):
        return {i.rule for i in Validator().validate(repo) if i.rule.startswith("profile")}

    def test_clean_model_has_no_issues(self):
        repo, *_ = _avionics()
        self.assertEqual(self._issues(repo), set())

    def test_detects_bad_state(self):
        repo, prof, eq, lru, port, bus = _avionics()
        arch, fmc, adc = _system(repo)
        app = P.apply_stereotype(repo, fmc, lru)
        app.raw_slots()[eq.tags[0]] = -5.0                 # out of range (min 0)
        app.raw_slots()[lru.tags[0]] = "Z"                 # not a literal
        bad_port = _new(repo, PortUsage, "p", fmc)
        from kerml.stereotypes import StereotypeApplication
        bad_port.add_annotation(StereotypeApplication(lru, {}))        # LRU on a port
        adc.add_annotation(StereotypeApplication(port, {}))
        adc.add_annotation(StereotypeApplication(port, {}))            # applied twice, and wrong kind
        arch.add_annotation(StereotypeApplication(eq, {}))             # abstract
        eq.tags[1].unit = "parsec"
        eq.tags[1].minimum, eq.tags[1].maximum = 5, 1
        rules = self._issues(repo)
        for rule in ("profile.value.invalid", "profile.application.applies_to",
                     "profile.application.duplicate", "profile.application.abstract",
                     "profile.property.definition"):
            self.assertIn(rule, rules)

    def test_detects_names_created_outside_the_editor(self):
        repo, prof, eq, lru, *_ = _avionics()
        odd = Stereotype(name="Line Unit")          # e.g. the generic "Add element" route
        prof.own(odd)
        notify_created(odd, repo)
        issues = [i for i in Validator().validate(repo) if i.rule == "profile.name"]
        self.assertEqual([i.element for i in issues], [odd])

    def test_detects_cycle(self):
        repo, prof, eq, lru, *_ = _avionics()
        eq.base = lru                                     # bypassing the API
        self.assertIn("profile.stereotype.cycle", self._issues(repo))
        self.assertEqual(len(lru.ancestors()), 2)         # walking stops at the cycle


if __name__ == "__main__":
    unittest.main()
