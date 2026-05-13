# Architecture

End-to-end architecture of the SysML v2 core engine. Eleven diagrams,
from the KerML kernel up through the SysML v2 metamodel, the engine
services, the GUI, the MCP server, and the knowledge-graph exporter.

## 1. Layered overview

```mermaid
flowchart TB
    subgraph UI["User Interfaces"]
        GUI["Tkinter GUI<br/>gui.app"]
        CLI["CLI<br/>engine.cli"]
        API["Python API<br/>examples/build_vehicle.py"]
        MCP["MCP server<br/>mcp_server.server<br/>(used by AI agents)"]
    end

    subgraph ENG["Engine Services"]
        REPO["Repository<br/>containment + UUID + qname"]
        PARSER["Textual Parser<br/>(.sysml → metamodel)"]
        VALID["Validator<br/>(well-formedness rules)"]
        SER["JSON Serializer<br/>(save / load)"]
        LINKS["Link Registry<br/>(15 typed link kinds)"]
        DIAG["Diagram exporter<br/>(BDD / IBD / Req / SM)"]
        KG["KG exporter<br/>(Turtle / JSON-LD / GraphML / Cypher)"]
    end

    subgraph SYSML["SysML v2 Metamodel"]
        SDEF["Definitions<br/>Part, Port, Action, State,<br/>Requirement, Constraint, Parameter,<br/>Interface, Calculation, ..."]
        SUSE["Usages<br/>typed Features for each Definition"]
        SREL["Relationships<br/>Satisfy, Verify, Refine, Trace,<br/>Allocate, Subject, Stakeholder, Actor,<br/>Assume, Require, Expose, ..."]
        SSM["State Machine<br/>(StateMachineDefinition + Runner)"]
        SLIB["Standard Library<br/>(SysML root types)"]
    end

    subgraph KERML["KerML Kernel"]
        KEL["Element / Relationship"]
        KNS["Namespace / Package /<br/>Membership / Import"]
        KTY["Type / Classifier /<br/>DataType / Class / Behavior"]
        KFE["Feature / Multiplicity /<br/>Subsetting / Redefinition /<br/>FeatureTyping / Conjugation"]
        KEX["Expressions"]
        KST["Stereotypes<br/>(user-extensible)"]
        KLIB["KerML Library<br/>(Anything, Occurrence, Object,<br/>Boolean, Integer, Real, ...)"]
    end

    GUI --> REPO
    CLI --> REPO
    API --> REPO
    MCP --> REPO

    GUI --> PARSER & VALID & SER & LINKS & DIAG & KG
    MCP --> PARSER & VALID & SER & LINKS & DIAG & KG
    CLI --> PARSER & VALID & SER

    REPO --> SDEF & SUSE & SREL & SSM
    LINKS --> SREL
    DIAG --> SSM
    KG   --> SREL

    SDEF --> SLIB
    SUSE --> SLIB
    SLIB --> KLIB

    SDEF -->|specializes| KTY
    SUSE -->|is a kind of| KFE
    SREL -->|is a kind of| KEL
    SSM  -->|specializes| SDEF

    KST --> KEL
    KFE --> KTY
    KTY --> KNS
    KNS --> KEL
    KEX --> KFE
    KLIB --> KTY
```

## 2. KerML metamodel (class view)

```mermaid
classDiagram
    class Element {
        +id : UUID
        +name : str
        +qualified_name : str
        +owner : Element
        +annotations : list~Annotation~
        +owned_relationships : list~Relationship~
    }
    class Relationship { +source +target }
    Element <|-- Relationship
    Element <|-- Annotation
    Annotation <|-- Comment
    Annotation <|-- Documentation
    Annotation <|-- StereotypeApplication

    class Namespace { +memberships +imports +resolve(qname) }
    Element <|-- Namespace
    Namespace <|-- Package
    Namespace <|-- Stereotype

    Relationship <|-- Membership
    Membership   <|-- OwningMembership
    Relationship <|-- Import

    class Type { +specializations +conforms_to() +all_features() }
    Namespace <|-- Type
    Relationship <|-- Specialization
    Relationship <|-- Conjugation
    Type <|-- Classifier
    Classifier <|-- DataType
    Classifier <|-- Class
    Class <|-- Structure
    Class <|-- Behavior
    Classifier <|-- Association

    class Feature {
      +typed_by
      +multiplicity
      +direction
      +is_composite
    }
    Type <|-- Feature
    Relationship <|-- FeatureTyping
    Relationship <|-- Subsetting
    Subsetting <|-- Redefinition

    Feature <|-- Expression
    Expression <|-- LiteralExpression
    Expression <|-- FeatureReferenceExpression
    Expression <|-- Invocation

    class StereotypeTag
    Feature <|-- StereotypeTag
```

## 3. SysML v2 — Definition / Usage taxonomy

