"""The complete IMA avionics example (engine/avionics/example.py): regenerated here, asserted by
counts and invariants, saved / loaded, exchanged as XLSX, compared, reported and checked."""
from __future__ import annotations

import unittest

import engine.requirements as rq
from engine import from_json, to_json
from engine import allocation as AL
from engine import architecture as A
from engine import interfaces as I
from engine.avionics import example, safety as SF, templates
from engine.avionics import profile as AP
from engine.interop import export_tables_file, read_tables_file, tables_to_project
from engine.interop.checks import run_model_check
from engine.interop.diff import compare
from engine.interop.report import generate_report
from engine.structure import components_of, connectors_of, definition_of, ports_of
from kerml.stereotypes import stereotypes_on
from sysmlv2.definitions import PartDefinition, PortUsage


def top(repo, name):
    return next(e for e in repo.root_package.owned_elements if e.name == name)


class ExampleBuildTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo = example.build_example()

    # --- architectures ------------------------------------------------------------------------
    def test_architectures_and_counts(self):
        repo = self.repo
        info = example.describe_example(repo)
        self.assertEqual(sorted(info["architectures"]),
                         ["FunctionalArchitecture", "LogicalArchitecture", "PhysicalArchitecture"])
        self.assertEqual(len(components_of(top(repo, "FunctionalArchitecture"))), 13)
        self.assertEqual(len(components_of(top(repo, "LogicalArchitecture"))), 12)
        phys = top(repo, "PhysicalArchitecture")
        names = [c.name for c in components_of(phys)]
        self.assertEqual(len(names), 24)
        for expected in ("ADC1", "ADC2", "IRU1", "IRU2", "RA1", "RA2", "GPS1", "GPS2", "RDC1", "RDC2", "SW_A",
                         "SW_B", "IMA_Cabinet", "FCC_L", "FCC_R", "PFD", "ND", "EICAS", "ElevAct", "AilAct",
                         "PSU1", "PSU2", "SidestickCapt", "SidestickFO"):
            self.assertIn(expected, names)
        self.assertEqual(info["physical_components"], 43)
        self.assertEqual(len(connectors_of(phys)), 73)
        # Every kind of link of the brief is there.
        buses = {AP.read(c, "busType") for c in connectors_of(phys)}
        self.assertEqual(buses, {"ARINC429", "AFDX", "MIL-STD-1553", "Discrete", "Analog", "Power"})

    def test_ima_cabinet_partitions_and_software(self):
        cab = definition_of(next(c for c in components_of(top(self.repo, "PhysicalArchitecture"))
                                 if c.name == "IMA_Cabinet"))
        modules = {m.name: m for m in components_of(cab)}
        self.assertEqual(sorted(modules), ["CPM1", "CPM2", "PSM"])
        parts = {p.name: p for m in ("CPM1", "CPM2") for p in components_of(definition_of(modules[m]))}
        self.assertEqual(sorted(parts), ["P_DMS", "P_FMS", "P_FWS", "P_MNT"])
        items = {i.name for p in parts.values() for i in components_of(p)}
        self.assertEqual(len(items), 8)
        for p in parts.values():
            self.assertIsNotNone(AP.read(p, "timeWindow"))
            self.assertIsNotNone(AP.read(p, "period"))
            self.assertEqual({a.stereotype.name for a in stereotypes_on(p)}, {"Partition"})
            for i in components_of(p):
                self.assertEqual({a.stereotype.name for a in stereotypes_on(i)}, {"SoftwareItem"})
                self.assertGreater(AP.read(i, "sloc"), 0)

    def test_every_port_has_an_interface(self):
        ports = [e for e in self.repo.root_package.walk() if isinstance(e, PortUsage)]
        self.assertEqual(len(ports), 175)
        self.assertEqual([p.qualified_name for p in ports if I.interface_of(p) is None], [])

    def test_equipment_values_live_on_the_definitions(self):
        pkg = top(self.repo, "Equipment")
        defs = [d for d in pkg.owned_elements if isinstance(d, PartDefinition)]
        self.assertEqual(len(defs), 16)
        for d in defs:
            names = {a.stereotype.name for a in stereotypes_on(d)}
            self.assertEqual(len(names & set(AP.EQUIPMENT_STEREOTYPES)), 1, d.name)
            for prop in ("mass", "powerNominal", "powerPeak", "mtbf", "partNumber", "manufacturer", "dal"):
                self.assertIsNotNone(AP.read(d, prop), f"{d.name}.{prop}")
        # Usages carry none of their own: they read the definition (AP.effective).
        adc1 = next(c for c in components_of(top(self.repo, "PhysicalArchitecture")) if c.name == "ADC1")
        self.assertEqual(stereotypes_on(adc1), [])
        self.assertEqual(AP.effective(adc1, "mass"), 3.6)
        self.assertEqual(AP.effective_dal(adc1), "B")
        # Units were converted by the profiles feature, not stored as text.
        fit = AP.read(definition_of(adc1), "failureRate")
        self.assertEqual(fit, 25000.0)
        self.assertAlmostEqual(1e9 / AP.read(definition_of(adc1), "mtbf"), fit)

    def test_bus_ports_and_links_carry_their_stereotypes(self):
        phys = top(self.repo, "PhysicalArchitecture")
        adc = definition_of(next(c for c in components_of(phys) if c.name == "ADC1"))
        out = next(p for p in ports_of(adc) if p.name == "airData")
        self.assertEqual(AP.read(out, "busType"), "ARINC429")
        self.assertIn("203", AP.read(out, "label"))
        fcc = definition_of(next(c for c in components_of(phys) if c.name == "FCC_L"))
        vl = next(p for p in ports_of(fcc) if p.name == "afdxA")
        self.assertEqual((AP.read(vl, "busType"), AP.read(vl, "virtualLink")), ("AFDX", 2001))
        afdx = [c for c in connectors_of(phys) if AP.read(c, "busType") == "AFDX"]
        self.assertEqual(len(afdx), 16)
        self.assertTrue(all(AP.read(c, "bandwidth") == 100.0 for c in afdx))

    def test_fcc_has_lanes_and_a_state_machine(self):
        fcc = definition_of(next(c for c in components_of(top(self.repo, "PhysicalArchitecture"))
                                 if c.name == "FCC_L"))
        self.assertEqual(sorted(c.name for c in components_of(fcc)), ["CommandLane", "MonitorLane"])
        sms = fcc.state_machines
        self.assertEqual(len(sms), 1)
        self.assertEqual(sorted(s.name for s in sms[0].states),
                         ["Degraded", "Engaged", "Failed", "Passive", "PowerUp", "Standby"])
        self.assertEqual(len(sms[0].transitions), 9)
        self.assertEqual(sms[0].initial_state.name, "PowerUp")
        view = A.view(self.repo, top(self.repo, "PhysicalArchitecture"))
        flags = {c["name"]: c["has_state_machine"] for c in view["components"]}
        self.assertTrue(flags["FCC_L"] and flags["FCC_R"] and not flags["ADC1"])

    # --- requirements, allocation, FHA ---------------------------------------------------------
    def test_requirement_sets_links_and_gaps(self):
        repo = self.repo
        sets = {s.name: s for s in rq.requirement_sets(repo)}
        self.assertEqual(sorted(sets), ["ItemRequirements", "SoftwareHighLevelRequirements",
                                        "SoftwareLowLevelRequirements", "SystemRequirements"])
        self.assertEqual(len(rq.all_requirements(repo)), 53)
        tests = [e for e in repo.root_package.walk() if rq.is_test_case(e)]
        self.assertEqual({rq.test_result(t) for t in tests}, {"passed", "failed", "unexecuted"})
        self.assertEqual(sorted(t.name for t in tests if rq.test_result(t) == "failed"),
                         example.OPEN_GAPS["failed_tests"])
        self.assertEqual(sorted(t.name for t in tests if rq.test_result(t) == "unexecuted"),
                         sorted(example.OPEN_GAPS["unexecuted_tests"]))
        kinds = {l["type"] for l in rq.all_links(repo)}
        self.assertEqual(kinds, {"implement", "verify", "derive", "refine"})
        for r in rq.all_requirements(repo):
            self.assertEqual(AP.read(r, "level"), {"SYS": "System", "ITM": "Item", "HLR": "HLR",
                                                   "LLR": "LLR"}[r.req_id.split("-")[0]])
        # The deliberate gaps are exactly what the avionics rules report.
        out = SF.safety_check(repo)
        names = lambda rule: sorted(i["name"].split(" ", 1)[1] if " " in i["name"] else i["name"]  # noqa: E731
                                    for i in out["issues"] if i["rule"] == rule)
        self.assertEqual(len([i for i in out["issues"] if i["rule"] == "avionics.req.unverified"]),
                         len(example.OPEN_GAPS["not_verified"]))
        text = " ".join(i["message"] for i in out["issues"] if i["rule"] == "avionics.req.unverified")
        for summary in example.OPEN_GAPS["not_verified"]:
            self.assertIn(summary, text)
        unimpl = [i["message"] for i in out["issues"] if i["rule"] == "avionics.req.unimplemented"]
        self.assertEqual(len(unimpl), 1)
        self.assertIn("GNSS integrity monitoring", unimpl[0])

    def test_allocation_chain_function_to_partition(self):
        repo = self.repo
        sets = {s.name: s for s in AL.allocation_sets(repo)}
        self.assertEqual(sorted(sets), ["FunctionsToLogical", "LogicalToPhysical"])
        for s in sets.values():
            self.assertEqual(AL.coverage(s.scenarios[0])["ratio"], 1.0, s.name)
        fn = next(c for c in components_of(top(repo, "FunctionalArchitecture")) if c.name == "ManageFlight")
        chain = AL.allocation_chain(fn)
        labels = {n["label"] if "label" in n else n.get("name") for n in chain["nodes"]}
        self.assertTrue({"ManageFlight", "FlightManagement", "P_FMS"} <= labels, labels)

    def test_fha_table(self):
        repo = self.repo
        rows = SF.fha_rows(repo)
        self.assertEqual(len(rows), 21)
        self.assertEqual({r.classification for r in rows}, set(SF.CLASSIFICATIONS))
        for r in rows:
            self.assertEqual(r.dal, SF.DAL_BY_CLASSIFICATION[r.classification])
            self.assertIsNotNone(r.fha_function)
            self.assertTrue(AL.allocated_to(r.fha_function))
        self.assertEqual(SF.function_dal(repo, rows[1].fha_function), "A")

    # --- checks ---------------------------------------------------------------------------------
    def test_model_check_has_no_errors(self):
        res = run_model_check(self.repo)
        self.assertEqual(res["counts"]["error"], 0, [i for i in res["issues"] if i["severity"] == "error"])
        # Only the deliberate requirement gaps are warnings; the rest is DAL hints.
        warnings = {i["rule"] for i in res["issues"] if i["severity"] == "warning"}
        self.assertEqual(warnings, {"avionics.req.unverified", "avionics.req.unimplemented"})
        infos = {i["rule"] for i in res["issues"] if i["severity"] == "info"}
        self.assertEqual(infos, {"avionics.dal.decomposition"})

    def test_layout_is_readable(self):
        for comp in example._all_compositions(self.repo):
            view = A.view(self.repo, comp)
            boxes = [c["layout"] for c in view["components"]]
            self.assertTrue(all("x" in b and "y" in b for b in boxes), comp.name)
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    self.assertFalse(a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                                     and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"],
                                     f"blocks overlap in {comp.name}")
            self.assertEqual([c["name"] for c in view["connectors"] if c["issues"]], [], comp.name)


class ExampleRoundTripTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo = example.build_example()

    def test_save_load_save_is_identical(self):
        text = to_json(self.repo)
        again = to_json(from_json(text))
        self.assertEqual(text, again)
        loaded = from_json(text)
        self.assertEqual(len(SF.fha_rows(loaded)), 21)
        self.assertEqual(SF.safety_check(loaded)["counts"], SF.safety_check(self.repo)["counts"])

    def test_xlsx_round_trip_compares_identical(self):
        data, name, _mime = export_tables_file(self.repo, "xlsx")
        again, _report = tables_to_project(read_tables_file(data, name))
        diff = compare(self.repo, again, include_layout=True)
        self.assertTrue(diff["identical"], diff["changes"][:3])
        # The FHA rows came back as rows with their function.
        rows = SF.fha_rows(again)
        self.assertEqual(len(rows), 21)
        self.assertTrue(all(r.fha_function is not None for r in rows))
        self.assertEqual(SF.safety_check(again)["counts"], SF.safety_check(self.repo)["counts"])

    def test_csv_round_trip_keeps_the_fha(self):
        data, name, _mime = export_tables_file(self.repo, "csv")
        again, _report = tables_to_project(read_tables_file(data, name))
        self.assertEqual([r.classification for r in SF.fha_rows(again)],
                         [r.classification for r in SF.fha_rows(self.repo)])

    def test_report_names_the_model(self):
        html = generate_report(self.repo, title="IMA", mermaid="none")
        for word in ("PhysicalArchitecture", "FlightControlComputer", "A429AirData", "SYS-2", "Avionics.Computer"):
            self.assertIn(word, html)

    def test_regenerating_gives_the_same_structure(self):
        other = example.build_example()
        self.assertEqual(example.describe_example(other), example.describe_example(self.repo))
        self.assertEqual(SF.safety_check(other)["by_rule"], SF.safety_check(self.repo)["by_rule"])
        self.assertEqual(len(list(other.all_elements())), len(list(self.repo.all_elements())))


