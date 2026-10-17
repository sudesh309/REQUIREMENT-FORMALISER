"""MCP tests for the architecture tools (mcp_server/tools/architecture.py)."""
import json
import unittest

from engine import Repository
from tests.test_mcp_server import _run as _stdio


def _tools():
    from mcp_server import server as m
    return m


class ArchitectureMcpTests(unittest.TestCase):

    def setUp(self):
        m = _tools()
        m.SESSION.set_repo(Repository("Mcp"))
        self.call = lambda tool, /, **kw: m.TOOL_BY_NAME[tool]["handler"](**kw)

    def ok(self, tool, /, **kw):
        out = self.call(tool, **kw)
        self.assertTrue(out["ok"], out)
        return out["result"]

    def fail(self, tool, /, **kw):
        out = self.call(tool, **kw)
        self.assertFalse(out["ok"], out)
        return out["error"]

    def test_tools_registered(self):
        names = set(_tools().TOOL_BY_NAME)
        for n in ("sysml_add_component", "sysml_add_port", "sysml_connect_ports", "sysml_arrange",
                  "sysml_group", "sysml_save_as_reference", "sysml_inline_component", "sysml_duplicate",
                  "sysml_undo", "sysml_redo", "sysml_arch_view", "sysml_set_model_type"):
            self.assertIn(n, names)

    def test_build_connect_arrange_and_undo(self):
        root = self.ok("sysml_new_architecture", name="Aircraft")
        adc = self.ok("sysml_add_component", composition=root["id"], name="ADC")
        fms = self.ok("sysml_add_component", composition="Aircraft")
        self.assertEqual(fms["name"], "Component")
        self.assertIn("409", self.fail("sysml_add_component", composition=root["id"], name="ADC"))
        self.ok("sysml_add_port", owner=adc["id"], name="air", direction="out")
        self.ok("sysml_add_port", owner=fms["id"], name="air", direction="in")
        self.assertIn("software", self.fail("sysml_add_port", owner=fms["id"], kind="client"))
        c = self.ok("sysml_connect_ports", composition=root["id"], source_component=fms["id"],
                    source_port="air", target_component=adc["id"], target_port="air")
        self.assertEqual(c["source"]["component_id"], adc["id"])                # auto-oriented
        err = self.fail("sysml_connect_ports", composition=root["id"], source_component=fms["id"],
                        source_port="air", target_component=fms["id"], target_port="air")
        self.assertIn("itself", err)
        pos = self.ok("sysml_arrange", composition=root["id"])["positions"]
        self.assertLess(pos[adc["id"]]["x"], pos[fms["id"]]["x"])
        view = self.ok("sysml_arch_view", composition=root["id"])
        self.assertEqual(len(view["connectors"]), 1)
        self.assertTrue(self.ok("sysml_undo")["undone"])                         # undo arrange
        self.assertTrue(self.ok("sysml_undo")["undone"])                         # undo connect
        self.assertEqual(self.ok("sysml_arch_view", composition=root["id"])["connectors"], [])
        self.assertTrue(self.ok("sysml_redo")["redone"])
        self.assertEqual(len(self.ok("sysml_arch_view", composition=root["id"])["connectors"]), 1)

    def test_group_reference_inline_duplicate_delete(self):
        root = self.ok("sysml_new_architecture", name="Aircraft")
        a = self.ok("sysml_add_component", composition=root["id"], name="A")
        b = self.ok("sysml_add_component", composition=root["id"], name="B")
        self.ok("sysml_add_port", owner=a["id"], name="o", direction="out")
        self.ok("sysml_add_port", owner=b["id"], name="i", direction="in")
        self.ok("sysml_connect_ports", composition=root["id"], source_component=a["id"], source_port="o",
                target_component=b["id"], target_port="i")
        g = self.ok("sysml_group", composition=root["id"], components=[b["id"]], name="G")
        self.assertEqual([p["name"] for p in g["ports"]], ["i"])
        ref = self.ok("sysml_save_as_reference", component=g["id"])
        self.assertTrue(ref["component"]["is_reference"])
        self.assertFalse(self.ok("sysml_inline_component", component=g["id"])["is_reference"])
        dup = self.ok("sysml_duplicate", components=[g["id"]])["components"]
        self.assertEqual(dup[0]["name"], "G1")
        self.ok("sysml_expand", component=g["id"])
        self.ok("sysml_delete_elements", elements=[dup[0]["id"]])
        names = [c["name"] for c in self.ok("sysml_arch_view", composition=root["id"])["components"]]
        self.assertEqual(sorted(names), ["A", "B"])
        tree = self.ok("sysml_arch_tree", root=root["id"])
        self.assertEqual(len(tree["children"]), 2)

    def test_model_type_and_summary(self):
        self.ok("sysml_set_model_type", type="software")
        root = self.ok("sysml_new_architecture")
        svc = self.ok("sysml_add_component", composition=root["id"], name="Svc")
        p = self.ok("sysml_add_port", owner=svc["id"], kind="server")
        el = _tools().tool_get_element(p["id"])["result"]
        self.assertEqual(el["port_kind"], "server")
        self.assertIn("server", el["badges"])
        self.assertIn("model type", self.fail("sysml_set_model_type", type="hardware"))

    def test_undo_covers_core_tool_edits_between_architecture_calls(self):
        m = _tools()
        root = self.ok("sysml_new_architecture", name="Aircraft")
        m.tool_create_element("PartDefinition", "Untracked")
        self.assertIsNotNone(m.SESSION.find("Untracked"))
        self.assertTrue(self.ok("sysml_undo")["undone"])
        self.assertIsNone(m.SESSION.find("Untracked"))
        self.assertIsNotNone(m.SESSION.find(root["id"]))


class ArchitectureMcpStdioTests(unittest.TestCase):

    def test_stdio_round_trip(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}}}

        def call(i, tool, /, **args):
            return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                    "params": {"name": tool, "arguments": args}}
        out = _stdio([init,
                      call(2, "sysml_new_architecture", name="Sys"),
                      call(3, "sysml_add_component", composition="Sys", name="A"),
                      call(4, "sysml_add_port", owner="Sys::A", name="o", direction="out"),
                      call(5, "sysml_add_port", owner="Sys", name="out", direction="out"),
                      call(6, "sysml_connect_ports", composition="Sys", source_component="Sys::A",
                           source_port="o", target_port="out"),
                      call(7, "sysml_arch_view", composition="Sys")])
        for r in out[1:]:
            self.assertFalse(r["result"].get("isError"), r)
        view = json.loads(out[-1]["result"]["content"][0]["text"])
        self.assertEqual(view["connectors"][0]["target"]["component_id"], None)
        self.assertEqual([b["name"] for b in view["boundary_ports"]], ["out"])


if __name__ == "__main__":
    unittest.main()
