"""Feedback when interfaces make connectors incompatible (PO-14).

System Composer lets the engineer assign any interface to a port and draw a connector
between any two ports; the studio does the same but must say so at once, naming the
connector and the reason (the answer's ``warnings`` and the ``X-Studio-Notices`` header
that the browser turns into a log line and a canvas toast), and the canvas view marks the
connector (``issues``).

``AssignFeedbackTests``: an interface assignment that leaves a connector incompatible (PO-14).
"""
import json
import unittest
import urllib.parse
import urllib.request

from engine import architecture as A
from engine import interfaces as I
from engine.structure import (
    connector_title, connector_warning_snapshot, connector_warnings, new_connector_warnings,
)
from engine import Repository
from kerml.features import FeatureDirection
from sysmlv2 import PartDefinition, PartUsage, PortUsage
from tests.webapp_harness import WebAppTestCase


def _notices(headers) -> list:
    raw = headers.get("X-Studio-Notices")
    return json.loads(urllib.parse.unquote(raw)) if raw else []


class FeedbackEngineTests(unittest.TestCase):
    """The shared helpers in engine/structure.py and the interfaces feature's source."""

    def setUp(self):
        I.install()
        A.install()
        self.repo = Repository("Fb")
        ac = self.repo.add(PartDefinition(name="Aircraft"))
        self.adiru, self.fms = PartUsage(name="ADIRU"), PartUsage(name="FMS")
        ac.own(self.adiru)
        ac.own(self.fms)
        self.out = PortUsage(name="airData", direction=FeatureDirection.OUT)
        self.adiru.own(self.out)
        self.inp = PortUsage(name="air", direction=FeatureDirection.IN)
        self.fms.own(self.inp)
        self.repo.registry.register_tree(ac)
        self.a = I.create_item(self.repo, "DataInterface", "AirDataWord",
                               elements=[{"name": "altitude", "type": "double"}])
        self.b = I.create_item(self.repo, "DataInterface", "InertialData",
                               elements=[{"name": "pitch", "type": "double"}])

    def test_compatible_connector_has_no_warning(self):
        I.assign_interface(self.repo, self.out, self.a)
        I.assign_interface(self.repo, self.inp, self.a)
        conn = I.connect_ports(self.repo, self.out, self.inp)
        self.assertEqual(connector_warnings(conn), [])
        self.assertEqual(connector_title(conn), "ADIRU.airData → FMS.air")

    def test_assignment_that_breaks_a_connector_is_reported_once(self):
        I.assign_interface(self.repo, self.out, self.a)
        I.assign_interface(self.repo, self.inp, self.a)
        conn = I.connect_ports(self.repo, self.out, self.inp)
        before = connector_warning_snapshot(self.repo, self.inp)
        I.assign_interface(self.repo, self.inp, self.b)
        found = new_connector_warnings(self.repo, self.inp, before)
        self.assertEqual(len(found), 1, found)
        self.assertIn("ADIRU.airData → FMS.air", found[0])
        self.assertIn("AirDataWord → InertialData", found[0])
        self.assertIn("element 'altitude'", found[0])
        # nothing new when the same problem is looked at again
        again = connector_warning_snapshot(self.repo, self.inp)
        self.assertEqual(new_connector_warnings(self.repo, self.inp, again), [])
        # the canvas view carries it as a connector issue
        ac = conn.owner
        issues = A.connector_view(conn, ac)["issues"]
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0].startswith("Incompatible interfaces AirDataWord → InertialData"))

    def test_fixing_or_clearing_gives_no_warning(self):
        I.assign_interface(self.repo, self.out, self.a)
        I.assign_interface(self.repo, self.inp, self.b)
        conn = I.connect_ports(self.repo, self.out, self.inp)
        self.assertEqual(len(connector_warnings(conn)), 1)
        before = connector_warning_snapshot(self.repo, self.inp)
        I.assign_interface(self.repo, self.inp, self.a)
        self.assertEqual(new_connector_warnings(self.repo, self.inp, before), [])
        self.assertEqual(A.connector_view(conn, conn.owner)["issues"], [])
        I.assign_interface(self.repo, self.inp, None)          # no interface: compatible with anything
        self.assertEqual(connector_warnings(conn), [])

    def test_port_without_interface_is_never_a_problem(self):
        I.assign_interface(self.repo, self.out, self.a)
        conn = I.connect_ports(self.repo, self.out, self.inp)
        self.assertEqual(connector_warnings(conn), [])


