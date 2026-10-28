"""Engine tests of the avionics pack: profile, interface library, requirement library, FHA and rules."""
from __future__ import annotations

import unittest

import engine.requirements as rq
from engine import Repository, from_json, to_json
from engine import allocation as AL
from engine import architecture as A
from engine import interfaces as I
from engine import profiles as P
from engine.avionics import interfaces_lib, requirements_lib, safety as SF
from engine.avionics import profile as AP
from engine.interop.diff import compare
from engine.validator import Severity
from kerml.stereotypes import stereotypes_on


# ---------------------------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------------------------

class ProfileTests(unittest.TestCase):

    def setUp(self):
        self.repo = Repository("P")
        self.prof = AP.ensure_profile(self.repo)

    def test_stereotypes_of_the_brief(self):
        names = {s.name for s in self.prof.stereotypes}
        self.assertEqual(names, {"Equipment", "LRU", "LRM", "Sensor", "Display", "Actuator", "Computer",
                                 "Switch", "Gateway", "PowerSupply", "Partition", "SoftwareItem",
                                 "LogicalItem", "DataBusPort", "BusLink", "AvionicsRequirement"})
        eq = AP.stereotype(self.repo, "Equipment")
        self.assertTrue(eq.is_abstract)
        props = {t.name: t for t in eq.tags}
        for p in ("mass", "powerNominal", "powerPeak", "mtbf", "failureRate", "partNumber", "manufacturer",
                  "ataChapter", "dal", "certificationBasis", "do160Categories"):
            self.assertIn(p, props)
        self.assertEqual((props["mass"].unit, props["powerNominal"].unit, props["mtbf"].unit,
                          props["failureRate"].unit), ("kg", "W", "h", "FIT"))
        self.assertEqual(props["dal"].literals, ["A", "B", "C", "D", "E"])
        for derived in ("LRU", "LRM", "Sensor", "Display", "Actuator", "Computer", "Switch", "Gateway"):
            self.assertTrue(AP.stereotype(self.repo, derived).is_kind_of(eq), derived)
        self.assertEqual({t.name for t in AP.stereotype(self.repo, "Partition").tags},
                         {"partitionId", "dal", "timeWindow", "period", "memory", "partitioningMark"})
        self.assertEqual({t.name for t in AP.stereotype(self.repo, "SoftwareItem").tags},
                         {"dal", "language", "sloc", "version"})
        self.assertEqual({t.name for t in AP.stereotype(self.repo, "DataBusPort").tags},
                         {"busType", "label", "virtualLink", "rtAddress"})
        self.assertEqual({t.name for t in AP.stereotype(self.repo, "BusLink").tags},
                         {"busType", "bandwidth", "latency", "length"})
        self.assertEqual({t.name for t in AP.stereotype(self.repo, "AvionicsRequirement").tags},
                         {"level", "dal", "derived", "safetyRelated", "verificationMethod"})
        self.assertEqual(P.validate_profiles(self.repo).__class__.__name__, "generator")
        self.assertEqual([i for i in P.validate_profiles(self.repo)], [])

    def test_abstract_equipment_cannot_be_applied_and_categories_hold(self):
        arch = A.create_architecture(self.repo, "Sys")
        c = A.add_component(self.repo, arch, "ADC")
        with self.assertRaises(P.ProfileError):
            P.apply_stereotype(self.repo, c, AP.stereotype(self.repo, "Equipment"))
        port = A.add_port(self.repo, c, "out1", "out")
        with self.assertRaises(Exception):
            P.apply_stereotype(self.repo, c, AP.stereotype(self.repo, "DataBusPort"))   # a port stereotype
        with self.assertRaises(Exception):
            P.apply_stereotype(self.repo, port, AP.stereotype(self.repo, "LRU"))        # a component one

    def test_ensure_is_idempotent_and_keeps_user_edits(self):
        n = len(list(self.repo.root_package.walk()))
        AP.ensure_profile(self.repo)
        self.assertEqual(len(list(self.repo.root_package.walk())), n)
        mass = AP.stereotype(self.repo, "Equipment").find_tag("mass")
        P.update_property(self.repo, mass, unit="g")
        AP.ensure_profile(self.repo)
        self.assertEqual(AP.stereotype(self.repo, "Equipment").find_tag("mass").unit, "g")
        P.delete_stereotype(self.repo, AP.stereotype(self.repo, "Gateway"))
        AP.ensure_profile(self.repo)
        self.assertIsNotNone(self.prof.stereotype("Gateway"))

    def test_values_are_checked_and_converted_with_units(self):
        arch = A.create_architecture(self.repo, "Sys")
        c = A.add_component(self.repo, arch, "ADC")
        AP.apply(self.repo, c, "Computer", {"mass": "9 lb", "mtbf": "40000 h", "failureRate": "25000 FIT",
                                            "dal": "b", "ataChapter": 34})
        self.assertAlmostEqual(AP.read(c, "mass"), 4.08233133, places=6)
        self.assertEqual(AP.read(c, "dal"), "B")
        self.assertEqual(AP.effective_dal(c), "B")
        AP.set_values(self.repo, c, "Computer", {"memory": "1 MB", "powerNominal": "2*15"})
        self.assertEqual(AP.read(c, "powerNominal"), 30.0)
        self.assertEqual(AP.read(c, "memory"), 1000.0)                 # kB
        with self.assertRaises(P.ProfileError):
            AP.set_values(self.repo, c, "Computer", {"mass": "-1 kg"})
        with self.assertRaises(P.ProfileError):
            AP.set_values(self.repo, c, "Computer", {"ataChapter": 300})
        with self.assertRaises(P.ProfileError):
            AP.set_values(self.repo, c, "Computer", {"dal": "F"})
        with self.assertRaises(P.ProfileError):
            AP.set_values(self.repo, c, "Computer", {"nonsense": 1})
        self.assertAlmostEqual(AP.read(c, "mass"), 4.08233133, places=6)      # nothing changed
        # The base is addressable (Avionics.Equipment.mass) and so is the derived stereotype.
        self.assertEqual(P.get_property_value(c, "Avionics.Equipment.dal"), "B")
        self.assertEqual(P.get_property_value(c, "Avionics.Computer.dal"), "B")

    def test_default_port_stereotype_for_ports_created_in_an_lru(self):
        arch = A.create_architecture(self.repo, "Sys")
        c = A.add_component(self.repo, arch, "ADC")
        AP.apply(self.repo, c, "LRU")
        p = A.add_port(self.repo, c, "airData", "out")
        self.assertEqual([a.stereotype.name for a in stereotypes_on(p)], ["DataBusPort"])
        self.assertEqual(AP.read(p, "busType"), "Unspecified")

    def test_usage_reads_its_definitions_values(self):
        arch = A.create_architecture(self.repo, "Sys")
        d = A.create_architecture(self.repo, "Adc")
        AP.apply(self.repo, d, "Computer", {"mass": 3.6, "dal": "B"})
        u1, u2 = (A.add_component(self.repo, arch, n, d) for n in ("ADC1", "ADC2"))
        AP.apply(self.repo, u2, "LogicalItem", {"dal": "A"})     # its own value wins
        self.assertEqual((AP.effective_dal(u1), AP.effective_dal(u2)), ("B", "A"))
        self.assertEqual(AP.effective(u1, "mass"), 3.6)
        self.assertIsNone(AP.read(u1, "mass"))
        summary = AP.equipment_summary(self.repo, arch)
        self.assertEqual(summary[0]["items"], 2)
        self.assertAlmostEqual(summary[0]["mass_kg"], 7.2)
        self.assertEqual(summary[0]["by_dal"], {"A": 1, "B": 1})

    def test_dal_helpers(self):
        self.assertTrue(AP.dal_at_least("A", "C") and AP.dal_at_least("c", "C"))
        self.assertFalse(AP.dal_at_least("D", "C"))
        self.assertFalse(AP.dal_at_least(None, "C"))
        self.assertEqual([AP.dal_rank(x) for x in "ABCDE"], [0, 1, 2, 3, 4])
        self.assertIsNone(AP.normalize_dal("F"))

    def test_profile_round_trips_through_save_and_load(self):
        again = from_json(to_json(self.repo))
        self.assertEqual({s.name for s in AP.find_profile(again).stereotypes},
                         {s.name for s in self.prof.stereotypes})
        self.assertEqual(AP.stereotype(again, "LRU").effective_default("port").name, "DataBusPort")


