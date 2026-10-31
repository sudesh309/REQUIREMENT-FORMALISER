"""SysML 1.x XMI (Cameo / MagicDraw) import."""
import unittest

from engine import Repository, to_json
from engine.interop import InteropError
from engine.interop.common import link_kind_name, model_links
from engine.interop.xmi_import import import_xmi, xmi_to_project
from kerml.elements import Documentation
from kerml.features import FeatureDirection
from kerml.stereotypes import stereotypes_on
from sysmlv2 import (
    AttributeDefinition, AttributeUsage, ConnectionUsage, EnumerationDefinition, PartDefinition,
    PartUsage, PortDefinition, PortUsage, RequirementDefinition, VerificationCaseDefinition,
)
from tests.test_interop_fixtures import XMI_FIXTURE


def _doc(e):
    return next((a.body for a in e.annotations if isinstance(a, Documentation)), None)


class XmiImportTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = XMI_FIXTURE.read_bytes()
        cls.repo, cls.report = xmi_to_project(cls.data)

    def test_project_and_packages(self):
        self.assertEqual(self.repo.name, "FlightDeckModel")
        self.assertEqual(self.report.warnings, [])
        self.assertEqual([p.name for p in self.repo.root_package.children][:3],
                         ["Interfaces", "Structure", "Requirements"])
        self.assertIn("Integrated modular avionics", _doc(self.repo.root_package))

    def test_blocks_and_interface_blocks(self):
        fmc = self.repo.resolve("Structure::FlightManagementComputer")
        self.assertIsInstance(fmc, PartDefinition)
        self.assertEqual(fmc.element_id, "_blk_fmc")
        self.assertEqual(_doc(fmc), "Computes the lateral and vertical flight plan.")
        self.assertEqual([s.target.name for s in fmc.specializations], ["AvionicsLRU"])
        self.assertTrue(self.repo.resolve("Structure::AvionicsLRU").is_abstract)
        self.assertFalse(fmc.is_abstract)
        word = self.repo.resolve("Interfaces::A429Word")
        self.assertIsInstance(word, PortDefinition)
        label = self.repo.resolve("Interfaces::A429Word::label")
        self.assertIsInstance(label, AttributeUsage)
        self.assertEqual(label.types[0].name, "Integer")
        self.assertIs(label.direction, FeatureDirection.OUT)
        self.assertIsInstance(self.repo.resolve("Interfaces::Altitude_ft"), AttributeDefinition)
        phase = self.repo.resolve("Interfaces::FlightPhase")
        self.assertIsInstance(phase, EnumerationDefinition)
        self.assertEqual([l.name for l in phase.literals], ["Taxi", "Cruise", "Landing"])

    def test_ports_and_directions(self):
        get = self.repo.resolve
        cases = {"Structure::GPSReceiver::navOut": FeatureDirection.OUT,          # proxy, flow out
                 "Structure::FlightManagementComputer::navIn": FeatureDirection.IN,  # conjugated
                 "Structure::FlightManagementComputer::displayOut": FeatureDirection.OUT,  # FlowPort
                 "Structure::PrimaryFlightDisplay::displayIn": FeatureDirection.IN}
        for path, direction in cases.items():
            port = get(path)
            self.assertIsInstance(port, PortUsage, path)
            self.assertIs(port.direction, direction, path)
            self.assertEqual(port.types[0].name, "A429Word")

    def test_parts_values_and_connectors(self):
        fd = self.repo.resolve("Structure::FlightDeck")
        parts = {p.name: p for p in fd.owned_elements if isinstance(p, PartUsage)}
        self.assertEqual(set(parts), {"gps", "fmc", "pfd"})
        self.assertEqual(parts["pfd"].types[0].name, "PrimaryFlightDisplay")
        self.assertEqual((parts["pfd"].multiplicity.lower, parts["pfd"].multiplicity.upper), (2, 2))
        alt = self.repo.resolve("Structure::FlightManagementComputer::cruiseAltitude")
        self.assertIsInstance(alt, AttributeUsage)
        self.assertEqual(alt.default_value, 35000)
        conns = {c.name: c for c in fd.owned_elements if isinstance(c, ConnectionUsage)}
        self.assertEqual([e.name for e in conns["navBus"].ends], ["navOut", "navIn"])
        unnamed = next(c for n, c in conns.items() if n != "navBus")
        self.assertEqual([e.name for e in unnamed.ends], ["displayOut", "displayIn"])
        if hasattr(unnamed, "end_contexts"):
            self.assertEqual([c.name for c in unnamed.end_contexts], ["fmc", "pfd"])

    def test_requirements_links_and_test_cases(self):
        nav = self.repo.resolve("Requirements::Navigation accuracy")
        self.assertIsInstance(nav, RequirementDefinition)
        self.assertEqual(nav.req_id, "SRS-001")
        self.assertIn("RNP 0.3", nav.text)
        disp = self.repo.resolve("Requirements::Attitude display")
        self.assertEqual(disp.text, "The system shall display attitude on both PFDs.")
        self.assertIsInstance(self.repo.resolve("Requirements::RNP flight test"),
                              VerificationCaseDefinition)
        links = {(link_kind_name(l), l.source.name, l.target.name) for l in model_links(self.repo)}
        self.assertEqual(links, {
            ("satisfy", "FlightManagementComputer", "Navigation accuracy"),
            ("satisfy", "PrimaryFlightDisplay", "Attitude display"),
            ("verify", "RNP flight test", "Navigation accuracy"),
            ("derive", "FMC lateral guidance", "Navigation accuracy"),
        })
        self.assertIn(self.repo.resolve("Structure::FlightManagementComputer"), nav.satisfied_by)

    def test_user_profile_stereotypes(self):
        fmc = self.repo.resolve("Structure::FlightManagementComputer")
        apps = stereotypes_on(fmc)
        self.assertEqual([a.stereotype.name for a in apps], ["LRU"])
        self.assertEqual(apps[0].values, {"mass": 4.2, "dal": "A", "ataChapter": 34})

    def test_reimport_updates_instead_of_duplicating(self):
        repo, _ = xmi_to_project(self.data)
        count = len(list(repo.root_package.walk()))
        report = import_xmi(repo, self.data, wrap=False)
        self.assertEqual(report.created, [])
        self.assertEqual(report.links_created, 0)
        self.assertEqual(len(list(repo.root_package.walk())), count)

    def test_import_into_existing_project_wraps_in_package(self):
        repo = Repository("Host")
        repo.add(PartDefinition(name="Existing"))
        report = import_xmi(repo, self.data)
        self.assertEqual(report.model_name, "FlightDeckModel")
        self.assertIsNotNone(repo.resolve("FlightDeckModel::Structure::FlightDeck"))
        self.assertIsNotNone(repo.resolve("Existing"))
        self.assertEqual(repo.resolve("FlightDeckModel").element_id, "_model_flightdeck")

    def test_imported_project_saves_and_loads(self):
        from engine import from_json
        text = to_json(self.repo)
        self.assertEqual(to_json(from_json(text)), text)


