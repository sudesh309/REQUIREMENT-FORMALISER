# SysML v2 Core Engine (KerML-based)

A Python implementation of a SysML v2 modeling core engine, built on a KerML
(Kernel Modeling Language) foundation. Inspired by Dassault / No Magic Cameo
Systems Modeler (MagicDraw SysML v1.6), but aligned with the OMG SysML v2 / KerML
specifications.

## Layers

```
+-------------------------------------------------------+
|  Applications (analysis, simulation, code-gen, UI)    |
+-------------------------------------------------------+
|  SysML v2 Metamodel  (PartDef, PortDef, ActionDef...) |
+-------------------------------------------------------+
|  KerML Kernel        (Element, Type, Feature, ...)    |
+-------------------------------------------------------+
|  Repository | Parser | Validator | Serializer         |
+-------------------------------------------------------+
```

## Modules

- `kerml/` — KerML metamodel: Element, Namespace, Relationship, Type,
  Classifier, Feature, Specialization, Subsetting, Redefinition, Multiplicity.
- `sysmlv2/` — SysML v2 metamodel layered on KerML: Part, Port, Item,
  Action, State, Requirement, Constraint, Connection, View, Analysis cases.
- `engine/repository.py` — In-memory model repository with qualified-name
  resolution, indexing, containment, and traversal.
- `engine/parser.py` — Textual KerML / SysML v2 parser (subset of the OMG
  textual notation) producing metamodel instances.
- `engine/validator.py` — Well-formedness rules (multiplicity, typing,
  redefinition, conformance).
- `engine/serializer.py` — JSON serialization round-trip.
- `examples/` — Sample models that exercise the engine end-to-end.

## Quick start

```bash
python -m engine.cli examples/vehicle.sysml
```

## Requirements, parameters & typed links

Authoring requirements, behavioral parameters, and traceability links is
first-class:

```python
from engine import create_link, links_of, list_link_kinds
from sysmlv2 import (
    ActionDefinition, AttributeDefinition, ParameterUsage,
    PartDefinition, RequirementDefinition, VerificationCaseDefinition,
)

# Behavior with directional parameters
Real = AttributeDefinition(name="Real")
accel = ActionDefinition(name="Accelerate")
accel.own(ParameterUsage(name="speed",  parameter_kind="in",     typed_by=Real))
accel.own(ParameterUsage(name="result", parameter_kind="return", typed_by=Real))

# Requirement with subject / stakeholders / actors
Vehicle = PartDefinition(name="Vehicle")
Driver  = PartDefinition(name="Driver")
req = RequirementDefinition(name="MaxSpeed", req_id="REQ-001",
                            text="Speed shall not exceed 130 km/h.")
create_link("subject",     req, Vehicle)
create_link("actor",       req, Driver)
create_link("satisfy",     Vehicle, req)
create_link("verify",      VerificationCaseDefinition(name="VC1"), req)
create_link("allocate",    accel, Vehicle)
```

All available link kinds (15) — usable by name in the GUI Link dialog,
the parser, the MCP `sysml_link` tool, and the `create_link()` API:

| Kind | Class | Notes |
|------|-------|-------|
| `satisfy`            | Satisfy             | populates `target.satisfied_by` |
| `verify`             | Verify              | populates `target.verified_by`  |
| `refine`             | Refine              | |
| `trace`              | Trace               | non-committal traceability |
| `derive`             | DeriveRequirement   | aliases: `derives_from` |
| `copy`               | Copy                | textual copy |
| `allocate`           | Allocation          | function→component / logical→physical |
| `subject`            | SubjectOf           | requirement / case / view subject |
| `stakeholder`        | StakeholderOf       | |
| `actor`              | ActorOf             | requirement / use-case actor |
| `framed_concern`     | FramedConcern       | concern framed by requirement / viewpoint |
| `parameter_binding`  | ParameterBinding    | bind two parameters at invocation |
| `assume`             | AssumeConstraint    | requirement assumes a constraint |
| `require`            | RequireConstraint   | requirement requires a constraint |
| `expose`             | Exposes             | view exposes elements |

