"""Engine tests for requirements and traceability (engine/requirements.py)."""
import json
import unittest

import engine.requirements as rq
from engine import Repository, Validator, export_knowledge_graph, from_json, to_json
from engine.properties import set_property
from sysmlv2 import ActionDefinition, PartDefinition, PartUsage, PortUsage, RequirementDefinition


def _model():
    repo = Repository("Avionics")
    arch = repo.add(PartDefinition(name="Aircraft"))
    fcc = PartUsage(name="FCC")
    adc = PartUsage(name="ADC")
    for c in (fcc, adc):
        arch.own(c)
    port = PortUsage(name="air_data")
    fcc.own(port)
    repo.registry.register_tree(arch)
    s = rq.create_requirement_set(repo, "FlightControls", prefix="FCS-")
    r1 = rq.add_requirement(repo, s, {"summary": "Pitch control", "description": "Control pitch.",
                                      "type": "functional"})
    r2 = rq.add_requirement(repo, s, {"summary": "Roll control"})
    r11 = rq.add_requirement(repo, r1, {"summary": "Pitch rate limit"})
    return repo, arch, fcc, adc, port, s, r1, r2, r11


class AuthoringTests(unittest.TestCase):

    def setUp(self):
        rq.install()
        (self.repo, self.arch, self.fcc, self.adc, self.port,
         self.set, self.r1, self.r2, self.r11) = _model()

    def test_set_and_auto_numbering(self):
        self.assertIsInstance(self.set, rq.RequirementSet)
        self.assertEqual([r.req_id for r, _d, _i in rq.walk_requirements(self.set)],
                         ["FCS-1", "FCS-3", "FCS-2"])
        self.assertEqual([i for _r, _d, i in rq.walk_requirements(self.set)], ["1", "1.1", "2"])
        self.assertIs(self.r11.owner, self.r1)
        self.assertIs(rq.set_of(self.r11), self.set)
        self.assertEqual(rq.next_req_id(self.set), "FCS-4")
        self.assertEqual(self.r1.req_type, "functional")
        self.assertEqual(self.r1.text, "Control pitch.")

    def test_default_summaries_are_unique(self):
        a = rq.add_requirement(self.repo, self.set)
        b = rq.add_requirement(self.repo, self.set)
        self.assertEqual((a.name, b.name), ("New requirement", "New requirement (2)"))

    def test_insert_after_sibling(self):
        mid = rq.add_requirement(self.repo, self.set, {"summary": "Yaw"}, after=self.r1)
        self.assertEqual([r.name for r in rq.child_requirements(self.set)],
                         ["Pitch control", "Yaw", "Roll control"])
        self.assertEqual(mid.req_id, "FCS-4")

    def test_field_validation(self):
        with self.assertRaisesRegex(rq.RequirementsError, "already used"):
            rq.update_requirement(self.repo, self.r2, {"id": "FCS-1"})
        with self.assertRaisesRegex(rq.RequirementsError, "Invalid type 'banana'.*functional"):
            rq.update_requirement(self.repo, self.r2, {"type": "banana"})
        with self.assertRaisesRegex(rq.RequirementsError, "unique among siblings"):
            rq.update_requirement(self.repo, self.r2, {"summary": "Pitch control"})
        with self.assertRaisesRegex(rq.RequirementsError, "Unknown requirement field"):
            rq.update_requirement(self.repo, self.r2, {"colour": "red"})
        with self.assertRaisesRegex(rq.RequirementsError, "cannot be empty"):
            rq.update_requirement(self.repo, self.r2, {"summary": "  "})
        # Atomic: a bad field leaves the good ones unapplied.
        with self.assertRaises(rq.RequirementsError):
            rq.update_requirement(self.repo, self.r2, {"priority": "high", "status": "nope"})
        self.assertIsNone(self.r2.priority)

    def test_enum_normalisation_and_clearing(self):
        rq.update_requirement(self.repo, self.r2, {"type": "Design Constraint", "priority": "H",
                                                   "status": "Approved", "verification_method": "T"})
        self.assertEqual((self.r2.req_type, self.r2.priority, self.r2.req_status,
                          self.r2.verification_method),
                         ("design-constraint", "high", "approved", "test"))
        rq.update_requirement(self.repo, self.r2, {"priority": ""})
        self.assertIsNone(self.r2.priority)

    def test_generic_property_editor_can_set_new_scalars(self):
        set_property(self.r2, "rationale", "Because DO-178C", self.repo.by_id)
        set_property(self.r2, "req_type", "safety", self.repo.by_id)
        self.assertEqual((self.r2.rationale, self.r2.req_type), ("Because DO-178C", "safety"))

    def test_move_up_down_indent_outdent(self):
        names = lambda c: [r.name for r in rq.child_requirements(c)]  # noqa: E731
        rq.move_requirement(self.repo, self.r2, "up")
        self.assertEqual(names(self.set), ["Roll control", "Pitch control"])
        rq.move_requirement(self.repo, self.r2, "down")
        self.assertEqual(names(self.set), ["Pitch control", "Roll control"])
        rq.move_requirement(self.repo, self.r2, "indent")
        self.assertEqual(names(self.r1), ["Pitch rate limit", "Roll control"])
        rq.move_requirement(self.repo, self.r2, "outdent")
        self.assertEqual(names(self.set), ["Pitch control", "Roll control"])
        self.assertEqual(names(self.r1), ["Pitch rate limit"])
        # The old parent no longer resolves the moved child by name.
        self.assertIsNone(self.r1.resolve("Roll control"))
        self.assertIs(self.repo.resolve("FlightControls::Roll control"), self.r2)
        for bad in (("up", self.r1), ("indent", self.r1), ("outdent", self.r1), ("down", self.r2),
                    ("sideways", self.r2)):
            with self.assertRaises(rq.RequirementsError):
                rq.move_requirement(self.repo, bad[1], bad[0])

    def test_test_cases(self):
        tc = rq.add_test_case(self.repo, self.set, "Pitch step test", description="Step input")
        self.assertEqual(rq.test_result(tc), "unexecuted")
        rq.update_test_case(self.repo, tc, {"result": "Pass"})
        self.assertEqual(rq.test_result(tc), "passed")
        with self.assertRaisesRegex(rq.RequirementsError, "Invalid test result"):
            rq.update_test_case(self.repo, tc, {"result": "maybe"})
        with self.assertRaises(rq.RequirementsError):
            rq.add_test_case(self.repo, self.set, "Pitch step test")

    def test_delete_requirement_removes_children_and_links(self):
        rq.create_trace_link(self.repo, "implement", self.fcc, self.r11)
        deleted = rq.delete_requirement(self.repo, self.r1)
        self.assertEqual(len(deleted), 2)
        self.assertEqual(rq.trace_links(self.repo), [])
        self.assertIsNone(self.repo.by_id(self.r11.element_id))


