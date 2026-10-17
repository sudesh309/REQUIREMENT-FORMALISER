"""Engine tests for System Composer interfaces (engine/interfaces.py)."""
import json
import unittest

from engine import Repository, Validator, from_json, to_json
from engine import interfaces as I
from engine.interfaces import InterfaceError
from kerml.features import FeatureDirection
from sysmlv2 import ConnectionUsage, EnumerationDefinition, PartDefinition, PartUsage, PortUsage


def _issues(repo, prefix="interfaces."):
    return [i for i in Validator().validate(repo) if i.rule.startswith(prefix)]


class _Base(unittest.TestCase):

    def setUp(self):
        I.install()             # other test modules may clear global registries
        self.repo = Repository("P")

    def arch(self):
        """Sys with two inline components (adiru.out -> fms.in) and a connector."""
        sysd = self.repo.add(PartDefinition(name="Sys"))
        adiru = PartUsage(name="adiru"); sysd.own(adiru)
        fms = PartUsage(name="fms"); sysd.own(fms)
        out = PortUsage(name="out", direction=FeatureDirection.OUT); adiru.own(out)
        inp = PortUsage(name="inp", direction=FeatureDirection.IN); fms.own(inp)
        self.repo.registry.register_tree(sysd)
        return sysd, adiru, fms, out, inp

    def air_data(self, name="AirData"):
        return I.create_item(self.repo, "DataInterface", name, elements=[
            {"name": "alt", "type": "double", "units": "ft"},
            {"name": "cas", "type": "single", "units": "kn"},
            {"name": "valid", "type": "boolean"},
        ])


class DataInterfaceTests(_Base):

    def test_dictionary_created_on_demand_and_items_live_there(self):
        self.assertIsNone(I.get_dictionary(self.repo, create=False))
        ad = self.air_data()
        dic = I.get_dictionary(self.repo, create=False)
        self.assertIsInstance(dic, I.InterfaceDictionary)
        self.assertIs(ad.owner, dic)
        self.assertEqual(dic.name, "Interfaces")
        self.assertTrue(ad.color.startswith("#"))

    def test_element_fields_and_order(self):
        ad = self.air_data()
        self.assertEqual([e.name for e in I.elements_of(ad)], ["alt", "cas", "valid"])
        alt = I.find_element(ad, "alt")
        I.set_fields(self.repo, alt, {"dimensions": "[3 1]", "minimum": "-1000", "maximum": 60000,
                                      "complexity": "real", "description": "Pressure altitude"})
        d = I.describe_element(alt)
        self.assertEqual((d["dimensions"], d["minimum"], d["maximum"], d["description"]),
                         ("[3 1]", -1000, 60000, "Pressure altitude"))
        I.move_element(I.find_element(ad, "valid"), index=0)
        I.move_element(alt, delta=1)
        self.assertEqual([e.name for e in I.elements_of(ad)], ["valid", "cas", "alt"])
        I.remove_element(self.repo, I.find_element(ad, "cas"))
        self.assertEqual([e.name for e in I.elements_of(ad)], ["valid", "alt"])

    def test_default_element_names_and_primitive_typing(self):
        ad = I.create_item(self.repo, "DataInterface")
        e0 = I.add_element(self.repo, ad)
        e1 = I.add_element(self.repo, ad, index=0)
        self.assertEqual(ad.name, "interface0")
        self.assertEqual([e.name for e in I.elements_of(ad)], [e1.name, e0.name])
        self.assertEqual(e0.name, "elem0")
        self.assertEqual(I.describe_type(e0), "double")
        self.assertEqual(e0.types[0].name, "Real")      # typed by the KerML scalar

    def test_invalid_fields_rejected_atomically(self):
        ad = self.air_data()
        alt = I.find_element(ad, "alt")
        for fields, fragment in (({"dimensions": "abc"}, "Invalid dimensions"),
                                 ({"dimensions": "0"}, "Invalid dimensions"),
                                 ({"minimum": 5, "maximum": 1}, "must not exceed"),
                                 ({"minimum": "low"}, "not a number"),
                                 ({"complexity": "imag"}, "Complexity"),
                                 ({"type": "float128"}, "Unknown type"),
                                 ({"name": "1bad"}, "not valid"),
                                 ({"name": "cas"}, "already exists"),
                                 ({"bogus": 1}, "no field")):
            with self.subTest(fields=fields):
                with self.assertRaises(InterfaceError) as cm:
                    I.set_fields(self.repo, alt, {"units": "m", **fields})
                self.assertIn(fragment, str(cm.exception))
                self.assertEqual(alt.units, "ft")      # nothing applied

    def test_unknown_units_warn(self):
        ad = self.air_data()
        warnings = I.set_fields(self.repo, I.find_element(ad, "alt"), {"units": "furlong"})
        self.assertTrue(warnings and "furlong" in warnings[0])
        self.assertEqual(I.set_fields(self.repo, I.find_element(ad, "cas"), {"units": "m/s^2"}), [])
        self.assertIn("interfaces.units", [i.rule for i in _issues(self.repo)])

    def test_rename_collision_and_identifier(self):
        ad = self.air_data()
        other = I.create_item(self.repo, "DataInterface", "Other")
        with self.assertRaises(InterfaceError) as cm:
            I.set_fields(self.repo, other, {"name": "AirData"})
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(InterfaceError):
            I.create_item(self.repo, "DataInterface", "AirData")
        I.set_fields(self.repo, ad, {"name": "AirData2", "color": "#123ABC"})
        self.assertEqual((ad.name, ad.color), ("AirData2", "#123abc"))
        with self.assertRaises(InterfaceError):
            I.set_fields(self.repo, ad, {"color": "red"})


