"""Interop MCP tools (in process, plus one stdio round trip)."""
import json
import tempfile
import unittest
from pathlib import Path

from engine import to_json
from mcp_server import server as srv
from mcp_server.core import SESSION
from tests.test_interop_fixtures import XMI_FIXTURE, avionics_repo
from tests.test_mcp_server import _run

NAMES = ["sysml_export_tables", "sysml_import_tables", "sysml_generate_report",
         "sysml_compare_projects", "sysml_merge_projects", "sysml_export_sysml_text",
         "sysml_import_sysml_text", "sysml_import_xmi", "sysml_model_check"]


def call(tool, **args):
    return srv.TOOL_BY_NAME[tool]["handler"](**args)


class InteropMcpTests(unittest.TestCase):

    def setUp(self):
        SESSION.set_repo(avionics_repo())
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tools_registered(self):
        for n in NAMES:
            self.assertIn(n, srv.TOOL_BY_NAME)

    def test_tables_round_trip_through_files(self):
        out = self.dir / "fd.xlsx"
        self.assertTrue(call("sysml_export_tables", format="xlsx", path=str(out))["ok"])
        saved = self.dir / "fd.json"
        SESSION.repo.save(str(saved))
        call("sysml_new_project", name="Blank")
        r = call("sysml_import_tables", path=str(out), mode="new")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["project"]["name"], "FlightDeck")
        diff = call("sysml_compare_projects", other_path=str(saved))
        self.assertTrue(diff["result"]["identical"])
        j = call("sysml_export_tables", format="json")
        self.assertIn("Ports", j["result"]["tables"])
        r = call("sysml_import_tables", tables=j["result"]["tables"])
        self.assertEqual(r["result"]["report"]["created"], 0)
        csv = call("sysml_export_tables", format="csv")
        self.assertTrue(csv["result"]["base64"])
        bad = call("sysml_import_tables", tables={"Ports": [["Name", "Kind"], ["p", "Nope"]]})
        self.assertFalse(bad["ok"])
        self.assertIn("unknown kind", bad["error"])

    def test_report_sysml_and_check(self):
        path = self.dir / "r.html"
        r = call("sysml_generate_report", path=str(path), title="SAR")
        self.assertTrue(r["ok"])
        html = path.read_text()
        self.assertIn("<title>SAR</title>", html)
        self.assertNotIn("/static/vendor/", html)          # standalone file inlines Mermaid
        text = call("sysml_export_sysml_text")["result"]["text"]
        self.assertIn("part def FlightDeck", text)
        r = call("sysml_import_sysml_text", text="package T { part def Q; }")
        self.assertEqual(r["result"]["created"], 2)
        bad = call("sysml_import_sysml_text", text="package {")
        self.assertFalse(bad["ok"])
        chk = call("sysml_model_check", severity=["warning"])
        self.assertTrue(all(i["severity"] == "warning" for i in chk["result"]["issues"]))

    def test_merge_and_xmi(self):
        base = to_json(avionics_repo())
        theirs = json.loads(base)
        next(e for e in theirs["elements"] if e["name"] == "gps")["name"] = "gnss"
        (self.dir / "base.json").write_text(base)
        (self.dir / "theirs.json").write_text(json.dumps(theirs))
        SESSION.set_repo(__import__("engine").from_json(base))
        r = call("sysml_merge_projects", base_path=str(self.dir / "base.json"),
                 theirs_path=str(self.dir / "theirs.json"), out_path=str(self.dir / "m.json"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["conflicts"], [])
        self.assertIsNotNone(SESSION.find("FlightDeck::gnss"))
        self.assertTrue((self.dir / "m.json").read_text().endswith("\n"))
        x = call("sysml_import_xmi", path=str(XMI_FIXTURE))
        self.assertTrue(x["ok"])
        self.assertEqual(SESSION.repo.name, "FlightDeckModel")
        self.assertFalse(call("sysml_import_xmi")["ok"])

    def test_stdio_tools_list_includes_interop(self):
        responses = _run([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "sysml_model_check", "arguments": {}}},
        ])
        names = {t["name"] for t in responses[1]["result"]["tools"]}
        self.assertTrue(set(NAMES) <= names)
        self.assertFalse(responses[2]["result"]["isError"])
        self.assertIn("counts", json.loads(responses[2]["result"]["content"][0]["text"]))


if __name__ == "__main__":
    unittest.main()