class XmiSafetyTests(unittest.TestCase):

    def test_rejects_entities_and_leaves_repo_untouched(self):
        repo = Repository("Safe")
        before = to_json(repo)
        bomb = ('<?xml version="1.0"?><!DOCTYPE xmi:XMI [<!ENTITY a "aaaaaaaaaa">'
                '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
                '<xmi:XMI xmlns:xmi="http://www.omg.org/spec/XMI/20131001" '
                'xmlns:uml="http://www.omg.org/spec/UML/20131001">'
                '<uml:Model xmi:id="m" name="&b;"/></xmi:XMI>')
        with self.assertRaises(InteropError) as ctx:
            import_xmi(repo, bomb)
        self.assertIn("DOCTYPE", str(ctx.exception))
        self.assertEqual(to_json(repo), before)

    def test_external_entity_rejected(self):
        xxe = ('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
               '<r>&x;</r>')
        with self.assertRaises(InteropError):
            xmi_to_project(xxe)

    def test_malformed_and_non_model_documents(self):
        with self.assertRaises(InteropError):
            xmi_to_project("<xmi:XMI")
        with self.assertRaises(InteropError) as ctx:
            xmi_to_project('<root><child/></root>')
        self.assertIn("no uml:Model", str(ctx.exception))

    def test_id_clash_with_other_kind_is_an_error(self):
        repo = Repository("Clash")
        e = repo.add(PartDefinition(name="X"))
        repo.registry.unregister(e)
        e.element_id = "_vt_altitude"         # the fixture's value type id
        repo.registry.register(e)
        with self.assertRaises(InteropError) as ctx:
            import_xmi(repo, XMI_FIXTURE.read_bytes(), wrap=False)
        self.assertIn("_vt_altitude", str(ctx.exception))
        self.assertIsNone(repo.resolve("Structure"))


if __name__ == "__main__":
    unittest.main()