class ValueTypeAndNestingTests(_Base):

    def test_value_type_as_element_type_and_port_interface(self):
        vt = I.create_value_type(self.repo, "Altitude", base_type="double", units="ft",
                                 minimum=-1000, maximum=60000)
        ad = I.create_item(self.repo, "DataInterface", "AirData",
                           elements=[{"name": "alt", "type": "ValueType: Altitude"}])
        alt = I.find_element(ad, "alt")
        self.assertEqual(I.describe_type(alt), "ValueType: Altitude")
        eff = I.describe_element(alt)["effective"]
        self.assertEqual((eff["type"], eff["units"], eff["minimum"]), ("double", "ft", -1000))
        self.assertEqual(I.elements_using(self.repo, vt), [alt])
        _, _, _, out, inp = self.arch()
        I.assign_interface(self.repo, out, vt)
        I.assign_interface(self.repo, inp, "Altitude")
        self.assertEqual(I.check_compatibility(out, inp), [])
        with self.assertRaises(InterfaceError):
            I.set_fields(self.repo, vt, {"base_type": "quad"})

    def test_nested_interfaces_and_cycle_rejection(self):
        pos = I.create_item(self.repo, "DataInterface", "Position",
                            elements=[{"name": "lat"}, {"name": "lon"}])
        nav = I.create_item(self.repo, "DataInterface", "Nav",
                            elements=[{"name": "pos", "type": "Bus: Position"}, {"name": "gs"}])
        self.assertEqual(I.element_paths(nav), ["pos", "pos.lat", "pos.lon", "gs"])
        self.assertIs(I.find_element(nav, "pos.lon").owner, pos)
        with self.assertRaises(InterfaceError) as cm:
            I.add_element(self.repo, pos, "back", type="Bus: Nav")
        self.assertIn("cycle", str(cm.exception))
        self.assertIsNone(I.find_element(pos, "back"))     # rolled back
        with self.assertRaises(InterfaceError):
            I.set_fields(self.repo, I.find_element(pos, "lat"), {"type": "Bus: Position"})

    def test_cycle_from_loaded_model_is_reported(self):
        a = I.create_item(self.repo, "DataInterface", "A", elements=[{"name": "x"}])
        b = I.create_item(self.repo, "DataInterface", "B", elements=[{"name": "a", "type": "Bus: A"}])
        I._set_typing(I.find_element(a, "x"), b)          # bypass the API check
        I.find_element(a, "x").primitive_type = None
        self.assertIn("interfaces.cycle", [i.rule for i in _issues(self.repo)])

    def test_deleting_a_value_type_falls_back_to_double(self):
        vt = I.create_value_type(self.repo, "Speed", units="kn")
        ad = I.create_item(self.repo, "DataInterface", "AD", elements=[{"name": "v", "type": "ValueType: Speed"}])
        self.repo.remove(vt)
        self.assertEqual(I.describe_type(I.find_element(ad, "v")), "double")


