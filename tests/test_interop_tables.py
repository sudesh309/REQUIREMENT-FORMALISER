"""Tables export / import (CSV ZIP and XLSX) and the ModelBuilder."""
import io
import unittest
import zipfile

from engine import Repository, to_json
from engine.interop import (
    InteropError, ModelBuilder, export_tables, export_tables_file, import_tables,
    read_csv_zip, read_tables_file, read_xlsx, tables_to_project, write_csv_zip, write_xlsx,
)
from engine.interop.diff import compare
from engine.interop.xlsx import safe_xml
from kerml.features import FeatureDirection
from kerml.stereotypes import stereotypes_on
from sysmlv2 import PartUsage
from tests.test_interop_fixtures import avionics_repo


def _rows(sheets, table):
    header, *rows = sheets[table]
    return [dict(zip(header, r)) for r in rows]


def _set(sheets, table, match, **changes):
    header = sheets[table][0]
    for row in sheets[table][1:]:
        d = dict(zip(header, row))
        if all(d.get(k) == v for k, v in match.items()):
            for k, v in changes.items():
                if k not in header:
                    header.append(k)
                    for r in sheets[table][1:]:
                        r.append("")
                row[header.index(k)] = v
            return
    raise AssertionError(f"no {table} row matching {match}")


class ExportTests(unittest.TestCase):

    def setUp(self):
        self.repo = avionics_repo()
        self.sheets = export_tables(self.repo)

    def test_sheets_and_headers(self):
        self.assertEqual(list(self.sheets), ["Model", "Profiles", "Components", "Ports", "Interfaces",
                                             "Connections", "Requirements", "Elements", "Links"])
        self.assertEqual(self.sheets["Components"][0][:7],
                         ["ID", "Name", "Kind", "Parent ID", "Parent", "Reference ID", "Reference"])
        self.assertIn("AvionicsProfile.LRU.mass", self.sheets["Components"][0])
        self.assertEqual(dict(self.sheets["Model"][1:])["Name"], "FlightDeck")

    def test_components_ports_connections_requirements_links(self):
        comps = {r["Name"]: r for r in _rows(self.sheets, "Components")}
        self.assertEqual(comps["gps"]["Reference"], "Components::GPSReceiver")
        self.assertEqual(comps["gps"]["Parent"], "FlightDeck")
        self.assertEqual(comps["pfd"]["Multiplicity"], "2")
        self.assertEqual(comps["FlightManagementComputer"]["Stereotypes"], "AvionicsProfile.LRU")
        self.assertEqual(comps["FlightManagementComputer"]["AvionicsProfile.LRU.mass"], 4.2)
        self.assertEqual(comps["partition1"]["Parent"], "FlightDeck::ims")
        ports = {r["Name"]: r for r in _rows(self.sheets, "Ports")}
        self.assertEqual(ports["navOut"]["Direction"], "out")
        self.assertEqual(ports["navIn"]["Interface"], "Interfaces::A429Word")
        self.assertEqual(ports["health"]["Component"], "FlightDeck::ims")
        conns = {r["Name"]: r for r in _rows(self.sheets, "Connections")}
        self.assertEqual(conns["navBus"]["Source Port"], "Components::GPSReceiver::navOut")
        self.assertEqual(conns["navBus"]["Target Port"], "Components::FlightManagementComputer::navIn")
        ifaces = {r["Name"]: r for r in _rows(self.sheets, "Interfaces")}
        self.assertEqual(ifaces["label"]["Type"], "KerML::ScalarValues::Integer")
        self.assertEqual(ifaces["label"]["Type ID"], "")       # library types go by name
        reqs = {r["Req ID"]: r for r in _rows(self.sheets, "Requirements")}
        self.assertEqual(reqs["SRS-001"]["Name"], "NavAccuracy")
        self.assertIn("RNP 0.3", reqs["SRS-001"]["Text"])
        links = {(r["Kind"], r["Source"], r["Target"]) for r in _rows(self.sheets, "Links")}
        self.assertIn(("satisfy", "Components::FlightManagementComputer",
                       "Requirements::NavAccuracy"), links)
        self.assertIn(("derive", "Requirements::LateralGuidance", "Requirements::NavAccuracy"),
                      links)
        profiles = {(r["Stereotype"], r["Property"]) for r in _rows(self.sheets, "Profiles")}
        self.assertEqual(profiles, {("LRU", "mass"), ("LRU", "dal")})

    def test_state_machine_reference_columns(self):
        elements = {r["Name"]: r for r in _rows(self.sheets, "Elements")}
        on = self.repo.resolve("Components::FlightManagementComputer::Modes::On")
        trans = next(r for n, r in elements.items() if r["Kind"] == "TransitionUsage")
        self.assertEqual(trans["transition_target ID"], on.element_id)
        self.assertEqual(trans["trigger_event"], "powerOn")
        self.assertEqual(elements["On"]["entry_action"], "selfTest()")

    def test_files_are_deterministic(self):
        a, name, mime = export_tables_file(self.repo, "xlsx")
        b, _, _ = export_tables_file(self.repo, "xlsx")
        self.assertEqual(a, b)
        self.assertEqual(name, "FlightDeck.xlsx")
        self.assertIn("spreadsheetml", mime)
        c, name, _ = export_tables_file(self.repo, "csv")
        self.assertEqual(c, export_tables_file(self.repo, "csv")[0])
        self.assertEqual(name, "FlightDeck_tables.zip")
        with zipfile.ZipFile(io.BytesIO(c)) as zf:
            self.assertIn("Components.csv", zf.namelist())
            self.assertTrue(zf.read("Ports.csv").startswith("﻿".encode("utf-8")))
        with self.assertRaises(InteropError):
            export_tables_file(self.repo, "ods")


