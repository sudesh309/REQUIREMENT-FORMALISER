"""Core validator rules: no noise for System Composer style models, named messages (PO-6, SU-10)."""
from __future__ import annotations

import unittest

from engine import Repository, Validator
from engine import architecture as A
from engine import interfaces as I
from engine.allocation import allocate, create_allocation_set
from engine.requirements import add_requirement, create_requirement_set, create_trace_link
from engine.interop.checks import install as install_advisor, run_model_check
from engine.validator import Severity
from kerml.elements import Documentation
from kerml.features import Feature, MultiplicityRange
from kerml.namespaces import Package
from sysmlv2 import (
    ActionDefinition, ActionUsage, AttributeUsage, ConnectionUsage, ItemUsage, PartDefinition,
    PartUsage, PortUsage, RequirementUsage,
)


def _doc(e, text="documented"):
    e.add_annotation(Documentation(body=text))
    return e


def _rules(repo, rule):
    return [i for i in Validator().validate(repo) if i.rule == rule]


def avionics_model() -> Repository:
    """A small but complete avionics model built the way the studio builds one.

    Interfaces AirDataWord / SurfaceCommand; architecture AircraftAvionics with an inline
    ADIRU, two reference components FCC-L / FCC-R of FlightControlComputer (which has an
    inline ControlLaw wired to its boundary ports) and inline Actuators, every port typed
    and connected; an untyped functional architecture allocated to the components;
    requirements with text and Implement links.
    """
    repo = Repository("Avionics")
    air = I.create_item(repo, "DataInterface", "AirDataWord",
                        elements=[{"name": "altitude"}, {"name": "cas"}])
    cmd = I.create_item(repo, "DataInterface", "SurfaceCommand", elements=[{"name": "deflection"}])
    arch = A.create_architecture(repo, "AircraftAvionics")
    adiru = A.add_component(repo, arch, "ADIRU")
    air_out = A.add_port(repo, adiru, "airData", "out", interface=air)
    fcc_l = A.add_component(repo, arch, "FCC-L")
    A.add_port(repo, fcc_l, "airDataIn", "in", interface=air)
    A.add_port(repo, fcc_l, "surfaceCmd", "out", interface=cmd)
    law = A.add_component(repo, fcc_l, "ControlLaw")
    A.add_port(repo, law, "airData", "in", interface=air)
    A.add_port(repo, law, "cmd", "out", interface=cmd)
    A.connect(repo, fcc_l, (None, "airDataIn"), (law, "airData"))
    A.connect(repo, fcc_l, (law, "cmd"), (None, "surfaceCmd"))
    fcc = A.save_as_reference(repo, fcc_l, "FlightControlComputer")
    fcc_r = A.add_component(repo, arch, "FCC-R", fcc)
    act = A.add_component(repo, arch, "Actuators")
    A.add_port(repo, act, "cmdL", "in", interface=cmd)
    A.add_port(repo, act, "cmdR", "in", interface=cmd)
    A.connect(repo, arch, (adiru, air_out), (fcc_l, "airDataIn"))
    A.connect(repo, arch, (adiru, air_out), (fcc_r, "airDataIn"))
    A.connect(repo, arch, (fcc_l, "surfaceCmd"), (act, "cmdL"))
    A.connect(repo, arch, (fcc_r, "surfaceCmd"), (act, "cmdR"))

    funcs = repo.add(Package(name="AvionicsFunctions"))
    fn_air = ActionUsage(name="ComputeAirData")
    fn_law = ActionUsage(name="ComputeControlLaw")
    for f in (fn_air, fn_law):
        funcs.own(f)
    repo.registry.register_tree(funcs)
    alloc = create_allocation_set(repo, "FunctionsToLRUs", funcs, arch)
    scenario = alloc.scenarios[0] if hasattr(alloc, "scenarios") else next(
        x for x in alloc.owned_elements if x.kind == "AllocationScenario")
    allocate(repo, scenario, fn_air, adiru)
    allocate(repo, scenario, fn_law, fcc_l)

    rset = create_requirement_set(repo, "System Requirements", prefix="SYS")
    r1 = add_requirement(repo, rset, {"name": "Air data",
                                        "text": "The ADIRU shall provide air data at 20 Hz."})
    r2 = add_requirement(repo, rset, {"name": "Control law",
                                        "text": "The FCC shall command the control surfaces."})
    create_trace_link(repo, "implement", adiru, r1)
    create_trace_link(repo, "implement", fcc, r2)

    for e in (repo.root_package, air, cmd, arch, fcc, *[x for x in repo.root_package.walk()
                                                      if isinstance(x, (PartUsage, PortUsage))]):
        if not any(isinstance(a, Documentation) for a in e.annotations):
            _doc(e)
    return repo


