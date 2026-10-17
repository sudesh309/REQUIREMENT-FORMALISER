import unittest

from engine.structure import (
    component_tree, components_of, connectors_of, definition_of, owning_component, ports_of,
)
from sysmlv2 import ConnectionUsage, PartDefinition, PartUsage, PortDefinition, PortUsage


def _model():
    Data = PortDefinition(name="Data")
    Sensor = PartDefinition(name="Sensor")
    out = PortUsage(name="out", typed_by=Data); Sensor.own(out)
    Sys = PartDefinition(name="System")
    s1 = PartUsage(name="s1", typed_by=Sensor); Sys.own(s1)
    extra = PortUsage(name="extra"); s1.own(extra)
    cpu = PartUsage(name="cpu"); Sys.own(cpu)                  # inline component
    inp = PortUsage(name="in"); cpu.own(inp)
    core = PartUsage(name="core"); cpu.own(core)
    conn = ConnectionUsage(name="c", ends=[out, inp]); Sys.own(conn)
    return Sys, Sensor, s1, cpu, core, out, extra, inp, conn


class StructureTests(unittest.TestCase):

    def test_reference_and_inline_components(self):
        Sys, Sensor, s1, cpu, core, out, extra, inp, conn = _model()
        self.assertIs(definition_of(s1), Sensor)
        self.assertIsNone(definition_of(cpu))
        self.assertEqual(components_of(Sys), [s1, cpu])
        self.assertEqual(components_of(cpu), [core])
        self.assertEqual(ports_of(s1), [extra, out])
        self.assertEqual(ports_of(cpu), [inp])
        self.assertEqual(connectors_of(Sys), [conn])
        self.assertIs(owning_component(inp), cpu)

    def test_component_tree_preorder_with_depth(self):
        Sys, Sensor, s1, cpu, core, *_ = _model()
        self.assertEqual([(c.name, d) for c, d, _ in component_tree(Sys)],
                         [("System", 0), ("s1", 1), ("cpu", 1), ("core", 2)])

    def test_recursive_definition_terminates(self):
        A = PartDefinition(name="A")
        A.own(PartUsage(name="self_ref", typed_by=A))
        names = [c.name for c, _, _ in component_tree(PartUsage(name="top", typed_by=A))]
        self.assertLess(len(names), 10)


if __name__ == "__main__":
    unittest.main()