# ---------------------------------------------------------------------------------------------
# Interface library
# ---------------------------------------------------------------------------------------------

class InterfaceLibraryTests(unittest.TestCase):

    def test_catalog(self):
        cat = interfaces_lib.catalog()
        self.assertEqual([g["id"] for g in cat["groups"]],
                         ["types", "a429", "a664", "m1553", "discrete", "analog", "a825", "a653", "power"])
        self.assertEqual(cat["count"], 37)
        self.assertIn("ICD", cat["warning"])
        names = {i["name"] for g in cat["groups"] for i in g["items"]}
        for n in ("A429Word", "A429AirData", "A429Inertial", "A429Navigation", "A664Message",
                  "M1553BMessage", "DiscreteLine", "AnalogVoltage", "AnalogCurrent", "SynchroSignal",
                  "A825Frame", "A653SamplingPort", "A653QueuingPort", "Power28VDCBus"):
            self.assertIn(n, names)

    def test_label_sets(self):
        by = {i["name"]: i for g in interfaces_lib.catalog()["groups"] for i in g["items"]}
        labels = lambda n: {l["element"]: l["label"] for l in by[n]["labels"]}  # noqa: E731
        self.assertEqual(sorted(labels("A429AirData").values()),
                         ["203", "204", "205", "206", "210", "211", "212", "213"])
        self.assertEqual(labels("A429AirData")["mach"], "205")
        self.assertEqual(set(labels("A429AirData")), {
            "pressureAltitude", "baroCorrectedAltitude", "mach", "computedAirspeed", "trueAirspeed",
            "totalAirTemperature", "staticAirTemperature", "verticalSpeed"})
        self.assertEqual(set(labels("A429Inertial")), {
            "pitch", "roll", "magneticHeading", "trackAngle", "groundSpeed", "latitude", "longitude",
            "longitudinalAcceleration", "lateralAcceleration", "normalAcceleration"})
        self.assertEqual(set(labels("A429Navigation")), {"selectedCourse", "distanceToGo", "desiredTrack"})

    def test_import_all_is_valid_and_idempotent(self):
        repo = Repository("L")
        res = interfaces_lib.import_library(repo)
        self.assertEqual(len(res["created"]), 37)
        self.assertEqual(res["skipped"], [])
        self.assertEqual(repo.validate(), [])
        again = interfaces_lib.import_library(repo)
        self.assertEqual(again["created"], [])
        self.assertEqual(len(again["skipped"]), 37)
        self.assertEqual(len(I.shared_items(repo)), 37)
        status = interfaces_lib.library_status(repo)
        self.assertEqual(status["present"], 37)

    def test_contents(self):
        repo = Repository("L")
        interfaces_lib.import_library(repo)
        el = lambda iface, name: I.find_element(I.find_item(repo, iface), name)  # noqa: E731
        word = I.find_item(repo, "A429Word")
        self.assertEqual([e.name for e in I.elements_of(word)], ["label", "sdi", "data", "ssm", "parity"])
        self.assertEqual(I.describe_type(el("A429Word", "ssm")), "Enum: Ssm429")
        self.assertEqual(I.describe_type(el("A429AirData", "pressureAltitude")), "ValueType: AltitudeFt")
        self.assertEqual({e.name for e in I.elements_of(I.find_item(repo, "A664Message"))},
                         {"vlId", "bag", "lmax", "jitterMax", "subVl", "network", "sequenceNumber", "payload"})
        self.assertEqual(el("A664Message", "bag").units, "ms")
        self.assertEqual({e.name for e in I.elements_of(I.find_item(repo, "M1553BMessage"))},
                         {"rtAddress", "transmit", "subaddress", "wordCount", "rate", "bus", "dataWords",
                          "statusWord"})
        self.assertEqual((el("AnalogVoltage", "value").minimum, el("AnalogVoltage", "value").maximum), (0, 10))
        self.assertEqual((el("AnalogCurrent", "current").minimum, el("AnalogCurrent", "current").maximum), (4, 20))
        self.assertEqual({e.name for e in I.elements_of(I.find_item(repo, "DiscreteLine"))},
                         {"level", "activeLow", "asserted", "valid"})
        level = I.find_item(repo, "DiscreteLevel")
        self.assertEqual([c.name for c in I.elements_of(level)], ["OPEN", "GROUND", "V28"])
        self.assertEqual({e.name for e in I.elements_of(I.find_item(repo, "A825Frame"))},
                         {"canId", "priority", "dlc", "data"})
        self.assertIn("discipline", {e.name for e in I.elements_of(I.find_item(repo, "A653QueuingPort"))})
        self.assertIn("refreshPeriod", {e.name for e in I.elements_of(I.find_item(repo, "A653SamplingPort"))})
        self.assertEqual(I.find_item(repo, "Power28VDCBus").kind, "PhysicalInterface")
        self.assertEqual(I.find_item(repo, "AltitudeFt").units, "ft")

    def test_selection_brings_its_value_types(self):
        repo = Repository("L")
        res = interfaces_lib.import_library(repo, names=["A429AirData"])
        self.assertIn("A429AirData", res["created"])
        self.assertIn("AltitudeFt", res["created"])
        self.assertIn("AltitudeFt", res["dependencies"])
        self.assertIsNone(I.find_item(repo, "A664Message"))
        only = Repository("L2")
        res = interfaces_lib.import_library(only, groups=["a664"])
        self.assertEqual(res["created"], ["NetworkId", "A664Message"])

    def test_conflicts(self):
        repo = Repository("L")
        I.create_from_template(repo, "arinc429")                      # the Interface Editor's A429Word
        res = interfaces_lib.import_library(repo, names=["A429Word"])
        self.assertEqual(res["created"], ["Ssm429"])
        self.assertEqual(res["skipped"], ["A429Word"])
        res = interfaces_lib.import_library(repo, names=["A429Word"], on_conflict="rename")
        self.assertEqual(res["renamed"]["A429Word"], "A429Word_1")
        self.assertIsNotNone(I.find_item(repo, "A429Word_1"))
        self.assertEqual(I.describe_type(I.find_element(I.find_item(repo, "A429Word_1"), "ssm")),
                         "Enum: Ssm429_1")
        with self.assertRaises(I.InterfaceError) as ctx:
            interfaces_lib.import_library(repo, names=["Nope"])
        self.assertEqual(ctx.exception.status, 404)
        with self.assertRaises(I.InterfaceError):
            interfaces_lib.import_library(repo, groups=["nope"])
        with self.assertRaises(I.InterfaceError):
            interfaces_lib.import_library(repo, on_conflict="overwrite")

    def test_compatibility_between_ports(self):
        repo = Repository("L")
        interfaces_lib.import_library(repo)
        arch = A.create_architecture(repo, "Sys")
        a, b, c = (A.add_component(repo, arch, n) for n in "ABC")
        out = A.add_port(repo, a, "o", "out", interface=I.find_item(repo, "A429AirData"))
        inp = A.add_port(repo, b, "i", "in", interface=I.find_item(repo, "A429AirData"))
        other = A.add_port(repo, c, "i", "in", interface=I.find_item(repo, "A429Inertial"))
        self.assertEqual(I.check_compatibility(out, inp), [])
        self.assertTrue(I.check_compatibility(out, other))

    def test_dictionary_export_import(self):
        repo = Repository("L")
        interfaces_lib.import_library(repo)
        doc = I.export_dictionary(repo)
        other = Repository("M")
        I.import_dictionary(other, doc)
        self.assertEqual(len(I.shared_items(other)), 37)
        self.assertEqual(other.validate(), [])