class FeatureTypedTests(unittest.TestCase):

    def setUp(self):
        install_advisor()          # other tests may clear the rule registries

    def test_system_composer_constructs_are_not_flagged(self):
        repo = Repository("P")
        arch = A.create_architecture(repo, "Arch")
        a = A.add_component(repo, arch, "A")                 # inline component
        b = A.add_component(repo, arch, "B")
        out = A.add_port(repo, a, "out", "out")             # port without an interface
        A.add_port(repo, b, "in", "in")
        A.connect(repo, arch, (a, out), (b, "in"))           # connector
        funcs = repo.add(ActionDefinition(name="Functions"))
        funcs.own(ActionUsage(name="Compute"))              # inline function
        a.own(AttributeUsage(name="spare"))                  # untyped attribute
        a.own(ItemUsage(name="payload"))
        repo.add(RequirementUsage(name="req"))
        repo.registry.register_tree(repo.root_package)
        self.assertEqual(_rules(repo, "feature.typed"), [])
        # Untyped ports keep their own, named rule.
        msgs = sorted(i.message for i in _rules(repo, "port.typed"))
        self.assertEqual(msgs, ["Port 'in' has no interface (it should be typed by a port definition)",
                                "Port 'out' has no interface (it should be typed by a port definition)"])

    def test_plain_kerml_feature_is_flagged_by_name(self):
        repo = Repository("P")
        holder = repo.add(PartDefinition(name="Holder"))
        holder.own(Feature(name="loose"))
        anon = Feature()
        holder.own(anon)
        repo.registry.register_tree(holder)
        issues = _rules(repo, "feature.typed")
        self.assertEqual(sorted(i.message for i in issues), [
            "Feature 'loose' has no type (it defaults to Anything)",
            "Feature unnamed Feature in 'Holder' has no type (it defaults to Anything)"])
        self.assertTrue(all(i.severity is Severity.WARNING for i in issues))

    def test_core_rule_messages_name_the_element(self):
        repo = Repository("P")
        holder = repo.add(PartDefinition(name="Holder"))
        for name, lower, upper in (("neg", -1, 1), ("inverted", 3, 1)):
            u = PartUsage(name=name, multiplicity=MultiplicityRange(0, 1))
            u.multiplicity.lower, u.multiplicity.upper = lower, upper     # bypass the checks
            holder.own(u)
        holder.own(ConnectionUsage(name="dangling", ends=[]))
        holder.own(PortUsage(name="p"))
        holder.own(PartUsage(name="byFeature", typed_by=holder.owned_elements[0]))
        repo.add(RequirementUsage(name="Empty requirement"))
        repo.registry.register_tree(repo.root_package)
        messages = {i.rule: i.message for i in Validator().validate(repo)}
        expected = {"multiplicity.lower": "'neg'", "multiplicity.upper": "'inverted'",
                    "connection.ends": "'dangling'", "port.typed": "'p'",
                    "usage.typing": "'byFeature'", "requirement.empty": "'Empty requirement'"}
        for rule, name in expected.items():
            with self.subTest(rule=rule):
                self.assertIn(name, messages[rule])


class AvionicsModelTests(unittest.TestCase):

    def setUp(self):
        install_advisor()

    def test_complete_avionics_model_has_no_errors_or_warnings(self):
        repo = avionics_model()
        result = run_model_check(repo)
        noisy = [f"{i['rule']}: {i['message']} ({i['qualified_name']})" for i in result["issues"]
                 if i["severity"] in ("error", "warning")]
        self.assertEqual(noisy, [])
        self.assertEqual((result["counts"]["error"], result["counts"]["warning"]), (0, 0))
        self.assertNotIn("feature.typed", result["by_rule"])


if __name__ == "__main__":
    unittest.main()