class PortAssignmentTests(_Base):

    def test_assign_shared_owned_and_empty(self):
        _, _, _, out, inp = self.arch()
        ad = self.air_data()
        I.assign_interface(self.repo, out, "AirData")
        self.assertIs(I.interface_of(out), ad)
        self.assertEqual(I.ports_using(self.repo, ad), [out])
        owned = I.assign_interface(self.repo, out, "owned")       # copy of the shared one
        self.assertTrue(I.is_owned(owned))
        self.assertIs(owned.owner, out)
        self.assertEqual([e.name for e in I.elements_of(owned)], ["alt", "cas", "valid"])
        I.assign_interface(self.repo, out, ad)                      # back to shared drops the owned
        self.assertNotIn(owned, out.owned_elements)
        I.assign_interface(self.repo, out, "<empty>")
        self.assertIsNone(I.interface_of(out))
        with self.assertRaises(InterfaceError):
            I.assign_interface(self.repo, out, "Missing")
        I.assign_interface(self.repo, inp, "owned")
        with self.assertRaises(InterfaceError) as cm:
            I.assign_interface(self.repo, out, I.interface_of(inp))
        self.assertIn("owned by port", str(cm.exception))

    def test_make_shared_with_collision_choices(self):
        _, _, _, out, inp = self.arch()
        shared = self.air_data()
        owned = I.make_owned(self.repo, inp)            # empty owned interface
        I.add_element(self.repo, owned, "only")
        with self.assertRaises(InterfaceError) as cm:
            I.make_shared(self.repo, inp, "AirData")
        self.assertEqual(cm.exception.status, 409)
        renamed = I.make_shared(self.repo, inp, "AirData", on_conflict="rename")
        self.assertEqual(renamed.name, "AirData_1")
        self.assertIs(renamed.owner, I.get_dictionary(self.repo))
        self.assertNotIn(renamed, inp.owned_elements)
        # keep: port uses the existing shared interface, owned copy is discarded
        I.make_owned(self.repo, out)
        kept = I.make_shared(self.repo, out, "AirData", on_conflict="keep")
        self.assertIs(kept, shared)
        self.assertIs(I.interface_of(out), shared)
        # replace: existing keeps identity, content overwritten
        owned2 = I.make_owned(self.repo, out)
        I.remove_element(self.repo, I.find_element(owned2, "cas"))
        replaced = I.make_shared(self.repo, out, "AirData", on_conflict="replace")
        self.assertIs(replaced, shared)
        self.assertEqual([e.name for e in I.elements_of(shared)], ["alt", "valid"])

    def test_move_owned_to_dictionary(self):
        _, _, _, out, inp = self.arch()
        I.make_owned(self.repo, out)
        I.make_owned(self.repo, inp)
        report = I.move_owned_to_dictionary(self.repo)
        self.assertEqual(len(report), 2)
        self.assertEqual(I.owned_interfaces(self.repo), [])
        self.assertFalse(I.is_owned(I.interface_of(out)))


