"""MCP tool tests for requirements and traceability (mcp_server/tools/requirements.py)."""
import json
import os
import tempfile
import unittest

import engine.requirements as rq
from engine import Repository


class RequirementsMcpTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from mcp_server import server
        cls.server = server

    def setUp(self):
        rq.install()
        self.server.SESSION.set_repo(Repository("Avionics"))
        self.tool = lambda tool_name, /, **kw: self.server.TOOL_BY_NAME[tool_name]["handler"](**kw)

    def ok(self, tool_name, /, **kw):
        out = self.tool(tool_name, **kw)
        self.assertTrue(out["ok"], out)
        return out["result"]

    def test_tools_registered_with_schemas(self):
        for name in ("sysml_create_requirement_set", "sysml_add_requirement", "sysml_update_requirement",
                     "sysml_link_requirement", "sysml_trace_matrix", "sysml_requirement_status",
                     "sysml_import_requirements", "sysml_export_requirements", "sysml_add_test_case",
                     "sysml_set_test_result", "sysml_clear_suspect", "sysml_trace_diagram",
                     "sysml_requirement_links", "sysml_unlink_requirement"):
            tool = self.server.TOOL_BY_NAME[name]
            self.assertEqual(tool["inputSchema"]["type"], "object")
            json.dumps(tool["inputSchema"])

    def test_end_to_end(self):
        arch = self.ok("sysml_create_element", kind="PartDefinition", name="Aircraft")
        self.ok("sysml_create_element", kind="PartUsage", name="FCC", parent=arch["id"])
        s = self.ok("sysml_create_requirement_set", name="FCS", prefix="FCS-")
        r1 = self.ok("sysml_add_requirement", set="FCS", summary="Pitch control", type="functional")
        r2 = self.ok("sysml_add_requirement", parent=r1["id"], summary="Pitch rate", priority="high")
        self.assertEqual((r1["req_id"], r2["req_id"], r2["parent_id"]), ("FCS-1", "FCS-2", r1["id"]))
        bad = self.tool("sysml_add_requirement", set="FCS", summary="X", type="banana")
        self.assertFalse(bad["ok"])
        self.assertIn("Invalid type", bad["error"])
        link = self.ok("sysml_link_requirement", type="implement", source="Aircraft::FCC", target=r2["id"])
        self.assertFalse(self.tool("sysml_link_requirement", type="verify", source="Aircraft::FCC",
                                   target=r2["id"])["ok"])
        tc = self.ok("sysml_add_test_case", name="Step test", set="FCS", verifies=[r2["id"]])
        self.ok("sysml_set_test_result", ref=tc["id"], result="passed")
        status = self.ok("sysml_requirement_status", ref="FCS")
        self.assertEqual(status["set"]["implementation"]["pct"], 100)
        self.assertEqual(status["set"]["verification"]["pct"], 100)
        upd = self.ok("sysml_update_requirement", ref=r2["id"], description="Rate below 5 deg/s")
        self.assertEqual(upd["suspect_count"], 2)   # the Implement and the Verify link
        links = self.ok("sysml_requirement_links", ref=r2["id"])["links"]
        self.assertTrue(any(l["suspect"] for l in links))
        self.assertEqual(self.ok("sysml_clear_suspect", ref=r2["id"])["cleared"], 2)
        m = self.ok("sysml_trace_matrix", set="FCS", columns="components")
        self.assertEqual(m["links"][0]["element"], "Avionics::Aircraft::FCC")
        self.assertIn("FCS-1 Pitch control", m["unlinked_requirements"])
        self.assertIn("FCC", self.ok("sysml_trace_matrix", set="FCS", format="csv")["text"])
        self.assertIn("flowchart", self.ok("sysml_trace_diagram", ref=r2["id"], depth=1)["text"])
        moved = self.ok("sysml_update_requirement", ref=r2["id"], move="outdent")
        self.assertIsNone(moved["parent_id"])
        self.ok("sysml_unlink_requirement", link=link["id"])
        self.assertFalse(self.tool("sysml_unlink_requirement", link=link["id"])["ok"])
        self.assertEqual(s["prefix"], "FCS-")

    def test_import_export(self):
        self.ok("sysml_create_requirement_set", name="SRS")
        rep = self.ok("sysml_import_requirements", format="csv", set="SRS",
                      content="id,summary,parent_id\nS-1,Top,\nS-2,Sub,S-1\n")
        self.assertEqual(rep["created"], 2)
        out = self.ok("sysml_export_requirements", format="reqif", set="SRS")
        self.assertIn("SPEC-HIERARCHY", out["text"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "srs.csv")
            self.ok("sysml_export_requirements", format="csv", set="SRS", path=path)
            rep2 = self.ok("sysml_import_requirements", format="csv", path=path, new_set="Copy")
            self.assertEqual(rep2["created"], 2)
        self.assertFalse(self.tool("sysml_import_requirements", format="csv")["ok"])
        self.assertFalse(self.tool("sysml_import_requirements", format="reqif",
                                   content="<!DOCTYPE a><REQ-IF/>")["ok"])


if __name__ == "__main__":
    unittest.main()
