"""Regression tests for core defects found by the System Composer audit."""
import unittest

from engine import Repository, from_json, links_of, create_link, register_removal_hook, to_json
from engine import repository as repo_module
from engine.properties import set_property
from kerml.features import FeatureDirection
from kerml.stereotypes import Stereotype, stereotypes_on
from sysmlv2 import (
    ConnectionUsage, PartDefinition, PartUsage, PortDefinition, PortUsage,
    RequirementDefinition,
)
from tests.webapp_harness import WebAppTestCase


def _vehicle():
    repo = Repository("P")
    Mech = repo.add(PortDefinition(name="Mech"))
    Engine = repo.add(PartDefinition(name="Engine"))
    shaft = PortUsage(name="shaft", typed_by=Mech); Engine.own(shaft)
    Trans = repo.add(PartDefinition(name="Trans"))
    inp = PortUsage(name="input", typed_by=Mech); Trans.own(inp)
    V = repo.add(PartDefinition(name="Vehicle"))
    V.own(PartUsage(name="engine", typed_by=Engine))
    V.own(ConnectionUsage(name="drive", ends=[shaft, inp]))
    repo.registry.register_tree(repo.root_package)
    return repo


class SetPropertyTests(unittest.TestCase):

    def test_direction_is_coerced(self):
        p = PortUsage(name="p")
        set_property(p, "direction", "in", lambda r: None)
        self.assertIs(p.direction, FeatureDirection.IN)
        with self.assertRaises(ValueError):
            set_property(p, "direction", "sideways", lambda r: None)

    def test_structural_attributes_rejected(self):
        c = ConnectionUsage(name="c")
        with self.assertRaises(ValueError):
            set_property(c, "ends", ["a", "b"], lambda r: None)
        with self.assertRaises(ValueError):
            set_property(c, "owner", "x", lambda r: None)
        with self.assertRaises(ValueError):
            set_property(c, "no_such_attr", 1, lambda r: None)

    def test_scalar_attributes_allowed(self):
        r = RequirementDefinition(name="R")
        set_property(r, "req_id", "R-9", lambda ref: None)
        set_property(r, "text", "shall", lambda ref: None)
        self.assertEqual((r.req_id, r.text), ("R-9", "shall"))
        set_property(r, "req_id", None, lambda ref: None)
        self.assertIsNone(r.req_id)
        with self.assertRaises(ValueError):
            set_property(r, "text", ["not", "scalar"], lambda ref: None)

    def test_typed_by_replaces_and_clears(self):
        repo = _vehicle()
        u = repo.resolve("Vehicle::engine")
        set_property(u, "typed_by", "Trans", repo.resolve)
        self.assertEqual([t.name for t in u.types], ["Trans"])
        set_property(u, "typed_by", "", repo.resolve)
        self.assertEqual(u.types, [])
        self.assertIn('"typed_by": []', to_json(repo))


class CascadingDeleteTests(unittest.TestCase):

    def test_deleting_port_removes_connector(self):
        repo = _vehicle()
        repo.remove(repo.resolve("Engine::shaft"))
        self.assertIsNone(repo.resolve("Vehicle::drive"))
        self.assertEqual(len(from_json(to_json(repo)).by_kind("ConnectionUsage")), 0)

    def test_deleting_type_clears_typings(self):
        repo = _vehicle()
        repo.remove(repo.resolve("Engine"))
        u = repo.resolve("Vehicle::engine")
        self.assertEqual(u.types, [])
        self.assertEqual([r for r in u.owned_relationships if r.kind == "FeatureTyping"], [])
        from_json(to_json(repo))  # still serializable

    def test_deleting_stereotype_removes_applications(self):
        repo = _vehicle()
        st = repo.add(Stereotype(name="crit"))
        V = repo.resolve("Vehicle")
        st.apply(V)
        repo.remove(st)
        self.assertEqual(stereotypes_on(V), [])

    def test_deleting_state_removes_transitions_and_initial(self):
        repo = _vehicle()
        sm = repo.resolve("Vehicle").attach_state_machine("SM")
        a = sm.add_state("A", is_initial=True); b = sm.add_state("B", is_final=True)
        sm.add_transition(a, b, trigger="go")
        repo.registry.register_tree(repo.root_package)
        repo.remove(a)
        self.assertIsNone(sm.initial_state)
        self.assertEqual(sm.transitions, [])
        repo.remove(b)
        self.assertEqual(sm.final_states, [])

    def test_link_side_lists_cleaned(self):
        repo = _vehicle()
        V, R = repo.resolve("Vehicle"), repo.add(RequirementDefinition(name="R"))
        create_link("satisfy", V, R)
        repo.remove(V)
        self.assertEqual(R.satisfied_by, [])
        self.assertEqual(links_of(R, direction="incoming"), [])

    def test_removal_hook_called(self):
        seen = []
        register_removal_hook(lambda repo, ids: seen.append(len(ids)))
        try:
            repo = _vehicle()
            repo.remove(repo.resolve("Trans"))
            self.assertTrue(seen and seen[0] >= 2)   # Trans + its port
        finally:
            repo_module._REMOVAL_HOOKS.pop()


class HttpPropertyTests(WebAppTestCase):

    def test_direction_patch_then_get(self):
        self.call("POST", "/api/new", {"name": "T"})
        p = self.call("POST", "/api/element", {"kind": "PortUsage", "name": "p"})
        out = self.call("PATCH", f"/api/element/{p['id']}", {"props": {"direction": "out"}})
        self.assertEqual(out["direction"], "out")
        self.assertEqual(self.call("GET", f"/api/element/{p['id']}")["direction"], "out")
        self.call("GET", "/api/save")

    def test_bad_props_return_400(self):
        self.call("POST", "/api/new", {"name": "T"})
        c = self.call("POST", "/api/element", {"kind": "ConnectionUsage", "name": "c"})
        self.call("PATCH", f"/api/element/{c['id']}", {"props": {"ends": ["x"]}}, expect=400)
        self.call("PATCH", f"/api/element/{c['id']}", {"props": {"direction": "up"}}, expect=400)
        self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "Z",
                                          "properties": {"bogus": 1}}, expect=400)
        names = [ch["name"] for ch in self.call("GET", "/api/tree")["children"]]
        self.assertNotIn("Z", names)


class McpPropertyTests(unittest.TestCase):

    def test_mcp_set_property_coerces_and_rejects(self):
        from mcp_server import server as m
        m.SESSION.set_repo(Repository("M"))
        p = m.tool_create_element("PortUsage", "p")["result"]
        self.assertTrue(m.tool_set_property(p["id"], "direction", "in")["ok"])
        self.assertFalse(m.tool_set_property(p["id"], "ends", ["x"])["ok"])
        to_json(m.SESSION.repo)


if __name__ == "__main__":
    unittest.main()