# ---------------------------------------------------------------------------------------------
# Requirement library
# ---------------------------------------------------------------------------------------------

class RequirementLibraryTests(unittest.TestCase):

    def test_catalog_and_guidance(self):
        cat = requirements_lib.catalog()
        self.assertEqual([s["key"] for s in cat["sets"]],
                         ["arp4754a-system", "arp4754a-item", "do178c-hlr", "do178c-llr"])
        self.assertEqual(sorted(cat["guidance"]), ["A", "B", "C", "D", "E"])
        self.assertEqual(cat["guidance"]["A"]["coverage"], "MC/DC")
        self.assertEqual(cat["guidance"]["B"]["coverage"], "Decision")
        self.assertEqual(cat["guidance"]["C"]["coverage"], "Statement")

    def test_import_each_set(self):
        repo = Repository("R")
        results = requirements_lib.import_requirement_library(repo)
        self.assertEqual([r["set"].id_prefix for r in results], ["SYS-", "ITM-", "HLR-", "LLR-"])
        for r in results:
            self.assertGreater(r["requirements"], 10)
            self.assertEqual(len(list(rq.walk_requirements(r["set"]))), r["requirements"])
        system = results[0]["set"]
        reqs = {x.name: x for x, _d, _i in rq.walk_requirements(system)}
        cat = reqs["Catastrophic failure conditions"]
        self.assertEqual(AP.read(cat, "dal"), "A")
        self.assertTrue(AP.read(cat, "safetyRelated"))
        self.assertFalse(AP.read(cat, "derived"))
        self.assertEqual(cat.req_type, "safety")
        self.assertEqual(cat.verification_method, "analysis")
        self.assertEqual(AP.read(cat, "verificationMethod"), "Analysis")
        self.assertEqual(AP.read(cat, "level"), "System")
        self.assertIn("1E-9", cat.text)
        derived = reqs["Derived requirement"]
        self.assertTrue(AP.read(derived, "derived"))
        self.assertTrue(derived.rationale)
        hlr = {x.name: x for x, _d, _i in rq.walk_requirements(results[2]["set"])}
        self.assertEqual(AP.read(hlr["Compute output"], "level"), "HLR")
        self.assertEqual(repo.validate(), [i for i in repo.validate() if i.severity is not Severity.ERROR])
        self.assertEqual([i for i in repo.validate() if i.severity is Severity.ERROR], [])

    def test_dal_override_and_unique_names(self):
        repo = Repository("R")
        first = requirements_lib.import_requirement_set(repo, "do178c-llr", dal="B")
        second = requirements_lib.import_requirement_set(repo, "do178c-llr")
        self.assertNotEqual(first["set"].name, second["set"].name)
        self.assertEqual({AP.read(x, "dal") for x, _d, _i in rq.walk_requirements(first["set"])}, {"B"})
        self.assertGreater(len({AP.read(x, "dal") for x, _d, _i in rq.walk_requirements(second["set"])}), 1)
        with self.assertRaises(rq.RequirementsError):
            requirements_lib.import_requirement_set(repo, "nope")
        with self.assertRaises(rq.RequirementsError):
            requirements_lib.import_requirement_set(repo, "do178c-hlr", dal="Z")

    def test_skeleton_round_trips(self):
        repo = Repository("R")
        requirements_lib.import_requirement_library(repo)
        self.assertEqual(to_json(from_json(to_json(repo))), to_json(repo))