class TemplateTests(unittest.TestCase):

    def test_template_list(self):
        ts = templates.list_templates()
        self.assertEqual([t["id"] for t in ts], ["blank", "ima_example"])
        with self.assertRaises(ValueError):
            templates.create_project("nope")

    def test_blank_project(self):
        repo = templates.create_project("blank", "MyAircraft")
        self.assertEqual(repo.name, "MyAircraft")
        self.assertIsNotNone(AP.find_profile(repo))
        self.assertGreaterEqual(len(I.shared_items(repo)), 30)
        self.assertEqual(sorted(s.name for s in rq.requirement_sets(repo)),
                         ["ItemRequirements", "SoftwareHighLevelRequirements",
                          "SoftwareLowLevelRequirements", "SystemRequirements"])
        arch = top(repo, "SystemArchitecture")
        self.assertEqual(components_of(arch), [])
        self.assertIsNotNone(SF.fha_table(repo))
        res = run_model_check(repo)
        self.assertEqual(res["counts"]["error"], 0)
        # Round trips like any project.
        self.assertEqual(to_json(from_json(to_json(repo))), to_json(repo))
        data, name, _m = export_tables_file(repo, "xlsx")
        again, _r = tables_to_project(read_tables_file(data, name))
        self.assertTrue(compare(repo, again, include_layout=True)["identical"])

    def test_ima_example_template(self):
        repo = templates.create_project("ima_example")
        self.assertEqual(repo.name, "IMA_Avionics")
        counts = templates.list_templates(counts=True)[1]["counts"]
        self.assertEqual(counts["fha_rows"], 21)


if __name__ == "__main__":
    unittest.main()
