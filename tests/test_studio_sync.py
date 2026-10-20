"""Cross-cutting studio contracts: the model revision header (every view learns about
every model change) and stereotype values shown with their units (PO-3)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from tests.webapp_harness import WebAppTestCase


class ModelRevisionTests(WebAppTestCase):

    def request(self, method: str, path: str, body=None) -> tuple[int, int, object]:
        """(status, X-Model-Revision, JSON) of one request."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status, headers, raw = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            status, headers, raw = e.code, e.headers, e.read()
        return status, int(headers["X-Model-Revision"]), json.loads(raw or b"null")

    def rev(self) -> int:
        return self.request("GET", "/api/state")[1]

    def setUp(self):
        self.call("POST", "/api/new", {"name": "Sync"})
        prof = self.call("POST", "/api/profiles", {"name": "Avionics"})
        lru = self.call("POST", f"/api/profiles/{prof['id']}/stereotypes", {"name": "LRU", "applies_to": "Component"})
        self.call("POST", f"/api/stereotypes/{lru['id']}/properties",
                  {"name": "mass", "type": "double", "unit": "kg", "default": 4.5})
        self.call("POST", f"/api/stereotypes/{lru['id']}/properties",
                  {"name": "dal", "type": "enumeration", "literals": ["A", "B", "C"]})
        self.root = self.call("POST", "/api/arch/architecture", {"name": "AircraftAvionics"})
        self.fms = self.call("POST", "/api/arch/component", {"composition": self.root["id"], "name": "FMS"})
        self.call("POST", f"/api/elements/{self.fms['id']}/stereotypes", {"stereotype": "Avionics.LRU"})

    def test_every_model_change_moves_the_revision(self):
        r0 = self.rev()
        status, r1, _ = self.request("PATCH", f"/api/elements/{self.fms['id']}/stereotypes",
                                     {"property": "Avionics.LRU.mass", "value": "7"})
        self.assertEqual((status, r1 > r0), (200, True), "a stereotype value edit is a model change")
        self.assertEqual(self.request("GET", "/api/state")[2]["revision"], r1)
        # Reads, rejected edits and edits that change nothing keep the revision.
        self.assertEqual(self.request("GET", f"/api/arch/view/{self.root['id']}")[1], r1)
        status, r2, _ = self.request("PATCH", f"/api/elements/{self.fms['id']}/stereotypes",
                                     {"property": "Avionics.LRU.mass", "value": "heavy"})
        self.assertEqual((status, r2), (400, r1))
        self.assertEqual(self.request("PATCH", f"/api/elements/{self.fms['id']}/stereotypes",
                                      {"property": "Avionics.LRU.mass", "value": "7"})[1], r1)
        self.assertEqual(self.request("POST", "/api/arch/layout", {"items": []})[1], r1)
        # Undo / redo / new / load switch the repository: all move the revision.
        r3 = self.request("POST", "/api/undo")[1]
        self.assertGreater(r3, r1)
        r4 = self.request("POST", "/api/redo")[1]
        self.assertGreater(r4, r3)
        text = self.call("GET", "/api/save")["text"]
        self.assertEqual(self.rev(), r4, "saving is not a change")
        r5 = self.request("POST", "/api/load", {"text": text})[1]
        self.assertGreater(r5, r4)
        self.assertGreater(self.request("POST", "/api/new", {"name": "Other"})[1], r5)

    def test_any_feature_edit_moves_the_revision(self):
        r0 = self.rev()
        self.request("POST", "/api/arch/port", {"owner": self.fms["id"], "name": "airData", "direction": "in"})
        r1 = self.rev()
        self.assertGreater(r1, r0)
        self.request("PATCH", f"/api/element/{self.fms['id']}", {"props": {"short_name": "fms"}})
        self.assertGreater(self.rev(), r1)

    def test_stereotype_values_carry_display_text_with_units(self):
        self.call("PATCH", f"/api/elements/{self.fms['id']}/stereotypes",
                  {"values": {"Avionics.LRU.mass": "7", "Avionics.LRU.dal": "B"}})
        view = self.call("GET", f"/api/arch/view/{self.root['id']}")
        st = view["components"][0]["stereotypes"][0]
        self.assertEqual(st["values"], {"mass": 7.0, "dal": "B"})
        self.assertEqual(st["display"], {"mass": "7 kg", "dal": "B"})
        el = self.call("GET", f"/api/element/{self.fms['id']}")
        self.assertEqual(el["stereotypes"][0]["display"]["mass"], "7 kg")