class RoundTripTests(unittest.TestCase):

    def setUp(self):
        self.repo = avionics_repo()
        self.sheets = export_tables(self.repo)

    def _assert_same(self, other):
        diff = compare(self.repo, other)
        self.assertTrue(diff["identical"], diff["changes"][:5])
        self.assertEqual({e.element_id for e in self.repo.root_package.walk()},
                         {e.element_id for e in other.root_package.walk()})

    def test_xlsx_round_trip_into_new_project_preserves_ids(self):
        new, report = tables_to_project(read_xlsx(write_xlsx(self.sheets)))
        self.assertEqual(new.name, "FlightDeck")
        self.assertEqual(report.warnings, [])
        self._assert_same(new)
        fmc = new.resolve("Components::FlightManagementComputer")
        app = stereotypes_on(fmc)[0]
        self.assertEqual(app.values, {"mass": 4.2, "dal": "A"})
        port = new.resolve("Components::FlightManagementComputer::navIn")
        self.assertIs(port.direction, FeatureDirection.IN)
        again = export_tables(new)
        for table, rows in self.sheets.items():
            # Sibling order across tables may differ (one table is imported after another).
            self.assertEqual(again[table][0], rows[0], table)
            self.assertEqual(sorted(map(str, again[table][1:])), sorted(map(str, rows[1:])), table)

    def test_csv_round_trip(self):
        new, _ = tables_to_project(read_csv_zip(write_csv_zip(self.sheets)))
        self._assert_same(new)

    def test_read_tables_file_detects_format(self):
        self.assertEqual(read_tables_file(write_xlsx(self.sheets), "x.xlsx")["Ports"],
                         read_xlsx(write_xlsx(self.sheets))["Ports"])
        self.assertIn("Ports", read_tables_file(write_csv_zip(self.sheets), "t.zip"))
        with self.assertRaises(InteropError):
            read_tables_file(b"not a zip", "x.xlsx")

    def test_reimport_into_same_project_changes_nothing(self):
        before = to_json(self.repo)
        report = import_tables(self.repo, self.sheets)
        self.assertEqual(report.created, [])
        self.assertEqual(report.updated, [])
        self.assertEqual(report.links_created, 0)
        self.assertEqual(to_json(self.repo), before)

    def test_update_existing_project_from_edited_tables(self):
        _set(self.sheets, "Components", {"Name": "gps"}, Name="gnss", Multiplicity="1..2")
        _set(self.sheets, "Ports", {"Name": "health"}, Direction="inout")
        _set(self.sheets, "Components", {"Name": "FlightManagementComputer"},
             **{"AvionicsProfile.LRU.mass": "5.5"})
        _set(self.sheets, "Requirements", {"Req ID": "SRS-002"}, Text="Shall show attitude.")
        gps_id = self.repo.resolve("FlightDeck::gps").element_id
        report = import_tables(self.repo, self.sheets)
        self.assertEqual(report.created, [])
        self.assertEqual(len(report.updated), 4)
        gnss = self.repo.by_id(gps_id)
        self.assertEqual(gnss.name, "gnss")
        self.assertEqual((gnss.multiplicity.lower, gnss.multiplicity.upper), (1, 2))
        self.assertIs(self.repo.resolve("FlightDeck::ims::health").direction, FeatureDirection.INOUT)
        fmc = self.repo.resolve("Components::FlightManagementComputer")
        self.assertEqual(stereotypes_on(fmc)[0].values["mass"], 5.5)
        self.assertEqual(self.repo.resolve("Requirements::AttitudeDisplay").text,
                         "Shall show attitude.")

    def test_move_and_relink(self):
        arch = self.repo.resolve("FlightDeck")
        _set(self.sheets, "Components", {"Name": "partition1"}, **{"Parent ID": arch.element_id})
        import_tables(self.repo, self.sheets)
        moved = self.repo.resolve("FlightDeck::partition1")
        self.assertIsNotNone(moved)
        self.assertIsNone(self.repo.resolve("FlightDeck::ims::partition1"))
        ims = self.repo.resolve("FlightDeck::ims")
        self.assertFalse(any(m.member is moved for m in ims.memberships))

    def test_hand_written_rows_without_ids(self):
        tables = {
            "Components": [["Name", "Parent", "Reference"],
                           ["Cockpit", "", ""],
                           ["gps2", "Cockpit", "Components::GPSReceiver"]],
            "Ports": [["Name", "Component", "Direction", "Interface"],
                      ["alert", "Cockpit::gps2", "out", "Interfaces::A429Word"]],
            "Links": [["Kind", "Source", "Target"],
                      ["satisfy", "Cockpit::gps2", "Requirements::NavAccuracy"]],
        }
        report = import_tables(self.repo, tables)
        self.assertEqual(len(report.created), 3)
        self.assertEqual(report.links_created, 1)
        cockpit = self.repo.resolve("Cockpit")
        self.assertEqual(cockpit.kind, "PartDefinition")
        gps2 = self.repo.resolve("Cockpit::gps2")
        self.assertIsInstance(gps2, PartUsage)
        self.assertEqual(gps2.types[0].name, "GPSReceiver")
        self.assertIs(self.repo.resolve("Cockpit::gps2::alert").direction, FeatureDirection.OUT)
        # Importing the same hand-written tables again matches by owner + name.
        again = import_tables(self.repo, tables)
        self.assertEqual(again.created, [])
        self.assertEqual(again.links_created, 0)

    def test_extra_attribute_columns_round_trip(self):
        class LruPart(PartUsage):
            kind = "TestLruPart"

            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.ata_chapter = ""
                self.spare = False

        repo = Repository("X")
        from sysmlv2 import PartDefinition
        arch = repo.add(PartDefinition(name="A"))
        p = LruPart(name="adc")
        p.ata_chapter, p.spare = "34", True
        arch.own(p)
        repo.registry.register_tree(arch)
        sheets = export_tables(repo)
        row = _rows(sheets, "Components")[1]
        self.assertEqual((row["Kind"], row["ata_chapter"], row["spare"]), ("TestLruPart", "34", True))
        new, _ = tables_to_project(read_csv_zip(write_csv_zip(sheets)))
        q = new.resolve("A::adc")
        self.assertIsInstance(q, LruPart)
        self.assertEqual((q.ata_chapter, q.spare), ("34", True))


