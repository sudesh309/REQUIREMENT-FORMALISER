"""MCP tool tests for interfaces (mcp_server/tools/interfaces.py)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine import Repository
from engine import interfaces as I
from mcp_server import server as msrv
from mcp_server.core import SESSION

ROOT = Path(__file__).resolve().parent.parent


def call(_tool, **args):
    return msrv.TOOL_BY_NAME[_tool]["handler"](**args)


class InterfaceToolTests(unittest.TestCase):

    def setUp(self):
        I.install()
        SESSION.set_repo(Repository("McpIfc"))

    def _ports(self):
        call("sysml_create_element", kind="PartDefinition", name="Sys")
        call("sysml_create_element", kind="PartUsage", name="gps", parent="Sys")
        call("sysml_create_element", kind="PartUsage", name="fmc", parent="Sys")
        call("sysml_create_element", kind="PortUsage", name="pos", parent="Sys::gps",
             properties={"direction": "out"})
        call("sysml_create_element", kind="PortUsage", name="pos", parent="Sys::fmc",
             properties={"direction": "in"})
        return "Sys::gps::pos", "Sys::fmc::pos"

    def test_tools_registered(self):
        for name in ("sysml_create_interface", "sysml_add_interface_element", "sysml_set_interface_element",
                     "sysml_create_value_type", "sysml_assign_interface", "sysml_check_compatibility",
                     "sysml_export_dictionary", "sysml_import_dictionary",
                     "sysml_create_adapter", "sysml_set_adapter_mappings"):
            self.assertIn(name, msrv.TOOL_BY_NAME)
            self.assertIn("inputSchema", msrv.TOOL_BY_NAME[name])

    def test_end_to_end_flow(self):
        out, inp = self._ports()
        r = call("sysml_create_value_type", name="Deg", units="deg", minimum=-180, maximum=180)
        self.assertTrue(r["ok"], r)
        r = call("sysml_create_interface", name="GpsPos")
        self.assertTrue(r["ok"], r)
        for name, typ in (("lat", "ValueType: Deg"), ("lon", "ValueType: Deg"), ("fix", "boolean")):
            r = call("sysml_add_interface_element", interface="GpsPos", name=name, type=typ)
            self.assertTrue(r["ok"], r)
        r = call("sysml_set_interface_element", interface="GpsPos", element="fix", move=-2,
                 description="3D fix")
        self.assertEqual(r["result"]["order"], ["fix", "lat", "lon"])
        self.assertTrue(call("sysml_assign_interface", port=out, interface="GpsPos")["ok"])
        self.assertTrue(call("sysml_assign_interface", port=inp, interface="GpsPos")["ok"])
        self.assertTrue(call("sysml_assign_interface", port=inp, interface="owned")["ok"])  # owned copy
        r = call("sysml_check_compatibility", source=out, target=inp)
        self.assertTrue(r["result"]["compatible"], r)
        # Connectors are created by the architecture tool (sysml_connect_ports); here the
        # engine helper is used because the test addresses ports by id only.
        conn = I.connect_ports(SESSION.repo, SESSION.find(out), SESSION.find(inp)).element_id
        owned = I.interface_of(SESSION.find(inp))
        r = call("sysml_set_interface_element", interface=owned.element_id, element="fix", type="uint8")
        self.assertTrue(r["ok"], r)
        r = call("sysml_check_compatibility", connector=conn)
        self.assertFalse(r["result"]["compatible"])
        issues = call("sysml_validate")["result"]
        self.assertIn("interfaces.compatibility", json.dumps(issues))
        summary = call("sysml_get_element", ref=out)["result"]
        self.assertEqual(summary["interface"]["name"], "GpsPos")
        self.assertIn("GpsPos", summary["badges"])
        r = call("sysml_make_interface_shared", port=inp, name="GpsPos", on_conflict="rename")
        self.assertEqual(r["result"]["name"], "GpsPos_1")

    def test_errors_are_reported_not_raised(self):
        out, _ = self._ports()
        call("sysml_create_element", kind="ConnectionUsage", name="Bare", parent="Sys")
        for name, args, fragment in (
                ("sysml_create_interface", {"kind": "Nope"}, "Unknown interface kind"),
                ("sysml_add_interface_element", {"interface": "Missing"}, "not found"),
                ("sysml_assign_interface", {"port": out, "interface": "Missing"}, "not found"),
                ("sysml_check_compatibility", {}, "give source and target"),
                ("sysml_check_compatibility", {"connector": "Sys::Bare"}, "does not join two ports"),
                ("sysml_set_connector_elements", {"connector": "Sys::Bare"}, "does not join two ports"),
                ("sysml_set_connector_elements", {"connector": "Sys"}, "is not a connector"),
                ("sysml_import_dictionary", {"text": "[]"}, "'items' list")):
            r = call(name, **args)
            self.assertFalse(r["ok"], (name, r))
            self.assertIn(fragment, r["error"])

    def test_export_import_files(self):
        call("sysml_create_interface", template="milstd1553")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dict.json")
            r = call("sysml_export_dictionary", path=path)
            self.assertEqual(r["result"]["items"], 1)
            SESSION.set_repo(Repository("Other"))
            r = call("sysml_import_dictionary", path=path)
            self.assertEqual(r["result"]["added"], ["M1553Message"])
            r = call("sysml_import_dictionary", path=path, dry_run=True)
            self.assertEqual(r["result"]["collisions"][0]["name"], "M1553Message")
            r = call("sysml_import_dictionary", path=path, on_conflict="rename")
            self.assertEqual(r["result"]["renamed"], {"M1553Message": "M1553Message_1"})

    def test_adapter_tools(self):
        call("sysml_create_element", kind="PartDefinition", name="Sys")
        r = call("sysml_create_adapter", parent="Sys", name="Conv")
        self.assertEqual(r["result"]["kind"], "Adapter")
        r = call("sysml_set_adapter_mappings", adapter="Sys::Conv",
                 mappings=[{"target": "a", "source": "b", "note": "ft->m"}])
        self.assertEqual(r["result"]["mappings"][0]["note"], "ft->m")
        r = call("sysml_create_element", kind="Adapter", name="Generic", parent="Sys")
        ports = [e.name for e in SESSION.find("Sys::Generic").owned_elements]
        self.assertEqual(ports, ["In", "Out"])


class McpStdioTests(unittest.TestCase):

    def test_tools_listed_and_callable_over_stdio(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "sysml_create_interface",
                        "arguments": {"name": "Bus1", "elements": [{"name": "a", "units": "m"}]}}},
        ]
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        proc = subprocess.run([sys.executable, "-m", "mcp_server.server"], input="".join(
            json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True, cwd=ROOT, env=env, timeout=20)
        out = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertIn("sysml_create_interface", names)
        self.assertFalse(out[2]["result"]["isError"], out[2])
        self.assertEqual(json.loads(out[2]["result"]["content"][0]["text"])["elements"][0]["units"], "m")


if __name__ == "__main__":
    unittest.main()
