"""Representative AST shapes, checked against the assignments of the kebnf productions."""
import unittest

from sysml_text import Node, Ref, dump, parse


def ok(text, language="sysml"):
    r = parse(text, language)
    assert not r.diagnostics, [str(d) for d in r.diagnostics]
    return r.root


def members(node):
    return node.get("ownedRelationship", [])


def el(membership):
    return membership["ownedRelatedElement"][0]


def types(node):
    return [m.type for m in members(node)]


class DefinitionUsageTests(unittest.TestCase):

    def test_part_def_with_attribute_value_and_unit(self):
        root = ok("part def A :> B { attribute x : Real = 1.5 [kg]; }")
        member = members(root)[0]
        self.assertEqual(member.type, "OwningMembership")  # PackageMember
        a = el(member)
        self.assertEqual((a.type, a["declaredName"]), ("PartDefinition", "A"))
        sub, attr_member = members(a)
        # SubclassificationPart: ownedRelationship += OwnedSubclassification (superclassifier = [QualifiedName])
        self.assertEqual(sub.type, "Subclassification")
        self.assertEqual(sub["superclassifier"], Ref("B"))
        # DefinitionBodyItem: ownedRelationship += NonFeatureOccurrenceUsageMember : FeatureMembership
        self.assertEqual(attr_member.type, "FeatureMembership")
        x = el(attr_member)
        self.assertEqual((x.type, x["declaredName"]), ("AttributeUsage", "x"))
        typing, value = members(x)
        self.assertEqual((typing.type, typing["type"].text), ("FeatureTyping", "Real"))
        self.assertEqual(value.type, "FeatureValue")
        bracket = el(value)
        self.assertEqual((bracket.type, bracket["operator"]), ("OperatorExpression", "["))
        quantity = members(bracket)[0]["ownedRelatedElement"][0]["ownedRelationship"][0]
        self.assertEqual(el(quantity).type, "LiteralRational")
        self.assertEqual(el(quantity)["value"], 1.5)

    def test_usage_prefixes_and_multiplicity(self):
        root = ok("part def P { in ref part p : Q[0..*] ordered nonunique :> qs; abstract item i; }")
        p = el(members(el(members(root)[0]))[0])
        self.assertEqual(p.type, "PartUsage")
        self.assertEqual({k: p[k] for k in ("direction", "isReference", "isOrdered", "isUnique")},
                         {"direction": "in", "isReference": True, "isOrdered": True, "isUnique": False})
        self.assertEqual(types(p), ["FeatureTyping", "OwningMembership", "Subsetting"])
        rng = el(members(p)[1])
        self.assertEqual(rng.type, "MultiplicityRange")
        self.assertEqual([el(b).type for b in members(rng)], ["LiteralInteger", "LiteralInfinity"])

    def test_short_name_and_quoted_names(self):
        root = ok("requirement def <'R1'> 'Mass Requirement';")
        r = el(members(root)[0])
        self.assertEqual((r["declaredShortName"], r["declaredName"]), ("R1", "Mass Requirement"))

    def test_port_definition_owns_its_conjugate(self):
        root = ok("port def FuelPort { out item fuel : Fuel; }")
        port = el(members(root)[0])
        self.assertEqual(types(port), ["FeatureMembership", "OwningMembership"])
        conj = el(members(port)[1])
        self.assertEqual(conj.type, "ConjugatedPortDefinition")
        self.assertEqual(members(conj)[0].type, "PortConjugation")
        typed = ok("part p { port fp : ~FuelPort; }")
        typing = members(el(members(el(members(typed)[0]))[0]))[0]
        self.assertEqual((typing.type, typing["originalPortDefinition"].text), ("ConjugatedPortTyping", "FuelPort"))

    def test_redefinition_shorthand_is_a_reference_usage(self):
        root = ok("part p { :>> mass = 10; }")
        u = el(members(el(members(root)[0]))[0])
        self.assertEqual(u.type, "ReferenceUsage")  # DefaultReferenceUsage
        self.assertEqual(types(u), ["Redefinition", "FeatureValue"])
        self.assertEqual(members(u)[0]["redefinedFeature"].text, "mass")