class LinkTests(unittest.TestCase):

    def setUp(self):
        rq.install()
        (self.repo, self.arch, self.fcc, self.adc, self.port,
         self.set, self.r1, self.r2, self.r11) = _model()

    def test_endpoint_rules(self):
        tc = rq.add_test_case(self.repo, self.set, "T1")
        fn = self.repo.add(ActionDefinition(name="ComputeAttitude"))
        ok = [("implement", self.fcc, self.r1), ("implement", self.port, self.r1),
              ("implement", fn, self.r2), ("verify", tc, self.r1), ("derive", self.r11, self.r2),
              ("refine", self.r11, self.r1), ("relate", self.fcc, self.adc), ("confirm", tc, self.r2)]
        for t, s, d in ok:
            rq.create_trace_link(self.repo, t, s, d)
        bad = [("implement", self.r1, self.r2, "Derive or Refine"), ("verify", self.fcc, self.r1, "test case"),
               ("derive", self.fcc, self.r1, "requirement as source"),
               ("implement", self.fcc, self.adc, "requirement as destination"),
               ("relate", self.fcc, self.fcc, "itself"), ("teleport", self.fcc, self.r1, "Unknown link type"),
               ("implement", self.fcc, self.r1, "already implements")]
        for t, s, d, msg in bad:
            with self.assertRaisesRegex(rq.RequirementsError, msg):
                rq.create_trace_link(self.repo, t, s, d)
        self.assertEqual(len(rq.trace_links(self.repo)), len(ok))

    def test_aliases_and_core_link_kinds(self):
        from engine import link_kind
        self.assertIs(rq.trace_type("satisfy"), rq.trace_type("implement"))
        self.assertIs(rq.trace_type("Trace"), rq.trace_type("relate"))
        self.assertIs(link_kind("confirm").cls, rq.Confirm)
        self.assertIs(link_kind("implement").cls, rq.Satisfy)

    def test_implementation_rollup(self):
        rq.create_trace_link(self.repo, "implement", self.fcc, self.r11)
        t = rq.requirements_table(self.repo, self.set)
        rows = {r["req_id"]: r for r in t["rows"]}
        self.assertTrue(rows["FCS-3"]["implementation"]["direct"])
        # FCS-1's only child is implemented, so FCS-1 is implemented as well.
        self.assertTrue(rows["FCS-1"]["implementation"]["implemented"])
        self.assertFalse(rows["FCS-1"]["implementation"]["direct"])
        self.assertEqual(rows["FCS-2"]["implementation"]["pct"], 0)
        self.assertEqual(t["sets"][0]["implementation"], {"done": 1, "total": 2, "pct": 50})
        # A parent's own Implement link covers all its leaves.
        r12 = rq.add_requirement(self.repo, self.r1, {"summary": "Pitch trim"})
        rq.create_trace_link(self.repo, "implement", self.adc, self.r1)
        st = rq.requirement_status(self.repo, r12)["requirement"]
        self.assertTrue(st["implementation"]["implemented"])

    def test_verification_states(self):
        t_pass = rq.add_test_case(self.repo, self.set, "P", result="passed")
        t_fail = rq.add_test_case(self.repo, self.set, "F", result="failed")
        t_new = rq.add_test_case(self.repo, self.set, "N")
        rq.create_trace_link(self.repo, "verify", t_pass, self.r11)
        state = lambda r: rq.requirement_status(self.repo, r)["requirement"]["verification"]  # noqa: E731
        self.assertEqual(state(self.r11)["state"], "passed")
        self.assertEqual(state(self.r1)["state"], "passed")
        self.assertEqual(state(self.r2)["state"], "missing")
        rq.create_trace_link(self.repo, "verify", t_new, self.r2)
        self.assertEqual(state(self.r2)["state"], "unexecuted")
        rq.create_trace_link(self.repo, "verify", t_fail, self.r2)
        self.assertEqual(state(self.r2)["state"], "failed")
        s = rq.set_summary(self.repo, self.set)["verification"]
        self.assertEqual((s["passed"], s["failed"], s["total"], s["pct"]), (1, 1, 2, 50))
        r12 = rq.add_requirement(self.repo, self.r1, {"summary": "Trim"})
        self.assertEqual(state(self.r1)["state"], "partial")
        self.assertEqual(state(r12)["state"], "missing")

    def test_suspect_links_and_clear(self):
        link = rq.create_trace_link(self.repo, "implement", self.fcc, self.r1)
        derive = rq.create_trace_link(self.repo, "derive", self.r11, self.r2)
        self.assertFalse(rq.is_suspect(link))
        rq.update_requirement(self.repo, self.r1, {"priority": "high"})       # not a text field
        self.assertFalse(rq.is_suspect(link))
        rq.update_requirement(self.repo, self.r1, {"description": "Control pitch within 2 deg."})
        self.assertTrue(rq.is_suspect(link))
        self.assertEqual(rq.suspect_ends(link), ["target"])
        self.assertFalse(rq.is_suspect(derive))
        rq.update_requirement(self.repo, self.r11, {"rationale": "Handling qualities"})
        self.assertEqual(rq.suspect_ends(derive), ["source"])
        rules = [i.rule for i in Validator().validate(self.repo)]
        self.assertEqual(rules.count("requirements.suspect-link"), 2)
        rq.clear_suspect(self.repo, link)
        self.assertFalse(rq.is_suspect(link))
        self.assertEqual(rq.clear_suspect_for(self.repo), 1)
        self.assertNotIn("requirements.suspect-link", [i.rule for i in Validator().validate(self.repo)])

    def test_untracked_links_are_baselined_before_edits(self):
        from engine import create_link
        rel = create_link("satisfy", self.fcc, self.r2)       # generic API: no baseline
        self.assertFalse(rq.link_info(rel)["tracked"])
        rq.update_requirement(self.repo, self.r2, {"summary": "Roll control law"})
        self.assertTrue(rq.is_suspect(rel))

    def test_delete_link_keeps_back_references_in_step(self):
        link = rq.create_trace_link(self.repo, "implement", self.fcc, self.r1)
        self.assertIn(self.fcc, self.r1.satisfied_by)
        rq.delete_trace_link(self.repo, link)
        self.assertNotIn(self.fcc, self.r1.satisfied_by)
        self.assertEqual(rq.trace_links(self.repo), [])
        self.assertIsNone(self.repo.by_id(link.element_id))
        with self.assertRaises(rq.RequirementsError):
            rq.delete_trace_link(self.repo, link)

    def test_all_links_and_set_scoped_suspect_clearing(self):
        other = rq.create_requirement_set(self.repo, "HLR", prefix="HLR-")
        h1 = rq.add_requirement(self.repo, other, {"summary": "Pitch law"})
        rq.create_trace_link(self.repo, "implement", self.fcc, self.r1)
        rq.create_trace_link(self.repo, "derive", h1, self.r11)
        tc = rq.add_test_case(self.repo, other, "HLR test")
        rq.create_trace_link(self.repo, "verify", tc, h1)
        self.assertEqual(len(rq.all_links(self.repo)), 3)
        self.assertEqual({l["type"] for l in rq.all_links(self.repo, self.set)}, {"implement", "derive"})
        self.assertEqual({l["type"] for l in rq.all_links(self.repo, other)}, {"derive", "verify"})
        rq.update_requirement(self.repo, self.r1, {"description": "changed"})
        rq.update_requirement(self.repo, h1, {"description": "changed too"})
        suspect = rq.all_links(self.repo, suspect_only=True)
        self.assertEqual({(l["type"], tuple(l["suspect_ends"])) for l in suspect},
                         {("implement", ("target",)), ("derive", ("source",)), ("verify", ("target",))})
        table = rq.requirements_table(self.repo, other)
        self.assertEqual((table["link_count"], table["suspect_link_count"]), (2, 2))
        # Clearing a set only touches links of its requirements and test cases.
        self.assertEqual(rq.clear_suspect_for(self.repo, other), 2)
        self.assertEqual([l["type"] for l in rq.all_links(self.repo, suspect_only=True)], ["implement"])

    def test_links_for_and_directions(self):
        rq.create_trace_link(self.repo, "implement", self.fcc, self.r1)
        rq.create_trace_link(self.repo, "derive", self.r11, self.r1)
        links = rq.links_for(self.repo, self.r1)
        self.assertEqual({(l["type"], l["direction"], l["other"]["name"]) for l in links},
                         {("implement", "incoming", "FCC"), ("derive", "incoming", "Pitch rate limit")})
        self.assertEqual(rq.links_for(self.repo, self.fcc)[0]["direction"], "outgoing")


