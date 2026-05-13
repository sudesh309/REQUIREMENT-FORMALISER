"""Smoke test for the MCP server using its stdio JSON-RPC protocol."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(messages: list[dict]) -> list[dict]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server.server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=ROOT, env=env, text=True,
    )
    input_text = "".join(json.dumps(m) + "\n" for m in messages)
    out, err = proc.communicate(input_text, timeout=10)
    if err.strip():
        print("server stderr:", err, file=sys.stderr)
    return [json.loads(line) for line in out.strip().splitlines() if line.strip()]


class MCPServerTests(unittest.TestCase):

    def test_initialize_and_list_tools(self):
        responses = _run([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05",
                        "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ])
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "sysmlv2-core-engine")
        tools = responses[1]["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertIn("sysml_create_element", names)
        self.assertIn("sysml_validate", names)
        self.assertIn("sysml_connect", names)

    def test_create_and_list_part(self):
        responses = _run([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "sysml_create_element",
                        "arguments": {"kind": "PartDefinition", "name": "Vehicle"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "sysml_list_elements",
                        "arguments": {"kind": "PartDefinition"}}},
        ])
        self.assertFalse(responses[1]["result"].get("isError"))
        text = responses[2]["result"]["content"][0]["text"]
        data = json.loads(text)
        self.assertTrue(any(e["name"] == "Vehicle" for e in data))


if __name__ == "__main__":
    unittest.main()