# ---------------------------------------------------------------------------------------------
# Safety rules
# ---------------------------------------------------------------------------------------------

class SafetyFixture(unittest.TestCase):
    """Functions -> logical item -> two hardware channels, with a requirement and an FHA row."""

    def setUp(self):
        self.repo = repo = Repository("S")
        AP.ensure_profile(repo)
        self.func_arch = A.create_architecture(repo, "Functions")
        self.func = A.add_component(repo, self.func_arch, "ProvideAirData")
        self.phys_arch = A.create_architecture(repo, "Physical")
        self.dadc = A.create_architecture(repo, "Adc")
        AP.apply(repo, self.dadc, "Computer", {"dal": "A"})
        self.adc1 = A.add_component(repo, self.phys_arch, "ADC1", self.dadc)
        self.adc2 = A.add_component(repo, self.phys_arch, "ADC2", self.dadc)
        self.alloc = AL.create_allocation_set(repo, "F2P", self.func_arch, self.phys_arch)
        self.sc = self.alloc.scenarios[0]
        AL.allocate(repo, self.sc, self.func, self.adc1)
        AL.allocate(repo, self.sc, self.func, self.adc2)
        self.row = SF.add_fha_row(repo, function=self.func, failure_condition="Loss of air data",
                                  classification="Catastrophic")

    def rules(self, severity=None, rule=None):
        out = SF.safety_check(self.repo)["issues"]
        return [i for i in out if (severity is None or i["severity"] == severity)
                and (rule is None or i["rule"] == rule)]

    def set_dal(self, dal):
        AP.set_values(self.repo, self.dadc, "Computer", {"dal": dal})


