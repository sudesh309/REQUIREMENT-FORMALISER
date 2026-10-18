"""SysML v2 textual export: engine.parse(export(model)) recreates the structure."""
import unittest

from engine import Repository, parse
from engine.interop.sysml_export import export_sysml, import_sysml, parser_capabilities
from kerml.elements import Documentation
from kerml.features import Feature, FeatureDirection, MultiplicityRange
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Package
from sysmlv2 import (
    ActionDefinition, ActionUsage, AttributeDefinition, AttributeUsage, ConnectionUsage,
    ConstraintDefinition, EnumerationDefinition, EnumerationUsage, InterfaceDefinition,
    ItemDefinition, ItemUsage, PartDefinition, PartUsage, PortDefinition, PortUsage,
    RequirementDefinition, RequirementUsage, StateDefinition, StateUsage,
)
from tests.test_interop_fixtures import avionics_repo


def _family(e) -> str:
    """Kind family the parser can reproduce."""
    for cls in (RequirementDefinition, ConstraintDefinition, StateDefinition, ActionDefinition,
                PartDefinition, ItemDefinition, PortDefinition, InterfaceDefinition,
                EnumerationDefinition, AttributeDefinition, RequirementUsage, StateUsage,
                ActionUsage, PartUsage, ItemUsage, PortUsage, ConnectionUsage, EnumerationUsage,
                AttributeUsage, Package):
        if isinstance(e, cls):
            return cls.__name__
    return e.kind


def _signature(repo, *, ignore_connection_names=True) -> dict:
    out = {}
    for e in repo.root_package.walk():
        if e is repo.root_package:
            continue
        doc = next((a.body for a in e.annotations if isinstance(a, Documentation)), None)
        sig = {"family": _family(e), "doc": doc,
               "supers": sorted(s.target.qualified_name.split("::", 1)[-1]
                                for s in getattr(e, "specializations", []))}
        if isinstance(e, Feature):
            sig["types"] = [t.qualified_name.split("::", 1)[-1] for t in e.types]
            sig["mult"] = (e.multiplicity.lower, e.multiplicity.upper)
        for attr in ("req_id", "text"):
            if getattr(e, attr, None):
                sig[attr] = getattr(e, attr)
        if isinstance(e, ConnectionUsage):
            sig["ends"] = [x.qualified_name.split("::", 1)[-1] for x in e.ends]
        key = e.qualified_name.split("::", 1)[-1]
        if isinstance(e, ConnectionUsage) and ignore_connection_names:
            # The parser names connectors itself (connect_<a>_<b>).
            key = f"{e.owner.qualified_name.split('::', 1)[-1]}::<connect {sig['ends']}>"
        out[key] = sig
    return out


def supported_model() -> Repository:
    """Only constructs the engine parser reads."""
    repo = Repository("Text")
    real = KERML_LIBRARY.resolve("ScalarValues::Real")
    pkg = repo.add(Package(name="Avionics"))
    # Declared before their users on purpose *and* out of order, to test ordering.
    sys_ = PartDefinition(name="FlightDeck")
    sys_.add_annotation(Documentation(body="Top-level architecture"))
    pkg.own(sys_)
    word = PortDefinition(name="A429Word")
    pkg.own(word)
    word.own(AttributeUsage(name="label", typed_by=real, multiplicity=MultiplicityRange(1, 1)))
    alt = AttributeDefinition(name="Altitude")
    pkg.own(alt)
    lru = PartDefinition(name="LRU")
    pkg.own(lru)
    fmc = PartDefinition(name="FMC")
    fmc.specialize(lru)
    pkg.own(fmc)
    fmc.own(PortUsage(name="navIn", typed_by=word, multiplicity=MultiplicityRange(1, 1)))
    fmc.own(AttributeUsage(name="cruise", typed_by=alt, multiplicity=MultiplicityRange(0, 1)))
    fmc.own(ItemUsage(name="msgs", typed_by=word, multiplicity=MultiplicityRange(0, None)))
    sys_.own(PartUsage(name="fmc", typed_by=fmc, multiplicity=MultiplicityRange(1, 2)))
    sys_.own(ActionUsage(name="navigate", multiplicity=MultiplicityRange(1, 1)))
    sys_.own(StateUsage(name="mode", multiplicity=MultiplicityRange(1, 1)))
    phase = EnumerationDefinition(name="Phase")
    pkg.own(phase)
    for lit in ("Taxi", "Cruise"):
        u = EnumerationUsage(name=lit)
        u.add_type(phase)
        phase.own(u)
        phase.literals.append(u)
    pkg.own(ItemDefinition(name="Fuel"))
    pkg.own(InterfaceDefinition(name="Bus"))
    pkg.own(ActionDefinition(name="Navigate"))
    pkg.own(StateDefinition(name="Modes"))
    pkg.own(ConstraintDefinition(name="MassLimit"))
    reqs = repo.add(Package(name="Reqs"))
    r = RequirementDefinition(name="NavAccuracy", req_id="SRS-001", text="Position within 0.3 NM.")
    r.add_annotation(Documentation(body="From the customer spec"))
    reqs.own(r)
    reqs.own(RequirementDefinition(name="Empty"))
    sub = RequirementDefinition(name="Derived", req_id="SRS-002")
    sub.specialize(r)
    reqs.own(sub)
    sub.own(RequirementUsage(name="parent", typed_by=r, multiplicity=MultiplicityRange(1, 1)))
    # Top-level usages and a connection between them.
    a = PartUsage(name="left", typed_by=fmc, multiplicity=MultiplicityRange(1, 1))
    b = PartUsage(name="right", typed_by=fmc, multiplicity=MultiplicityRange(1, 1))
    pkg.own(a)
    pkg.own(b)
    pkg.own(ConnectionUsage(name="link1", ends=[a, b]))
    repo.registry.register_tree(repo.root_package)
    return repo