class ImportErrorTests(unittest.TestCase):

    def setUp(self):
        self.repo = avionics_repo()
        self.before = to_json(self.repo)

    def _fails(self, tables, *fragments):
        with self.assertRaises(InteropError) as ctx:
            import_tables(self.repo, tables)
        for f in fragments:
            self.assertIn(f, str(ctx.exception))
        self.assertEqual(to_json(self.repo), self.before, "failed import must change nothing")

    def test_unknown_kind_and_wrong_table(self):
        self._fails({"Components": [["Name", "Kind"], ["X", "Spaceship"]]},
                    "Components row 2", "unknown kind 'Spaceship'")
        self._fails({"Ports": [["Name", "Kind"], ["p", "PartUsage"]]},
                    "does not belong in the Ports table")

    def test_bad_values(self):
        self._fails({"Ports": [["Name", "Component", "Direction"], ["p", "FlightDeck", "sideways"]]},
                    "invalid direction 'sideways'")
        self._fails({"Components": [["Name", "Parent", "Multiplicity"], ["c", "FlightDeck", "3..1"]]},
                    "Components row 2")
        self._fails({"Components": [["Name", "Parent ID"], ["c", "no-such-id"]]},
                    "parent 'no-such-id' not found")
        self._fails({"Ports": [["Name", "Component", "Interface"], ["p", "FlightDeck", "Nope::X"]]},
                    "Interface 'Nope::X' not found")

    def test_errors_detected_late_still_leave_the_model_untouched(self):
        tables = {"Components": [["Name", "Parent"], ["NewOne", "FlightDeck"]],
                  "Links": [["Kind", "Source", "Target"], ["satisfy", "FlightDeck::NewOne", "Missing"]]}
        self._fails(tables, "Links row 2", "target 'Missing' not found")
        self.assertIsNone(self.repo.resolve("FlightDeck::NewOne"))

    def test_id_conflicts(self):
        fd = self.repo.resolve("FlightDeck")
        self._fails({"Ports": [["ID", "Name", "Component"], [fd.element_id, "p", "FlightDeck"]]},
                    "is a PartDefinition in the model")
        self._fails({"Components": [["ID", "Name"], ["a", "X"], ["a", "Y"]]}, "duplicate ID 'a'")

    def test_stereotype_errors(self):
        self._fails({"Components": [["Name", "Parent", "Stereotypes"], ["c", "FlightDeck", "Nope"]]},
                    "stereotype 'Nope' not found")
        self._fails({"Components": [["Name", "Stereotypes", "AvionicsProfile.LRU.bogus"],
                                    ["FlightDeck", "AvionicsProfile.LRU", "1"]]},
                    "has no property 'bogus'")