```mermaid
classDiagram
    class Classifier
    class Feature
    class Definition
    class Usage
    Classifier <|-- Definition
    Feature    <|-- Usage
    Definition "1" o-- "*" Usage : owns / typed by

    Definition <|-- OccurrenceDefinition
    OccurrenceDefinition <|-- ItemDefinition
    ItemDefinition <|-- PartDefinition
    OccurrenceDefinition <|-- PortDefinition
    Definition <|-- AttributeDefinition
    AttributeDefinition <|-- ParameterDefinition
    AttributeDefinition <|-- EnumerationDefinition
    Definition <|-- ConnectionDefinition
    ConnectionDefinition <|-- InterfaceDefinition
    ConnectionDefinition <|-- FlowConnectionDefinition
    OccurrenceDefinition <|-- ActionDefinition
    ActionDefinition <|-- StateDefinition
    StateDefinition <|-- StateMachineDefinition
    ActionDefinition <|-- CalculationDefinition
    CalculationDefinition <|-- ConstraintDefinition
    ConstraintDefinition <|-- RequirementDefinition
    RequirementDefinition <|-- ConcernDefinition
    RequirementDefinition <|-- ViewpointDefinition
    CalculationDefinition <|-- CaseDefinition
    CaseDefinition <|-- UseCaseDefinition
    CaseDefinition <|-- AnalysisCaseDefinition
    CaseDefinition <|-- VerificationCaseDefinition
    Definition <|-- AllocationDefinition
    Definition <|-- ViewDefinition
    Definition <|-- MetadataDefinition
    Definition <|-- EventDefinition
```

## 4. Link registry (15 typed link kinds)

```mermaid
flowchart LR
    subgraph trace [Traceability]
        S[satisfy] --- V[verify] --- F[refine] --- T[trace] --- D[derive] --- C[copy]
    end
    subgraph alloc [Allocation]
        A[allocate]
    end
    subgraph reqstruct [Requirement structure]
        SU[subject] --- ST[stakeholder] --- AC[actor]
        FC[framed_concern] --- AS[assume] --- RQ[require]
    end
    subgraph other [Other]
        PB[parameter_binding] --- EX[expose]
    end
    LINKS([engine.links<br/>LINK_KINDS]) --> trace
    LINKS --> alloc
    LINKS --> reqstruct
    LINKS --> other
    LINKS -. used by .-> API[Python API]
    LINKS -. used by .-> GUI[GUI Link dialog]
    LINKS -. used by .-> MCP[MCP sysml_link]
    LINKS -. exported by .-> KG[KG exporter]
```

## 5. Engine services data-flow

```mermaid
flowchart LR
    SRC[".sysml source"] -->|tokenize + parse| PARSER[Parser]
    PARSER -->|metamodel objects| REPO[(Repository)]
    REPO -->|register_tree| REG[Element registry<br/>UUID → Element]
    REPO --> VALID[Validator]
    VALID --> ISSUES[Issue list<br/>severity · rule · element]
    REPO --> SER[Serializer]
    SER -->|to_json| JSON[(project.json)]
    JSON -->|from_json| REPO
    REPO --> DIAG[Diagram exporter]
    DIAG --> DOT[(Graphviz DOT)]
    REPO --> KG[KG exporter]
    KG --> FORMATS[(Turtle / JSON-LD /<br/>GraphML / Cypher)]
    REPO --> LINKS[Link registry]
    LINKS --> CREATE[create_link / links_of]
```

## 6. GUI runtime

```mermaid
flowchart TB
    subgraph TK["Tkinter window — gui.app.SysMLApp"]
        MENU["File · Edit · Model · StateMachine · Links · Stereotypes · Export"]
        TOOL["Toolbar (Add: Part / Attribute / Port / ... / Parameter / Stereotype)"]
        TREE["Containment tree (ttk.Treeview)"]
        subgraph NB[Right pane — Notebook]
            PROPS["Properties tab"]
            DIAGV["Diagram tab<br/>(BDD · IBD · Requirements · StateMachine)"]
        end
        LOG["Output / Validation log"]
        STATUS["Status bar"]
        DLG["Dialogs: LinkDialog, RequirementDialog"]
    end
    USER((User)) --> MENU & TOOL & TREE & PROPS
    MENU & TOOL --> CTRL[Controller methods<br/>(cmd_*)]
    TREE --> CTRL
    PROPS --> CTRL
    DLG --> CTRL
    CTRL --> REPO[(Repository)]
    CTRL --> PARSER[Parser]
    CTRL --> VALID[Validator]
    CTRL --> SER[Serializer]
    CTRL --> LINKS[Link registry]
    CTRL --> DIAG[Diagram exporter]
    CTRL --> KG[KG exporter]
    REPO --> TREE
    REPO --> PROPS
    REPO --> DIAGV
    VALID --> LOG
```

## 7. State machine runtime

