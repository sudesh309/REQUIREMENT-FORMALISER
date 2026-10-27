"""MCP tools of the avionics pack (mcp_server/tools/avionics.py): in process and over stdio."""
from __future__ import annotations

import json
import unittest

from engine.undo import history_for
from mcp_server import core
from mcp_server.tools import avionics as tools
from tests.test_mcp_server import _run

TOOL = {t["name"]: t["handler"] for t in tools.TOOLS}
NAMES = ["sysml_list_avionics_templates", "sysml_create_avionics_project", "sysml_avionics_overview",
         "sysml_ensure_avionics_profile", "sysml_list_interface_library", "sysml_import_interface_library",
         "sysml_list_requirement_library", "sysml_import_requirement_library", "sysml_fha_list",
         "sysml_fha_set_row", "sysml_fha_delete_row", "sysml_safety_check"]


class AvionicsToolTests(unittest.TestCase):

    def call(self, tool, **kwargs):
        res = TOOL[tool](**kwargs)
        self.assertTrue(res["ok"], res)
        return res["result"]

    def fail(self, tool, **kwargs):
        res = TOOL[tool](**kwargs)
        self.assertFalse(res["ok"], res)
        return res["error"]

    def test_tool_list(self):
        self.assertEqual(sorted(TOOL), sorted(NAMES))
        for t in tools.TOOLS:
            self.assertTrue(t["description"] and t["inputSchema"]["type"] == "object")

    def test_create_blank_and_work_with_the_fha(self):
        out = self.call("sysml_create_avionics_project", template="blank", name="MyAircraft")
        self.assertEqual(out["name"], "MyAircraft")
        self.assertEqual(core.SESSION.repo.name, "MyAircraft")
        self.assertFalse(history_for(core.SESSION).state()["can_undo"])
        over = self.call("sysml_avionics_overview")
        self.assertTrue(over["profile"]["present"])
        self.assertEqual(over["interfaces"]["present"], 37)
        # FHA rows: add, update, list, delete; one undo step each.
        from engine import architecture as A
        func_arch = A.create_architecture(core.SESSION.repo, "Functions")
        fn_el = A.add_component(core.SESSION.repo, func_arch, "ProvideAirData")
        row = self.call("sysml_fha_set_row", failure_condition="Loss of air data", function=fn_el.element_id,
                        classification="Hazardous", flight_phase="Cruise")
        self.assertEqual((row["fha_id"], row["dal"]), ("FHA-1", "B"))
        row = self.call("sysml_fha_set_row", row="FHA-1", classification="Catastrophic")
        self.assertEqual(row["dal"], "A")
        self.call("sysml_fha_set_row", row="FHA-1", clear_function=True)
        lst = self.call("sysml_fha_list")
        self.assertEqual(len(lst["rows"]), 1)
        self.assertIsNone(lst["rows"][0]["function"])
        self.assertEqual(lst["dal_by_classification"]["Minor"], "D")
        check = self.call("sysml_safety_check")
        self.assertTrue(any(i["rule"] == "avionics.fha.unallocated" for i in check["issues"]))
        self.assertEqual(self.call("sysml_fha_delete_row", row="FHA-1"), {"deleted": "FHA-1"})
        self.assertEqual(self.call("sysml_fha_list")["rows"], [])
        hist = history_for(core.SESSION)
        self.assertGreaterEqual(hist.state()["undo_depth"], 4)
        self.assertEqual(hist.state()["undo_label"], "Delete an FHA row")

    def test_errors_are_reported(self):
        self.call("sysml_create_avionics_project", template="blank")
        self.assertIn("Unknown template", self.fail("sysml_create_avionics_project", template="nope"))
        self.assertIn("needs a description", self.fail("sysml_fha_set_row", failure_condition=""))
        self.assertIn("not one of", self.fail("sysml_fha_set_row", failure_condition="x", classification="Bad"))
        self.assertIn("not found", self.fail("sysml_fha_delete_row", row="FHA-99"))
        self.assertIn("Unknown library item", self.fail("sysml_import_interface_library", names=["Nope"]))
        self.assertIn("Unknown requirement library", self.fail("sysml_import_requirement_library", sets=["nope"]))
        self.assertIn("not found", self.fail("sysml_safety_check", element="Nope"))

    def test_libraries_and_profile(self):
        from engine import Repository
        core.SESSION.set_repo(Repository("Empty"))
        self.assertEqual(self.call("sysml_list_interface_library")["present"], 0)
        res = self.call("sysml_import_interface_library", groups=["analog"])
        self.assertEqual(sorted(res["created"]), ["AnalogCurrent", "AnalogVoltage", "SynchroSignal"])
        self.assertEqual(history_for(core.SESSION).state()["undo_label"], "Import the avionics interface library")
        sets = self.call("sysml_import_requirement_library", sets=["arp4754a-item"], dal="B")
        self.assertEqual(sets["sets"][0]["prefix"], "ITM-")
        self.assertTrue(self.call("sysml_ensure_avionics_profile")["created"] is False)
        lib = self.call("sysml_list_requirement_library")
        self.assertEqual(len(lib["sets"]), 4)

    def test_example_and_the_safety_check(self):
        self.call("sysml_create_avionics_project", template="ima_example")
        self.assertEqual(self.call("sysml_avionics_overview")["fha"]["rows"], 21)
        out = self.call("sysml_safety_check", severity=["error", "warning"])
        self.assertEqual(out["counts"]["error"], 0)
        self.assertEqual({i["rule"] for i in out["issues"]}, {"avionics.req.unverified",
                                                              "avionics.req.unimplemented"})
        # The same model through the core DAL stereotype tool: lowering the DAL fires rules.
        fcc = core.SESSION.find("IMA_Avionics::Equipment::FlightControlComputer")
        from engine.avionics import profile as AP
        AP.set_values(core.SESSION.repo, fcc, "Computer", {"dal": "C"})
        out = self.call("sysml_safety_check", severity="error", rule="avionics.dal.allocation")
        self.assertEqual(len(out["issues"]), 1)
        self.assertEqual(out["issues"][0]["rule"], "avionics.dal.allocation")
        mine = self.call("sysml_safety_check", element=fcc.element_id)
        self.assertEqual(mine["issues"], [])         # issues name the usages, not the definition

    def test_stdio_round_trip(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "0"}}}
        responses = _run([init,
                          {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                          {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "sysml_create_avionics_project",
                                      "arguments": {"template": "ima_example"}}},
                          {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                           "params": {"name": "sysml_safety_check", "arguments": {"severity": "warning"}}}])
        names = {t["name"] for t in responses[1]["result"]["tools"]}
        self.assertTrue(set(NAMES) <= names)
        self.assertFalse(responses[2]["result"].get("isError"))
        data = json.loads(responses[3]["result"]["content"][0]["text"])
        self.assertEqual(data["counts"]["error"], 0)
        self.assertEqual(len(data["issues"]), 6)


if __name__ == "__main__":
    unittest.main()