class MatrixDiagramTests(unittest.TestCase):

    def setUp(self):
        rq.install()
        (self.repo, self.arch, self.fcc, self.adc, self.port,
         self.set, self.r1, self.r2, self.r11) = _model()

    def test_matrix(self):
        rq.create_trace_link(self.repo, "implement", self.fcc, self.r1)
        m = rq.trace_matrix(self.repo, self.set, "components")
        self.assertEqual([c["name"] for c in m["columns"]], ["Aircraft", "FCC", "ADC"])
        self.assertEqual(len(m["cells"]), 1)
        cell = m["cells"][0]
        self.assertEqual((cell["row"], cell["col"]), (self.r1.element_id, self.fcc.element_id))
        self.assertEqual(cell["links"][0]["direction"], "incoming")
        self.assertIn(self.r2.element_id, m["unlinked_rows"])
        self.assertIn(self.adc.element_id, m["unlinked_columns"])
        reqs = rq.trace_matrix(self.repo, self.set, "requirements", self.set)
        self.assertEqual(len(reqs["columns"]), 3)
        self.assertEqual(rq.trace_matrix(self.repo, self.set, "ports")["columns"][0]["name"], "air_data")
        with self.assertRaisesRegex(rq.RequirementsError, "Unknown column kind"):
            rq.trace_matrix(self.repo, self.set, "widgets")
        csv_text = rq.matrix_csv(self.repo, self.set, "components")
        self.assertIn("← Implement", csv_text)
        self.assertTrue(csv_text.startswith("Index,ID,Summary,Aircraft,FCC,ADC"))

    def test_diagram_follows_derive_chain(self):
        # system req <- derived req <- implemented by FCC: a multi-level chain.
        rq.create_trace_link(self.repo, "derive", self.r2, self.r1)
        rq.create_trace_link(self.repo, "implement", self.fcc, self.r2)
        d1 = rq.trace_diagram(self.repo, self.r1, 1)
        d2 = rq.trace_diagram(self.repo, self.r1, 2)
        self.assertEqual({n["label"] for n in d1["nodes"]}, {"FCS-1 Pitch control", "FCS-2 Roll control"})
        self.assertIn("FCC", {n["label"] for n in d2["nodes"]})
        self.assertTrue(d2["text"].startswith("flowchart LR"))
        self.assertIn('"derives from"', d2["text"])
        rq.update_requirement(self.repo, self.r2, {"description": 'Roll "fast" <now>; #1'})
        d3 = rq.trace_diagram(self.repo, self.r1, 2)
        self.assertIn("-.->", d3["text"])
        self.assertIn("linkStyle", d3["text"])
        with self.assertRaises(rq.RequirementsError):
            rq.trace_diagram(self.repo, self.r1, "deep")

    def test_mermaid_escaping(self):
        rq.update_requirement(self.repo, self.r1, {"summary": 'A "quoted" <b>|x|; #1 [y]'})
        text = rq.trace_diagram(self.repo, self.r1, 1)["text"]
        label_line = text.splitlines()[1]
        summary = label_line.split("<br/>", 1)[1].rsplit('"]', 1)[0]
        for ch in '"<>|[]':
            self.assertNotIn(ch, summary)
        self.assertEqual(summary, "A #quot;quoted#quot; #lt;b#gt;#124;x#124;#59; #35;1 #91;y#93;")