Query the graph: `links_of(element, direction='outgoing'|'incoming'|'both', kind='satisfy')`.

GUI: **Links** menu → Create link… (Ctrl+L), New requirement…, Add
parameter to selection. MCP: `sysml_link`, `sysml_list_links`,
`sysml_link_kinds`, `sysml_add_parameter`, `sysml_create_requirement`.

## Custom stereotypes & interfaces

User-defined **stereotypes** and **interfaces** extend the metamodel
without forking it:

```python
from kerml.stereotypes import Stereotype
from sysmlv2 import PartDefinition, InterfaceDefinition

safety = Stereotype(name="safetyCritical", applies_to=[PartDefinition])
safety.define_tag("asilLevel", default="QM")
project.own(safety)

drivetrain = InterfaceDefinition(name="Drivetrain")
project.own(drivetrain)

safety.apply(vehicle, {"asilLevel": "D"})   # attaches a typed tag-bag
```

The GUI exposes Stereotypes › Define / Add tag / Apply menus; the MCP
server exposes `sysml_define_stereotype`, `sysml_apply_stereotype`,
`sysml_list_stereotypes`.

## Visualization

Three diagram domains are rendered:

- **BDD** (Block Definition Diagram) — Definitions with stereotypes,
  features, specialization and composition edges.
- **IBD** (Internal Block Diagram) — internal parts and ports of a
  single PartDefinition joined by connections.
- **Requirements** — Requirement nodes with Satisfy/Verify/Refine/
  Trace/Derive edges.

Two surfaces:

- **GUI Diagram tab** — interactive Tkinter Canvas, no extra deps.
- **`engine.bdd / ibd / requirements`** — Graphviz DOT output, ready
  for `dot -Tsvg` or any DOT-aware renderer.

## Knowledge-graph export

Export the project to any of four interoperable formats:

| Format     | Function                          | Use with                      |
|------------|-----------------------------------|-------------------------------|
| Turtle/RDF | `export_knowledge_graph(r, "turtle")`  | Apache Jena, RDFLib, GraphDB, Stardog |
| JSON-LD    | `export_knowledge_graph(r, "json-ld")` | RDFLib, Neo4j, JSON graph tools       |
| GraphML    | `export_knowledge_graph(r, "graphml")` | Gephi, yEd, Cytoscape, NetworkX       |
| Cypher     | `export_knowledge_graph(r, "cypher")`  | Neo4j browser / bolt clients          |

Every Element becomes a typed node; every typed relationship
(`specializes`, `subsets`, `redefines`, `typedBy`, `owns`,
`stereotype`, `satisfies`, `verifies`, `refines`, `traces`,
`derivesFrom`, `connects`, `imports`) becomes a labeled edge.

The GUI exposes Export › Knowledge graph; the MCP server exposes
`sysml_export_graph` and `sysml_export_diagram`.

## GUI

A Tkinter desktop GUI is bundled — three panes (containment tree,
properties editor, validation log) plus a toolbar with one-click
creation of every common SysML v2 element kind:

```bash
python -m gui.app
```

(Requires Tk; on Debian/Ubuntu: `sudo apt install python3-tk`.)

Features:

- File: New / Open JSON / Save JSON / Import `.sysml`
- Tree: containment view of the project package, right-click to add or delete
- Properties pane: edit name, short name, multiplicity, typing (by qualified
  name), `req_id` / `text` fields, documentation; "Apply changes" commits
- **Diagram tab**: BDD / IBD / Requirements rendered live on a Tk Canvas
  with stereotype labels, plus "Export DOT…" for Graphviz
- Toolbar buttons add Package, Part / Attribute / Port / Interface /
  Connection / Action / State / Requirement / Constraint / Enum Def +
  Usages and Stereotype
- Stereotypes menu: Define stereotype, Add tag, Apply to selection
- Export menu: Knowledge graph (Turtle / JSON-LD / GraphML / Cypher)
- F5 runs the validator, listing all issues in the bottom pane