class FhaTests(SafetyFixture):

    def test_standard_mapping(self):
        self.assertEqual(SF.DAL_BY_CLASSIFICATION, {"Catastrophic": "A", "Hazardous": "B", "Major": "C",
                                                    "Minor": "D", "No Safety Effect": "E"})
        self.assertEqual(self.row.dal, "A")
        for cls, dal in SF.DAL_BY_CLASSIFICATION.items():
            SF.update_fha_row(self.repo, self.row, classification=cls)
            self.assertEqual(self.row.dal, dal)

    def test_crud(self):
        repo = self.repo
        r2 = SF.add_fha_row(repo, failure_condition="  Erroneous   air data ", function=self.func.element_id,
                            flight_phase="climb, Cruise", effect="Misleading", classification="hazardous")
        self.assertEqual((r2.name, r2.failure_condition, r2.flight_phase, r2.classification),
                         ("FHA-2", "Erroneous air data", "Climb,Cruise", "Hazardous"))
        self.assertEqual(SF.normalize_phases("all"), "All")
        self.assertEqual(SF.normalize_phases("Taxi"), "Ground")
        self.assertEqual(SF.normalize_phases("Cruise,Climb"), "Climb,Cruise")
        SF.update_fha_row(repo, "FHA-2", classification="Minor", effect="None", fha_id="FHA-9")
        self.assertEqual(SF.find_row(repo, "FHA-9").classification, "Minor")
        SF.update_fha_row(repo, r2.element_id, function=None)
        self.assertIsNone(r2.fha_function)
        self.assertEqual(SF.delete_fha_row(repo, "FHA-9"), "FHA-9")
        self.assertEqual([r.name for r in SF.fha_rows(repo)], ["FHA-1"])
        self.assertEqual(SF.add_fha_row(repo, failure_condition="x").name, "FHA-2")

    def test_validation(self):
        repo = self.repo
        for kwargs in ({"failure_condition": ""}, {"failure_condition": "x", "classification": "Bad"},
                       {"failure_condition": "x", "flight_phase": "Orbit"}, {"failure_condition": "x",
                                                                           "function": "Nope"}):
            with self.assertRaises(SF.FhaError):
                SF.add_fha_row(repo, **kwargs)
        with self.assertRaises(SF.FhaError) as ctx:
            SF.add_fha_row(repo, failure_condition="x", fha_id="FHA-1")
        self.assertEqual(ctx.exception.status, 409)
        with self.assertRaises(SF.FhaError):
            SF.add_fha_row(repo, failure_condition="x", function=self.alloc.element_id)   # not a function
        with self.assertRaises(SF.FhaError) as ctx:
            SF.find_row(repo, "FHA-77")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(len(SF.fha_rows(repo)), 1)                   # nothing was added
        with self.assertRaises(SF.FhaError):
            SF.update_fha_row(repo, "FHA-1", classification="Bad", effect="changed")
        self.assertEqual(self.row.effect, "")                          # all or nothing

    def test_codec_and_function_reference(self):
        again = from_json(to_json(self.repo))
        row = SF.fha_rows(again)[0]
        self.assertEqual((row.name, row.classification, row.failure_condition), ("FHA-1", "Catastrophic",
                                                                                 "Loss of air data"))
        self.assertEqual(row.fha_function.name, "ProvideAirData")
        self.assertEqual(row.dal, "A")

    def test_deleting_the_function_clears_the_reference(self):
        self.repo.remove(self.func)
        self.assertIsNone(self.row.fha_function)
        self.assertIn("names no function", " ".join(i["message"] for i in self.rules(rule="avionics.fha.unallocated")))

    def test_compare_sees_a_changed_row(self):
        other = from_json(to_json(self.repo))
        self.assertTrue(compare(self.repo, other)["identical"])
        SF.update_fha_row(other, "FHA-1", classification="Major")
        diff = compare(self.repo, other)
        self.assertFalse(diff["identical"])
        self.assertEqual(diff["changes"][0]["name"], "FHA-1")

    def test_function_choices(self):
        names = [f["name"] for f in SF.function_choices(self.repo)]
        self.assertEqual(names, ["ProvideAirData"])