class PersistenceTests(unittest.TestCase):

    def setUp(self):
        rq.install()

    def test_round_trip(self):
        repo, arch, fcc, adc, port, s, r1, r2, r11 = _model()
        rq.update_requirement(repo, r2, {"rationale": "DO-178C", "priority": "high", "status": "reviewed",
                                         "verification_method": "analysis", "type": "safety"})
        rq.move_requirement(repo, r2, "up")
        tc = rq.add_test_case(repo, s, "T1", result="failed")
        rq.create_trace_link(repo, "verify", tc, r2)
        link = rq.create_trace_link(repo, "implement", fcc, r1)
        rq.create_trace_link(repo, "confirm", adc, r1)
        rq.update_requirement(repo, r1, {"description": "changed"})
        loaded = from_json(to_json(repo))
        # The core saves elements in registry order (creation order before the first load,
        # containment order after it), so the text is stable from the second save on.
        text = to_json(loaded)
        self.assertEqual(to_json(from_json(text)), text)
        ls = rq.requirement_sets(loaded)[0]
        self.assertEqual(ls.id_prefix, "FCS-")
        self.assertEqual([r.req_id for r, _d, _i in rq.walk_requirements(ls)], ["FCS-2", "FCS-1", "FCS-3"])
        lr2 = loaded.by_id(r2.element_id)
        self.assertEqual((lr2.rationale, lr2.priority, lr2.req_status, lr2.verification_method,
                          lr2.req_type), ("DO-178C", "high", "reviewed", "analysis", "safety"))
        self.assertEqual(rq.test_result(loaded.by_id(tc.element_id)), "failed")
        self.assertTrue(rq.is_suspect(loaded.by_id(link.element_id)))
        self.assertEqual({rq.type_of(r).name for r in rq.trace_links(loaded)},
                         {"verify", "implement", "confirm"})
        self.assertIn(loaded.by_id(fcc.element_id), loaded.by_id(r1.element_id).satisfied_by)

    def test_validator_rules(self):
        repo, arch, fcc, adc, port, s, r1, r2, r11 = _model()
        r2.req_id = "FCS-1"                        # bypassing the API
        r1.req_type = "bogus"
        r11.req_status = "verified"
        issues = {(i.rule, i.element.name) for i in Validator().validate(repo)}
        self.assertIn(("requirements.duplicate-id", "Roll control"), issues)
        self.assertIn(("requirements.invalid-value", "Pitch control"), issues)
        self.assertIn(("requirements.status-mismatch", "Pitch rate limit"), issues)
        from engine import create_link
        create_link("verify", fcc, r2)             # verify from a non-test element
        rules = [i.rule for i in Validator().validate(repo)]
        self.assertIn("requirements.link-endpoint", rules)

    def test_knowledge_graph_and_dot_compatibility(self):
        repo, arch, fcc, adc, port, s, r1, r2, r11 = _model()
        rq.create_trace_link(repo, "confirm", adc, r1)
        self.assertIn("sysml:confirms", export_knowledge_graph(repo.root_package, "turtle"))
        # engine.requirements is both this module and (callable) the DOT requirements diagram.
        from engine import requirements as legacy
        self.assertIn("digraph", legacy(repo.root_package))