class CompatibilityTests(_Base):

    def test_same_structural_and_mismatches(self):
        _, _, _, out, inp = self.arch()
        a = self.air_data("A")
        b = self.air_data("B")
        I.assign_interface(self.repo, out, a)
        self.assertEqual(I.check_compatibility(out, inp), [])           # empty is compatible
        I.assign_interface(self.repo, inp, a)
        self.assertEqual(I.check_compatibility(out, inp), [])
        I.assign_interface(self.repo, inp, b)
        self.assertEqual(I.check_compatibility(out, inp), [])           # structurally equal
        I.set_fields(self.repo, I.find_element(b, "alt"), {"units": "m"})
        I.set_fields(self.repo, I.find_element(b, "cas"), {"type": "double", "dimensions": "3"})
        I.add_element(self.repo, b, "extra")
        reasons = I.check_compatibility(out, inp)
        joined = " | ".join(reasons)
        for fragment in ("units ft vs m", "type single vs double", "dimensions 1 vs 3", "'extra'"):
            self.assertIn(fragment, joined)

    def test_element_selection_at_connector_ends(self):
        _, _, _, out, inp = self.arch()
        ad = self.air_data()
        vt = I.create_value_type(self.repo, "Alt", units="ft")
        I.assign_interface(self.repo, out, ad)
        I.assign_interface(self.repo, inp, vt)
        self.assertTrue(I.check_compatibility(out, inp))                  # bus vs value type
        self.assertEqual(I.check_compatibility(out, inp, "alt"), [])     # element vs value type
        self.assertTrue(I.check_compatibility(out, inp, "cas"))           # single/kn vs double/ft
        self.assertIn("no element 'nope'", I.check_compatibility(out, inp, "nope")[0])
        conn = I.connect_ports(self.repo, out, inp, source_element="alt")
        self.assertEqual(conn.source_element, "alt")
        self.assertEqual(I.connector_compatibility(conn), [])
        with self.assertRaises(InterfaceError):
            I.set_connector_elements(conn, target_element="x")         # value type has no elements
        I.set_fields(self.repo, I.find_element(ad, "alt"), {"name": "altitude"})
        self.assertEqual(conn.source_element, "altitude")               # rename follows

    def test_connector_owner_and_validator_rule(self):
        sysd, _, _, out, inp = self.arch()
        I.assign_interface(self.repo, out, self.air_data("A"))
        b = self.air_data("B")
        I.assign_interface(self.repo, inp, b)
        conn = I.connect_ports(self.repo, out, inp)
        self.assertIs(conn.owner, sysd)
        self.assertEqual(_issues(self.repo, "interfaces.compatibility"), [])
        I.set_fields(self.repo, I.find_element(b, "valid"), {"type": "uint8"})
        issues = _issues(self.repo, "interfaces.compatibility")
        self.assertEqual(len(issues), 1)
        self.assertIs(issues[0].element, conn)
        self.assertIn("type boolean vs uint8", issues[0].message)

    def test_enum_and_nested_structural_comparison(self):
        for name in ("Mode1", "Mode2"):
            I.create_item(self.repo, "Enumeration", name, literals=[{"name": "OFF"}, {"name": "ON"}])
        I.create_item(self.repo, "DataInterface", "N1", elements=[{"name": "m", "type": "Enum: Mode1"}])
        I.create_item(self.repo, "DataInterface", "N2", elements=[{"name": "m", "type": "Enum: Mode2"}])
        I.create_item(self.repo, "DataInterface", "W1", elements=[{"name": "n", "type": "Bus: N1"}])
        I.create_item(self.repo, "DataInterface", "W2", elements=[{"name": "n", "type": "Bus: N2"}])
        _, _, _, out, inp = self.arch()
        I.assign_interface(self.repo, out, "W1")
        I.assign_interface(self.repo, inp, "W2")
        self.assertEqual(I.check_compatibility(out, inp), [])
        mode2 = I.find_item(self.repo, "Mode2")
        I.add_element(self.repo, mode2, "STBY")
        self.assertIn("element 'n.m'", I.check_compatibility(out, inp)[0])

    def test_physical_domains(self):
        _, _, _, out, inp = self.arch()
        p1 = I.create_item(self.repo, "PhysicalInterface", "Pwr",
                           elements=[{"name": "pos", "domain": "electrical"}])
        p2 = I.create_item(self.repo, "PhysicalInterface", "Pwr2",
                           elements=[{"name": "pos", "domain": "electrical"}])
        I.assign_interface(self.repo, out, p1)
        I.assign_interface(self.repo, inp, p2)
        self.assertEqual(I.check_compatibility(out, inp), [])
        I.set_fields(self.repo, I.find_element(p2, "pos"), {"domain": "hydraulic"})
        self.assertIn("domain electrical vs hydraulic", I.check_compatibility(out, inp)[0])
        with self.assertRaises(InterfaceError):
            I.set_fields(self.repo, I.find_element(p2, "pos"), {"domain": "plasma"})
        I.assign_interface(self.repo, inp, self.air_data())
        self.assertIn("cannot connect", I.check_compatibility(out, inp)[0])

    def test_service_client_server(self):
        _, _, _, out, inp = self.arch()        # out = client, inp = server
        s1 = I.create_item(self.repo, "ServiceInterface", "Nav", elements=[
            {"name": "getPos", "prototype": "[lat, lon] = getPos(t)"}])
        s2 = I.create_item(self.repo, "ServiceInterface", "NavSrv", elements=[
            {"name": "getPos", "prototype": "[lat,lon]=getPos(t)"},
            {"name": "reset", "prototype": "reset()", "asynchronous": True}])
        fn = I.find_element(s1, "getPos")
        self.assertEqual(fn.prototype, "[lat, lon] = getPos(t)")
        self.assertEqual([(a["name"], a["direction"]) for a in fn.arguments],
                         [("t", "in"), ("lat", "out"), ("lon", "out")])
        I.assign_interface(self.repo, out, s1)
        I.assign_interface(self.repo, inp, s2)
        self.assertEqual(I.check_compatibility(out, inp), [])       # server may offer more
        self.assertTrue(I.check_compatibility(inp, out) == [])      # roles come from directions
        I.set_fields(self.repo, I.find_element(s2, "getPos"), {"prototype": "lat = getPos(t)"})
        self.assertIn("prototype", I.check_compatibility(out, inp)[0])
        inp.direction = FeatureDirection.OUT
        self.assertIn("both ports are clients", I.check_compatibility(out, inp)[0])
        with self.assertRaises(InterfaceError):
            I.set_fields(self.repo, fn, {"prototype": "y = other(u)"})
        with self.assertRaises(InterfaceError):
            I.set_fields(self.repo, fn, {"prototype": "not a prototype"})
        I.set_fields(self.repo, fn, {"name": "getPosition"})
        self.assertTrue(fn.prototype.endswith("getPosition(t)"))