class ConnectionTests(unittest.TestCase):

    def test_connect_with_feature_chains(self):
        root = ok("part s { connect a.p to b.q; }")
        conn = el(members(el(members(root)[0]))[0])
        self.assertEqual(conn.type, "ConnectionUsage")
        ends = members(conn)
        self.assertEqual([m.type for m in ends], ["EndFeatureMembership", "EndFeatureMembership"])
        end = el(ends[0])
        self.assertEqual(end.type, "ReferenceUsage")  # ConnectorEnd : ReferenceUsage
        subsetting = members(end)[0]
        self.assertEqual(subsetting.type, "ReferenceSubsetting")
        chain = subsetting["referencedFeature"]
        self.assertIsInstance(chain, Node)
        self.assertIs(chain, subsetting["ownedRelatedElement"][0])  # { ownedRelatedElement += ... }
        self.assertEqual([c["chainingFeature"].text for c in members(chain)], ["a", "p"])

    def test_interface_binding_allocation(self):
        root = ok("""part s {
            interface i : I connect [1] x ::> a.p to b.q;
            bind a.x = b.y;
            allocate f to c;
            flow of Fuel from tank.fuelOut to engine.fuelIn;
        }""")
        items = [el(m) for m in members(el(members(root)[0]))]
        self.assertEqual([i.type for i in items],
                         ["InterfaceUsage", "BindingConnectorAsUsage", "AllocationUsage", "FlowUsage"])
        end = el(members(items[0])[1])
        self.assertEqual((end.type, end["declaredName"]), ("PortUsage", "x"))  # InterfaceEnd : PortUsage
        self.assertEqual(types(end), ["OwningMembership", "ReferenceSubsetting"])  # cross multiplicity first
        flow = items[3]
        self.assertEqual(types(flow), ["FeatureMembership", "EndFeatureMembership", "EndFeatureMembership"])
        flow_end = el(members(flow)[1])
        self.assertEqual(flow_end.type, "FlowEnd")
        sub, feature_member = members(flow_end)
        self.assertEqual(sub["referencedFeature"].text, "tank")
        self.assertEqual(members(el(feature_member))[0]["redefinedFeature"].text, "fuelOut")


class BehaviorTests(unittest.TestCase):

    def test_transition_with_trigger_guard_and_effect(self):
        root = ok("""state def S {
            state s1; state s2;
            transition t first s1 accept sig : Sig if x > 0 do send done() to y then s2;
        }""")
        t = el(members(el(members(root)[0]))[2])
        self.assertEqual((t.type, t["declaredName"]), ("TransitionUsage", "t"))
        rels = members(t)
        self.assertEqual([m.type for m in rels],
                         ["Membership", "ParameterMembership", "ParameterMembership", "TransitionFeatureMembership",
                          "TransitionFeatureMembership", "TransitionFeatureMembership", "OwningMembership"])
        self.assertEqual(rels[0]["memberElement"].text, "s1")
        self.assertEqual([m.get("kind") for m in rels[3:6]], ["trigger", "guard", "effect"])
        self.assertEqual([el(m).type for m in rels[3:6]],
                         ["AcceptActionUsage", "OperatorExpression", "SendActionUsage"])
        payload = el(members(el(rels[3]))[0])
        self.assertEqual((payload.type, payload["declaredName"]), ("ReferenceUsage", "sig"))
        succession = el(rels[6])
        self.assertEqual(succession.type, "Succession")
        target = el(members(succession)[1])
        self.assertEqual(members(target)[0]["referencedFeature"].text, "s2")

    def test_state_entry_and_target_transitions(self):
        root = ok("state def S { entry; then off; state off; accept Go then on; state on; }")
        rels = members(el(members(root)[0]))
        self.assertEqual([(m.type, el(m).type) for m in rels],
                         [("StateSubactionMembership", "ActionUsage"), ("FeatureMembership", "SuccessionAsUsage"),
                          ("FeatureMembership", "StateUsage"), ("FeatureMembership", "TransitionUsage"),
                          ("FeatureMembership", "StateUsage")])
        self.assertEqual(rels[0]["kind"], "entry")

    def test_action_successions_and_nodes(self):
        root = ok("""action def A {
            first start;
            then action a1;
            then decide d;
                if x > 0 then a2;
                else a3;
            action a2; action a3;
            assign y := y + 1;
            while i < 3 { } until done;
        }""")
        rels = members(el(members(root)[0]))
        self.assertEqual(rels[0].type, "Membership")  # InitialNodeMember (GRAMMAR_NOTES D9)
        self.assertEqual(el(rels[1]).type, "SuccessionAsUsage")  # SourceSuccessionMember ...
        self.assertEqual(el(rels[2]).type, "ActionUsage")  # ... then its usage member
        self.assertEqual(el(rels[4]).type, "DecisionNode")
        guarded = el(rels[5])
        self.assertEqual(guarded.type, "TransitionUsage")
        self.assertEqual(members(guarded)[0]["kind"], "guard")
        self.assertEqual(el(rels[6]).type, "TransitionUsage")  # else a3
        assign = el(rels[9])
        self.assertEqual(assign.type, "AssignmentActionUsage")
        self.assertEqual(types(assign), ["ParameterMembership", "Membership", "ParameterMembership"])
        self.assertEqual(el(rels[10]).type, "WhileLoopActionUsage")

    def test_calculation_result_expression(self):
        root = ok("calc def Area { in w : Real; in h : Real; return a : Real; w * h }")
        rels = members(el(members(root)[0]))
        self.assertEqual([m.type for m in rels], ["FeatureMembership", "FeatureMembership",
                                                  "ReturnParameterMembership", "ResultExpressionMembership"])
        self.assertEqual(el(rels[3])["operator"], "*")


