"""Tests for the shared extension points that feature modules build on."""
import unittest

from engine import (
    Repository, Validator, ValidationIssue, Severity, export_knowledge_graph,
    from_json, register_codec, register_edge_source, register_repo_codec,
    register_rule, to_json,
)
from engine import graph_export, serializer, validator
from sysmlv2 import PartDefinition
from tests.webapp_harness import WebAppTestCase
from webapp import core


def _encode_rating(e):
    return getattr(e, "rating", None)


def _decode_rating(e, data, by_id):
    e.rating = data


def _encode_notes(repo):
    return getattr(repo, "notes", None)


def _decode_notes(repo, data, by_id):
    repo.notes = data


class SerializerExtensionTests(unittest.TestCase):

    def setUp(self):
        register_codec("test-rating", _encode_rating, _decode_rating)
        register_repo_codec("test-notes", _encode_notes, _decode_notes)

    def tearDown(self):
        serializer._CODECS.pop("test-rating", None)
        serializer._REPO_CODECS.pop("test-notes", None)

    def test_element_and_repo_codecs_round_trip(self):
        repo = Repository("P")
        v = repo.add(PartDefinition(name="V"))
        v.rating = 5
        repo.notes = ["hello"]
        text = to_json(repo)
        loaded = from_json(text)
        self.assertEqual(loaded.resolve("V").rating, 5)
        self.assertEqual(loaded.notes, ["hello"])
        self.assertEqual(text, to_json(loaded))

    def test_tool_data_persists_and_skips_unserializable(self):
        repo = Repository("P")
        v = repo.add(PartDefinition(name="V"))
        v.tool_data["layout"] = {"x": 10, "y": 20, "w": 120, "h": 80}
        v.tool_data["handle"] = object()
        loaded = from_json(to_json(repo))
        self.assertEqual(loaded.resolve("V").tool_data, {"layout": {"x": 10, "y": 20, "w": 120, "h": 80}})


class RuleAndEdgeRegistryTests(unittest.TestCase):

    def tearDown(self):
        validator._ELEMENT_RULES.clear()
        graph_export._EDGE_SOURCES.clear()

    def test_registered_rule_runs(self):
        def no_x(e):
            if getattr(e, "name", None) == "X":
                yield ValidationIssue(Severity.ERROR, "test.no-x", "X is not allowed", e)
        register_rule(no_x)
        repo = Repository("P")
        repo.add(PartDefinition(name="X"))
        rules = [i.rule for i in Validator().validate(repo)]
        self.assertIn("test.no-x", rules)

    def test_registered_edge_source_exported(self):
        repo = Repository("P")
        a = repo.add(PartDefinition(name="A"))
        b = repo.add(PartDefinition(name="B"))
        register_edge_source(lambda e: [("dependsOn", e, b, {})] if e is a else [])
        self.assertIn("sysml:dependsOn", export_knowledge_graph(repo.root_package, "turtle"))


class WebPluginApiTests(WebAppTestCase):

    def test_plugin_route_and_hooks(self):
        core.route("GET", r"^/api/test-echo/(?P<word>[a-z]+)$")(
            lambda req, word: core.ok({"word": word, "q": req["query"]}))
        core.register_summary_hook(lambda e, d: d.setdefault("test_flag", True))
        core.register_prop_hook(lambda e, k, v: k == "test_prop" and setattr(e, "test_prop", v * 2) is None)
        try:
            self.assertEqual(self.call("GET", "/api/test-echo/hi?x=1"), {"word": "hi", "q": {"x": "1"}})
            self.call("POST", "/api/new", {"name": "T"})
            el = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "V"})
            self.assertTrue(el["test_flag"])
            self.call("PATCH", f"/api/element/{el['id']}", {"props": {"test_prop": 21}})
            self.assertEqual(core.session().find(el["id"]).test_prop, 42)
        finally:
            core.PLUGIN_ROUTES.pop()
            core._SUMMARY_HOOKS.pop()
            core._PROP_HOOKS.pop()

    def test_tool_data_merges_over_http(self):
        self.call("POST", "/api/new", {"name": "T"})
        el = self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "V"})
        self.call("PATCH", f"/api/element/{el['id']}", {"props": {"tool_data": {"layout": {"x": 1}}}})
        out = self.call("PATCH", f"/api/element/{el['id']}", {"props": {"tool_data": {"color": "red"}}})
        self.assertEqual(out["tool_data"], {"layout": {"x": 1}, "color": "red"})

    def test_plugins_endpoint_and_studio_api_shipped(self):
        self.assertIsInstance(self.call("GET", "/api/plugins"), list)
        js = self.get_text("/static/app.js")
        for name in ("registerTab", "registerToolbarButton", "registerInspectorSection",
                     "registerTreeBadge", "registerShortcut", "loadPlugins"):
            self.assertIn(name, js)

    def test_new_project_clears_plugin_state(self):
        core.session().plugin_state["x"] = 1
        self.call("POST", "/api/new", {"name": "T"})
        self.assertEqual(core.session().plugin_state, {})


class McpCoreTests(unittest.TestCase):

    def test_server_shares_core_session_and_loads_tool_plugins(self):
        from mcp_server import core as mcore, server as msrv
        from mcp_server.tools import load_tools
        self.assertIs(msrv.SESSION, mcore.SESSION)
        self.assertIsInstance(load_tools(), list)
        self.assertIn("sysml_create_element", msrv.TOOL_BY_NAME)


if __name__ == "__main__":
    unittest.main()


class CreatedHookTests(WebAppTestCase):

    def test_created_hook_runs_for_web_and_mcp(self):
        from engine import hooks, register_created_hook
        seen = []
        register_created_hook(lambda e, repo: seen.append(e.name))
        try:
            self.call("POST", "/api/new", {"name": "T"})
            self.call("POST", "/api/element", {"kind": "PartDefinition", "name": "WebMade"})
            from mcp_server import server as m
            m.tool_create_element("PartDefinition", "McpMade")
            self.assertEqual(seen, ["WebMade", "McpMade"])
        finally:
            hooks._CREATED_HOOKS.pop()
