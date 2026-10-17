"""HTTP API tests for profiles, stereotypes and stereotype values."""
import json
import urllib.parse

from tests.webapp_harness import WebAppTestCase


class ProfilesHttpTests(WebAppTestCase):

    def setUp(self):
        self.call("POST", "/api/new", {"name": "Aircraft"})
        self.arch = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "System"})
        self.fmc = self.call("POST", "/api/element", {"kind": "PartUsage", "name": "FMC",
                                                       "parent": self.arch["id"]})

    def _profile(self):
        prof = self.call("POST", "/api/profiles", {"name": "Avionics", "description": "d", "version": "1.2"})
        lru = self.call("POST", f"/api/profiles/{prof['id']}/stereotypes",
                        {"name": "LRU", "applies_to": "Component", "style": {"fill": "#ffeeaa", "icon": "computer"}})
        self.call("POST", f"/api/stereotypes/{lru['id']}/properties",
                  {"name": "mass", "type": "double", "unit": "kg", "default": "1.5"})
        self.call("POST", f"/api/stereotypes/{lru['id']}/properties",
                  {"name": "dal", "type": "enumeration", "literals": ["A", "B", "C", "D", "E"]})
        return prof, lru

    def test_meta_and_units(self):
        meta = self.call("GET", "/api/profiles/meta")
        self.assertIn("enumeration", meta["types"])
        self.assertIn("InterfaceElement", meta["categories"])
        self.assertIn("sensor", meta["icons"])
        self.assertIn("kt", {u["symbol"] for u in meta["units"]})
        conv = self.call("GET", "/api/units/convert?" + urllib.parse.urlencode({"value": "3 lb", "to": "kg"}))
        self.assertAlmostEqual(conv["value"], 1.36077711)
        self.call("GET", "/api/units/convert?" + urllib.parse.urlencode({"value": "3 lb", "to": "W"}), expect=400)

    def test_profile_editor_flow(self):
        prof, lru = self._profile()
        listed = self.call("GET", "/api/profiles")
        self.assertEqual([p["name"] for p in listed["profiles"]], ["Avionics"])
        st = listed["profiles"][0]["stereotypes"][0]
        self.assertEqual(st["qualified_name"], "Avionics.LRU")
        self.assertEqual([p["name"] for p in st["properties"]], ["mass", "dal"])
        self.assertEqual(st["properties"][0]["default"], 1.5)
        self.assertEqual(st["properties"][1]["default"], "A")
        # property edits: rename, reorder, unit, delete
        out = self.call("PATCH", f"/api/stereotypes/Avionics.LRU/properties/mass", {"name": "weight"})
        self.assertEqual(out["path"], "Avionics.LRU.weight")
        out = self.call("PATCH", f"/api/stereotypes/{lru['id']}/properties/dal", {"index": 0})
        self.assertEqual([p["name"] for p in out["stereotype"]["properties"]], ["dal", "weight"])
        self.call("PATCH", f"/api/stereotypes/{lru['id']}/properties/weight", {"unit": "W"}, expect=200)
        self.call("PATCH", f"/api/stereotypes/{lru['id']}/properties/weight", {"type": "float"}, expect=400)
        self.call("PATCH", f"/api/stereotypes/{lru['id']}/properties/nope", {"name": "x"}, expect=404)
        self.call("POST", f"/api/stereotypes/{lru['id']}/properties", {"name": "dal"}, expect=409)
        auto = self.call("POST", f"/api/stereotypes/{lru['id']}/properties", {})
        self.assertEqual((auto["name"], auto["type"]), ("Property", "double"))
        self.call("DELETE", f"/api/stereotypes/{lru['id']}/properties/Property")
        # stereotype + profile edits
        out = self.call("PATCH", f"/api/stereotypes/{lru['id']}", {"name": "Unit", "abstract": False,
                                                                    "description": "LRU"})
        self.assertEqual(out["qualified_name"], "Avionics.Unit")
        self.call("PATCH", f"/api/stereotypes/{lru['id']}", {"applies_to": "Gizmo"}, expect=400)
        self.call("PATCH", f"/api/stereotypes/{lru['id']}", {"base": lru["id"]}, expect=400)
        out = self.call("PATCH", f"/api/profiles/{prof['id']}", {"version": "2.0", "name": "Avio"})
        self.assertEqual((out["name"], out["version"]), ("Avio", "2.0"))
        self.call("POST", "/api/profiles", {"name": "Avio"}, expect=409)
        self.call("POST", "/api/profiles", {"name": "no spaces"}, expect=400)
        self.call("GET", "/api/profiles/Missing", expect=404)

    def test_apply_and_edit_values(self):
        _prof, lru = self._profile()
        view = self.call("GET", f"/api/elements/{self.fmc['id']}/stereotypes")
        self.assertEqual(view["applied"], [])
        self.assertEqual([s["qualified_name"] for s in view["applicable"]], ["Avionics.LRU"])
        self.assertEqual(view["element"]["categories"], ["Component"])
        view = self.call("POST", f"/api/elements/{self.fmc['id']}/stereotypes", {"stereotype": "Avionics.LRU"})
        group = view["applied"][0]["groups"][0]
        self.assertEqual([(p["name"], p["value"], p["display"]) for p in group["properties"]],
                         [("mass", 1.5, "1.5 kg"), ("dal", "A", "A")])
        self.call("POST", f"/api/elements/{self.fmc['id']}/stereotypes", {"stereotype": "Avionics.LRU"}, expect=409)
        out = self.call("PATCH", f"/api/elements/{self.fmc['id']}/stereotypes",
                        {"property": "Avionics.LRU.mass", "value": "3 lb"})
        self.assertEqual(out["stored"], {"Avionics.LRU.mass": 1.36077711})
        mass = out["applied"][0]["groups"][0]["properties"][0]
        self.assertEqual(mass["display"], "1.36077711 kg")
        err = self.call("PATCH", f"/api/elements/{self.fmc['id']}/stereotypes",
                        {"values": {"Avionics.LRU.mass": "3 psi"}}, expect=400)
        self.assertIn("cannot convert psi", err["error"])
        err = self.call("PATCH", f"/api/elements/{self.fmc['id']}/stereotypes",
                        {"values": {"Avionics.LRU.dal": "F"}}, expect=400)
        self.assertIn("literals", err["error"])
        # generic PATCH with a dotted key
        self.call("PATCH", f"/api/element/{self.fmc['id']}", {"props": {"Avionics.LRU.dal": "d"}})
        full = self.call("GET", f"/api/element/{self.fmc['id']}")
        self.assertEqual(full["stereotypes"][0]["values"]["dal"], "D")
        self.assertEqual(full["stereotypes"][0]["qualified_name"], "Avionics.LRU")
        self.assertIn("«LRU»", full["badges"])
        self.assertEqual(full["style"], {"fill": "#ffeeaa", "icon": "computer"})
        tree = self.call("GET", "/api/tree")
        fmc_node = tree["children"][0]["children"][0]
        self.assertEqual((fmc_node["name"], fmc_node["badges"]), ("FMC", ["«LRU»"]))
        # remove one / all
        self.call("DELETE", f"/api/elements/{self.fmc['id']}/stereotypes/Avionics.LRU")
        self.call("DELETE", f"/api/elements/{self.fmc['id']}/stereotypes/Avionics.LRU", expect=404)
        self.call("POST", f"/api/elements/{self.fmc['id']}/stereotypes",
                  {"stereotype": lru["id"], "values": {"mass": 7}})
        out = self.call("DELETE", f"/api/elements/{self.fmc['id']}/stereotypes")
        self.assertEqual((out["removed"], out["applied"]), (1, []))
        self.call("GET", "/api/elements/nope/stereotypes", expect=404)

    def test_generic_patch_of_definitions_is_checked(self):
        _prof, lru = self._profile()
        self.call("POST", f"/api/elements/{self.fmc['id']}/stereotypes", {"stereotype": lru["id"]})
        tag = self.call("GET", f"/api/stereotypes/{lru['id']}")["properties"][0]
        self.call("PATCH", f"/api/element/{tag['id']}", {"props": {"name": "weight"}})
        view = self.call("GET", f"/api/elements/{self.fmc['id']}/stereotypes")
        self.assertEqual(view["applied"][0]["values"], {"weight": 1.5, "dal": "A"})
        self.call("PATCH", f"/api/element/{tag['id']}", {"props": {"name": "bad name"}}, expect=400)
        self.call("PATCH", f"/api/element/{tag['id']}", {"props": {"default_value": "abc"}}, expect=400)
        # The generic element route answers 400 for every rejected edit.
        self.call("PATCH", f"/api/element/{lru['id']}", {"props": {"is_abstract": True}}, expect=400)
        self.call("PATCH", f"/api/stereotypes/{lru['id']}", {"abstract": True}, expect=409)

    def test_delete_propagation(self):
        prof, lru = self._profile()
        self.call("POST", f"/api/elements/{self.fmc['id']}/stereotypes", {"stereotype": lru["id"]})
        out = self.call("DELETE", f"/api/stereotypes/{lru['id']}/properties/mass")
        self.assertEqual(out["values_removed"], 1)
        self.assertEqual(self.call("GET", f"/api/elements/{self.fmc['id']}/stereotypes")["applied"][0]["values"],
                         {"dal": "A"})
        out = self.call("DELETE", f"/api/profiles/{prof['id']}")
        self.assertEqual(out["applications_removed"], 1)
        self.assertEqual(self.call("GET", f"/api/element/{self.fmc['id']}")["stereotypes"], [])

    def test_batch_apply(self):
        _prof, lru = self._profile()
        other = self.call("POST", "/api/element", {"kind": "PartUsage", "name": "ADC", "parent": self.arch["id"]})
        out = self.call("POST", f"/api/stereotypes/{lru['id']}/batch",
                        {"scope": "selection", "ids": [self.fmc["id"]], "values": {"dal": "B"}})
        self.assertEqual(out["applied"], [self.fmc["id"]])
        out = self.call("POST", f"/api/stereotypes/{lru['id']}/batch",
                        {"scope": "composition", "root": self.arch["id"]})
        self.assertEqual(set(out["applied"]), {self.arch["id"], other["id"]})
        self.assertEqual(out["skipped"][0]["reason"], "already applied")
        self.call("POST", f"/api/stereotypes/{lru['id']}/batch", {"scope": "selection", "ids": []}, expect=400)

    def test_export_import_and_save_load(self):
        prof, lru = self._profile()
        self.call("POST", f"/api/elements/{self.fmc['id']}/stereotypes",
                  {"stereotype": lru["id"], "values": {"mass": "2 kg"}})
        exported = self.call("GET", f"/api/profiles/{prof['id']}/export")
        self.assertEqual(exported["file_name"], "Avionics.profile.json")
        self.call("POST", "/api/profiles/import", {"text": exported["text"]}, expect=409)
        data = json.loads(exported["text"])
        data["profile"]["version"] = "9"
        out = self.call("POST", "/api/profiles/import",
                        {"text": json.dumps(data), "replace": True, "file_name": "v9.json"})
        self.assertEqual((out["created"], out["profile"]["version"]), (False, "9"))
        self.call("POST", "/api/profiles/import", {"text": "{oops"}, expect=400)
        self.call("POST", "/api/profiles/import", {}, expect=400)
        saved = self.call("GET", "/api/save")["text"]
        self.call("POST", "/api/new", {"name": "Empty"})
        self.call("POST", "/api/load", {"text": saved})
        view = self.call("GET", f"/api/elements/{self.fmc['id']}/stereotypes")
        self.assertEqual(view["applied"][0]["values"], {"mass": 2.0, "dal": "A"})
        listed = self.call("GET", "/api/profiles")
        self.assertEqual(listed["imports"][0]["file"], "v9.json")
        # imported into a fresh project
        self.call("POST", "/api/new", {"name": "Fresh"})
        out = self.call("POST", "/api/profiles/import", {"text": exported["text"], "file_name": "a.json"})
        self.assertTrue(out["created"])
        self.assertEqual(out["profile"]["stereotypes"][0]["qualified_name"], "Avionics.LRU")

    def test_legacy_endpoints_still_work_and_check_values(self):
        sdef = self.call("POST", "/api/stereotype/define",
                         {"name": "critical", "applies_to": ["PartUsage"], "tags": [{"name": "asil"}]})
        out = self.call("POST", "/api/stereotype/apply",
                        {"stereotype": sdef["id"], "target": self.fmc["id"], "values": {"asil": "D"}})
        self.assertEqual(out["values"], {"asil": "D"})
        self.call("POST", "/api/stereotype/apply", {"stereotype": sdef["id"], "target": self.fmc["id"]},
                  expect=400)                                         # already applied
        listed = self.call("GET", "/api/profiles")
        self.assertEqual([s["qualified_name"] for s in listed["ungrouped"]], ["critical"])
        _prof, lru = self._profile()
        other = self.call("POST", "/api/element", {"kind": "PartUsage", "name": "IRS", "parent": self.arch["id"]})
        out = self.call("POST", "/api/stereotype/apply",
                        {"stereotype": lru["id"], "target": other["id"], "values": {"mass": "1000 g"}})
        self.assertEqual(out["values"]["mass"], 1.0)
        self.call("POST", "/api/stereotype/apply",
                  {"stereotype": lru["id"], "target": self.arch["id"], "values": {"mass": "1 W"}}, expect=400)

    def test_validate_reports_profile_issues(self):
        _prof, lru = self._profile()
        self.call("POST", f"/api/elements/{self.fmc['id']}/stereotypes", {"stereotype": lru["id"]})
        from webapp import core
        from engine import profiles as P
        app = P.stereotypes_on(core.session().find(self.fmc["id"]))[0]
        app.raw_slots()[app.tag("dal")] = "Z"
        issues = self.call("GET", "/api/validate")["issues"]
        self.assertIn("profile.value.invalid", {i["rule"] for i in issues})