class RequirementTests(unittest.TestCase):

    def test_subject_and_constraints(self):
        root = ok("""requirement def MassReq {
            subject v : Vehicle;
            attribute limit : MassValue;
            require constraint { v.mass <= limit }
            assume a1;
        }""")
        rels = members(el(members(root)[0]))
        self.assertEqual([m.type for m in rels], ["SubjectMembership", "FeatureMembership",
                                                  "RequirementConstraintMembership", "RequirementConstraintMembership"])
        subject = el(rels[0])
        self.assertEqual((subject.type, subject["declaredName"]), ("ReferenceUsage", "v"))
        self.assertTrue(subject.span.text.startswith("subject"))
        self.assertEqual([rels[2]["kind"], rels[3]["kind"]], ["requirement", "assumption"])
        constraint = el(rels[2])
        self.assertEqual(constraint.type, "ConstraintUsage")
        self.assertEqual(members(constraint)[0].type, "ResultExpressionMembership")
        self.assertEqual(members(el(rels[3]))[0]["referencedFeature"].text, "a1")

    def test_satisfy(self):
        root = ok("satisfy MassReq by vehicle; assert not satisfy R2 by v2;")
        s1, s2 = (el(m) for m in members(root))
        self.assertEqual([s1.type, s2.type], ["SatisfyRequirementUsage"] * 2)
        self.assertTrue(s2["isNegated"])
        self.assertEqual(types(s1), ["ReferenceSubsetting", "SubjectMembership"])


class ImportAndMetadataTests(unittest.TestCase):

    def test_imports_and_alias(self):
        root = ok("private import A::*; public import B::c::**; private import all D::*::**; alias E for F::g;")
        a, b, d, e = members(root)
        self.assertEqual((a.type, a["visibility"], a["importedNamespace"].text), ("NamespaceImport", "private", "A"))
        self.assertEqual((b.type, b["importedMembership"].text, b["isRecursive"]), ("MembershipImport", "B::c", True))
        self.assertTrue(d["isImportAll"] and d["isRecursive"])
        self.assertEqual((e.type, e["memberName"], e["memberElement"].text), ("Membership", "E", "F::g"))

    def test_import_with_filter(self):
        root = ok("private import Q::*[@Safety][not @Draft];")
        imp = members(root)[0]
        self.assertEqual(imp.type, "NamespaceImport")
        pkg = imp["importedNamespace"]
        self.assertIs(pkg, el(imp))  # importedNamespace = FilterPackage { ownedRelatedElement += ... }
        self.assertEqual(pkg.type, "Package")
        inner, f1, f2 = members(pkg)
        self.assertEqual((inner.type, inner["visibility"], inner["importedNamespace"].text),
                         ("NamespaceImport", "public", "Q"))
        self.assertEqual([f1.type, f2.type], ["ElementFilterMembership"] * 2)
        self.assertEqual(el(f1)["operator"], "@")

    def test_prefix_metadata(self):
        root = ok("#Safety #Approved part p : P;")
        p = el(members(root)[0])
        self.assertEqual(types(p), ["OwningMembership", "OwningMembership", "FeatureTyping"])
        md = el(members(p)[0])
        self.assertEqual(md.type, "MetadataUsage")  # PrefixMetadataUsage
        self.assertEqual(members(md)[0]["type"].text, "Safety")

    def test_metadata_usage_with_body(self):
        root = ok('@Issue about p, q { text = "x"; status = Status::open; }')
        md = el(members(root)[0])
        self.assertEqual(md.type, "MetadataUsage")
        self.assertEqual(types(md), ["FeatureTyping", "Annotation", "Annotation",
                                     "FeatureMembership", "FeatureMembership"])
        self.assertEqual(members(md)[1]["annotatedElement"].text, "p")
        body = el(members(md)[3])
        self.assertEqual(body.type, "ReferenceUsage")  # MetadataBodyUsage
        self.assertEqual(members(body)[0]["redefinedFeature"].text, "text")

    def test_comments_documentation_and_representation(self):
        root = ok("""package P {
            doc /* Package doc. */
            comment c about A, B /* About A and B. */
            /* A plain comment. */
            rep r language "ocl" /* self.x > 0 */
        }""")
        rels = members(el(members(root)[0]))
        items = [el(m) for m in rels]
        self.assertEqual([i.type for i in items], ["Documentation", "Comment", "Comment", "TextualRepresentation"])
        self.assertEqual(items[0]["body"], "Package doc.")
        self.assertEqual([a["annotatedElement"].text for a in members(items[1])], ["A", "B"])
        self.assertEqual(items[3]["language"], "ocl")


