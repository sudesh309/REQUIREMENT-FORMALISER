"""Interop with the profiles feature: stereotypes of real profiles (engine.profiles) in tables,
reports, SysML text, XMI, compare / merge, and atomic imports."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from engine import from_json, to_json
from engine import profiles as P
from engine.interop import (
    InteropError, ModelBuilder, export_tables, import_tables, read_csv_zip, read_xlsx,
    tables_to_project, write_csv_zip, write_xlsx,
)
from engine.interop import tables as T
from engine.interop.diff import compare, merge_to_repo, three_way_merge
from engine.interop.report import generate_report
from engine.interop.sysml_export import export_sysml
from engine.interop.xmi_import import import_xmi
from kerml.stereotypes import Profile, stereotypes_on
from tests.test_interop_fixtures import XMI_FIXTURE, add_avionics_profile, avionics_repo
from tests.test_interop_tables import _rows, _set

ROOT = Path(__file__).resolve().parent.parent


def _avionics():
    repo = avionics_repo()
    add_avionics_profile(repo)
    return repo


class ProfileTablesExportTests(unittest.TestCase):

    def setUp(self):
        self.repo = _avionics()
        self.sheets = export_tables(self.repo)

    def test_columns_are_named_by_the_profiles_feature(self):
        comps = {r["Name"]: r for r in _rows(self.sheets, "Components")}
        fmc = comps["fmc"]
        self.assertEqual(fmc["Stereotypes"], "Avionics.LRU")
        self.assertEqual(fmc["Avionics.LRU.mass"], 1.36077711)     # 3 lb, stored in kg
        self.assertEqual((fmc["Avionics.LRU.dal"], fmc["Avionics.LRU.ata"]), ("B", 34))
        self.assertIs(fmc["Avionics.LRU.spare"], False)
        # The legacy stereotype in a plain package keeps its bare name.
        self.assertEqual(comps["FlightManagementComputer"]["Stereotypes"], "LRU")
        ports = {r["Name"]: r for r in _rows(self.sheets, "Ports")}
        self.assertEqual(ports["navIn"]["Avionics.A429Port.rate"], 12.5)

    def test_profiles_sheet_carries_the_whole_definition(self):
        rows = {(r["Profile"], r["Stereotype"], r["Property"]): r
                for r in _rows(self.sheets, "Profiles")}
        mass = rows[("Avionics", "Equipment", "mass")]
        self.assertEqual((mass["Type"], mass["Unit"], mass["Default"], mass["Min"], mass["Max"]),
                         ("double", "kg", 1.5, 0, ""))
        self.assertEqual((mass["Profile Version"], mass["Profile Description"]),
                         ("2.1", "Avionics equipment"))
        self.assertEqual((mass["Applies To"], mass["Abstract"], mass["Style"]),
                         ("Component", True, "fill=#dbeafe; icon=computer"))
        dal = rows[("Avionics", "LRU", "dal")]
        self.assertEqual((dal["Base"], dal["Literals"], dal["Default"], dal["Defaults"],
                          dal["Style"]),
                         ("Avionics.Equipment", "A, B, C, D, E", "C",
                          "port=Avionics.A429Port", "stroke=#1d4ed8; line=dashed"))
        self.assertEqual(rows[("Avionics", "LRU", "pn")]["Description"], "part number")
        self.assertEqual(rows[("Spare", "", "")]["Profile Version"], "0.1")   # empty profile
        legacy = rows[("AvionicsProfile", "LRU", "mass")]
        self.assertEqual((legacy["Type"], legacy["Applies To"], legacy["Default"]),
                         ("", "PartDefinition;PartUsage", 0.0))


class ProfileTablesRoundTripTests(unittest.TestCase):

    def setUp(self):
        self.repo = _avionics()
        self.sheets = export_tables(self.repo)

    def test_xlsx_and_csv_round_trip_is_identical(self):
        for label, data in (("xlsx", read_xlsx(write_xlsx(self.sheets))),
                            ("csv", read_csv_zip(write_csv_zip(self.sheets)))):
            with self.subTest(label):
                new, report = tables_to_project(data)
                self.assertEqual(report.warnings, [])
                diff = compare(self.repo, new)
                self.assertTrue(diff["identical"], (diff["changes"][:3], diff["project"]))
                self.assertEqual(export_tables(new), self.sheets)
                avionics = P.find_profile(new, "Avionics")
                self.assertIsInstance(avionics, Profile)
                self.assertEqual(avionics.element_id, P.find_profile(self.repo, "Avionics").element_id)
                fmc = new.resolve("FlightDeck::fmc")
                self.assertEqual(P.get_property_value(fmc, "Avionics.LRU.mass"), 1.36077711)
                self.assertEqual(P.get_property_value(fmc, "Avionics.LRU.ata"), 34)
                self.assertIs(type(P.get_property_value(fmc, "Avionics.LRU.ata")), int)
                lru = P.find_stereotype(new, "Avionics.LRU")
                self.assertEqual(lru.base.full_name, "Avionics.Equipment")
                self.assertEqual(lru.default_port_stereotype.full_name, "Avionics.A429Port")
                self.assertTrue(P.find_stereotype(new, "Avionics.Equipment").is_abstract)
                # Legacy untyped values come back typed, also from CSV text.
                legacy = stereotypes_on(new.resolve("Components::FlightManagementComputer"))[0]
                self.assertEqual(legacy.values, {"mass": 4.2, "dal": "A"})

    def test_reimport_into_the_same_project_changes_nothing(self):
        before = to_json(self.repo)
        for data in (self.sheets, read_csv_zip(write_csv_zip(self.sheets))):
            report = import_tables(self.repo, data)
            self.assertEqual((report.created, report.updated, report.profile_changes), ([], [], []))
        self.assertEqual(to_json(self.repo), before)

    def test_values_are_checked_and_converted_by_profiles(self):
        _set(self.sheets, "Components", {"Name": "fmc"},
             **{"Avionics.LRU.mass": "2 lb", "Avionics.LRU.dal": "a", "Avionics.LRU.ata": "21",
                "Avionics.LRU.spare": "yes"})
        report = import_tables(self.repo, self.sheets)
        fmc = self.repo.resolve("FlightDeck::fmc")
        self.assertEqual(len(report.updated), 1)
        self.assertEqual(P.get_property_value(fmc, "Avionics.LRU.mass"), 0.90718474)
        self.assertEqual(P.get_property_value(fmc, "Avionics.LRU.dal"), "A")
        self.assertEqual(P.get_property_value(fmc, "Avionics.LRU.ata"), 21)
        self.assertIs(P.get_property_value(fmc, "Avionics.LRU.spare"), True)

    def test_invalid_values_are_rejected_and_nothing_changes(self):
        before = to_json(self.repo)
        for column, value, fragment in (
                ("Avionics.LRU.mass", "-1", "below the minimum 0 kg"),
                ("Avionics.LRU.mass", "5 W", "cannot convert W"),
                ("Avionics.LRU.dal", "F", "not one of the literals"),
                ("Avionics.LRU.ata", "300", "outside the uint8 range"),
                ("Avionics.LRU.bogus", "1", "has no property 'bogus'")):
            with self.subTest(column=column, value=value):
                sheets = export_tables(self.repo)
                _set(sheets, "Components", {"Name": "fmc"}, **{column: value})
                with self.assertRaises(InteropError) as ctx:
                    import_tables(self.repo, sheets)
                self.assertIn("Components row", str(ctx.exception))
                self.assertIn(fragment, str(ctx.exception))
                self.assertEqual(to_json(self.repo), before)

    def test_columns_may_name_a_base_or_a_legacy_package_stereotype(self):
        import_tables(self.repo, {"Components": [["Name", "Parent", "Avionics.Equipment.mass"],
                                                 ["fmc", "FlightDeck", "4 kg"]]})
        fmc = self.repo.resolve("FlightDeck::fmc")
        self.assertEqual(P.get_property_value(fmc, "Avionics.LRU.mass"), 4.0)
        # Tables written before the profiles feature named a plain-package stereotype
        # 'Package.Stereotype'; they still import (as the qualified name Package::Stereotype).
        report = import_tables(self.repo, {
            "Components": [["Name", "Parent", "Stereotypes", "AvionicsProfile.LRU.mass"],
                           ["GPSReceiver", "Components", "AvionicsProfile.LRU", "7.5"]]})
        self.assertEqual(report.warnings, [])
        gps = stereotypes_on(self.repo.resolve("Components::GPSReceiver"))
        self.assertEqual([a.stereotype.full_name for a in gps], ["LRU"])
        self.assertEqual(gps[0].values["mass"], 7.5)

    def test_ambiguous_stereotype_names_are_reported(self):
        ground = P.create_profile(self.repo, "Ground")
        P.add_stereotype(self.repo, ground, "Equipment", applies_to="Component")
        before = to_json(self.repo)
        with self.assertRaises(InteropError) as ctx:
            import_tables(self.repo, {"Components": [["Name", "Parent", "Stereotypes"],
                                                     ["fmc", "FlightDeck", "Equipment"]]})
        self.assertIn("Components row 2", str(ctx.exception))
        self.assertIn("ambiguous", str(ctx.exception))
        self.assertEqual(to_json(self.repo), before)

    def test_stereotype_order_is_kept(self):
        extra = P.add_stereotype(self.repo, P.find_profile(self.repo, "Avionics"), "Tagged",
                                 style={"fill": "#ffeeee"})
        fmc = self.repo.resolve("FlightDeck::fmc")
        P.apply_stereotype(self.repo, fmc, extra)
        _set(self.sheets, "Components", {"Name": "fmc"}, Stereotypes="Avionics.Tagged;Avionics.LRU")
        import_tables(self.repo, export_tables(self.repo) | {"Components": self.sheets["Components"]})
        self.assertEqual([a.stereotype.name for a in stereotypes_on(fmc)], ["Tagged", "LRU"])
        self.assertEqual(P.display_fields(fmc)[1]["fill"], "#ffeeee")      # first one wins

    def test_new_rows_keep_default_stereotypes_unless_the_cell_says_otherwise(self):
        fmc = self.repo.resolve("FlightDeck::fmc")
        ims = self.repo.resolve("FlightDeck::ims")
        P.apply_stereotype(self.repo, ims, P.find_stereotype(self.repo, "Avionics.LRU"))
        report = import_tables(self.repo, {"Ports": [
            ["Name", "Component", "Direction", "Stereotypes"],
            ["maint", "FlightDeck::ims", "in", ""],          # default «A429Port» kept
            ["test", "FlightDeck::ims", "in", "Avionics.A429Port"],
            ["spare", "FlightDeck::fmc", "in", ""]]})        # fmc's definition owns no LRU defaults
        self.assertEqual(len(report.created), 3)
        names = lambda e: [a.stereotype.full_name for a in stereotypes_on(e)]  # noqa: E731
        self.assertEqual(names(self.repo.resolve("FlightDeck::ims::maint")), ["Avionics.A429Port"])
        self.assertEqual(names(self.repo.resolve("FlightDeck::ims::test")), ["Avionics.A429Port"])
        self.assertEqual(names(self.repo.resolve("FlightDeck::fmc::spare")), ["Avionics.A429Port"])
        self.assertIsNotNone(fmc)
        # An existing element's empty cell removes its stereotypes.
        import_tables(self.repo, {"Ports": [["Name", "Component", "Stereotypes"],
                                            ["maint", "FlightDeck::ims", ""]]})
        self.assertEqual(names(self.repo.resolve("FlightDeck::ims::maint")), [])


class ProfileSheetEditTests(unittest.TestCase):

    def setUp(self):
        self.repo = _avionics()
        self.sheets = export_tables(self.repo)
        self.fmc = self.repo.resolve("FlightDeck::fmc")

    def test_unit_change_propagates_through_profiles(self):
        _set(self.sheets, "Profiles", {"Stereotype": "Equipment", "Property": "mass"}, Unit="g")
        report = import_tables(self.repo, self.sheets)
        tag = P.find_property(self.repo, "Avionics.Equipment.mass")
        self.assertEqual((tag.unit, tag.default_value, tag.minimum), ("g", 1500.0, 0))
        self.assertAlmostEqual(P.get_property_value(self.fmc, "Avionics.LRU.mass"), 1360.77711)
        self.assertEqual(report.profile_changes, ["updated property Avionics.Equipment.mass: unit"])
        self.assertEqual(report.updated, [self.fmc.element_id])      # its value was converted

    def test_edits_in_one_row_are_not_undone_by_the_other_rows(self):
        P.set_property_value(self.repo, self.fmc, "Avionics.LRU.pn", "822-1234")
        self.sheets = export_tables(self.repo)
        dal = {"Profile": "Avionics", "Stereotype": "LRU", "Property": "dal"}
        _set(self.sheets, "Profiles", dal, **{"Profile Version": "2.2", "Stereotype": "Lru",
                                              "Stereotype Description": "Line replaceable unit"})
        _set(self.sheets, "Profiles", {"Profile": "Avionics", "Stereotype": "LRU", "Property": "pn"},
             Property="partNumber")
        report = import_tables(self.repo, self.sheets)
        prof = P.find_profile(self.repo, "Avionics")
        lru = P.find_stereotype(self.repo, "Avionics.Lru")
        self.assertEqual((prof.version, lru.description), ("2.2", "Line replaceable unit"))
        self.assertEqual([t.name for t in lru.tags], ["dal", "ata", "spare", "partNumber"])
        self.assertIs(stereotypes_on(self.fmc)[0].stereotype, lru)        # applications kept
        self.assertEqual(P.get_property_value(self.fmc, "Avionics.Lru.dal"), "B")
        # Element rows still name the stereotype and property as exported: values kept.
        self.assertEqual(P.get_property_value(self.fmc, "Avionics.Lru.partNumber"), "822-1234")
        # ... and the renamed column takes edits.
        sheets = export_tables(self.repo)
        _set(sheets, "Components", {"Name": "fmc"}, **{"Avionics.Lru.partNumber": "822-9"})
        import_tables(self.repo, sheets)
        self.assertEqual(P.get_property_value(self.fmc, "Avionics.Lru.partNumber"), "822-9")
        self.assertIn("updated profile Avionics: version", report.profile_changes)
        self.assertIn("updated «Avionics.Lru»: name, description", report.profile_changes)

    def test_new_profile_stereotype_and_property_rows(self):
        report = import_tables(self.repo, {"Profiles": [
            ["Profile", "Profile Version", "Stereotype", "Applies To", "Base", "Property", "Type",
             "Unit", "Default", "Min", "Max", "Literals"],
            ["Avionics", "2.1", "IMAModule", "", "Avionics.Equipment", "partitions", "uint8", "", 4,
             1, 16, ""],
            ["Power", "1.0", "Load", "Component", "", "power", "double", "W", "0.5 kW", 0, "", ""],
            ["Power", "1.0", "Load", "Component", "", "bus", "enumeration", "", "", "", "",
             "AC1, AC2, DC1"]]})
        ima = P.find_stereotype(self.repo, "Avionics.IMAModule")
        self.assertEqual(ima.effective_category(), "Component")
        self.assertEqual([t.name for t in ima.all_tags()], ["partitions", "mass"])
        power = P.find_property(self.repo, "Power.Load.power")
        self.assertEqual((power.unit, power.default_value), ("W", 500.0))
        self.assertEqual(P.find_property(self.repo, "Power.Load.bus").default_value, "AC1")
        self.assertIsInstance(P.find_profile(self.repo, "Power"), Profile)
        self.assertEqual(report.stereotypes_created, 2)
        self.assertIn("created profile Power", report.profile_changes)

    def test_blank_repeated_cells_do_not_clear_what_another_row_sets(self):
        # Hand-written: profile / stereotype columns filled on the first row only.
        import_tables(self.repo, {"Profiles": [
            ["Profile", "Profile Version", "Stereotype", "Stereotype Description", "Property",
             "Type", "Unit"],
            ["Avionics", "3.0", "Sensor", "Senses things", "range", "double", "m"],
            ["Avionics", "", "Sensor", "", "rate", "double", "Hz"]]})
        sensor = P.find_stereotype(self.repo, "Avionics.Sensor")
        self.assertEqual((P.find_profile(self.repo, "Avionics").version, sensor.description),
                         ("3.0", "Senses things"))
        self.assertEqual([(t.name, t.unit) for t in sensor.tags], [("range", "m"), ("rate", "Hz")])
        # A column left blank on every row of the stereotype does clear it.
        import_tables(self.repo, {"Profiles": [["Profile", "Stereotype", "Stereotype Description"],
                                               ["Avionics", "Sensor", ""]]})
        self.assertEqual(sensor.description, "")

    def test_model_builder_into_a_project_with_the_profile(self):
        b = ModelBuilder()
        sensor = b.add_stereotype("Sensor", profile="Avionics", applies_to="Component", properties=[
            {"Property": "range", "Type": "double", "Unit": "km", "Default": "5 nmi", "Min": 0}])
        arch = self.repo.resolve("FlightDeck").element_id
        adc = b.add_component("adc", parent_id=arch, stereotypes=[sensor],
                              values={f"{sensor}.range": "250 m"})
        b.add_component("radar", parent_id=arch, stereotypes=["Avionics.LRU"],
                        values={"Avionics.LRU.mass": "12 kg"})
        report = b.build(self.repo)
        prof = P.find_profile(self.repo, "Avionics")
        self.assertEqual((prof.version, prof.description), ("2.1", "Avionics equipment"))
        lru = P.find_stereotype(self.repo, "Avionics.LRU")
        self.assertEqual((lru.base.name, lru.style["line"]), ("Equipment", "dashed"))
        rng = P.find_property(self.repo, "Avionics.Sensor.range")
        self.assertEqual((rng.unit, rng.default_value), ("km", 9.26))
        self.assertEqual(P.get_property_value(self.repo.by_id(adc), "Avionics.Sensor.range"), 0.25)
        self.assertEqual(P.get_property_value(self.repo.resolve("FlightDeck::radar"),
                                              "Avionics.LRU.mass"), 12.0)
        self.assertEqual(report.profile_changes,
                         ["created stereotype «Avionics.Sensor»", "created property Avionics.Sensor.range"])

    def test_profile_errors_are_reported_with_the_row_and_change_nothing(self):
        before = to_json(self.repo)
        lru = {"Profile": "Avionics", "Stereotype": "LRU"}
        cases = [
            ({"Stereotype": "Equipment", "Property": "mass"}, {"Unit": "parsec"},
             "Unknown unit 'parsec'"),
            ({**lru, "Property": "dal"}, {"Abstract": True}, "«Avionics.LRU» is applied to 1 element"),
            ({**lru, "Property": "dal"}, {"Applies To": "Port"}, "cannot apply to Port"),
            ({**lru, "Property": "dal"}, {"Base": "Avionics.Nope"},
             "base stereotype 'Avionics.Nope' not found"),
            ({**lru, "Property": "dal"}, {"Style": "glow=1"}, "Style 'glow=1'"),
            ({**lru, "Property": "ata"}, {"Type": "int2"}, "int2"),
            ({**lru, "Property": "ata"}, {"Default": "300"}, "outside the uint8 range"),
        ]
        for match, change, fragment in cases:
            with self.subTest(change=change):
                sheets = export_tables(self.repo)
                _set(sheets, "Profiles", match, **change)
                with self.assertRaises(InteropError) as ctx:
                    import_tables(self.repo, sheets)
                self.assertIn("Profiles row", str(ctx.exception))
                self.assertIn(fragment, str(ctx.exception))
                self.assertEqual(to_json(self.repo), before)


class ProfileOutputsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo = _avionics()

    def test_report_shows_profile_names_and_units(self):
        html = generate_report(self.repo, date="x")
        self.assertIn("<td>Avionics.LRU</td><td>mass</td><td>1.36077711 kg</td>", html)
        self.assertIn("<td>Avionics.LRU</td><td>dal</td><td>B</td>", html)
        self.assertIn("<span class=stereo>«Avionics.LRU»</span>", html)

    def test_sysml_text_shows_profile_names_and_units(self):
        text = export_sysml(self.repo)
        self.assertIn('// #Avionics.LRU { mass = 1.36077711 [kg]; dal = "B"; ata = 34; '
                      'spare = false; pn = ""; }', text)
        self.assertIn("// #Avionics.A429Port { rate = 12.5 [kbit/s]; }", text)
        self.assertIn("// metadata def LRU :> Avionics.Equipment {", text)
        self.assertIn("package Avionics {", text)

    def test_compare_and_merge_profile_values(self):
        base = to_json(self.repo)
        mine, theirs = from_json(base), from_json(base)
        P.set_property_value(mine, mine.resolve("FlightDeck::fmc"), "Avionics.LRU.mass", "2 kg")
        P.set_property_value(theirs, theirs.resolve("FlightDeck::fmc"), "Avionics.LRU.mass", "5 kg")
        diff = compare(base, mine)
        props = {p["property"]: (p["old"], p["new"]) for c in diff["changes"] for p in c["properties"]}
        self.assertEqual(props, {"Avionics.LRU.mass": (1.36077711, 2.0)})   # profiles naming
        res = three_way_merge(base, to_json(theirs), to_json(mine))
        self.assertEqual([c.property for c in res.conflicts], ["«Avionics.LRU».mass"])
        merged = merge_to_repo(res, default="theirs")
        self.assertEqual(P.get_property_value(merged.resolve("FlightDeck::fmc"),
                                              "Avionics.LRU.mass"), 5.0)


class XmiProfileTests(unittest.TestCase):

    def test_xmi_stereotypes_use_an_existing_profile_stereotype(self):
        repo = _avionics()
        lru = P.find_stereotype(repo, "Avionics.LRU")
        tags = [t.name for t in lru.all_tags()]
        report = import_xmi(repo, XMI_FIXTURE.read_bytes())
        fmc = repo.resolve("FlightDeckModel::Structure::FlightManagementComputer")
        apps = stereotypes_on(fmc)
        self.assertEqual([a.stereotype for a in apps], [lru])
        self.assertEqual(P.get_property_value(fmc, "Avionics.LRU.mass"), 4.2)
        self.assertEqual(P.get_property_value(fmc, "Avionics.LRU.dal"), "A")
        self.assertEqual([t.name for t in lru.all_tags()], tags)     # the profile is not changed
        self.assertTrue(any("ataChapter" in w for w in report.warnings), report.warnings)
        self.assertIsNone(repo.resolve("XMI_Profiles"))


class AtomicImportTests(unittest.TestCase):

    def test_failed_import_in_a_fresh_process_leaves_the_project_byte_identical(self):
        # Feature modules (and their codecs) load with engine.interop, not mid-import.
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from engine import to_json\n"
            "from engine.interop import import_tables, InteropError\n"
            "from tests.test_interop_fixtures import avionics_repo\n"
            "repo = avionics_repo(); before = to_json(repo)\n"
            "try:\n"
            "    import_tables(repo, {'Components': [['Name', 'Kind'], ['X', 'Spaceship']]})\n"
            "except InteropError:\n"
            "    pass\n"
            "sys.exit(0 if to_json(repo) == before else 1)\n") % str(ROOT)
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                              cwd=ROOT, timeout=60, env={**os.environ})
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_project_is_restored_if_the_real_run_fails(self):
        repo = _avionics()
        before = to_json(repo)
        original_links = T._Importer.import_links
        calls = []

        def flaky(self):
            original_links(self)
            calls.append(1)
            if len(calls) == 2:                      # the rehearsal passed, the real run fails
                raise RuntimeError("disk full")

        tables = {"Components": [["Name", "Parent", "Avionics.LRU.mass"],
                                 ["fmc", "FlightDeck", "9 kg"], ["adc", "FlightDeck", ""]]}
        with mock.patch.object(T._Importer, "import_links", flaky):
            with self.assertRaises(RuntimeError):
                import_tables(repo, tables)
        self.assertEqual(to_json(repo), before)
        self.assertIsNone(repo.resolve("FlightDeck::adc"))
        self.assertIsNotNone(repo.by_id(repo.resolve("FlightDeck::fmc").element_id))


if __name__ == "__main__":
    unittest.main()