class ImportExportTests(unittest.TestCase):

    def setUp(self):
        rq.install()
        self.repo = Repository("P")
        self.set = rq.create_requirement_set(self.repo, "SRS", prefix="SRS-")

    def test_csv_import_with_hierarchy_and_update(self):
        text = ("id,summary,description,type,priority,parent_id\n"
                "SRS-1.1,Child,Child text,performance,low,SRS-1\n"
                "SRS-1,Parent,Parent text,functional,high,\n"
                "SRS-2,Other,,wrong-type,2,\n")
        rep = rq.import_csv(self.repo, text, self.set)
        self.assertEqual((rep["created"], rep["updated"]), (3, 0))
        self.assertEqual(len(rep["warnings"]), 1)
        self.assertIn("wrong-type", rep["warnings"][0])
        rows = [(r.req_id, d, r.name, r.req_type, r.priority) for r, d, _i in rq.walk_requirements(self.set)]
        self.assertEqual(rows, [("SRS-1", 0, "Parent", "functional", "high"),
                                ("SRS-1.1", 1, "Child", "performance", "low"),
                                ("SRS-2", 0, "Other", None, "medium")])
        rep2 = rq.import_csv(self.repo, "ID;Summary;Description\nSRS-2;Other renamed;Now with text\n",
                             self.set)
        self.assertEqual((rep2["created"], rep2["updated"]), (0, 1))
        r = self.repo.resolve("SRS::Other renamed")
        self.assertEqual(r.text, "Now with text")

    def test_csv_errors(self):
        with self.assertRaisesRegex(rq.RequirementsError, "'id' or a 'summary'"):
            rq.import_csv(self.repo, "foo,bar\n1,2\n", self.set)
        with self.assertRaisesRegex(rq.RequirementsError, "empty"):
            rq.import_csv(self.repo, "   ", self.set)

    def test_export_csv_reimports(self):
        rq.import_csv(self.repo, "id,summary,parent_id\nA,a,\nB,b,A\n", self.set)
        out = rq.export_csv(self.repo, self.set)
        repo2 = Repository("Q")
        rep = rq.import_requirements(repo2, "csv", out, new_set="Copy")
        self.assertEqual(rep["created"], 2)
        s2 = rq.requirement_sets(repo2)[0]
        self.assertEqual([(r.req_id, d) for r, d, _i in rq.walk_requirements(s2)], [("A", 0), ("B", 1)])

    def test_reqif_round_trip(self):
        a = rq.add_requirement(self.repo, self.set, {"summary": "Top", "description": "T & <x>",
                                                     "rationale": "why", "type": "safety"})
        b = rq.add_requirement(self.repo, a, {"summary": "Sub"})
        rq.create_trace_link(self.repo, "derive", b, a)
        xml = rq.export_reqif(self.repo, self.set)
        self.assertIn("<REQ-IF xmlns=\"http://www.omg.org/spec/ReqIF/20110401/reqif.xsd\">", xml)
        repo2 = Repository("Q")
        rep = rq.import_requirements(repo2, "reqif", xml)
        self.assertEqual((rep["created"], rep["linked"], rep["set"]), (2, 1, "SRS"))
        s2 = rq.requirement_sets(repo2)[0]
        got = [(r.req_id, d, r.name, r.text, r.rationale, r.req_type) for r, d, _i in rq.walk_requirements(s2)]
        self.assertEqual(got, [("SRS-1", 0, "Top", "T & <x>", "why", "safety"),
                               ("SRS-2", 1, "Sub", None, None, None)])
        self.assertEqual([rq.type_of(l).name for l in rq.trace_links(repo2)], ["derive"])

    def test_reqif_foreign_document(self):
        doc = """<?xml version="1.0" encoding="UTF-8"?>
<REQ-IF xmlns="http://www.omg.org/spec/ReqIF/20110401/reqif.xsd" xmlns:xhtml="http://www.w3.org/1999/xhtml">
 <CORE-CONTENT><REQ-IF-CONTENT>
  <DATATYPES>
   <DATATYPE-DEFINITION-ENUMERATION IDENTIFIER="DT-PRIO"><SPECIFIED-VALUES>
     <ENUM-VALUE IDENTIFIER="EV-H" LONG-NAME="High"/></SPECIFIED-VALUES></DATATYPE-DEFINITION-ENUMERATION>
  </DATATYPES>
  <SPEC-TYPES><SPEC-OBJECT-TYPE IDENTIFIER="T"><SPEC-ATTRIBUTES>
   <ATTRIBUTE-DEFINITION-STRING IDENTIFIER="A1" LONG-NAME="ReqIF.ForeignID"/>
   <ATTRIBUTE-DEFINITION-XHTML IDENTIFIER="A2" LONG-NAME="ReqIF.Text"/>
   <ATTRIBUTE-DEFINITION-ENUMERATION IDENTIFIER="A3" LONG-NAME="Priority"/>
   <ATTRIBUTE-DEFINITION-STRING IDENTIFIER="A4" LONG-NAME="Owner"/>
  </SPEC-ATTRIBUTES></SPEC-OBJECT-TYPE></SPEC-TYPES>
  <SPEC-OBJECTS>
   <SPEC-OBJECT IDENTIFIER="O1" LONG-NAME="Altitude hold"><VALUES>
    <ATTRIBUTE-VALUE-STRING THE-VALUE="AP-7"><DEFINITION><ATTRIBUTE-DEFINITION-STRING-REF>A1</ATTRIBUTE-DEFINITION-STRING-REF></DEFINITION></ATTRIBUTE-VALUE-STRING>
    <ATTRIBUTE-VALUE-XHTML><DEFINITION><ATTRIBUTE-DEFINITION-XHTML-REF>A2</ATTRIBUTE-DEFINITION-XHTML-REF></DEFINITION>
      <THE-VALUE><xhtml:div>Hold <xhtml:b>altitude</xhtml:b> within 50 ft.</xhtml:div></THE-VALUE></ATTRIBUTE-VALUE-XHTML>
    <ATTRIBUTE-VALUE-ENUMERATION><DEFINITION><ATTRIBUTE-DEFINITION-ENUMERATION-REF>A3</ATTRIBUTE-DEFINITION-ENUMERATION-REF></DEFINITION>
      <VALUES><ENUM-VALUE-REF>EV-H</ENUM-VALUE-REF></VALUES></ATTRIBUTE-VALUE-ENUMERATION>
    <ATTRIBUTE-VALUE-STRING THE-VALUE="Bob"><DEFINITION><ATTRIBUTE-DEFINITION-STRING-REF>A4</ATTRIBUTE-DEFINITION-STRING-REF></DEFINITION></ATTRIBUTE-VALUE-STRING>
   </VALUES></SPEC-OBJECT>
   <SPEC-OBJECT IDENTIFIER="O2" LONG-NAME="Orphan"/>
  </SPEC-OBJECTS>
  <SPECIFICATIONS><SPECIFICATION IDENTIFIER="S1" LONG-NAME="Autopilot SRS"><CHILDREN>
   <SPEC-HIERARCHY IDENTIFIER="H1"><OBJECT><SPEC-OBJECT-REF>O1</SPEC-OBJECT-REF></OBJECT></SPEC-HIERARCHY>
  </CHILDREN></SPECIFICATION></SPECIFICATIONS>
 </REQ-IF-CONTENT></CORE-CONTENT>
</REQ-IF>"""
        rep = rq.import_requirements(self.repo, "reqif", doc)
        self.assertEqual(rep["set"], "Autopilot SRS")
        self.assertEqual(rep["ignored_attributes"], ["Owner"])
        s = self.repo.resolve("Autopilot SRS")
        reqs = [r for r, _d, _i in rq.walk_requirements(s)]
        self.assertEqual([(r.req_id, r.name) for r in reqs][0], ("AP-7", "Altitude hold"))
        self.assertEqual(reqs[0].text, "Hold altitude within 50 ft.")
        self.assertEqual(reqs[0].priority, "high")
        self.assertEqual(reqs[1].name, "Orphan")

    def test_reqif_rejects_dtd_and_entities(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>'
                "<REQ-IF>&lol2;</REQ-IF>")
        with self.assertRaisesRegex(rq.RequirementsError, "DOCTYPE or ENTITY"):
            rq.import_reqif(self.repo, bomb, self.set)
        xxe = '<!doctype x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><REQ-IF>&xxe;</REQ-IF>'
        with self.assertRaisesRegex(rq.RequirementsError, "DOCTYPE or ENTITY"):
            rq.import_reqif(self.repo, xxe, self.set)
        with self.assertRaisesRegex(rq.RequirementsError, "Not a ReqIF"):
            rq.import_reqif(self.repo, "<html/>", self.set)
        with self.assertRaisesRegex(rq.RequirementsError, "Malformed XML"):
            rq.import_reqif(self.repo, "<REQ-IF>", self.set)
        self.assertEqual(rq.child_requirements(self.set), [])

    def test_reports(self):
        a = rq.add_requirement(self.repo, self.set, {"summary": "Alpha"})
        rq.add_requirement(self.repo, self.set, {"summary": "Beta <script>"})
        arch = self.repo.add(PartDefinition(name="Sys"))
        link = rq.create_trace_link(self.repo, "implement", arch, a)
        rq.update_requirement(self.repo, a, {"description": "edited"})
        html_text = rq.export_requirements(self.repo, "report-html", self.set)["text"]
        self.assertIn("Requirements traceability report", html_text)
        self.assertIn("Beta &lt;script&gt;", html_text)
        self.assertNotIn("<script>", html_text)
        self.assertIn("Sys implements SRS-1 Alpha", html_text)
        csv_text = rq.export_requirements(self.repo, "report-csv", self.set)["text"]
        self.assertIn("SRS-1,Alpha,100,missing,Implement,incoming,P::Sys,PartDefinition,yes", csv_text)
        self.assertTrue(rq.is_suspect(link))
        with self.assertRaises(rq.RequirementsError):
            rq.export_requirements(self.repo, "pdf", self.set)


class ModelTests(unittest.TestCase):

    def test_requirement_set_rules(self):
        repo = Repository("P")
        s = rq.create_requirement_set(repo, "S")
        with self.assertRaisesRegex(rq.RequirementsError, "already contains"):
            rq.create_requirement_set(repo, "S")
        with self.assertRaisesRegex(rq.RequirementsError, "not inside another set"):
            rq.create_requirement_set(repo, "Inner", parent=s)
        with self.assertRaisesRegex(rq.RequirementsError, "set or under another requirement"):
            rq.add_requirement(repo, repo.root_package, {"summary": "x"})
        loose = repo.add(RequirementDefinition(name="Loose"))
        self.assertTrue(rq.is_linkable(loose))
        rq.update_requirement_set(repo, s, name="SRS", prefix="X-", description="Software reqs")
        self.assertEqual(rq.add_requirement(repo, s).req_id, "X-1")
        self.assertEqual(rq.set_summary(repo, s)["description"], "Software reqs")
        meta = rq.meta()
        self.assertEqual([t["name"] for t in meta["link_types"]],
                         ["implement", "verify", "refine", "derive", "relate", "confirm"])
        json.dumps(meta)


if __name__ == "__main__":
    unittest.main()