class ModelBuilderTests(unittest.TestCase):

    def test_build_new_model(self):
        b = ModelBuilder("IMA")
        lru = b.add_stereotype("LRU", profile="Avionics", properties=[("mass", 0.0), "dal"])
        a429 = b.add_interface("A429Word")
        b.add_element_in_interface("label", a429, type="ScalarValues::Integer")
        arch = b.add_component("Cabinet")
        cpm = b.add_component("cpm", parent_id=arch, stereotypes=[lru],
                              values={f"{lru}.mass": 3.5, f"{lru}.dal": "A"})
        io_ = b.add_component("iom", parent_id=arch)
        out = b.add_port("busOut", "out", cpm, interface_id=a429)
        inp = b.add_port("busIn", "in", io_, interface_id=a429)
        b.add_connection("afdx", out, inp, owner_id=arch)
        req = b.add_requirement("Partitioning", req_id="IMA-1", text="Shall partition.")
        b.add_link("satisfy", cpm, req)
        pkg = b.add_element("Notes", "Package")
        b.add_element("Temp", "AttributeDefinition", owner_id=pkg)
        repo = b.build()
        self.assertEqual(repo.name, "IMA")
        cab = repo.resolve("Cabinet")
        self.assertEqual([c.name for c in cab.owned_elements if isinstance(c, PartUsage)],
                         ["cpm", "iom"])
        conn = repo.resolve("Cabinet::afdx")
        self.assertEqual([e.name for e in conn.ends], ["busOut", "busIn"])
        self.assertEqual(repo.by_id(cpm).name, "cpm")
        app = stereotypes_on(repo.by_id(cpm))[0]
        self.assertEqual(app.values, {"mass": 3.5, "dal": "A"})
        self.assertEqual(repo.resolve("Partitioning").req_id, "IMA-1")
        self.assertIsNotNone(repo.resolve("Notes::Temp"))
        tables = b.tables()
        self.assertEqual(_rows(tables, "Ports")[0]["Name"], "busOut")

    def test_build_into_existing_project(self):
        repo = avionics_repo()
        arch = repo.resolve("FlightDeck").element_id
        b = ModelBuilder()
        b.add_component("adc", parent_id=arch)
        report = b.build(repo)
        self.assertEqual(len(report.created), 1)
        self.assertEqual(repo.resolve("FlightDeck::adc").kind, "PartUsage")


