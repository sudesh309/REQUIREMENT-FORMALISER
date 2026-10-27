"""HTTP and MCP tests for SU-15: reference components inherit stereotype values from their
definition (read, override, reset, undo, persistence, every view)."""
import json
import re
import unittest

from mcp_server import server as M
from tests.webapp_harness import WebAppTestCase

RAW = re.compile(r"/api/|\b(GET|POST|PATCH|PUT|DELETE)\b|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-")


class InheritanceHttpTests(WebAppTestCase):

    def setUp(self):
        self.call("POST", "/api/new", {"name": "Aircraft"})
        prof = self.call("POST", "/api/profiles", {"name": "Avionics"})
        self.lru = self.call("POST", f"/api/profiles/{prof['id']}/stereotypes",
                             {"name": "LRU", "applies_to": "Component", "style": {"fill": "#ffeeaa"}})
        for p in ({"name": "mass", "type": "double", "unit": "kg", "default": "1.5"},
                  {"name": "dal", "type": "enumeration", "literals": ["A", "B", "C", "D", "E"]}):
            self.call("POST", f"/api/stereotypes/{self.lru['id']}/properties", p)
        self.root = self.call("POST", "/api/arch/architecture", {"name": "Aircraft"})
        self.fcc_def = self.call("POST", "/api/arch/architecture", {"name": "FCC"})
        self.call("POST", f"/api/elements/{self.fcc_def['id']}/stereotypes",
                  {"stereotype": "Avionics.LRU", "values": {"mass": "3 kg", "dal": "A"}})
        self.fcc1 = self.call("POST", "/api/arch/component",
                              {"composition": self.root["id"], "name": "fcc1", "definition": self.fcc_def["id"]})
        self.fcc2 = self.call("POST", "/api/arch/component",
                              {"composition": self.root["id"], "name": "fcc2", "definition": self.fcc_def["id"]})
        self.plain = self.call("POST", "/api/arch/component", {"composition": self.root["id"], "name": "plain"})

    def view(self, e):
        return self.call("GET", f"/api/elements/{e['id']}/stereotypes")

    def props(self, e):
        (app,) = self.view(e)["applied"]
        return {p["name"]: p for g in app["groups"] for p in g["properties"]}

    def depth(self):
        return self.call("GET", "/api/undo/state")["undo_depth"]

    def label(self):
        label = self.call("GET", "/api/undo/state")["undo_label"]
        self.assertIsNone(RAW.search(label or ""), label)
        return label

    # ------------------------------------------------------------------------------------

    def test_reference_component_shows_the_definitions_values(self):
        view = self.view(self.fcc1)
        (app,) = view["applied"]
        self.assertEqual((app["qualified_name"], app["inherited"], app["overridden"]),
                         ("Avionics.LRU", True, False))
        self.assertEqual(app["inherited_from"]["name"], "FCC")
        p = self.props(self.fcc1)
        self.assertEqual((p["mass"]["value"], p["mass"]["display"], p["mass"]["origin"], p["mass"]["inherited"]),
                         (3.0, "3 kg", "inherited", True))
        self.assertEqual(p["dal"]["value"], "A")
        self.assertEqual(view["applicable"], [])               # already carried, nothing to add
        self.assertEqual(self.view(self.plain)["applied"], [])
        self.assertEqual([a["qualified_name"] for a in self.view(self.plain)["applicable"]], ["Avionics.LRU"])
        # element JSON: tree badge, canvas style, stereotypes entry
        el = self.call("GET", f"/api/element/{self.fcc1['id']}")
        self.assertIn("«LRU»", el["badges"])
        self.assertEqual(el["style"]["fill"], "#ffeeaa")
        (entry,) = el["stereotypes"]
        self.assertEqual((entry["qualified_name"], entry["inherited"], entry["values"]["mass"],
                          entry["display"]["mass"]), ("Avionics.LRU", True, 3.0, "3 kg"))
        # the canvas view model carries it as well
        self.assertIn("mass", {k for c in self.call("GET", f"/api/arch/view/{self.root['id']}")["components"]
                               if c["name"] == "fcc1" for s in c["stereotypes"] for k in s["values"]})

    def test_override_reset_and_undo(self):
        base = self.depth()
        out = self.call("PATCH", f"/api/elements/{self.fcc1['id']}/stereotypes",
                        {"property": "Avionics.LRU.mass", "value": "2 lb"})
        self.assertAlmostEqual(out["stored"]["Avionics.LRU.mass"], 0.90718474)
        (app,) = out["applied"]
        self.assertEqual((app["inherited"], app["overridden"]), (False, True))
        p = {q["name"]: q for g in app["groups"] for q in g["properties"]}
        self.assertEqual((p["mass"]["origin"], p["mass"]["overridden"], p["mass"]["inherited_value"]),
                         ("own", True, 3.0))
        self.assertEqual((p["dal"]["origin"], p["dal"]["overridden"]), ("inherited", False))
        self.assertEqual(self.depth(), base + 1)
        self.assertEqual(self.label(), "Set Avionics.LRU.mass of fcc1")
        # the other usage and the definition are untouched; the definition's changes still reach fcc1
        self.assertEqual(self.props(self.fcc2)["mass"]["value"], 3.0)
        self.call("PATCH", f"/api/elements/{self.fcc_def['id']}/stereotypes",
                  {"values": {"Avionics.LRU.dal": "D", "Avionics.LRU.mass": 9}})
        self.assertEqual(self.props(self.fcc1)["dal"]["value"], "D")
        self.assertAlmostEqual(self.props(self.fcc1)["mass"]["value"], 0.90718474)
        self.assertEqual(self.props(self.fcc2)["mass"]["value"], 9.0)
        # reset the override
        before = self.depth()
        out = self.call("POST", f"/api/elements/{self.fcc1['id']}/stereotypes/reset",
                        {"properties": ["Avionics.LRU.mass"]})
        self.assertEqual((out["reset"], out["removed"]), (["Avionics.LRU.mass"], ["Avionics.LRU"]))
        (app,) = out["applied"]
        self.assertEqual((app["inherited"], app["overridden"]), (True, False))
        self.assertEqual(self.props(self.fcc1)["mass"]["value"], 9.0)
        self.assertEqual(self.depth(), before + 1)
        self.assertEqual(self.label(), "Reset Avionics.LRU.mass of fcc1 to the inherited value")
        # undo brings the override back, with its record (is it still an override after the reload?)
        self.call("POST", "/api/undo")
        p = self.props(self.fcc1)
        self.assertAlmostEqual(p["mass"]["value"], 0.90718474)
        self.assertEqual((p["mass"]["origin"], p["dal"]["origin"]), ("own", "inherited"))
        self.call("POST", "/api/redo")
        self.assertEqual(self.props(self.fcc1)["mass"]["origin"], "inherited")
        # errors
        self.call("POST", f"/api/elements/{self.fcc1['id']}/stereotypes/reset", {}, expect=400)
        self.call("POST", f"/api/elements/{self.fcc1['id']}/stereotypes/reset",
                  {"properties": ["Avionics.LRU.nope"]}, expect=404)
        bad = self.call("PATCH", f"/api/elements/{self.fcc1['id']}/stereotypes",
                        {"property": "Avionics.LRU.mass", "value": "5 psi"}, expect=400)
        self.assertIn("cannot convert psi", bad["error"])
        self.assertEqual(self.props(self.fcc1)["mass"]["origin"], "inherited")      # nothing stored

    def test_generic_patch_and_apply_are_overrides(self):
        self.call("PATCH", f"/api/element/{self.fcc2['id']}", {"props": {"Avionics.LRU.dal": "e"}})
        self.assertEqual((self.props(self.fcc2)["dal"]["value"], self.props(self.fcc2)["dal"]["origin"]),
                         ("E", "own"))
        out = self.call("POST", f"/api/elements/{self.fcc1['id']}/stereotypes",
                        {"stereotype": "Avionics.LRU", "values": {"dal": "B"}})
        (app,) = out["applied"]
        self.assertTrue(app["overridden"])
        self.assertEqual(self.props(self.fcc1)["dal"]["value"], "B")
        self.assertEqual(self.props(self.fcc1)["mass"]["value"], 3.0)
        self.call("POST", f"/api/elements/{self.fcc1['id']}/stereotypes", {"stereotype": "Avionics.LRU"},
                  expect=409)                                           # a second own one is a duplicate

    def test_removing(self):
        err = self.call("DELETE", f"/api/elements/{self.fcc1['id']}/stereotypes/Avionics.LRU", expect=409)
        self.assertIn("inherited from", err["error"])
        out = self.call("DELETE", f"/api/elements/{self.fcc1['id']}/stereotypes")
        self.assertEqual(out["removed"], 0)
        self.call("PATCH", f"/api/elements/{self.fcc1['id']}/stereotypes", {"property": "mass", "value": 4})
        self.call("DELETE", f"/api/elements/{self.fcc1['id']}/stereotypes/Avionics.LRU")   # drops the override
        self.assertEqual(self.props(self.fcc1)["mass"]["value"], 3.0)
        self.call("DELETE", f"/api/elements/{self.fcc_def['id']}/stereotypes/Avionics.LRU")
        self.assertEqual(self.view(self.fcc1)["applied"], [])

    def test_multi_selection_inspector(self):
        """The canvas inspector edits several components at once: inherited and overridden alike."""
        ids = ",".join([self.fcc1["id"], self.fcc2["id"]])
        out = self.call("GET", f"/api/arch/stereotypes?ids={ids}")
        (app,) = out["applied"]
        p = {q["name"]: q for g in app["groups"] for q in g["properties"]}
        self.assertEqual((p["mass"]["value"], p["mass"]["mixed"]), (3.0, False))
        self.call("PATCH", "/api/arch/stereotypes", {"ids": [self.fcc1["id"]], "property": "mass", "value": 4})
        out = self.call("GET", f"/api/arch/stereotypes?ids={ids}")
        self.assertTrue({q["name"]: q for g in out["applied"][0]["groups"] for q in g["properties"]}["mass"]["mixed"])
        out = self.call("PATCH", "/api/arch/stereotypes", {"ids": [self.fcc1["id"], self.fcc2["id"]],
                                                            "property": "mass", "value": "5 kg"})
        self.assertEqual(self.props(self.fcc2)["mass"]["value"], 5.0)
        self.assertEqual(self.props(self.fcc1)["mass"]["value"], 5.0)

    def test_save_load_and_undo_keep_overrides(self):
        self.call("PATCH", f"/api/elements/{self.fcc1['id']}/stereotypes", {"property": "Avionics.LRU.mass", "value": 4})
        text = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/new", {"name": "Other"})
        self.call("POST", "/api/load", {"text": text})
        tree = self.call("GET", "/api/tree")

        def find(node, name):
            if node.get("name") == name:
                return node
            for c in node.get("children", []):
                hit = find(c, name)
                if hit:
                    return hit
        fcc1, fcc2, fdef = (find(tree, n) for n in ("fcc1", "fcc2", "FCC"))
        v1 = self.call("GET", f"/api/elements/{fcc1['id']}/stereotypes")["applied"][0]
        origins = {p["name"]: p["origin"] for g in v1["groups"] for p in g["properties"]}
        self.assertEqual(origins, {"mass": "own", "dal": "inherited"})
        self.call("PATCH", f"/api/elements/{fdef['id']}/stereotypes", {"values": {"Avionics.LRU.mass": 8,
                                                                               "Avionics.LRU.dal": "C"}})
        got = {n["name"]: {p["name"]: p["value"] for g in self.call("GET", f"/api/elements/{n['id']}/stereotypes")["applied"][0]["groups"]
                           for p in g["properties"]} for n in (fcc1, fcc2)}
        self.assertEqual(got, {"fcc1": {"mass": 4.0, "dal": "C"}, "fcc2": {"mass": 8.0, "dal": "C"}})

    def test_interop_views_agree(self):
        """Model Tables, the report, SysML export and Model Check read what get_property_value reads."""
        self.call("PATCH", f"/api/elements/{self.fcc1['id']}/stereotypes", {"property": "Avionics.LRU.mass", "value": 4})
        sheets = self.call("GET", "/api/interop/tables?format=json")["tables"]
        rows = {r["Name"]: r for r in _rows(sheets, "Components")}
        self.assertEqual((rows["fcc1"]["Stereotypes"], rows["fcc1"]["Avionics.LRU.mass"], rows["fcc1"]["Avionics.LRU.dal"]),
                         ("Avionics.LRU", 4.0, "A"))
        self.assertEqual((rows["fcc2"]["Stereotypes"], rows["fcc2"]["Avionics.LRU.mass"]), ("Avionics.LRU", 3.0))
        self.assertEqual(rows["plain"]["Stereotypes"], "")


