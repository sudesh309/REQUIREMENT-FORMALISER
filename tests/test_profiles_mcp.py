"""MCP tool tests for profiles and stereotype properties."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp_server import server as M

ROOT = Path(__file__).resolve().parent.parent


def call(tool, /, **args):
    return M.TOOL_BY_NAME[tool]["handler"](**args)


def ok(tool, /, **args):
    out = call(tool, **args)
    assert out["ok"], out
    return out["result"]


class ProfileToolTests(unittest.TestCase):

    def setUp(self):
        ok("sysml_new_project", name="Aircraft")
        self.arch = ok("sysml_create_element", kind="PartDefinition", name="System")
        self.fmc = ok("sysml_create_element", kind="PartUsage", name="FMC", parent=self.arch["id"])

    def _profile(self):
        ok("sysml_create_profile", name="Avionics", description="Avionics profile", version="1.0")
        ok("sysml_add_stereotype", profile="Avionics", name="LRU", applies_to="Component",
           style={"fill": "#ffeeaa"})
        ok("sysml_add_stereotype_property", stereotype="Avionics.LRU", name="mass", type="double",
           unit="kg", default=1.5, min=0)
        ok("sysml_add_stereotype_property", stereotype="Avionics.LRU", name="dal", type="enumeration",
           literals=["A", "B", "C", "D", "E"])
        ok("sysml_add_stereotype", profile="Avionics", name="A429Port", applies_to="Port")

    def test_tools_listed(self):
        for name in ("sysml_create_profile", "sysml_add_stereotype", "sysml_add_stereotype_property",
                     "sysml_apply_stereotype", "sysml_remove_stereotype", "sysml_set_stereotype_property",
                     "sysml_get_stereotype_properties", "sysml_batch_apply_stereotype",
                     "sysml_export_profile", "sysml_import_profile", "sysml_list_profiles"):
            self.assertIn(name, M.TOOL_BY_NAME)
        names = [t["name"] for t in M.TOOLS]
        self.assertEqual(len(names), len(set(names)), "tool names are unique")

    def test_end_to_end(self):
        self._profile()
        # the pre-existing apply tool now checks typed values
        out = ok("sysml_apply_stereotype", stereotype="Avionics::LRU", target=self.fmc["id"],
                 values={"mass": "3 lb"})
        self.assertAlmostEqual(out["values"]["mass"], 1.36077711)
        bad = call("sysml_apply_stereotype", stereotype="Avionics::A429Port", target=self.fmc["id"])
        self.assertFalse(bad["ok"])
        res = ok("sysml_set_stereotype_property", target=self.fmc["id"],
                 property="Avionics.LRU.dal", value="b")
        self.assertEqual(res["stored"], {"Avionics.LRU.dal": "B"})
        bad = call("sysml_set_stereotype_property", target=self.fmc["id"],
                   values={"Avionics.LRU.mass": -3})
        self.assertFalse(bad["ok"])
        self.assertIn("minimum", bad["error"])
        one = ok("sysml_get_stereotype_properties", target=self.fmc["id"], property="Avionics.LRU.mass")
        self.assertEqual((one["value"], one["display"]), (1.36077711, "1.36077711 kg"))
        props = ok("sysml_get_stereotype_properties", target=self.fmc["id"])
        self.assertEqual(props["stereotypes"][0]["values"], {"mass": 1.36077711, "dal": "B"})
        summary = ok("sysml_get_element", ref=self.fmc["id"])
        self.assertIn("«LRU»", summary["badges"])
        self.assertEqual(summary["stereotypes"][0]["stereotype"], "Avionics.LRU")
        # definition edits propagate
        upd = ok("sysml_update_stereotype_property", stereotype="Avionics.LRU", property="mass", unit="g")
        self.assertEqual(upd["converted"], 1)
        self.assertEqual(ok("sysml_get_stereotype_properties", target=self.fmc["id"],
                            property="mass")["value"], 1360.77711)
        ok("sysml_update_stereotype_property", stereotype="Avionics.LRU", property="mass", clear=["min"])
        ok("sysml_remove_stereotype", target=self.fmc["id"], stereotype="Avionics.LRU")
        self.assertEqual(ok("sysml_get_stereotype_properties", target=self.fmc["id"])["stereotypes"], [])

    def test_apply_tool_is_extended(self):
        self._profile()
        # one tool of that name: the profiles plugin replaced the core tool in place
        self.assertEqual([t["name"] for t in M.TOOLS].count("sysml_apply_stereotype"), 1)
        out = ok("sysml_apply_stereotype", stereotype="Avionics.LRU", target=self.fmc["id"],
                 values={"Avionics.LRU.mass": "2*1.5", "dal": "a"})
        self.assertEqual((out["applied"], out["stereotype"]), ("LRU", "Avionics.LRU"))
        self.assertEqual(out["values"], {"mass": 3.0, "dal": "A"})
        self.assertEqual(out["stereotypes"][0]["qualified_name"], "Avionics.LRU")
        dup = call("sysml_apply_stereotype", stereotype="LRU", target=self.fmc["id"])
        self.assertIn("already applied", dup["error"])
        ok("sysml_create_profile", name="Other")
        ok("sysml_add_stereotype", profile="Other", name="LRU")
        amb = call("sysml_apply_stereotype", stereotype="LRU", target=self.arch["id"])
        self.assertIn("ambiguous", amb["error"])
        bad = call("sysml_apply_stereotype", stereotype="Avionics.LRU", target=self.arch["id"],
                   values={"mass": "1 W"})
        self.assertIn("cannot convert", bad["error"])

    def test_batch_and_delete(self):
        self._profile()
        ok("sysml_create_element", kind="PartUsage", name="ADC", parent=self.arch["id"])
        out = ok("sysml_batch_apply_stereotype", stereotype="Avionics.LRU", scope="model")
        self.assertEqual(out["count"], 3)
        out = ok("sysml_delete_stereotype_property", stereotype="Avionics.LRU", property="dal")
        self.assertEqual(out["values_removed"], 3)
        out = ok("sysml_delete_profile", profile="Avionics")
        self.assertEqual(out["applications_removed"], 3)
        self.assertEqual(ok("sysml_list_profiles")["profiles"], [])

    def test_export_import_with_path_and_text(self):
        self._profile()
        text = ok("sysml_export_profile", profile="Avionics")["text"]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "Avionics.profile.json")
            ok("sysml_export_profile", profile="Avionics", path=path)
            ok("sysml_new_project", name="Other")
            out = ok("sysml_import_profile", path=path)
            self.assertTrue(out["created"])
            self.assertEqual(ok("sysml_list_profiles")["imports"][0]["file"], "Avionics.profile.json")
        again = call("sysml_import_profile", text=text)
        self.assertFalse(again["ok"])
        self.assertIn("already exists", again["error"])
        out = ok("sysml_import_profile", text=text, replace=True)
        self.assertFalse(out["created"])
        self.assertFalse(call("sysml_import_profile")["ok"])

    def test_units_tools(self):
        self.assertIn("lb", {u["symbol"] for u in ok("sysml_list_units", quantity="mass")})
        self.assertAlmostEqual(ok("sysml_convert_units", value="250 kt", to="km/h")["value"], 463.0)
        self.assertFalse(call("sysml_convert_units", value="1 kg", to="W")["ok"])


class StdioTests(unittest.TestCase):

    def test_tools_list_over_stdio(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "sysml_create_profile", "arguments": {"name": "Avionics"}}}]
        proc = subprocess.run([sys.executable, "-m", "mcp_server.server"], input="".join(
            json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True, cwd=ROOT, env=env, timeout=20)
        lines = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
        names = [t["name"] for t in lines[0]["result"]["tools"]]
        self.assertIn("sysml_batch_apply_stereotype", names)
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(lines[1]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
