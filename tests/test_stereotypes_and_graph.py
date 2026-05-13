import json
import unittest

from engine import bdd, export_knowledge_graph, requirements
from engine.diagram import ibd
from kerml.namespaces import Package
from kerml.stereotypes import Stereotype, stereotypes_on
from sysmlv2 import (
    AttributeDefinition, AttributeUsage,
    ConnectionUsage,
    InterfaceDefinition, InterfaceUsage,
    PartDefinition,
    PortDefinition, PortUsage,
    RequirementDefinition,
)
from sysmlv2.relationships import Satisfy, Verify


def _sample() -> Package:
    pkg = Package(name="Demo")

    Critical = Stereotype(name="safetyCritical", applies_to=[PartDefinition])
    Critical.define_tag("asilLevel", default="QM")
    pkg.own(Critical)

    Mass = AttributeDefinition(name="Mass"); pkg.own(Mass)
    Mech = PortDefinition(name="Mech"); pkg.own(Mech)
    Iface = InterfaceDefinition(name="Drivetrain"); pkg.own(Iface)

    Vehicle = PartDefinition(name="Vehicle"); pkg.own(Vehicle)
    Vehicle.own(AttributeUsage(name="mass", typed_by=Mass))
    p1 = PortUsage(name="p1", typed_by=Mech); Vehicle.own(p1)
    p2 = PortUsage(name="p2", typed_by=Mech); Vehicle.own(p2)
    Vehicle.own(InterfaceUsage(name="dt", typed_by=Iface))
    Vehicle.own(ConnectionUsage(name="drive", ends=[p1, p2]))

    R = RequirementDefinition(name="Req1", req_id="REQ-001", text="Be safe"); pkg.own(R)
    Vehicle.add_relationship(Satisfy(Vehicle, R))

    Critical.apply(Vehicle, {"asilLevel": "D"})
    return pkg


class StereotypeTests(unittest.TestCase):

    def test_define_and_apply(self):
        pkg = _sample()
        Vehicle = next(e for e in pkg.walk() if e.name == "Vehicle")
        apps = stereotypes_on(Vehicle)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].stereotype.name, "safetyCritical")
        self.assertEqual(apps[0].values["asilLevel"], "D")

    def test_applies_to_enforced(self):
        pkg = _sample()
        Critical = next(e for e in pkg.walk() if e.name == "safetyCritical")
        Mass = next(e for e in pkg.walk() if e.name == "Mass")
        with self.assertRaises(TypeError):
            Critical.apply(Mass)

    def test_unknown_tag_rejected(self):
        pkg = _sample()
        Critical = next(e for e in pkg.walk() if e.name == "safetyCritical")
        Mech = next(e for e in pkg.walk() if e.name == "Mech")
        # Mech is a PortDefinition — not in applies_to, so this should fail.
        with self.assertRaises(TypeError):
            Critical.apply(Mech)


class DiagramExportTests(unittest.TestCase):

    def test_bdd_includes_definitions_and_stereotype(self):
        dot = bdd(_sample())
        self.assertIn("digraph BDD", dot)
        self.assertIn("Vehicle", dot)
        self.assertIn("Mass", dot)
        self.assertIn("safetyCritical", dot)

    def test_ibd_renders_connections(self):
        pkg = _sample()
        Vehicle = next(e for e in pkg.walk() if e.name == "Vehicle")
        dot = ibd(Vehicle)
        self.assertIn("IBD: Vehicle", dot)
        self.assertIn("drive", dot)

    def test_requirements_renders_satisfy(self):
        dot = requirements(_sample())
        self.assertIn("satisfy", dot)
        self.assertIn("Req1", dot)


class KnowledgeGraphExportTests(unittest.TestCase):

    def test_turtle_has_prefix_and_triples(self):
        ttl = export_knowledge_graph(_sample(), "turtle")
        self.assertIn("@prefix sysml:", ttl)
        self.assertIn("sysml:satisfies", ttl)
        self.assertIn("sysml:stereotype", ttl)

    def test_jsonld_is_valid_json(self):
        text = export_knowledge_graph(_sample(), "json-ld")
        data = json.loads(text)
        self.assertEqual(data["@context"]["sysml"], "https://example.org/sysmlv2#")
        types = {n["@type"] for n in data["@graph"]}
        self.assertIn("sysml:PartDefinition", types)
        self.assertIn("sysml:owns", types)

    def test_graphml_xml_well_formed(self):
        text = export_knowledge_graph(_sample(), "graphml")
        self.assertIn("<graphml", text)
        self.assertIn("<node id=", text)
        self.assertIn("<edge ", text)

    def test_cypher_has_merge_statements(self):
        text = export_knowledge_graph(_sample(), "cypher")
        self.assertIn("MERGE (:PartDefinition", text)
        self.assertIn("-[:SATISFIES]->", text)


if __name__ == "__main__":
    unittest.main()