Run tests:

```bash
python -m unittest discover -s tests -v
```

## MCP server

The engine ships an MCP (Model Context Protocol) server so any
MCP-compatible AI agent — Claude Desktop, Claude Code, Cursor, custom
agents — can drive it:

```bash
python -m mcp_server.server     # speaks JSON-RPC 2.0 over stdio
```

### Tools exposed

| Tool                        | Purpose                                              |
|-----------------------------|------------------------------------------------------|
| `sysml_new_project`         | start a fresh project                                |
| `sysml_open_project`        | load from JSON                                       |
| `sysml_save_project`        | save to JSON                                         |
| `sysml_parse_sysml`         | parse `.sysml` source into the model                 |
| `sysml_list_elements`       | filter by kind / parent                              |
| `sysml_get_element`         | fetch by UUID or qualified name                      |
| `sysml_create_element`      | create any SysML v2 element (PartDefinition, ...)    |
| `sysml_delete_element`      | delete and prune subtree                             |
| `sysml_set_property`        | name, multiplicity, doc, req_id, text, abstract, ... |
| `sysml_set_feature_type`    | bind/rebind a Feature's type                         |
| `sysml_connect`             | create a ConnectionUsage between two ends            |
| `sysml_satisfy`             | Satisfy traceability relationship                    |
| `sysml_verify`              | Verify traceability relationship                     |
| `sysml_validate`            | run the well-formedness validator                    |
| `sysml_tree`                | dump the containment tree as nested JSON             |
| `sysml_define_stereotype`   | declare a custom stereotype with tags + applies_to   |
| `sysml_apply_stereotype`    | apply a stereotype with tag values to a target       |
| `sysml_list_stereotypes`    | list defined stereotypes / applications on a target  |
| `sysml_export_diagram`      | export BDD / IBD / Requirements as Graphviz DOT      |
| `sysml_export_graph`        | export Turtle / JSON-LD / GraphML / Cypher           |
| `sysml_link`                | create any of 15 typed links between two elements    |
| `sysml_list_links`          | list links touching an element / project-wide        |
| `sysml_link_kinds`          | describe every registered link kind                  |
| `sysml_add_parameter`       | add a directional parameter to a behavior/constraint |
| `sysml_create_requirement`  | create a Requirement and wire its subject/actors etc |

### Resources exposed

- `sysml://project` — JSON snapshot of the active project
- `sysml://library/kerml` — built-in KerML library
- `sysml://library/sysml` — built-in SysML v2 library

### Wire into Claude Desktop / Claude Code

Copy `mcp_server/claude_desktop_config.example.json` into your client's
config (e.g. `~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS), fix the absolute paths, and restart the client.

### Use with a local LLM in VS Code (Ollama + Continue/Cline/Copilot)

The workspace ships a `.vscode/mcp.json` so MCP-aware VS Code
extensions (GitHub Copilot Chat 1.95+, Continue, Cursor, Cline)
auto-discover the server. Run a local LLM with Ollama and point the
extension at it. See [docs/LOCAL_LLM_VSCODE.md](docs/LOCAL_LLM_VSCODE.md)
for step-by-step setup.

## Mapping to Cameo SysML 1.6 concepts

| Cameo / SysML 1.6        | This engine (SysML v2)              |
|--------------------------|-------------------------------------|
| Block                    | `PartDefinition`                    |
| Part Property            | `PartUsage`                         |
| Value Property           | `AttributeUsage`                    |
| Port / Flow Port         | `PortUsage` (with conjugation)      |
| Connector                | `ConnectionUsage`                   |
| Activity / Action        | `ActionDefinition` / `ActionUsage`  |
| State Machine            | `StateDefinition` / `StateUsage`    |
| Requirement              | `RequirementDefinition` / Usage     |
| Constraint Block         | `ConstraintDefinition`              |
| Generalization           | KerML `Specialization`              |
