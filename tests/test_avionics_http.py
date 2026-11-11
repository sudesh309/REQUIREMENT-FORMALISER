"""HTTP API of the avionics pack (webapp/routes/avionics.py)."""
from __future__ import annotations

import urllib.request

from tests.webapp_harness import WebAppTestCase


class AvionicsHttpTests(WebAppTestCase):

    def send(self, method, path, body=None, expect=200):
        return self.call(method, path, body, expect=expect)

    def undo_label(self):
        return self.call("GET", "/api/undo/state")["undo_label"]

    def blank(self, name="Av"):
        return self.call("POST", "/api/new/avionics", {"template": "blank", "name": name})

    def example(self):
        return self.call("POST", "/api/new/avionics", {"template": "ima_example"})

    def element(self, qname):
        return self.call("GET", f"/api/element/{urllib.request.quote(qname, safe='')}")

    # --- templates -------------------------------------------------------------------------
    def test_templates(self):
        ts = self.call("GET", "/api/avionics/templates")["templates"]
        self.assertEqual([t["id"] for t in ts], ["blank", "ima_example"])
        self.assertTrue(all(t["name"] and t["description"] and t["includes"] for t in ts))
        counted = self.call("GET", "/api/avionics/templates?counts=1")["templates"]
        self.assertEqual(counted[1]["counts"]["fha_rows"], 21)

    def test_blank_project(self):
        self.call("POST", "/api/new", {"name": "Old"})
        self.call("POST", "/api/element", {"kind": "Package", "name": "Scratch"})
        res = self.blank("MyAircraft")
        self.assertEqual(res["name"], "MyAircraft")
        self.assertEqual([a["name"] for a in res["architectures"]], ["SystemArchitecture"])
        self.assertEqual(res["open"], res["architectures"][0]["id"])
        # Like New: the project is replaced and the undo history starts afresh.
        undo = self.call("GET", "/api/undo/state")
        self.assertFalse(undo["can_undo"])
        self.assertFalse(undo["dirty"])
        self.assertEqual(self.call("GET", "/api/state")["name"], "MyAircraft")
        names = {c["name"] for c in self.call("GET", "/api/tree")["children"]}
        self.assertTrue({"Avionics", "Interfaces", "SystemArchitecture", "FHA", "SystemRequirements",
                         "SoftwareLowLevelRequirements"} <= names, names)
        self.assertNotIn("Scratch", names)
        info = self.call("GET", "/api/avionics/info")
        self.assertTrue(info["profile"]["present"])
        self.assertEqual(info["interfaces"], {"present": 37, "total": 37})
        self.assertEqual(len(info["requirement_sets"]), 4)
        self.assertEqual(info["fha"]["rows"], 0)

    def test_example_project_opens_and_checks(self):
        res = self.example()
        self.assertEqual(res["name"], "IMA_Avionics")
        self.assertEqual({a["name"] for a in res["architectures"]},
                         {"FunctionalArchitecture", "LogicalArchitecture", "PhysicalArchitecture"})
        view = self.call("GET", f"/api/arch/view/{res['open']}")
        self.assertEqual(view["composition"]["name"], "PhysicalArchitecture")
        self.assertEqual(len(view["components"]), 24)
        self.assertEqual(len(view["connectors"]), 73)
        check = self.call("GET", "/api/interop/check")
        self.assertEqual(check["counts"]["error"], 0)
        titles = {r["id"]: r["title"] for r in check["rules"]}
        self.assertEqual(titles["avionics.dal.allocation"], "Function allocated below its FHA DAL")
        self.assertEqual(self.call("GET", "/api/validate")["errors"], 0)
        info = self.call("GET", "/api/avionics/info")
        phys = next(e for e in info["equipment"] if e["name"] == "PhysicalArchitecture")
        self.assertGreater(phys["mass_kg"], 100)
        self.assertEqual(info["safety"]["counts"]["error"], 0)
        self.assertEqual(info["fha"]["rows"], 21)

    def test_unknown_template_and_bad_name(self):
        self.call("POST", "/api/new/avionics", {"template": "nope"}, expect=400)
        self.call("POST", "/api/new/avionics", {"template": "blank", "name": "a::b"}, expect=400)

    # --- profile and libraries -------------------------------------------------------------
    def test_profile(self):
        self.call("POST", "/api/new", {"name": "P"})
        self.assertFalse(self.call("GET", "/api/avionics/profile")["present"])
        res = self.call("POST", "/api/avionics/profile")
        self.assertTrue(res["created"] and res["present"])
        self.assertEqual(len(res["stereotypes"]), 16)
        self.assertEqual(self.undo_label(), "Add the Avionics profile")
        again = self.call("POST", "/api/avionics/profile")
        self.assertFalse(again["created"])
        self.assertEqual(again["added"], 0)

    def test_interface_library(self):
        self.call("POST", "/api/new", {"name": "L"})
        lib = self.call("GET", "/api/avionics/interfaces/library")
        self.assertEqual((lib["present"], lib["count"]), (0, 37))
        self.assertIn("ICD", lib["warning"])
        res = self.call("POST", "/api/avionics/interfaces/import", {"names": ["A429AirData"]})
        self.assertIn("A429AirData", res["created"])
        self.assertEqual(self.undo_label(), "Import A429AirData (6 items)")
        res = self.call("POST", "/api/avionics/interfaces/import", {"groups": ["a664", "m1553"]})
        self.assertEqual(sorted(res["created"]), ["A664Message", "BusSelect", "M1553BMessage", "NetworkId"])
        res = self.call("POST", "/api/avionics/interfaces/import", {})
        self.assertEqual(len(res["created"]) + len(res["skipped"]), 37)
        self.assertEqual(self.undo_label(), "Import the avionics interface library (27 items)")
        self.assertEqual(self.call("POST", "/api/avionics/interfaces/import", {})["created"], [])
        self.call("POST", "/api/avionics/interfaces/import", {"names": ["Nope"]}, expect=404)
        self.call("POST", "/api/avionics/interfaces/import", {"on_conflict": "boom"}, expect=400)
        # Undo takes the whole import back in one step.
        self.call("POST", "/api/undo")
        items = self.call("GET", "/api/interfaces")["items"]
        self.assertEqual(len(items), 10)
        # An interface from the library can be assigned to a port like any other.
        arch = self.call("POST", "/api/arch/architecture", {"name": "S"})
        comp = self.call("POST", "/api/arch/component", {"composition": arch["id"], "name": "ADC"})
        port = self.call("POST", "/api/arch/port", {"owner": comp["id"], "name": "air", "direction": "out",
                                                    "interface": "Interfaces::A429AirData"})
        self.assertEqual(port["interface"]["name"], "A429AirData")

    def test_requirement_library(self):
        self.call("POST", "/api/new", {"name": "R"})
        lib = self.call("GET", "/api/avionics/requirements/library")
        self.assertEqual([s["key"] for s in lib["sets"]], ["arp4754a-system", "arp4754a-item", "do178c-hlr",
                                                           "do178c-llr"])
        self.assertTrue(all(not s["present"] for s in lib["sets"]))
        self.assertEqual(sorted(lib["guidance"]), ["A", "B", "C", "D", "E"])
        res = self.call("POST", "/api/avionics/requirements/import", {"sets": ["do178c-hlr"], "dal": "B"})
        self.assertEqual(res["sets"][0]["name"], "SoftwareHighLevelRequirements")
        self.assertEqual(self.undo_label(), "Import requirement sets SoftwareHighLevelRequirements")
        table = self.call("GET", f"/api/req/table?set={res['sets'][0]['id']}")
        self.assertEqual(len(table["rows"]), res["requirements"])
        lib = self.call("GET", "/api/avionics/requirements/library")
        self.assertTrue(next(s for s in lib["sets"] if s["key"] == "do178c-hlr")["present"])
        self.call("POST", "/api/avionics/requirements/import", {"sets": ["nope"]}, expect=400)
        self.call("POST", "/api/avionics/requirements/import", {"dal": "Z"}, expect=400)

    # --- FHA ------------------------------------------------------------------------------
    def test_fha_crud_labels_and_undo(self):
        self.blank()
        arch = self.call("POST", "/api/arch/architecture", {"name": "Functions"})
        fn = self.call("POST", "/api/arch/component", {"composition": arch["id"], "name": "ProvideAirData"})
        view = self.call("GET", "/api/avionics/fha")
        self.assertEqual(view["rows"], [])
        self.assertEqual(view["classifications"], ["Catastrophic", "Hazardous", "Major", "Minor",
                                                   "No Safety Effect"])
        self.assertEqual(view["dal_by_classification"]["Hazardous"], "B")
        self.assertIn("Cruise", view["phases"])
        row = self.call("POST", "/api/avionics/fha", {
            "failure_condition": "Total loss of air data", "function": fn["id"], "flight_phase": "Cruise,Climb",
            "effect": "Loss of airspeed", "classification": "Hazardous"})
        self.assertEqual((row["fha_id"], row["dal"], row["flight_phase"]), ("FHA-1", "B", "Climb,Cruise"))
        self.assertEqual(self.undo_label(), "Add FHA row FHA-1")
        self.assertEqual(row["function"]["name"], "ProvideAirData")
        self.assertFalse(row["allocated"])
        upd = self.call("PATCH", f"/api/avionics/fha/{row['id']}", {"classification": "Catastrophic"})
        self.assertEqual(upd["dal"], "A")
        self.assertEqual(self.undo_label(), "Set classification of FHA-1 to Catastrophic")
        self.call("PATCH", "/api/avionics/fha/FHA-1", {"function": None})
        self.assertEqual(self.undo_label(), "Clear the function of FHA-1")
        self.call("PATCH", "/api/avionics/fha/FHA-1", {"failure_condition": "Loss of all air data"})
        self.assertEqual(self.undo_label(), "Edit the failure condition of FHA-1")
        self.call("PATCH", "/api/avionics/fha/FHA-1", {"effect": "e", "flight_phase": "All"})
        self.assertEqual(self.undo_label(), "Edit FHA row FHA-1 effect, flight phase")
        self.assertEqual(self.call("GET", "/api/avionics/fha")["rows"][0]["failure_condition"],
                         "Loss of all air data")
        # Undo / redo walk back through the edits.
        self.call("POST", "/api/undo")
        self.call("POST", "/api/undo")
        self.assertEqual(self.call("GET", "/api/avionics/fha")["rows"][0]["failure_condition"],
                         "Total loss of air data")
        self.call("POST", "/api/redo")
        self.assertEqual(self.call("GET", "/api/avionics/fha")["rows"][0]["failure_condition"],
                         "Loss of all air data")
        self.call("DELETE", "/api/avionics/fha/FHA-1")
        self.assertEqual(self.undo_label(), "Delete FHA row FHA-1")
        self.assertEqual(self.call("GET", "/api/avionics/fha")["rows"], [])
        self.call("POST", "/api/undo")
        self.assertEqual(len(self.call("GET", "/api/avionics/fha")["rows"]), 1)
        self.assertEqual(self.call("GET", "/api/avionics/fha")["functions"][0]["name"], "ProvideAirData")

    def test_fha_errors(self):
        self.blank()
        self.call("POST", "/api/avionics/fha", {"failure_condition": ""}, expect=400)
        self.call("POST", "/api/avionics/fha", {"failure_condition": "x", "classification": "bad"}, expect=400)
        self.call("POST", "/api/avionics/fha", {"failure_condition": "x", "flight_phase": "Orbit"}, expect=400)
        self.call("POST", "/api/avionics/fha", {"failure_condition": "x", "function": "Nope"}, expect=404)
        self.call("POST", "/api/avionics/fha", {"failure_condition": "x"})
        self.call("POST", "/api/avionics/fha", {"failure_condition": "y", "fha_id": "FHA-1"}, expect=409)
        self.call("PATCH", "/api/avionics/fha/FHA-9", {"effect": "x"}, expect=404)
        self.call("DELETE", "/api/avionics/fha/FHA-9", expect=404)
        self.assertEqual(len(self.call("GET", "/api/avionics/fha")["rows"]), 1)

    def test_fha_row_through_the_generic_element_api(self):
        self.example()
        row = self.element("IMA_Avionics::FHA::FHA-1")
        self.assertEqual(row["kind"], "FhaEntry")
        self.assertEqual(row["fha"]["classification"], "Hazardous")
        self.assertIn("Hazardous", row["badges"])
        self.assertIn("DAL B", row["badges"])
        self.call("PATCH", f"/api/element/{row['id']}", {"props": {"classification": "Major"}})
        self.assertEqual(self.element("IMA_Avionics::FHA::FHA-1")["fha"]["dal"], "C")
        self.call("PATCH", f"/api/element/{row['id']}", {"props": {"classification": "Bogus"}}, expect=400)

    # --- safety ---------------------------------------------------------------------------
    def test_safety_check_and_a_dal_edit_makes_rules_fire(self):
        self.example()
        base = self.call("GET", "/api/avionics/safety")
        self.assertEqual(base["counts"]["error"], 0)
        fcc = self.element("IMA_Avionics::Equipment::FlightControlComputer")
        self.assertIn("DAL A", fcc["badges"])
        self.call("PATCH", f"/api/elements/{fcc['id']}/stereotypes",
                        {"property": "Avionics.Computer.dal", "value": "C"})
        self.assertEqual(self.undo_label(), "Set Avionics.Computer.dal of FlightControlComputer")
        out = self.call("GET", "/api/avionics/safety?severity=error")
        rules = {i["rule"] for i in out["issues"]}
        self.assertTrue({"avionics.dal.requirement", "avionics.dal.allocation"} <= rules, rules)
        issue = next(i for i in out["issues"] if i["rule"] == "avionics.dal.allocation")
        self.assertIn("FCC_L (DAL C)", issue["message"])
        self.assertTrue(all(e["id"] for e in issue["elements"]))
        self.assertEqual(issue["title"], "Function allocated below its FHA DAL")
        check = self.call("GET", "/api/interop/check?rule=avionics.dal.allocation")
        self.assertTrue(check["issues"])
        # Per element and per rule filters.
        mine = self.call("GET", f"/api/avionics/safety?element={issue['element_id']}")
        self.assertTrue(mine["issues"] and all(any(e["id"] == issue["element_id"] for e in i["elements"])
                                               for i in mine["issues"]))
        only = self.call("GET", "/api/avionics/safety?rule=avionics.dal.requirement")
        self.assertEqual({i["rule"] for i in only["issues"]}, {"avionics.dal.requirement"})
        self.call("GET", "/api/avionics/safety?element=Nope", expect=404)
        # Undo takes the rules back to clean.
        self.call("POST", "/api/undo")
        self.assertEqual(self.call("GET", "/api/avionics/safety")["counts"]["error"], 0)

    # --- persistence and interop ----------------------------------------------------------
    def test_save_and_load_keep_everything(self):
        self.example()
        saved = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/new", {"name": "Empty"})
        self.assertEqual(self.call("GET", "/api/avionics/fha")["rows"], [])
        self.call("POST", "/api/load", {"text": saved})
        self.assertEqual(len(self.call("GET", "/api/avionics/fha")["rows"]), 21)
        self.assertEqual(self.call("GET", "/api/avionics/safety")["counts"]["error"], 0)
        self.assertEqual(self.call("GET", "/api/save")["text"], saved)

    def test_xlsx_round_trip_compares_identical(self):
        self.example()
        self.call("POST", "/api/interop/snapshot", {"label": "example"})
        xlsx = self.call("GET", "/api/interop/tables?format=xlsx")
        self.call("POST", "/api/interop/tables/import",
                  {"base64": xlsx["base64"], "filename": xlsx["filename"], "mode": "new"})
        self.assertEqual(len(self.call("GET", "/api/avionics/fha")["rows"]), 21)
        diff = self.call("POST", "/api/interop/compare", {"against": "snapshot", "include_layout": True})
        self.assertTrue(diff["identical"], diff["summary"])

    def test_model_tables_carry_the_fha(self):
        self.example()
        tables = self.call("GET", "/api/interop/tables?format=json")["tables"]
        rows = tables["Elements"]
        header = rows[0]
        fhas = [dict(zip(header, r)) for r in rows[1:] if r[header.index("Kind")] == "FhaEntry"]
        self.assertEqual(len(fhas), 21)
        self.assertIn("classification", header)
        self.assertIn("fha_function ID", header)
        self.assertTrue(all(f["fha_function ID"] for f in fhas))

    def test_report_mentions_the_fha_rows_and_profile(self):
        self.example()
        html = self.call("GET", "/api/interop/report?mermaid=none")["html"]
        self.assertIn("Avionics.Computer", html)
        self.assertIn("PhysicalArchitecture", html)


if __name__ == "__main__":
    import unittest
    unittest.main()
