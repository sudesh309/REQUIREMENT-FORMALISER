"""Qualified names returned by the API can be used to look elements up again (PO-7)."""
from __future__ import annotations

import unittest
import urllib.parse

from engine import Repository
from kerml.library import KERML_LIBRARY
from kerml.namespaces import Package
from sysmlv2 import AttributeUsage, PartDefinition, PartUsage
from tests.webapp_harness import WebAppTestCase
from webapp import core


def _walk(node):
    yield node
    for c in node.get("children", []):
        yield from _walk(c)


class RepositoryResolveTests(unittest.TestCase):

    def setUp(self):
        self.repo = Repository("Avionics")
        self.pkg = self.repo.add(Package(name="Systems"))
        self.arch = PartDefinition(name="AircraftAvionics")
        self.pkg.own(self.arch)
        self.adiru = PartUsage(name="ADIRU")
        self.arch.own(self.adiru)
        self.anon = PartUsage()
        self.arch.own(self.anon)
        self.repo.registry.register_tree(self.pkg)

    def test_every_form_of_a_qualified_name(self):
        r = self.repo.resolve
        self.assertEqual(self.adiru.qualified_name, "Avionics::Systems::AircraftAvionics::ADIRU")
        self.assertIs(r("Systems::AircraftAvionics::ADIRU"), self.adiru)            # root-relative
        self.assertIs(r("Avionics::Systems::AircraftAvionics::ADIRU"), self.adiru)  # fully qualified
        self.assertIs(r(" Avionics::Systems "), self.pkg)
        self.assertIs(r("Avionics"), self.repo.root_package)
        real = KERML_LIBRARY.resolve("ScalarValues::Real")
        self.assertIs(r(real.qualified_name), real)                                 # KerML::...
        self.assertIs(r("ScalarValues::Real"), real)
        self.assertIs(r(self.anon.qualified_name), self.anon)                       # <1a2b3c4d>
        for missing in ("", "Nope", "Avionics::Nope", "Systems::ADIRU", "<00000000>", None):
            self.assertIsNone(r(missing), missing)

    def test_root_relative_wins_when_both_read(self):
        same = self.repo.add(Package(name="Avionics"))       # a package named like the project
        inner = PartDefinition(name="Systems")
        same.own(inner)
        self.repo.registry.register_tree(same)
        self.assertIs(self.repo.resolve("Avionics::Systems"), inner)
        self.assertIs(self.repo.resolve("Avionics::Avionics::Systems"), inner)
        self.assertIs(self.repo.resolve("Avionics::Systems::AircraftAvionics"), self.arch)


class HttpQualifiedNameTests(WebAppTestCase):
    built = None

    def setUp(self):
        if HttpQualifiedNameTests.built is None:
            core.session().set_repo(Repository("Avionics"))
            HttpQualifiedNameTests.built = self._build()

    def _build(self):
        arch = self.call("POST", "/api/arch/architecture", {"name": "AircraftAvionics"})
        adiru = self.call("POST", "/api/arch/component", {"composition": arch["id"], "name": "ADIRU"})
        fms = self.call("POST", "/api/arch/component", {"composition": arch["id"], "name": "Flight Mgmt"})
        word = self.call("POST", "/api/interfaces", {"kind": "DataInterface", "name": "AirDataWord",
                                                     "elements": [{"name": "altitude"}]})
        # Owners and ends given by the qualified names the API itself returned.
        out = self.call("POST", "/api/arch/port", {"owner": adiru["qualified_name"], "name": "airData",
                                                   "direction": "out", "interface": word["qualified_name"]})
        self.call("POST", "/api/arch/port", {"owner": fms["qualified_name"], "name": "air in",
                                             "direction": "in"})
        self.call("POST", "/api/arch/connector", {
            "composition": arch["qualified_name"],
            "source": {"component": adiru["qualified_name"],
                       "port": self.call("GET", f"/api/element/{out['id']}")["qualified_name"]},
            "target": {"component": fms["qualified_name"], "port": "air in"}})
        repo = core.session().repo
        adiru_el = repo.by_id(adiru["id"])
        adiru_el.own(AttributeUsage(name="mass", typed_by=KERML_LIBRARY.resolve("ScalarValues::Real")))
        adiru_el.own(PartUsage())                           # an unnamed element
        repo.registry.register_tree(adiru_el)
        return arch

    def test_round_trip_of_every_summary(self):
        nodes = list(_walk(self.call("GET", "/api/tree")))
        self.assertGreater(len(nodes), 8)
        self.assertTrue(any(n["qualified_name"].startswith("<") for n in nodes))
        self.assertTrue(any(n.get("ends") for n in nodes))
        for n in nodes:
            qn = n["qualified_name"]
            with self.subTest(qn=qn):
                got = self.call("GET", "/api/element/" + urllib.parse.quote(qn, safe=""))
                self.assertEqual(got["id"], n["id"])
                if " " not in qn and "<" not in qn:
                    self.assertEqual(self.call("GET", f"/api/element/{qn}")["id"], n["id"])
                # Names inside summaries (types, connector ends) resolve as well.
                for ref in n.get("typed_by", []) + n.get("ends", []):
                    self.call("GET", "/api/element/" + urllib.parse.quote(ref, safe=""))

    def test_fully_qualified_names_in_feature_routes(self):
        qn = "Avionics::AircraftAvionics::ADIRU"
        self.assertEqual(self.call("GET", f"/api/element/{qn}")["name"], "ADIRU")
        self.assertEqual(self.call("GET", "/api/element/AircraftAvionics::ADIRU")["name"], "ADIRU")
        st = self.call("GET", f"/api/elements/{urllib.parse.quote(qn, safe='')}/stereotypes")
        self.assertEqual(st["element"]["name"], "ADIRU")
        port = self.call("POST", "/api/arch/port", {"owner": qn, "name": "health", "direction": "out"})
        self.assertEqual(self.call("GET", f"/api/element/{port['id']}")["qualified_name"], qn + "::health")
        self.call("GET", "/api/element/Avionics::Nope", expect=404)


class McpQualifiedNameTests(unittest.TestCase):

    def setUp(self):
        from mcp_server import server as m
        self.m = m
        m.SESSION.set_repo(Repository("Avionics"))
        self.call = lambda tool, /, **kw: m.TOOL_BY_NAME[tool]["handler"](**kw)

    def ok(self, tool, /, **kw):
        out = self.call(tool, **kw)
        self.assertTrue(out["ok"], out)
        return out["result"]

    def test_session_find_and_tools_take_returned_names(self):
        arch = self.ok("sysml_new_architecture", name="AircraftAvionics")
        self.assertEqual(arch["qualified_name"], "Avionics::AircraftAvionics")
        adiru = self.ok("sysml_add_component", composition=arch["qualified_name"], name="ADIRU")
        self.ok("sysml_add_port", owner=adiru["qualified_name"], name="airData", direction="out")
        s = self.m.SESSION
        self.assertIs(s.find("Avionics::AircraftAvionics::ADIRU"), s.find("AircraftAvionics::ADIRU"))
        self.assertIsNotNone(s.find("Avionics::AircraftAvionics::ADIRU"))
        for summary in self.ok("sysml_list_elements"):
            with self.subTest(qn=summary["qualified_name"]):
                got = self.ok("sysml_get_element", ref=summary["qualified_name"])
                self.assertEqual(got["id"], summary["id"])


if __name__ == "__main__":
    unittest.main()