class AdapterTests(_Base):

    def test_adapter_mappings_drive_compatibility(self):
        sysd, adiru, fms, out, inp = self.arch()
        src = I.create_item(self.repo, "DataInterface", "Src", elements=[
            {"name": "altitude_ft", "units": "ft"}, {"name": "valid", "type": "boolean"}])
        dst = I.create_item(self.repo, "DataInterface", "Dst", elements=[
            {"name": "alt", "units": "m"}, {"name": "valid", "type": "boolean"}])
        I.assign_interface(self.repo, out, src)
        I.assign_interface(self.repo, inp, dst)
        ad = I.create_adapter(self.repo, sysd, "Conv")
        a_in, a_out = [p for p in ad.owned_elements if isinstance(p, PortUsage)]
        self.assertEqual((a_in.name, a_in.direction, a_out.direction),
                         ("In", FeatureDirection.IN, FeatureDirection.OUT))
        c1 = I.connect_ports(self.repo, out, a_in)
        c2 = I.connect_ports(self.repo, a_out, inp)
        self.assertEqual(I.connector_compatibility(c1), [])
        reasons = I.connector_compatibility(c2)
        self.assertIn("'alt' has no mapping", reasons[0])
        I.set_adapter_mappings(ad, [{"target": "alt", "source": "altitude_ft"}])
        self.assertIn("units ft vs m", " ".join(I.connector_compatibility(c2)))
        I.set_adapter_mappings(ad, [{"target": "alt", "source": "altitude_ft", "note": "x 0.3048"}])
        self.assertEqual(I.connector_compatibility(c2), [])
        I.set_adapter_mappings(ad, [{"target": "alt", "source": "In.nope", "note": "n"}])
        self.assertIn("not in the adapter input", I.connector_compatibility(c2)[0])
        with self.assertRaises(InterfaceError):
            I.set_adapter_mappings(ad, [{"target": "alt"}])
        # renaming a source element follows into the mappings
        I.set_adapter_mappings(ad, [{"target": "alt", "source": "altitude_ft", "note": "x"}])
        I.set_fields(self.repo, I.find_element(src, "altitude_ft"), {"name": "alt_ft"})
        self.assertEqual(ad.mappings[0]["source"], "alt_ft")


