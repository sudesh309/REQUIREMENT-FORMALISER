"""MCP tool tests for the Allocation Editor (mcp_server/tools/allocation.py)."""
import json
import unittest

from engine import Repository
from engine import allocation as A
from mcp_server import core
from mcp_server.tools import allocation as tools
from sysmlv2 import PartDefinition, PartUsage
from tests.test_mcp_server import _run

TOOL = {t["name"]: t["handler"] for t in tools.TOOLS}


class AllocationToolTests(unittest.TestCase):

    def setUp(self):
        A.install()
        repo = Repository("Avionics")
        logical = PartDefinition(name="LogicalArch")
        for n in ("FMS", "DisplaySys"):
            logical.own(PartUsage(name=n))
        physical = PartDefinition(name="PhysicalArch")
        for n in ("IMA", "MFD"):
            physical.own(PartUsage(name=n))
        repo.add(logical)
        repo.add(physical)
        core.SESSION.set_repo(repo)

    def call(self, tool, **kwargs):
        res = TOOL[tool](**kwargs)
        self.assertTrue(res["ok"], res)
        return res["result"]

    def test_tools_end_to_end(self):
        s = self.call("sysml_create_allocation_set", name="L2P", source="LogicalArch",
                      target="PhysicalArch", require_complete_coverage=True)
        self.assertEqual(s["scenarios"][0]["name"], "Scenario 1")
        sc = self.call("sysml_create_allocation_scenario", set="Allocations::L2P", name="Alt")
        self.assertEqual(sc["name"], "Alt")
        a = self.call("sysml_allocate", scenario="Allocations::L2P::Scenario 1",
                      source="LogicalArch::FMS", target="PhysicalArch::IMA")
        self.assertEqual(a["label"], "FMS → IMA")
        self.call("sysml_allocate", scenario="Allocations::L2P::Alt",
                  source="LogicalArch::FMS", target="PhysicalArch::MFD")
        self.assertEqual([x["name"] for x in self.call("sysml_allocated_to", element="LogicalArch::FMS")],
                         ["IMA", "MFD"])
        self.assertEqual([x["name"] for x in self.call("sysml_allocated_to", element="LogicalArch::FMS",
                                                        scenario="Allocations::L2P::Alt")], ["MFD"])
        self.assertEqual([x["name"] for x in self.call("sysml_allocated_from", element="PhysicalArch::IMA")],
                         ["FMS"])
        cov = self.call("sysml_allocation_coverage", scenario="Allocations::L2P")
        self.assertEqual([u["name"] for u in cov["unallocated"]], ["DisplaySys"])
        self.assertEqual(len(self.call("sysml_allocation_map", scenario="Allocations::L2P")), 1)
        mx = self.call("sysml_allocation_matrix", scenario="Allocations::L2P", show="unallocated")
        self.assertEqual([r["name"] for r in mx["rows"]], ["DisplaySys"])
        self.assertEqual(len(self.call("sysml_allocation_chain", element="LogicalArch::FMS")["edges"]), 2)
        dup = self.call("sysml_duplicate_allocation_scenario", scenario="Allocations::L2P::Alt")
        self.assertEqual(dup["allocation_count"], 1)
        self.call("sysml_rename_allocation_scenario", scenario=dup["id"], name="Alt2")
        self.call("sysml_delete_allocation_scenario", scenario="Allocations::L2P::Alt2")
        self.call("sysml_deallocate", scenario="Allocations::L2P::Alt",
                  source="LogicalArch::FMS", target="PhysicalArch::MFD")
        upd = self.call("sysml_update_allocation_set", set="Allocations::L2P", name="Log2Phys")
        self.assertEqual(upd["name"], "Log2Phys")
        self.assertEqual([x["name"] for x in self.call("sysml_list_allocation_sets")], ["Log2Phys"])
        summary = core.SESSION.element_summary(core.SESSION.find(a["id"]))
        self.assertEqual(summary["badges"], ["FMS → IMA"])
        self.call("sysml_delete_allocation_set", set="Allocations::Log2Phys")
        self.assertEqual(self.call("sysml_list_allocation_sets"), [])

    def test_errors_are_reported(self):
        res = TOOL["sysml_allocate"](scenario="nope", source="LogicalArch::FMS", target="PhysicalArch::IMA")
        self.assertFalse(res["ok"])
        self.assertIn("not found", res["error"])
        self.call("sysml_create_allocation_set", name="L2P", source="LogicalArch", target="PhysicalArch")
        res = TOOL["sysml_allocate"](scenario="Allocations::L2P", source="PhysicalArch::IMA",
                                     target="PhysicalArch::MFD")
        self.assertIn("not part of source architecture", res["error"])
        res = TOOL["sysml_create_allocation_set"](name="L2P", source="LogicalArch", target="PhysicalArch")
        self.assertIn("already exists", res["error"])


class AllocationToolsOverStdioTests(unittest.TestCase):

    def test_listed_and_callable(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "0"}}}
        call = lambda i, name, args: {"jsonrpc": "2.0", "id": i, "method": "tools/call",  # noqa: E731
                                      "params": {"name": name, "arguments": args}}
        out = _run([
            init,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            call(3, "sysml_create_element", {"kind": "PartDefinition", "name": "A"}),
            call(4, "sysml_create_element", {"kind": "PartUsage", "name": "a1", "parent": "A"}),
            call(5, "sysml_create_element", {"kind": "PartDefinition", "name": "B"}),
            call(6, "sysml_create_element", {"kind": "PartUsage", "name": "b1", "parent": "B"}),
            call(7, "sysml_create_allocation_set", {"name": "S", "source": "A", "target": "B"}),
            call(8, "sysml_allocate", {"scenario": "Allocations::S", "source": "A::a1", "target": "B::b1"}),
            call(9, "sysml_allocated_to", {"element": "A::a1"}),
        ])
        names = {t["name"] for t in out[1]["result"]["tools"]}
        for n in ("sysml_create_allocation_set", "sysml_create_allocation_scenario", "sysml_allocate",
                  "sysml_deallocate", "sysml_allocated_to", "sysml_allocated_from",
                  "sysml_allocation_coverage"):
            self.assertIn(n, names)
        self.assertFalse(out[7]["result"]["isError"], out[7])
        self.assertEqual([x["name"] for x in json.loads(out[8]["result"]["content"][0]["text"])], ["b1"])


if __name__ == "__main__":
    unittest.main()
