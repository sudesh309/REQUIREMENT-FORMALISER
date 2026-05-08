import json
import unittest
from pathlib import Path

from engine import Repository, Validator, parse, to_json, from_json
from engine.validator import Severity
from sysmlv2 import (
    AttributeDefinition, AttributeUsage,
    PartDefinition, PartUsage, PortDefinition, PortUsage,
    ConnectionUsage,
)


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class ParserTests(unittest.TestCase):

    def test_parse_vehicle(self):
        repo = Repository("VehicleParsed")
        parse((EXAMPLES / "vehicle.sysml").read_text(), into=repo.root_package)
        repo.registry.register_tree(repo.root_package)
        pkg = repo.resolve("Vehicles")
        self.assertIsNotNone(pkg)
        vehicle = repo.resolve("Vehicles::Vehicle")
        self.assertIsInstance(vehicle, PartDefinition)
        feature_names = sorted(f.name for f in vehicle.owned_features)
        self.assertIn("engine", feature_names)
        self.assertIn("mass", feature_names)

    def test_parse_requirements(self):
        repo = Repository("Reqs")
        parse((EXAMPLES / "requirements.sysml").read_text(), into=repo.root_package)
        repo.registry.register_tree(repo.root_package)
        r = repo.resolve("VehicleRequirements::TopLevelRange")
        self.assertIsNotNone(r)
        self.assertEqual(r.req_id, "REQ-001")


class ValidatorTests(unittest.TestCase):

    def test_connection_needs_two_ends(self):
        repo = Repository("ValidationCheck")
        Mech = PortDefinition(name="Mech"); repo.add(Mech)
        bad = ConnectionUsage(name="bad")  # no ends
        repo.add(bad)
        issues = Validator().validate(repo)
        self.assertTrue(any(i.rule == "connection.ends" and i.severity is Severity.ERROR
                            for i in issues))


class SerializerTests(unittest.TestCase):

    def test_round_trip(self):
        repo = Repository("Round")
        Mass = AttributeDefinition(name="Mass"); repo.add(Mass)
        Vehicle = PartDefinition(name="Vehicle"); repo.add(Vehicle)
        Vehicle.own(AttributeUsage(name="mass", typed_by=Mass))
        repo.registry.register_tree(Vehicle)

        text = to_json(repo)
        # Validate the JSON shape is well formed.
        data = json.loads(text)
        self.assertEqual(data["format"], "sysmlv2-core/1")

        repo2 = from_json(text)
        self.assertIsNotNone(repo2.resolve("Vehicle"))
        self.assertIsNotNone(repo2.resolve("Mass"))


if __name__ == "__main__":
    unittest.main()
