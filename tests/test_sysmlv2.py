import unittest

from sysmlv2 import (
    AttributeDefinition, AttributeUsage,
    PartDefinition, PartUsage,
    PortDefinition, PortUsage,
    ConnectionUsage,
    RequirementDefinition,
)
from sysmlv2.library import SYSML_LIBRARY


class SysMLv2Tests(unittest.TestCase):

    def test_library_root_definitions(self):
        self.assertIsNotNone(SYSML_LIBRARY.resolve("Parts::Part"))
        self.assertIsNotNone(SYSML_LIBRARY.resolve("Requirements::Requirement"))
        self.assertIsNotNone(SYSML_LIBRARY.resolve("Connections::Connection"))

    def test_part_with_attribute_and_port(self):
        Mass = AttributeDefinition(name="Mass")
        Mech = PortDefinition(name="Mech")
        Vehicle = PartDefinition(name="Vehicle")
        Vehicle.own(AttributeUsage(name="mass", typed_by=Mass))
        Vehicle.own(PortUsage(name="shaft", typed_by=Mech))
        names = [f.name for f in Vehicle.owned_features]
        self.assertEqual(sorted(names), ["mass", "shaft"])

    def test_connection_ends(self):
        Mech = PortDefinition(name="Mech")
        a = PortUsage(name="a", typed_by=Mech)
        b = PortUsage(name="b", typed_by=Mech)
        c = ConnectionUsage(name="c", ends=[a, b])
        self.assertEqual(len(c.ends), 2)

    def test_requirement_metadata(self):
        r = RequirementDefinition(
            name="Range", req_id="REQ-001",
            text="Vehicle shall have a range of at least 400 km.",
        )
        self.assertEqual(r.req_id, "REQ-001")
        self.assertIn("range", r.text)


if __name__ == "__main__":
    unittest.main()