class PersistenceTests(_Base):

    def test_full_round_trip(self):
        sysd, adiru, fms, out, inp = self.arch()
        vt = I.create_value_type(self.repo, "Alt", units="ft", minimum=0, maximum=50000,
                                 description="Altitude")
        I.create_item(self.repo, "Enumeration", "Mode", literals=[{"name": "OFF"}, {"name": "ON", "value": 5}],
                      default="ON")
        I.create_item(self.repo, "Constant", "MaxAlt", value="50000", type="int32", units="ft")
        ad = I.create_item(self.repo, "DataInterface", "AD", color="#00aa00", elements=[
            {"name": "a", "type": "ValueType: Alt"}, {"name": "m", "type": "Enum: Mode"},
            {"name": "v", "type": "uint8", "dimensions": "[2 3]", "complexity": "complex"}])
        I.move_element(I.find_element(ad, "v"), index=0)
        I.create_item(self.repo, "PhysicalInterface", "Pw", elements=[{"name": "p", "domain": "thermal"}])
        I.create_item(self.repo, "ServiceInterface", "Sv",
                      elements=[{"name": "f", "prototype": "y = f(u)", "asynchronous": True}])
        I.assign_interface(self.repo, out, ad)
        I.assign_interface(self.repo, inp, ad)
        own = I.assign_interface(self.repo, inp, "owned")
        conn = I.connect_ports(self.repo, out, inp, source_element="a", target_element="a")
        adapter = I.create_adapter(self.repo, sysd, "Ad1")
        I.set_adapter_mappings(adapter, [{"target": "x", "source": "y", "note": "n"}])
        text = to_json(self.repo)
        r2 = from_json(text)
        text2 = to_json(r2)
        self.assertEqual(to_json(from_json(text2)), text2)          # load/save is stable
        self.assertEqual(sorted(json.loads(text2)["elements"], key=lambda r: r["id"]),
                         sorted(json.loads(text)["elements"], key=lambda r: r["id"]))
        ad2 = r2.resolve("Interfaces::AD")
        self.assertEqual([e.name for e in I.elements_of(ad2)], ["v", "a", "m"])
        self.assertEqual(ad2.color, "#00aa00")
        v = I.describe_element(I.find_element(ad2, "v"))
        self.assertEqual((v["type"], v["dimensions"], v["complexity"]), ("uint8", "[2 3]", "complex"))
        self.assertEqual(I.describe_type(I.find_element(ad2, "a")), "ValueType: Alt")
        self.assertEqual(I.describe_type(I.find_element(ad2, "m")), "Enum: Mode")
        self.assertEqual(I.find_element(ad2, "v").types[0].name, "Natural")
        vt2 = r2.resolve("Interfaces::Alt")
        self.assertEqual((vt2.units, vt2.maximum, I._doc(vt2)), ("ft", 50000, "Altitude"))
        mode = r2.resolve("Interfaces::Mode")
        self.assertEqual([(c.name, c.default_value) for c in I.elements_of(mode)], [("OFF", 0), ("ON", 5)])
        self.assertEqual(I.describe_item(mode)["default"], "ON")
        c2 = r2.resolve("Interfaces::MaxAlt")
        self.assertEqual((c2.value, c2.primitive_type, c2.units), ("50000", "int32", "ft"))
        self.assertEqual(r2.resolve("Interfaces::Pw::p").domain, "thermal")
        f = r2.resolve("Interfaces::Sv::f")
        self.assertEqual((f.prototype, f.asynchronous, len(f.arguments)), ("y = f(u)", True, 2))
        out2 = r2.resolve("Sys::adiru::out")
        inp2 = r2.resolve("Sys::fms::inp")
        self.assertIs(I.interface_of(out2), ad2)
        self.assertTrue(I.is_owned(I.interface_of(inp2)))
        conn2 = next(e for e in r2.root_package.walk() if isinstance(e, ConnectionUsage))
        self.assertEqual((conn2.source_element, conn2.target_element), ("a", "a"))
        self.assertEqual(r2.resolve("Sys::Ad1").mappings, [{"target": "x", "source": "y", "note": "n"}])
        self.assertEqual([i for i in _issues(r2) if i.rule != "interfaces.compatibility"], [])
        self.assertEqual(own.name, I.interface_of(inp2).name)