```mermaid
sequenceDiagram
    actor U as User / Agent
    participant SM as StateMachineDefinition
    participant R  as StateMachineRunner
    participant Cur as current state
    participant Tgt as target state

    U->>R: fire("park", speed=0)
    R->>SM: transitions_from(current="Driving")
    SM-->>R: [Driving→Parked guard=λ, trigger="park"]
    R->>R: evaluate guard({speed:0}) → True
    R->>Cur: exit_action  → brake()
    R->>R: effect (if any)
    R->>Tgt: entry_action → lock()
    R-->>U: new current = Parked
```

## 8. MCP server protocol

```mermaid
sequenceDiagram
    participant AGENT as AI agent
    participant HOST as MCP host<br/>(Claude Desktop / Code, VS Code, Cursor)
    participant SRV as mcp_server.server (stdio JSON-RPC)
    participant ENG as Engine

    AGENT->>HOST: "Build me an EV model"
    HOST->>SRV: initialize
    SRV-->>HOST: capabilities + serverInfo
    HOST->>SRV: tools/list
    SRV-->>HOST: 30+ sysml_* tools
    loop authoring
        AGENT->>HOST: pick next tool
        HOST->>SRV: tools/call name=sysml_create_element ...
        SRV->>ENG: create + register
        ENG-->>SRV: element summary
        SRV-->>HOST: text content
    end
    HOST-->>AGENT: results streamed back to chat
```

Tool surface (≈ 30 tools) grouped by family:

```mermaid
mindmap
  root((MCP tools))
    Project
      new_project
      open_project
      save_project
      parse_sysml
      tree
    CRUD
      create_element
      delete_element
      get_element
      list_elements
      set_property
      set_feature_type
    Requirements
      create_requirement
      add_parameter
    Links
      link
      list_links
      link_kinds
    Stereotypes
      define_stereotype
      apply_stereotype
      list_stereotypes
    State machines
      attach_state_machine
      add_state
      add_transition
      fire_event
      state_machine_status
      reset_state_machine
    Visualize / Export
      export_diagram
      export_graph
    Quality
      validate
```

## 9. Knowledge-graph export

```mermaid
flowchart LR
    REPO[(Repository)] --> ITER["_iter_edges()<br/>collects every Element<br/>+ ownership / relationships /<br/>typing / subsetting / stereotype / ends"]
    ITER --> TTL[to_turtle] --> RDF[(Turtle / RDF)]
    ITER --> JL[to_jsonld] --> JSONLD[(JSON-LD)]
    ITER --> GM[to_graphml] --> GRAPHML[(GraphML)]
    ITER --> CY[to_cypher] --> CYPHER[(Cypher MERGE)]
    RDF --> JENA[Jena / RDFLib / Stardog / GraphDB]
    JSONLD --> NEO[Neo4j n10s]
    GRAPHML --> GEPHI[Gephi / yEd / Cytoscape]
    CYPHER --> N4J[Neo4j Browser]
```

## 10. Persistence format

```mermaid
flowchart LR
    REPO[(Repository)] -->|to_dict| MAP[/"{<br/>  format: 'sysmlv2-core/1',<br/>  name, root,<br/>  elements: [ {id, class, kind,<br/>    name, owner, ...payload} ]<br/>}"/]
    MAP -->|json.dumps| FILE[(project.json)]
    FILE -->|json.loads → from_dict| REPO2[(Repository′)]
    REPO2 -->|element ids preserved| ROUND["round-trip: ids,<br/>names, types,<br/>multiplicities, specializations"]
```

## 11. Module dependency map

```mermaid
flowchart LR
    subgraph kerml
        kE[elements.py]
        kN[namespaces.py]
        kT[types.py]
        kF[features.py]
        kX[expressions.py]
        kS[stereotypes.py]
        kL[library.py]
    end
    subgraph sysmlv2
        sD[definitions.py]
        sR[relationships.py]
        sSM[state_machines.py]
        sL[library.py]
    end
    subgraph engine
        eR[repository.py]
        eP[parser.py]
        eV[validator.py]
        eS[serializer.py]
        eC[cli.py]
        eL[links.py]
        eD[diagram.py]
        eK[graph_export.py]
    end
    subgraph gui
        gA[app.py]
        gD[diagram_view.py]
    end
    subgraph mcp
        mS[server.py]
    end

    kN --> kE
    kT --> kN
    kF --> kT
    kX --> kF
    kS --> kE
    kS --> kF
    kL --> kT
    sD --> kF
    sD --> kT
    sR --> kE
    sSM --> sD
    sL --> sD
    eR --> kN
    eR --> sL
    eP --> sD
    eV --> sD
    eS --> sD
    eL --> sR
    eD --> sD
    eD --> sSM
    eK --> sR
    eK --> kS
    eC --> eR
    eC --> eP
    eC --> eV
    eC --> eS
    gA --> eR
    gA --> eP
    gA --> eV
    gA --> eS
    gA --> eL
    gA --> eK
    gA --> sSM
    gA --> kS
    gA --> gD
    gD --> eD
    gD --> sSM
    mS --> eR
    mS --> eP
    mS --> eV
    mS --> eS
    mS --> eL
    mS --> eD
    mS --> eK
    mS --> sSM
    mS --> kS
```