class SysmlExportTests(unittest.TestCase):

    def test_round_trip_recreates_structure(self):
        repo = supported_model()
        text = export_sysml(repo)
        new = Repository("RT")
        parse(text, into=new.root_package)
        new.registry.register_tree(new.root_package)
        self.assertEqual(_signature(new), _signature(repo))

    def test_round_trip_is_stable(self):
        def again(text):
            new = Repository("Text")
            parse(text, into=new.root_package)
            return export_sysml(new)
        first = again(export_sysml(supported_model()))
        self.assertEqual(again(first), first)

    def test_text_uses_sysml_v2_notation(self):
        text = export_sysml(supported_model())
        for snippet in ("package Avionics {", "part def FMC : LRU {", "port navIn : A429Word;",
                        "attribute label : ScalarValues::Real;", "attribute cruise : Altitude [0..1];",
                        "item msgs : A429Word [0..*];", "part fmc : FMC [1..2];",
                        'requirement def NavAccuracy id="SRS-001" {',
                        "doc /* Position within 0.3 NM. */", "/* From the customer spec */",
                        "enum def Phase {", "connect left to right;"):
            self.assertIn(snippet, text)
        # Definitions referenced by others come first for a parser without forward references.
        if not parser_capabilities()["forward_ref"]:
            self.assertLess(text.index("part def FMC"), text.index("part def FlightDeck"))
            self.assertLess(text.index("port def A429Word"), text.index("part def FMC"))

    def test_full_model_with_unsupported_constructs_still_parses(self):
        repo = avionics_repo()
        text = export_sysml(repo)
        new = Repository("RT")
        parse(text, into=new.root_package)          # must not raise
        new.registry.register_tree(new.root_package)
        self.assertIn("// #AvionicsProfile.LRU { mass = 4.2; dal = \"A\"; }", text)
        self.assertIn("// satisfy Requirements::NavAccuracy by Components::FlightManagementComputer;",
                      text)
        self.assertIn("// transition", text)
        self.assertIn("first Off accept powerOn then On;", text)
        caps = parser_capabilities()
        nav = new.resolve("Components::GPSReceiver::navOut")
        self.assertIsNotNone(nav)
        self.assertEqual(nav.types[0].name, "A429Word")
        if caps["direction"]:
            self.assertIs(nav.direction, FeatureDirection.OUT)
            self.assertIn("out port navOut : Interfaces::A429Word [0..*];", text)
        else:
            self.assertIn("port navOut : Interfaces::A429Word [0..*];  // out", text)
        fd = new.resolve("FlightDeck")
        self.assertEqual({p.name for p in fd.owned_elements if isinstance(p, PartUsage)},
                         {"gps", "fmc", "pfd", "ims"})
        self.assertEqual(new.resolve("FlightDeck::pfd").multiplicity.lower, 2)
        conns = [c for c in fd.owned_elements if isinstance(c, ConnectionUsage)]
        if caps["connect_in_def"]:
            self.assertEqual(len(conns), 2)
        else:
            self.assertEqual(conns, [])
            self.assertIn("// connection navBus connect gps.navOut to fmc.navIn;", text)
        req = new.resolve("Requirements::NavAccuracy")
        self.assertEqual((req.req_id, req.text), ("SRS-001", repo.resolve("Requirements::NavAccuracy").text))

    def test_names_that_need_quoting_are_commented(self):
        repo = Repository("Q")
        pd = repo.add(PartDefinition(name="Weird name"))
        ok = repo.add(PartDefinition(name="Fine"))
        ok.own(PortUsage(name="in", multiplicity=MultiplicityRange(1, 1)))
        repo.registry.register_tree(repo.root_package)
        text = export_sysml(repo)
        self.assertIn("// part def 'Weird name';", text)
        new = Repository("RT")
        parse(text, into=new.root_package)
        self.assertIsNone(new.resolve("Weird name"))
        self.assertIsNotNone(new.resolve("Fine"))
        self.assertIsNotNone(pd)

    def test_capabilities_are_booleans(self):
        caps = parser_capabilities()
        self.assertEqual(set(caps), {"direction", "usage_body", "connect_in_def", "forward_ref",
                                     "keyword_names", "scoped_package_usages"})
        self.assertTrue(all(isinstance(v, bool) for v in caps.values()))

    def test_import_sysml_registers_and_notifies(self):
        from engine import hooks, register_created_hook
        seen = []
        register_created_hook(lambda e, repo: seen.append(e.name))
        try:
            repo = Repository("I")
            created = import_sysml(repo, "package P { part def A; }")
        finally:
            hooks._CREATED_HOOKS.pop()
        self.assertEqual([e.name for e in created], ["P", "A"])
        self.assertEqual(seen, ["P", "A"])
        self.assertIs(repo.by_id(created[1].element_id), created[1])


if __name__ == "__main__":
    unittest.main()