class DictionaryExchangeTests(_Base):

    def _exported(self):
        src = Repository("Src")
        I.create_value_type(src, "Alt", units="ft")
        I.create_item(src, "DataInterface", "AirData", elements=[
            {"name": "alt", "type": "ValueType: Alt"}, {"name": "ok", "type": "boolean"}])
        I.create_item(src, "DataInterface", "Wrap", elements=[{"name": "ad", "type": "Bus: AirData"}])
        return json.loads(json.dumps(I.export_dictionary(src)))

    def test_export_import_into_empty_project(self):
        data = self._exported()
        self.assertEqual(data["format"], I.EXPORT_FORMAT)
        self.assertEqual([i["name"] for i in data["items"]], ["Alt", "AirData", "Wrap"])
        report = I.import_dictionary(self.repo, data)
        self.assertEqual(report["added"], ["Alt", "AirData", "Wrap"])
        wrap = I.find_item(self.repo, "Wrap")
        self.assertEqual(I.element_paths(wrap), ["ad", "ad.alt", "ad.ok"])
        self.assertEqual(I.describe_type(I.find_element(wrap, "ad.alt")), "ValueType: Alt")

    def test_collisions_keep_replace_rename(self):
        data = self._exported()
        mine = I.create_item(self.repo, "DataInterface", "AirData", elements=[{"name": "local"}])
        _, _, _, out, _ = self.arch()
        I.assign_interface(self.repo, out, mine)
        preview = I.import_dictionary(self.repo, data, dry_run=True)
        self.assertEqual([c["name"] for c in preview["collisions"]], ["AirData"])
        self.assertEqual(preview["collisions"][0]["suggested_rename"], "AirData_1")
        with self.assertRaises(InterfaceError) as cm:
            I.import_dictionary(self.repo, data)
        self.assertEqual(cm.exception.status, 409)
        self.assertIsNone(I.find_item(self.repo, "Alt"))           # nothing imported

        report = I.import_dictionary(self.repo, data, resolution={"AirData": "keep"})
        self.assertEqual(report["kept"], ["AirData"])
        wrap = I.find_item(self.repo, "Wrap")
        self.assertIs(I._model_type(I.find_element(wrap, "ad")), mine)   # points at the kept one

        report = I.import_dictionary(self.repo, data, default="rename")
        self.assertEqual(report["renamed"], {"Alt": "Alt_1", "AirData": "AirData_1", "Wrap": "Wrap_1"})
        wrap1 = I.find_item(self.repo, "Wrap_1")
        self.assertEqual(I._model_type(I.find_element(wrap1, "ad")).name, "AirData_1")

        report = I.import_dictionary(self.repo, data, default="replace")
        self.assertIn("AirData", report["replaced"])
        self.assertIs(I.find_item(self.repo, "AirData"), mine)               # identity kept
        self.assertEqual([e.name for e in I.elements_of(mine)], ["alt", "ok"])
        self.assertIs(I.interface_of(out), mine)                              # port still assigned

    def test_import_rejects_bad_documents(self):
        for bad, fragment in (("not json", "not valid JSON"),
                              ({"items": "x"}, "'items' list"),
                              ({"format": "other/9", "items": []}, "Unsupported"),
                              ({"items": [{"kind": "Gizmo", "name": "A"}]}, "Unknown interface kind"),
                              ({"items": [{"kind": "DataInterface", "name": "A"},
                                          {"kind": "ValueType", "name": "A"}]}, "twice"),
                              ({"items": [{"kind": "DataInterface", "name": "A",
                                           "elements": [{"name": "x", "type": "ValueType: Nope"}]}]},
                               "not found")):
            with self.subTest(bad=bad):
                with self.assertRaises(InterfaceError) as cm:
                    I.import_dictionary(self.repo, bad)
                self.assertIn(fragment, str(cm.exception))
        self.assertIsNone(I.find_item(self.repo, "A"))

    def test_templates(self):
        a429 = I.create_from_template(self.repo, "arinc429")
        self.assertEqual(a429.name, "A429Word")
        self.assertEqual([e.name for e in I.elements_of(a429)], ["label", "sdi", "data", "ssm", "parity"])
        again = I.create_from_template(self.repo, "arinc429")
        self.assertEqual(again.name, "A429Word_1")
        pwr = I.create_from_template(self.repo, "power28vdc", "MainBus")
        self.assertIsInstance(pwr, I.PhysicalInterface)
        with self.assertRaises(InterfaceError):
            I.create_from_template(self.repo, "nope")
        self.assertEqual([i for i in _issues(self.repo)], [])
        self.assertEqual([str(i) for i in Validator().validate(self.repo)
                          if i.rule in ("feature.typed", "usage.typing")], [])