class RuleTests(SafetyFixture):

    def test_clean_when_the_items_meet_the_dal(self):
        self.assertEqual([i for i in self.rules() if i["severity"] != "info"], [])

    def test_allocation_below_the_fha_dal(self):
        self.set_dal("C")
        errors = self.rules("error", "avionics.dal.allocation")
        self.assertEqual(len(errors), 1)
        issue = errors[0]
        self.assertIn("ProvideAirData needs DAL A", issue["message"])
        self.assertIn("ADC1 (DAL C)", issue["message"])
        self.assertEqual({e["name"] for e in issue["elements"]}, {"ADC1", "ADC2", "ProvideAirData", "FHA-1"})
        self.assertEqual(issue["title"], "Function allocated below its FHA DAL")

    def test_valid_decomposition_is_only_a_hint(self):
        self.set_dal("B")                                          # A = B + B over two ADCs
        self.assertEqual(self.rules("error"), [])
        hint = self.rules("info", "avionics.dal.decomposition")[0]
        self.assertIn("valid DAL decomposition", hint["message"])

    def test_single_item_cannot_decompose(self):
        AL.deallocate(self.repo, self.sc, self.func, self.adc2)
        self.set_dal("B")
        self.assertEqual(len(self.rules("error", "avionics.dal.allocation")), 1)

    def test_two_c_items_are_not_a_decomposition_of_a(self):
        self.set_dal("C")
        self.assertEqual(len(self.rules("error", "avionics.dal.allocation")), 1)
        self.assertEqual(self.rules("info", "avionics.dal.decomposition"), [])

    def test_decomposition_hint_when_channels_meet_the_dal(self):
        hint = self.rules("info", "avionics.dal.decomposition")
        self.assertEqual(len(hint), 1)
        self.assertIn("A = A + C or B + B", hint[0]["message"])

    def test_valid_decomposition_table(self):
        vd = SF.valid_decomposition
        self.assertTrue(vd("A", ["A", "C"]) and vd("A", ["B", "B"]) and vd("A", ["B", "B", "E"]))
        self.assertFalse(vd("A", ["B", "C"]) or vd("A", ["C", "C"]) or vd("A", ["A"]))
        self.assertTrue(vd("B", ["B", "D"]) and vd("B", ["C", "C"]))
        self.assertFalse(vd("B", ["C", "D"]))
        self.assertTrue(vd("C", ["C", "E"]) and vd("C", ["D", "D"]))
        self.assertFalse(vd("D", ["D", "D"]) or vd("E", ["E", "E"]) or vd("X", ["A", "A"]))

    def test_requirement_dal(self):
        repo = self.repo
        rset = rq.create_requirement_set(repo, "Sys", prefix="SYS-")
        req = rq.add_requirement(repo, rset, {"summary": "Provide air data"})
        AP.apply(repo, req, "AvionicsRequirement", {"dal": "A"})
        rq.create_trace_link(repo, "implement", self.adc1, req)
        self.assertEqual(self.rules("error", "avionics.dal.requirement"), [])
        self.set_dal("C")
        errors = self.rules("error", "avionics.dal.requirement")
        self.assertEqual(len(errors), 1)
        self.assertIn("ADC1 (DAL C) implements SYS-1 Provide air data which needs DAL A", errors[0]["message"])
        self.assertEqual([e["name"] for e in errors[0]["elements"]], ["ADC1", "Provide air data"])
        # A component with no DAL at all is reported too, as a warning.
        bare = A.add_component(repo, self.phys_arch, "Bare")
        rq.create_trace_link(repo, "implement", bare, req)
        warn = self.rules("warning", "avionics.dal.requirement")
        self.assertEqual(len(warn), 1)
        self.assertIn("no DAL assigned", warn[0]["message"])

    def test_partitioning_mark_and_hosting(self):
        repo = self.repo
        module = A.create_architecture(repo, "Cpm")
        AP.apply(repo, module, "LRM", {"dal": "B", "partitioningMark": False})
        p1 = A.add_component(repo, module, "P1")
        p2 = A.add_component(repo, module, "P2")
        AP.apply(repo, p1, "Partition", {"dal": "B"})
        AP.apply(repo, p2, "Partition", {"dal": "D"})
        issues = self.rules(rule="avionics.dal.partitioning")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "warning")
        self.assertIn("without a partitioning mark", issues[0]["message"])
        self.assertEqual({e["name"] for e in issues[0]["elements"]}, {"Cpm", "P1", "P2"})
        AP.set_values(repo, module, "LRM", {"partitioningMark": True})
        self.assertEqual(self.rules(rule="avionics.dal.partitioning"), [])
        # Software items in a partition: the partition must meet the highest level it hosts.
        sw = A.add_component(repo, p2, "Sw")
        AP.apply(repo, sw, "SoftwareItem", {"dal": "B"})
        hosting = self.rules("error", "avionics.dal.hosting")
        self.assertEqual(len(hosting), 1)
        self.assertIn("P2 (DAL D) hosts Sw (DAL B)", hosting[0]["message"])
        AP.set_values(repo, p2, "Partition", {"dal": "B"})
        self.assertEqual(self.rules("error", "avionics.dal.hosting"), [])
        # A hosted level above its module's is an error as well.
        AP.set_values(repo, module, "LRM", {"dal": "C"})
        self.assertEqual(len(self.rules("error", "avionics.dal.hosting")), 2)

    def test_fha_rows_without_an_allocated_function(self):
        repo = self.repo
        loose = SF.add_fha_row(repo, failure_condition="Unowned failure")
        other = A.add_component(repo, self.func_arch, "Unallocated")
        unalloc = SF.add_fha_row(repo, failure_condition="Orphan", function=other)
        msgs = {i["message"] for i in self.rules("warning", "avionics.fha.unallocated")}
        self.assertEqual(len(msgs), 2)
        self.assertTrue(any("names no function" in m and "FHA-2" in m for m in msgs))
        self.assertTrue(any("Unallocated" in m and "not allocated to any item" in m for m in msgs))
        AL.allocate(repo, self.sc, other, self.adc1)
        SF.update_fha_row(repo, loose, function=other)
        self.assertEqual(self.rules(rule="avionics.fha.unallocated"), [])
        self.assertIsNotNone(unalloc)

    def test_invalid_row_is_an_error(self):
        self.row.classification = "Bogus"
        self.row.flight_phase = "Orbit"
        issues = self.rules("error", "avionics.fha.invalid")
        self.assertEqual(len(issues), 2)

    def test_reliability_hint(self):
        AP.set_values(self.repo, self.dadc, "Computer", {"mtbf": 1000, "failureRate": 5})
        hint = self.rules("info", "avionics.equipment.reliability")
        self.assertEqual(len(hint), 1)
        self.assertIn("1e+06 FIT", hint[0]["message"].replace("1000000 FIT", "1e+06 FIT"))
        AP.set_values(self.repo, self.dadc, "Computer", {"failureRate": 1e6})
        self.assertEqual(self.rules(rule="avionics.equipment.reliability"), [])

    def test_rules_appear_in_the_validator(self):
        self.set_dal("C")
        issues = [i for i in self.repo.validate() if i.rule.startswith("avionics.")]
        self.assertTrue(any(i.rule == "avionics.dal.allocation" and i.severity is Severity.ERROR for i in issues))
        self.assertTrue(all(i.element is not None for i in issues))

    def test_filters(self):
        self.set_dal("C")
        out = SF.safety_check(self.repo, severities=["error"])
        self.assertTrue(out["issues"] and all(i["severity"] == "error" for i in out["issues"]))
        self.assertEqual(out["counts"]["error"], len(out["issues"]))
        out = SF.safety_check(self.repo, rules=["avionics.dal.allocation"])
        self.assertEqual({i["rule"] for i in out["issues"]}, {"avionics.dal.allocation"})
        ids = {r["id"] for r in out["rules"]}
        self.assertTrue({"avionics.dal.requirement", "avionics.dal.allocation", "avionics.dal.partitioning",
                         "avionics.dal.decomposition", "avionics.fha.unallocated", "avionics.req.verification"} <= ids)