class XlsxReaderTests(unittest.TestCase):

    def _workbook(self, sheet_xml: str, shared: str = "", prolog: str = "") -> bytes:
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml",
                        f'<workbook {ns} xmlns:r="{rel}"><sheets>'
                        '<sheet name="Ports" sheetId="1" r:id="rId7"/></sheets></workbook>')
            zf.writestr("xl/_rels/workbook.xml.rels",
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                        'relationships"><Relationship Id="rId7" Target="/xl/worksheets/s1.xml" '
                        f'Type="{rel}/worksheet"/></Relationships>')
            zf.writestr("xl/worksheets/s1.xml", f"{prolog}<worksheet {ns}><sheetData>{sheet_xml}"
                        "</sheetData></worksheet>")
            if shared:
                zf.writestr("xl/sharedStrings.xml", f"<sst {ns}>{shared}</sst>")
        return buf.getvalue()

    def test_shared_strings_rich_text_numbers_and_booleans(self):
        data = self._workbook(
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>'
            '<row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3"><v>2.5</v></c>'
            '<c r="C3" t="b"><v>1</v></c><c r="D3" t="str"><v>x</v></c></row>',
            "<si><t>Name</t></si><si><r><t>Dir</t></r><r><t>ection</t></r></si>"
            "<si><t>p1</t><rPh><t>ignored</t></rPh></si>")
        rows = read_xlsx(data)["Ports"]
        self.assertEqual(rows[0], ["Name", None, "Direction", None])
        self.assertEqual(rows[1], [None, None, None, None])
        self.assertEqual(rows[2], ["p1", 2.5, True, "x"])

    def test_rejects_dtd_and_entities(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
                '<!ENTITY lol2 "&lol;&lol;">]><lolz>&lol2;</lolz>')
        with self.assertRaises(InteropError):
            safe_xml(bomb)
        with self.assertRaises(InteropError):
            safe_xml(bomb.encode("utf-16"))
        bad = self._workbook('<row r="1"><c r="A1"><v>1</v></c></row>',
                             prolog='<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>')
        with self.assertRaises(InteropError) as ctx:
            read_xlsx(bad)
        self.assertIn("DOCTYPE", str(ctx.exception))

    def test_zip_bomb_limits(self):
        from engine.interop import xlsx
        old = xlsx.MAX_ARCHIVE_BYTES
        xlsx.MAX_ARCHIVE_BYTES = 100
        try:
            with self.assertRaises(InteropError):
                read_xlsx(write_xlsx({"S": [["a" * 500]]}))
        finally:
            xlsx.MAX_ARCHIVE_BYTES = old


if __name__ == "__main__":
    unittest.main()
