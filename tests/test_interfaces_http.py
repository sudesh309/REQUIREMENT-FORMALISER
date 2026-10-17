"""HTTP tests for the interface editor API (webapp/routes/interfaces.py)."""
import json
import unittest

from engine import interfaces as I
from tests.webapp_harness import WebAppTestCase


class InterfacesHttpTests(WebAppTestCase):

    def setUp(self):
        I.install()
        self.call("POST", "/api/new", {"name": "Avionics"})

    # -- helpers ---------------------------------------------------------
    def elem(self, kind, name, parent=None, **props):
        body = {"kind": kind, "name": name, "parent": parent}
        if props:
            body["properties"] = props
        return self.call("POST", "/api/element", body)

    def arch(self):
        sysd = self.elem("PartDefinition", "Aircraft")
        adiru = self.elem("PartUsage", "ADIRU", sysd["id"])
        fms = self.elem("PartUsage", "FMS", sysd["id"])
        out = self.elem("PortUsage", "AirDataOut", adiru["id"], direction="out")
        inp = self.elem("PortUsage", "AirDataIn", fms["id"], direction="in")
        return sysd, adiru, fms, out, inp

    def air_data(self, name="AirData"):
        return self.call("POST", "/api/interfaces", {"kind": "DataInterface", "name": name, "elements": [
            {"name": "altitude", "type": "double", "units": "ft"},
            {"name": "airspeed", "type": "double", "units": "kn"},
            {"name": "valid", "type": "boolean"}]})

    # -- tests -------------------------------------------------------------
    def test_listing_and_metadata(self):
        listing = self.call("GET", "/api/interfaces")
        self.assertIsNone(listing["dictionary"])
        meta = listing["meta"]
        self.assertIn("uint32", meta["primitive_types"])
        self.assertIn("electrical", [d["id"] for d in meta["physical_domains"]])
        self.assertIn("arinc429", [t["id"] for t in meta["templates"]])
        self.air_data()
        listing = self.call("GET", "/api/interfaces")
        self.assertEqual(listing["dictionary"]["name"], "Interfaces")
        self.assertEqual([(i["name"], i["kind"], i["element_count"]) for i in listing["items"]],
                         [("AirData", "DataInterface", 3)])

    def test_item_and_element_crud(self):
        ad = self.air_data()
        vt = self.call("POST", "/api/interfaces", {"kind": "ValueType", "name": "Altitude",
                                                   "units": "ft", "minimum": -1000, "maximum": 60000})
        self.assertEqual((vt["kind"], vt["units"], vt["maximum"]), ("ValueType", "ft", 60000))
        r = self.call("POST", f"/api/interfaces/item/{ad['id']}/elements", {"name": "heading", "units": "deg",
                                                                            "index": 0})
        self.assertEqual([e["name"] for e in r["interface"]["elements"]],
                         ["heading", "altitude", "airspeed", "valid"])
        r = self.call("PATCH", f"/api/interfaces/item/{ad['id']}/elements/altitude",
                      {"type": "ValueType: Altitude", "description": "Baro altitude"})
        self.assertEqual(r["element"]["type"], "ValueType: Altitude")
        self.assertEqual(r["element"]["effective"]["units"], "ft")
        r = self.call("PATCH", f"/api/interfaces/item/{ad['id']}/elements/heading", {"units": "furlongs"})
        self.assertIn("furlongs", r["warnings"][0])
        r = self.call("POST", f"/api/interfaces/item/{ad['id']}/elements/valid/move", {"delta": -3})
        self.assertEqual(r["index"], 0)
        r = self.call("PATCH", f"/api/interfaces/item/{ad['id']}/elements/valid", {"name": "isValid"})
        self.assertEqual(r["interface"]["elements"][0]["name"], "isValid")
        r = self.call("DELETE", f"/api/interfaces/item/{ad['id']}/elements/heading")
        self.assertEqual([e["name"] for e in r["interface"]["elements"]], ["isValid", "altitude", "airspeed"])
        r = self.call("PATCH", f"/api/interfaces/item/{ad['id']}", {"name": "AirDataBus", "color": "#aa0000",
                                                                   "description": "ADIRU output"})
        self.assertEqual((r["name"], r["color"], r["description"]), ("AirDataBus", "#aa0000", "ADIRU output"))
        detail = self.call("GET", "/api/interfaces/item/Interfaces::AirDataBus")
        self.assertEqual(detail["id"], ad["id"])
        self.call("DELETE", f"/api/interfaces/item/{ad['id']}")
        self.call("GET", f"/api/interfaces/item/{ad['id']}", expect=404)

    def test_clear_errors(self):
        ad = self.air_data()
        base = f"/api/interfaces/item/{ad['id']}"
        cases = [
            ("POST", "/api/interfaces", {"kind": "Gizmo"}, 400, "Unknown interface kind"),
            ("POST", "/api/interfaces", {"kind": "DataInterface", "name": "AirData"}, 409, "already exists"),
            ("POST", "/api/interfaces", {"kind": "DataInterface", "name": "bad name"}, 400, "not valid"),
            ("PATCH", f"{base}/elements/altitude", {"dimensions": "[0 3]"}, 400, "Invalid dimensions"),
            ("PATCH", f"{base}/elements/altitude", {"minimum": 10, "maximum": 1}, 400, "must not exceed"),
            ("PATCH", f"{base}/elements/altitude", {"type": "Bus: Nope"}, 404, "not found"),
            ("PATCH", f"{base}/elements/altitude", {"type": "Bus: AirData"}, 400, "cycle"),
            ("PATCH", f"{base}/elements/altitude", {"name": "airspeed"}, 409, "already exists"),
            ("PATCH", f"{base}/elements/nope", {"units": "m"}, 404, "no element"),
            ("POST", f"{base}/elements/altitude/move", {}, 400, "delta"),
            ("GET", "/api/interfaces/item/missing", None, 404, "not found"),
            ("GET", "/api/interfaces/compatibility", None, 400, "source"),
            ("POST", "/api/interfaces/assign", {"port": "nope", "interface": None}, 404, "not found"),
        ]
        for method, path, body, status, fragment in cases:
            with self.subTest(path=path, body=body):
                r = self.call(method, path, body, expect=status)
                self.assertIn(fragment, r["error"])

    def test_assign_badges_compatibility_and_validate(self):
        sysd, _, _, out, inp = self.arch()
        ad = self.air_data()
        r = self.call("POST", "/api/interfaces/assign", {"port": out["id"], "interface": ad["id"]})
        self.assertEqual(r["interface"]["name"], "AirData")
        self.call("POST", "/api/interfaces/assign", {"port": inp["id"], "interface": "AirData"})
        port = self.call("GET", f"/api/element/{out['id']}")
        self.assertIn("AirData", port["badges"])
        self.assertEqual(port["style"]["stroke"], ad["color"])
        self.assertEqual(port["interface"]["name"], "AirData")
        detail = self.call("GET", f"/api/interfaces/item/{ad['id']}")
        self.assertEqual(sorted(p["name"] for p in detail["ports"]), ["AirDataIn", "AirDataOut"])

        r = self.call("GET", f"/api/interfaces/compatibility?source={out['id']}&target={inp['id']}")
        self.assertTrue(r["compatible"])
        self.assertEqual(r["source"]["element_paths"], ["altitude", "airspeed", "valid"])
        c = self.call("POST", "/api/interfaces/connect", {"source": out["id"], "target": inp["id"]})
        self.assertTrue(c["compatible"])
        conn_id = c["connector"]["id"]
        conn = self.call("GET", f"/api/element/{conn_id}")
        self.assertEqual(conn["owner_id"], sysd["id"])
        self.assertTrue(conn["compatibility"]["compatible"])

        # owned copy on the target, then change one element type -> incompatible
        r = self.call("POST", "/api/interfaces/make-owned", {"port": inp["id"]})
        owned = r["interface"]
        self.assertTrue(owned["owned"])
        self.call("PATCH", f"/api/interfaces/item/{owned['id']}/elements/valid", {"type": "uint8"})
        r = self.call("GET", f"/api/interfaces/compatibility?connector={conn_id}")
        self.assertFalse(r["compatible"])
        self.assertIn("type boolean vs uint8", r["reasons"][0])
        v = self.call("GET", "/api/validate")
        issues = [i for i in v["issues"] if i["rule"] == "interfaces.compatibility"]
        self.assertEqual(len(issues), 1)
        self.assertIn("type boolean vs uint8", issues[0]["message"])
        conn = self.call("GET", f"/api/element/{conn_id}")
        self.assertIn("incompatible", conn["badges"])
        self.assertEqual(conn["style"]["stroke"], "#dc2626")

        # save the owned interface to the dictionary: collision -> rename
        r = self.call("POST", "/api/interfaces/make-shared", {"port": inp["id"], "name": "AirData"}, expect=409)
        self.assertIn("keep, replace or rename", r["error"])
        r = self.call("POST", "/api/interfaces/make-shared",
                      {"port": inp["id"], "name": "AirData", "on_conflict": "rename"})
        self.assertEqual(r["interface"]["name"], "AirData_1")
        self.assertFalse(r["interface"]["owned"])

    def test_element_selection_on_connector(self):
        _, _, _, out, inp = self.arch()
        ad = self.air_data()
        self.call("POST", "/api/interfaces", {"kind": "ValueType", "name": "Alt", "units": "ft"})
        self.call("POST", "/api/interfaces/assign", {"port": out["id"], "interface": ad["id"]})
        self.call("POST", "/api/interfaces/assign", {"port": inp["id"], "interface": "Alt"})
        c = self.call("POST", "/api/interfaces/connect", {"source": out["id"], "target": inp["id"]})
        self.assertFalse(c["compatible"])
        r = self.call("POST", "/api/interfaces/connector-elements",
                      {"connector": c["connector"]["id"], "source_element": "altitude"})
        self.assertTrue(r["compatible"])
        self.assertEqual(r["source"]["element"], "altitude")
        r = self.call("PATCH", f"/api/element/{c['connector']['id']}",
                      {"props": {"source_element": "nope"}}, expect=400)
        self.assertIn("no element 'nope'", r["error"])
        cands = self.call("GET", f"/api/interfaces/candidates/{out['id']}")
        self.assertEqual([x["qualified_name"].split("::")[-1] for x in cands["candidates"]], ["AirDataIn"])

    def test_generic_element_api_goes_through_validation(self):
        ad = self.air_data()
        el = self.elem("DataElement", "mach", ad["id"])
        self.assertEqual(el["type"], "double")
        self.assertEqual(el["interface_category"], "InterfaceElement")
        r = self.call("PATCH", f"/api/element/{el['id']}", {"props": {"dimensions": "x"}}, expect=400)
        self.assertIn("Invalid dimensions", r["error"])
        r = self.call("PATCH", f"/api/element/{el['id']}", {"props": {"units": "Mach", "typed_by": "single"}})
        self.assertEqual((r["units"], r["type"]), ("Mach", "single"))
        r = self.call("PATCH", f"/api/element/{el['id']}", {"props": {"typed_by": r["typed_by"][0]}})
        self.assertEqual(r["type"], "single")                 # core form round trip is a no-op
        self.call("PATCH", f"/api/element/{el['id']}", {"props": {"name": "altitude"}}, expect=400)
        sysd, _, _, out, _ = self.arch()
        r = self.call("PATCH", f"/api/element/{out['id']}", {"props": {"typed_by": "Interfaces::AirData"}})
        self.assertEqual(r["interface"]["name"], "AirData")
        r = self.call("PATCH", f"/api/element/{out['id']}", {"props": {"typed_by": "owned"}})
        self.assertTrue(r["interface"]["owned"])
        self.assertIn("owned", r["badges"])

    def test_dictionary_export_import_round_trip(self):
        self.air_data()
        self.call("POST", "/api/interfaces", {"template": "arinc429"})
        exported = self.call("GET", "/api/interfaces/dictionary/export")
        self.assertEqual(exported["filename"], "Interfaces.json")
        text = exported["text"]
        self.assertEqual(json.loads(text)["format"], I.EXPORT_FORMAT)
        # fresh project: import adds everything
        self.call("POST", "/api/new", {"name": "Other"})
        r = self.call("POST", "/api/interfaces/dictionary/import", {"text": text})
        self.assertEqual(sorted(r["added"]), ["A429Word", "AirData"])
        # again: dry run shows collisions, then per-item choices
        r = self.call("POST", "/api/interfaces/dictionary/import", {"text": text, "dry_run": True})
        self.assertEqual(sorted(c["name"] for c in r["collisions"]), ["A429Word", "AirData"])
        r = self.call("POST", "/api/interfaces/dictionary/import", {"text": text}, expect=409)
        self.assertIn("choose keep, replace or rename", r["error"])
        r = self.call("POST", "/api/interfaces/dictionary/import",
                      {"text": text, "resolution": {"AirData": "rename", "A429Word": "keep"}})
        self.assertEqual((r["renamed"], r["kept"]), ({"AirData": "AirData_1"}, ["A429Word"]))
        r = self.call("POST", "/api/interfaces/dictionary/import", {"text": "{bad"}, expect=400)
        self.assertIn("not valid JSON", r["error"])

    def test_adapter_endpoints(self):
        sysd, _, _, out, inp = self.arch()
        self.call("POST", "/api/interfaces", {"kind": "DataInterface", "name": "Src",
                                              "elements": [{"name": "alt_ft", "units": "ft"}]})
        self.call("POST", "/api/interfaces", {"kind": "DataInterface", "name": "Dst",
                                              "elements": [{"name": "alt_m", "units": "m"}]})
        self.call("POST", "/api/interfaces/assign", {"port": out["id"], "interface": "Src"})
        self.call("POST", "/api/interfaces/assign", {"port": inp["id"], "interface": "Dst"})
        a = self.call("POST", "/api/interfaces/adapter", {"parent": sysd["id"], "name": "UnitConv"})
        adapter = self.call("GET", f"/api/element/{a['id']}")
        self.assertEqual(adapter["kind"], "Adapter")
        self.assertIn("Adapter", adapter["badges"])
        tree = self.call("GET", "/api/tree")
        aircraft = next(c for c in tree["children"] if c["name"] == "Aircraft")
        node = next(c for c in aircraft["children"] if c["name"] == "UnitConv")
        a_in, a_out = [c["id"] for c in node["children"]]
        self.call("POST", "/api/interfaces/connect", {"source": out["id"], "target": a_in})
        c = self.call("POST", "/api/interfaces/connect", {"source": a_out, "target": inp["id"]})
        self.assertFalse(c["compatible"])
        info = self.call("GET", f"/api/interfaces/adapter/{a['id']}")
        self.assertEqual((info["source_paths"], info["target_paths"]), (["alt_ft"], ["alt_m"]))
        r = self.call("PATCH", f"/api/interfaces/adapter/{a['id']}",
                      {"mappings": [{"target": "alt_m", "source": "alt_ft", "note": "ft * 0.3048"}]})
        self.assertEqual(len(r["mappings"]), 1)
        r = self.call("GET", f"/api/interfaces/compatibility?connector={c['connector']['id']}")
        self.assertTrue(r["compatible"])
        self.call("PATCH", f"/api/interfaces/adapter/{a['id']}", {"mappings": "x"}, expect=400)

    def test_project_save_load_keeps_interfaces(self):
        _, _, _, out, inp = self.arch()
        self.air_data()
        self.call("POST", "/api/interfaces/assign", {"port": out["id"], "interface": "AirData"})
        self.call("POST", "/api/interfaces/assign", {"port": inp["id"], "interface": "owned"})
        text = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/new", {"name": "Empty"})
        self.call("POST", "/api/load", {"text": text})
        listing = self.call("GET", "/api/interfaces")
        self.assertEqual([i["name"] for i in listing["items"]], ["AirData"])
        self.assertEqual(len(listing["owned"]), 1)
        port = self.call("GET", f"/api/element/{out['id']}")
        self.assertEqual(port["interface"]["name"], "AirData")


if __name__ == "__main__":
    unittest.main()