class KerMLTests(unittest.TestCase):

    def test_classifier_and_features(self):
        root = ok("""package P {
            abstract class A specializes B, C {
                feature f : T[0..*] ordered nonunique subsets g redefines h;
                in x : Real;
                composite feature parts : Part[*];
            }
        }""", "kerml")
        a = el(members(el(members(root)[0]))[0])
        self.assertEqual((a.type, a["isAbstract"]), ("Class", True))
        self.assertEqual(types(a)[:2], ["Subclassification", "Subclassification"])
        f = el(members(a)[2])
        self.assertEqual(f.type, "Feature")
        self.assertEqual(types(f), ["FeatureTyping", "OwningMembership", "Subsetting", "Redefinition"])
        self.assertEqual((f["isOrdered"], f["isUnique"]), (True, False))
        self.assertEqual(members(a)[3].type, "FeatureMembership")
        self.assertEqual(el(members(a)[3])["direction"], "in")

    def test_function_with_result_expression(self):
        root = ok("function twice { in x : Real; return : Real; x * 2 }", "kerml")
        fn = el(members(root)[0])
        self.assertEqual(fn.type, "Function")
        self.assertEqual(types(fn), ["FeatureMembership", "ReturnParameterMembership",
                                     "ResultExpressionMembership"])

    def test_connector_succession_flow(self):
        root = ok("""assoc struct S {
            end [0..1] feature a : A;
            connector c : C from x to y;
            succession first s1 then s2;
            flow f of p : P from a.outPort to b.inPort;
        }""", "kerml")
        s = el(members(root)[0])
        self.assertEqual(s.type, "AssociationStructure")
        end, conn, succ, flow = (el(m) for m in members(s))
        self.assertTrue(end["isEnd"])
        self.assertEqual(types(end)[0], "OwningMembership")  # OwnedCrossFeatureMember
        self.assertEqual((conn.type, conn["declaredName"]), ("Connector", "c"))
        self.assertEqual(types(conn), ["FeatureTyping", "EndFeatureMembership", "EndFeatureMembership"])
        self.assertEqual(types(succ), ["EndFeatureMembership", "EndFeatureMembership"])
        self.assertEqual(flow.type, "Flow")
        self.assertEqual(el(members(flow)[0]).type, "PayloadFeature")

    def test_relationships_as_members(self):
        root = ok("""specialization Sp subtype A specializes B;
            subclassifier C :> D;
            typing f : T;
            subset a.b :> c;
            redefinition x :>> y;
            conjugation cj conjugate P ~ Q;
            disjoining disjoint A from B;
            featuring f by T;
            dependency from x to y, z;""", "kerml")
        items = [el(m) for m in members(root)]
        self.assertEqual([i.type for i in items],
                         ["Specialization", "Subclassification", "FeatureTyping", "Subsetting", "Redefinition",
                          "Conjugation", "Disjoining", "TypeFeaturing", "Dependency"])
        self.assertEqual((items[0]["specific"].text, items[0]["general"].text), ("A", "B"))
        self.assertEqual(items[2]["type"].text, "T")
        self.assertIs(items[3]["subsettingFeature"], items[3]["ownedRelatedElement"][0])  # a chain
        self.assertEqual([s.text for s in items[8]["supplier"]], ["y", "z"])

    def test_library_package_and_metadata(self):
        root = ok("""standard library package L {
            metaclass M;
            #M feature x;
            @M { a = 1; }
        }""", "kerml")
        lib = el(members(root)[0])
        self.assertEqual((lib.type, lib["isStandard"]), ("LibraryPackage", True))
        x = el(members(lib)[1])
        self.assertEqual(el(members(x)[0]).type, "MetadataFeature")
        md = el(members(lib)[2])
        self.assertEqual(el(members(md)[1]).type, "Feature")  # MetadataBodyFeature


class NodeApiTests(unittest.TestCase):

    def test_walk_spans_and_dump(self):
        root = ok("package P {\n  part def A;\n  part a : A;\n}")
        nodes = list(root.walk())
        self.assertIs(nodes[0], root)
        a = root.find("PartUsage")[0]
        self.assertEqual((a.span.line, a.span.col), (3, 3))
        self.assertEqual(a.span.text, "part a : A;")
        typing = members(a)[0]
        self.assertEqual((typing["type"].span.line, typing["type"].span.col), (3, 12))
        text = dump(root)
        self.assertIn("PartDefinition declaredName='A'", text)
        self.assertIn("FeatureTyping type=-> A", text)

    def test_walk_visits_shared_nodes_once(self):
        root = ok("part p { connect a.b to c.d; }")
        ids = [id(n) for n in root.walk()]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
