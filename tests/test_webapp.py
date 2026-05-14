"""Smoke tests for the web frontend's HTTP backend."""
import json
import os
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webapp import server as web  # noqa: E402


def _start_server(port: int):
    httpd = web.ThreadingHTTPServer(("127.0.0.1", port), web.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


PORT = 8770   # use a fixed-but-uncommon port for tests


class WebAppTests(unittest.TestCase):
    httpd = None

    @classmethod
    def setUpClass(cls):
        # Reset session before each test class.
        web.SESSION = web.Session()
        cls.httpd = _start_server(PORT)
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        if cls.httpd:
            cls.httpd.shutdown(); cls.httpd.server_close()

    # ----- basic plumbing ---------------------------------------------
    def test_state_and_static_index(self):
        s = _req("GET", "/api/state")
        self.assertIn("name", s)
        # Index page should be served.
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=5) as r:
            body = r.read().decode("utf-8")
        self.assertIn("SysML v2 Studio", body)
        self.assertIn("/static/app.js", body)

    def test_create_and_get_element(self):
        _req("POST", "/api/new", {"name": "Test1"})
        out = _req("POST", "/api/element",
                   {"kind": "PartDefinition", "name": "Vehicle"})
        self.assertEqual(out["name"], "Vehicle")
        eid = out["id"]
        got = _req("GET", f"/api/element/{eid}")
        self.assertEqual(got["kind"], "PartDefinition")
        self.assertEqual(got["name"], "Vehicle")
        # And the tree contains it.
        tree = _req("GET", "/api/tree")
        names = [c["name"] for c in tree["children"]]
        self.assertIn("Vehicle", names)

    def test_update_and_delete_element(self):
        _req("POST", "/api/new", {"name": "Test2"})
        e = _req("POST", "/api/element", {"kind": "PartDefinition", "name": "X"})
        eid = e["id"]
        upd = _req("PATCH", f"/api/element/{eid}",
                   {"props": {"name": "Y", "doc": "Hello", "is_abstract": True}})
        self.assertEqual(upd["name"], "Y")
        self.assertEqual(upd["doc"], "Hello")
        self.assertTrue(upd["is_abstract"])
        _req("DELETE", f"/api/element/{eid}")
        tree = _req("GET", "/api/tree")
        self.assertFalse(any(c["id"] == eid for c in tree["children"]))

    # ----- link, validate ---------------------------------------------
    def test_link_and_validate(self):
        _req("POST", "/api/new", {"name": "Test3"})
        v = _req("POST", "/api/element", {"kind": "PartDefinition", "name": "V"})
        r = _req("POST", "/api/element", {"kind": "RequirementDefinition", "name": "R"})
        rel = _req("POST", "/api/link",
                   {"kind": "satisfy", "source": v["id"], "target": r["id"]})
        self.assertEqual(rel["kind"], "satisfy")
        links = _req("GET", f"/api/links/{v['id']}")
        self.assertEqual({l["kind"] for l in links}, {"satisfy"})
        issues = _req("GET", "/api/validate")
        self.assertIn("issues", issues)

    # ----- diagram + KG export ----------------------------------------
    def test_diagram_mermaid_and_dot(self):
        _req("POST", "/api/new", {"name": "Test4"})
        _req("POST", "/api/element", {"kind": "PartDefinition", "name": "V"})
        m = _req("GET", "/api/diagram/mermaid?kind=bdd")
        self.assertEqual(m["format"], "mermaid")
        self.assertIn("classDiagram", m["text"])
        d = _req("GET", "/api/diagram/dot?kind=bdd")
        self.assertIn("digraph", d["text"])

    def test_export_formats(self):
        _req("POST", "/api/new", {"name": "Test5"})
        _req("POST", "/api/element", {"kind": "PartDefinition", "name": "V"})
        for fmt in ("turtle", "json-ld", "graphml", "cypher"):
            r = _req("GET", f"/api/export/{fmt}")
            self.assertEqual(r["format"], fmt)
            self.assertTrue(len(r["text"]) > 50)

    # ----- state machine end-to-end -----------------------------------
    def test_state_machine_flow(self):
        _req("POST", "/api/new", {"name": "Test6"})
        v = _req("POST", "/api/element", {"kind": "PartDefinition", "name": "V"})
        sm = _req("POST", "/api/sm/attach", {"part": v["id"], "name": "SM"})
        _req("POST", "/api/sm/state",
             {"state_machine": sm["id"], "name": "A", "is_initial": True})
        _req("POST", "/api/sm/state",
             {"state_machine": sm["id"], "name": "B"})
        _req("POST", "/api/sm/transition",
             {"state_machine": sm["id"], "source": "A", "target": "B",
              "trigger": "go"})
        fired = _req("POST", "/api/sm/fire",
                     {"state_machine": sm["id"], "event": "go"})
        self.assertEqual(fired["transitioned_to"], "B")
        sm_diag = _req("GET",
                       f"/api/diagram/mermaid?kind=statemachine&target={sm['id']}")
        self.assertIn("stateDiagram", sm_diag["text"])

    # ----- stereotypes -------------------------------------------------
    def test_stereotype_define_and_apply(self):
        _req("POST", "/api/new", {"name": "Test7"})
        v = _req("POST", "/api/element", {"kind": "PartDefinition", "name": "V"})
        sdef = _req("POST", "/api/stereotype/define",
                    {"name": "critical", "applies_to": ["PartDefinition"],
                     "tags": [{"name": "asilLevel"}]})
        out = _req("POST", "/api/stereotype/apply",
                   {"stereotype": sdef["id"], "target": v["id"],
                    "values": {"asilLevel": "D"}})
        self.assertEqual(out["values"]["asilLevel"], "D")
        v_full = _req("GET", f"/api/element/{v['id']}")
        self.assertEqual(v_full["stereotypes"][0]["name"], "critical")


if __name__ == "__main__":
    unittest.main()