def _rows(sheets, name):
    sheet = sheets[name] if isinstance(sheets, dict) and name in sheets else sheets["sheets"][name]
    head, *body = sheet
    return [dict(zip(head, r)) for r in body]


def call(tool, /, **args):
    return M.TOOL_BY_NAME[tool]["handler"](**args)


def ok(tool, /, **args):
    out = call(tool, **args)
    assert out["ok"], out
    return out["result"]


class InheritanceMcpTests(unittest.TestCase):

    def setUp(self):
        ok("sysml_new_project", name="Aircraft")
        ok("sysml_create_profile", name="Avionics")
        ok("sysml_add_stereotype", profile="Avionics", name="LRU", applies_to="Component")
        ok("sysml_add_stereotype_property", stereotype="Avionics.LRU", name="mass", type="double", unit="kg",
           default=1.5)
        ok("sysml_add_stereotype_property", stereotype="Avionics.LRU", name="dal", type="enumeration",
           literals=["A", "B", "C"])
        self.arch = ok("sysml_new_architecture", name="Aircraft")
        self.fcc_def = ok("sysml_new_architecture", name="FCC")
        self.fcc = ok("sysml_add_component", composition=self.arch["id"], name="fcc", definition=self.fcc_def["id"])
        ok("sysml_apply_stereotype", stereotype="Avionics.LRU", target=self.fcc_def["id"],
           values={"mass": "3 kg", "dal": "B"})

    def test_inherit_override_reset(self):
        got = ok("sysml_get_stereotype_properties", target=self.fcc["id"], property="Avionics.LRU.mass")
        self.assertEqual((got["value"], got["origin"], got["inherited"]), (3.0, "inherited", True))
        full = ok("sysml_get_stereotype_properties", target=self.fcc["id"])
        (st,) = full["stereotypes"]
        self.assertEqual((st["qualified_name"], st["inherited"], st["inherited_from"]["name"]),
                         ("Avionics.LRU", True, "FCC"))
        self.assertEqual(full["applicable"], [])
        out = ok("sysml_set_stereotype_property", target=self.fcc["id"], property="Avionics.LRU.mass", value="2 lb")
        self.assertAlmostEqual(out["stored"]["Avionics.LRU.mass"], 0.90718474)
        got = ok("sysml_get_stereotype_properties", target=self.fcc["id"], property="Avionics.LRU.mass")
        self.assertEqual((got["origin"], got["overridden"], got["inherited_value"]), ("own", True, 3.0))
        self.assertEqual(ok("sysml_get_stereotype_properties", target=self.fcc["id"],
                            property="Avionics.LRU.dal")["value"], "B")
        out = ok("sysml_reset_stereotype_property", target=self.fcc["id"], property="Avionics.LRU.mass")
        self.assertEqual((out["reset"], out["removed"]), (["Avionics.LRU.mass"], ["Avionics.LRU"]))
        got = ok("sysml_get_stereotype_properties", target=self.fcc["id"], property="Avionics.LRU.mass")
        self.assertEqual((got["value"], got["origin"]), (3.0, "inherited"))
        bad = call("sysml_reset_stereotype_property", target=self.fcc["id"])
        self.assertFalse(bad["ok"])
        # removing an inherited stereotype points at the definition; summaries and the core list tool agree
        bad = call("sysml_remove_stereotype", target=self.fcc["id"], stereotype="Avionics.LRU")
        self.assertFalse(bad["ok"])
        self.assertIn("inherited from", bad["error"])
        listed = ok("sysml_list_stereotypes", target=self.fcc["id"])
        self.assertEqual([(s["stereotype"], s["values"]["mass"], s["inherited"]) for s in listed],
                         [("Aircraft::Avionics::LRU", 3.0, True)])
        apply = ok("sysml_apply_stereotype", stereotype="Avionics.LRU", target=self.fcc["id"], values={"dal": "C"})
        self.assertEqual(apply["values"], {"mass": 3.0, "dal": "C"})      # an override, not a duplicate
        self.assertFalse(call("sysml_apply_stereotype", stereotype="Avionics.LRU", target=self.fcc["id"])["ok"])


if __name__ == "__main__":
    unittest.main()