class SummaryTests(_Base):

    def test_port_badge_style_and_categories(self):
        _, _, _, out, inp = self.arch()
        ad = self.air_data()
        I.assign_interface(self.repo, out, ad)
        d = {"badges": [], "style": {}}
        I.summary_fields(out, d)
        self.assertEqual(d["badges"], ["AirData"])
        self.assertEqual(d["style"]["stroke"], ad.color)
        self.assertEqual(d["interface"]["name"], "AirData")
        d = {}
        I.summary_fields(ad, d)
        self.assertEqual((d["interface_category"], d["interface_kind"]), ("Interface", "DataInterface"))
        d = {}
        I.summary_fields(I.find_element(ad, "alt"), d)
        self.assertEqual((d["interface_category"], d["type"], d["units"]), ("InterfaceElement", "double", "ft"))
        I.assign_interface(self.repo, inp, ad)
        I.assign_interface(self.repo, inp, "owned")            # owned copy of AirData
        I.set_fields(self.repo, I.find_element(I.interface_of(inp), "alt"), {"units": "m"})
        conn = I.connect_ports(self.repo, out, inp)
        d = {"badges": [], "style": {}}
        I.summary_fields(conn, d)
        self.assertFalse(d["compatibility"]["compatible"])
        self.assertIn("incompatible", d["badges"])


if __name__ == "__main__":
    unittest.main()