class _FeedbackBase(WebAppTestCase):

    def setUp(self):
        I.install()
        A.install()
        self.call("POST", "/api/new", {"name": "Avionics"})
        self.root = self.call("POST", "/api/arch/architecture", {"name": "Aircraft"})
        self.adc = self.call("POST", "/api/arch/component", {"composition": self.root["id"], "name": "ADC"})
        self.fms = self.call("POST", "/api/arch/component", {"composition": self.root["id"], "name": "FMS"})
        self.out = self.call("POST", "/api/arch/port", {"owner": self.adc["id"], "name": "airData",
                                                        "direction": "out"})
        self.inp = self.call("POST", "/api/arch/port", {"owner": self.fms["id"], "name": "air",
                                                        "direction": "in"})
        self.word = self.call("POST", "/api/interfaces", {"kind": "DataInterface", "name": "AirDataWord",
                                                          "elements": [{"name": "altitude", "type": "double"}]})
        self.inertial = self.call("POST", "/api/interfaces", {"kind": "DataInterface", "name": "InertialData",
                                                              "elements": [{"name": "pitch", "type": "double"}]})

    def raw(self, method, path, body=None):
        """(payload, headers) of a request, so the notices header can be checked."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8")), r.headers

    def connect(self):
        return self.call("POST", "/api/arch/connector", {
            "composition": self.root["id"],
            "source": {"component": self.adc["id"], "port": self.out["id"]},
            "target": {"component": self.fms["id"], "port": self.inp["id"]}})

    def wire(self, left, right):
        """Both ports typed (left, right), then the connector drawn."""
        self.call("POST", "/api/interfaces/assign", {"port": self.out["id"], "interface": left["id"]})
        self.call("POST", "/api/interfaces/assign", {"port": self.inp["id"], "interface": right["id"]})
        return self.connect()


class AssignFeedbackTests(_FeedbackBase):

    def test_assign_breaking_a_connector_warns_but_succeeds(self):
        conn = self.wire(self.word, self.word)
        self.assertEqual(conn["issues"], [])
        payload, headers = self.raw("POST", "/api/interfaces/assign",
                                    {"port": self.inp["id"], "interface": self.inertial["id"]})
        self.assertEqual(payload["interface"]["name"], "InertialData")        # it succeeded
        self.assertEqual(len(payload["warnings"]), 1, payload["warnings"])
        warning = payload["warnings"][0]
        self.assertIn("ADC.airData → FMS.air", warning)                      # names the connector
        self.assertIn("element 'altitude' is in 'AirDataWord' but not in 'InertialData'", warning)
        notices = _notices(headers)
        self.assertEqual([n["message"] for n in notices], payload["warnings"])
        self.assertEqual(notices[0]["severity"], "warning")
        # the connector is now flagged in the canvas view
        view = self.call("GET", f"/api/arch/view/{self.root['id']}")
        issues = view["connectors"][0]["issues"]
        self.assertEqual(len(issues), 1)
        self.assertIn("Incompatible interfaces AirDataWord → InertialData", issues[0])

    def test_assign_that_keeps_connectors_compatible_is_silent(self):
        self.wire(self.word, self.word)
        payload, headers = self.raw("POST", "/api/interfaces/assign",
                                    {"port": self.inp["id"], "interface": self.word["id"]})
        self.assertNotIn("warnings", payload)
        self.assertEqual(_notices(headers), [])
        payload, headers = self.raw("POST", "/api/interfaces/assign",
                                    {"port": self.inp["id"], "interface": None})
        self.assertNotIn("warnings", payload)
        self.assertEqual(_notices(headers), [])

    def test_canvas_port_update_warns(self):
        self.wire(self.word, self.word)
        payload, headers = self.raw("PATCH", f"/api/arch/port/{self.out['id']}",
                                    {"interface": self.inertial["id"]})
        self.assertEqual(payload["interface"]["name"], "InertialData")
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertIn("ADC.airData → FMS.air", payload["warnings"][0])
        self.assertIn("AirDataWord", payload["warnings"][0])
        self.assertEqual(len(_notices(headers)), 1)
        # renaming the port does not repeat the warning
        payload, headers = self.raw("PATCH", f"/api/arch/port/{self.out['id']}", {"name": "airDataOut"})
        self.assertNotIn("warnings", payload)
        self.assertEqual(_notices(headers), [])

    def test_properties_tab_typing_a_port_warns(self):
        self.wire(self.word, self.word)
        payload, headers = self.raw("PATCH", f"/api/element/{self.inp['id']}",
                                    {"props": {"typed_by": "Interfaces::InertialData"}})
        self.assertEqual(payload["interface"]["name"], "InertialData")
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertEqual(len(_notices(headers)), 1)
        # the form sends typed_by again on every save: no repeat
        payload, headers = self.raw("PATCH", f"/api/element/{self.inp['id']}",
                                    {"props": {"typed_by": "Interfaces::InertialData", "name": "air"}})
        self.assertNotIn("warnings", payload)
        self.assertEqual(_notices(headers), [])

    def test_notices_do_not_leak_into_the_next_request(self):
        self.wire(self.word, self.word)
        self.raw("POST", "/api/interfaces/assign", {"port": self.inp["id"], "interface": self.inertial["id"]})
        _payload, headers = self.raw("GET", "/api/tree")
        self.assertEqual(_notices(headers), [])


if __name__ == "__main__":
    unittest.main()