class RequirementRuleTests(unittest.TestCase):

    def setUp(self):
        self.repo = repo = Repository("Q")
        AP.ensure_profile(repo)
        self.rset = rq.create_requirement_set(repo, "S", prefix="R-")

    def req(self, summary, level, dal, method, *, derived=False, safety=False, rationale=None, parent=None):
        fields = {"summary": summary, "verification_method": method}
        if rationale:
            fields["rationale"] = rationale
        r = rq.add_requirement(self.repo, parent or self.rset, fields)
        AP.apply(self.repo, r, "AvionicsRequirement", {"level": level, "dal": dal, "derived": derived,
                                                       "safetyRelated": safety})
        return r

    def issues(self, rule):
        return [i for i in SF.safety_check(self.repo)["issues"] if i["rule"] == rule]

    def test_verification_method_per_dal(self):
        self.req("hlr-insp", "HLR", "B", "inspection")
        self.req("hlr-test", "HLR", "B", "test")
        self.req("sys-insp-a", "System", "A", "inspection")
        self.req("sys-insp-c", "System", "C", "inspection")
        self.req("sys-analysis-a", "System", "A", "analysis")
        got = sorted(i["name"] for i in self.issues("avionics.req.verification"))
        self.assertEqual(got, ["R-1 hlr-insp", "R-3 sys-insp-a"])
        msg = self.issues("avionics.req.verification")[0]["message"]
        self.assertIn("requirements-based tests", msg + self.issues("avionics.req.verification")[1]["message"])

    def test_unverified_and_unimplemented(self):
        r = self.req("a", "System", "A", "test")
        self.req("d", "System", "D", "test")
        self.assertEqual(len(self.issues("avionics.req.unverified")), 1)
        self.assertEqual(len(self.issues("avionics.req.unimplemented")), 1)
        tc = rq.add_test_case(self.repo, self.rset, "TC")
        arch = A.create_architecture(self.repo, "Sys")
        comp = A.add_component(self.repo, arch, "C")
        rq.create_trace_link(self.repo, "verify", tc, r)
        rq.create_trace_link(self.repo, "implement", comp, r)
        self.assertEqual(self.issues("avionics.req.unverified"), [])
        self.assertEqual(self.issues("avionics.req.unimplemented"), [])

    def test_draft_requirements_are_not_reported_for_coverage(self):
        r = self.req("a", "System", "A", "test")
        self.assertEqual(len(self.issues("avionics.req.unverified")), 1)
        rq.update_requirement(self.repo, r, {"status": "draft"})
        self.assertEqual(self.issues("avionics.req.unverified"), [])
        self.assertEqual(self.issues("avionics.req.unimplemented"), [])

    def test_skeleton_sets_are_drafts_and_quiet(self):
        repo = Repository("Skel")
        requirements_lib.import_requirement_library(repo)
        self.assertEqual({x.req_status for x in rq.all_requirements(repo)}, {"draft"})
        self.assertEqual(SF.safety_check(repo)["issues"], [])

    def test_a_parent_verification_counts(self):
        parent = self.req("parent", "System", "B", "test")
        self.req("child", "System", "B", "test", parent=parent)
        tc = rq.add_test_case(self.repo, self.rset, "TC")
        rq.create_trace_link(self.repo, "verify", tc, parent)
        self.assertEqual(self.issues("avionics.req.unverified"), [])

    def test_derived_and_safety_related(self):
        self.req("derived", "System", "C", "test", derived=True)
        self.req("derived ok", "System", "C", "test", derived=True, rationale="because")
        self.req("safety", "System", "E", "test", safety=True)
        self.assertEqual([i["name"] for i in self.issues("avionics.req.derived")], ["R-1 derived"])
        self.assertEqual([i["name"] for i in self.issues("avionics.req.safety-dal")], ["R-3 safety"])

    def test_requirements_without_the_stereotype_are_ignored(self):
        rq.add_requirement(self.repo, self.rset, {"summary": "plain", "verification_method": "inspection"})
        self.assertEqual([i for i in SF.safety_check(self.repo)["issues"]], [])


if __name__ == "__main__":
    unittest.main()
