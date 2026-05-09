# Architecture

End-to-end architecture of the SysML v2 core engine, from the KerML
kernel up through the SysML v2 metamodel, the engine services, and the
Tkinter GUI front-end.

## 1. Layered overview

```mermaid
flowchart TB
    subgraph UI["User Interfaces"]
        GUI["Tkinter GUI<br/>(gui/app.py)"]
        CLI["CLI<br/>(engine/cli.py)"]
        API["Programmatic API<br/>(examples/build_vehicle.py)"]
    end

    subgraph ENG["Engine Services"]
        REPO["Repository<br/>(containment tree + UUID registry)"]
        PARSER["Textual Parser<br/>(.sysml → metamodel)"]
        VALID["Validator<br/>(well-formedness rules)"]
        SER["JSON Serializer<br/>(save / load)"]
    end

    subgraph SYSML["SysML v2 Metamodel"]
        SDEF["Definitions<br/>Part, Port, Action, State,<br/>Requirement, Constraint, ..."]
        SUSE["Usages<br/>typed Features for each Definition"]
        SREL["Relationships<br/>Satisfy, Verify, Refine, Trace, ..."]
        SLIB["Standard Library<br/>(SysML root types)"]
    end

    subgraph KERML["KerML Kernel Metamodel"]
        KEL["Element / Relationship"]
        KNS["Namespace / Package /<br/>Membership / Import"]
        KTY["Type / Classifier /<br/>DataType / Class / Behavior"]
        KFE["Feature / Multiplicity /<br/>Subsetting / Redefinition /<br/>FeatureTyping / Conjugation"]
        KEX["Expressions<br/>(Literal / Reference / Invocation)"]
        KLIB["KerML Standard Library<br/>(Anything, Occurrence, Object,<br/>Boolean, Integer, Real, ...)"]
    end

    GUI --> REPO
    CLI --> REPO
    API --> REPO

    GUI --> PARSER
    CLI --> PARSER
    GUI --> VALID
    CLI --> VALID
    GUI --> SER
    CLI --> SER

    REPO --> SDEF
    REPO --> SUSE
    REPO --> SREL
    PARSER --> SDEF
    PARSER --> SUSE
    VALID --> SDEF
    VALID --> SUSE
    SER --> SDEF
    SER --> SUSE
    SER --> SREL

    SDEF --> SLIB
    SUSE --> SLIB
    SLIB --> KLIB

    SDEF -->|specializes| KTY
    SUSE -->|is a kind of| KFE
    SREL -->|is a kind of| KEL

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
        +walk()
    }

    class Relationship {
        +source : Element
        +target : Element
    }
    Element <|-- Relationship

    class Annotation
    Element <|-- Annotation
    class Comment
    class Documentation
    Annotation <|-- Comment
    Annotation <|-- Documentation

    class Namespace {
        +memberships : list~Membership~
        +imports : list~Import~
        +resolve(qname)
    }
    Element <|-- Namespace

    class Package
    Namespace <|-- Package

    class Membership
    Relationship <|-- Membership
    class OwningMembership
    Membership <|-- OwningMembership
    class Import
    Relationship <|-- Import

    class Type {
        +specializations
        +conforms_to(other) bool
        +all_features()
    }
    Namespace <|-- Type

    class Specialization
    Relationship <|-- Specialization
    class Conjugation
    Relationship <|-- Conjugation

    class Classifier
    Type <|-- Classifier
    class DataType
    class Class
    class Structure
    class Behavior
    class Association
    Classifier <|-- DataType
    Classifier <|-- Class
    Class      <|-- Structure
    Class      <|-- Behavior
    Classifier <|-- Association

    class Feature {
        +typed_by
        +multiplicity
        +direction
        +is_composite
        +subset(other)
        +redefine(other)
    }
    Type <|-- Feature

    class FeatureTyping
    Relationship <|-- FeatureTyping
    class Subsetting
    Relationship <|-- Subsetting
    class Redefinition
    Subsetting   <|-- Redefinition

    class Expression
    Feature <|-- Expression
    class LiteralExpression
    class FeatureReferenceExpression
    class Invocation
    Expression <|-- LiteralExpression
    Expression <|-- FeatureReferenceExpression
    Expression <|-- Invocation
```

## 3. SysML v2 metamodel — Definition / Usage pattern

```mermaid
classDiagram
    class Classifier
    class Feature

    class Definition {
        +is_variation
        +is_individual
    }
    Classifier <|-- Definition

    class Usage {
        +is_variant
        +is_reference
        +portion_kind
    }
    Feature <|-- Usage

    Definition "1" o-- "*" Usage : owns (typed by)

    class OccurrenceDefinition
    class ItemDefinition
    class PartDefinition
    class AttributeDefinition
    class PortDefinition
    class InterfaceDefinition
    class ConnectionDefinition
    class FlowConnectionDefinition
    class ActionDefinition
    class StateDefinition
    class CalculationDefinition
    class ConstraintDefinition
    class RequirementDefinition
    class CaseDefinition
    class UseCaseDefinition
    class AnalysisCaseDefinition
    class VerificationCaseDefinition
    class AllocationDefinition
    class ViewDefinition
    class ViewpointDefinition
    class ConcernDefinition
    class MetadataDefinition
    class EnumerationDefinition

    Definition <|-- OccurrenceDefinition
    OccurrenceDefinition <|-- ItemDefinition
    ItemDefinition       <|-- PartDefinition
    OccurrenceDefinition <|-- PortDefinition
    Definition <|-- AttributeDefinition
    Definition <|-- ConnectionDefinition
    ConnectionDefinition <|-- InterfaceDefinition
    ConnectionDefinition <|-- FlowConnectionDefinition
    OccurrenceDefinition <|-- ActionDefinition
    ActionDefinition <|-- StateDefinition
    ActionDefinition <|-- CalculationDefinition
    CalculationDefinition <|-- ConstraintDefinition
    ConstraintDefinition  <|-- RequirementDefinition
    RequirementDefinition <|-- ConcernDefinition
    RequirementDefinition <|-- ViewpointDefinition
    CalculationDefinition <|-- CaseDefinition
    CaseDefinition <|-- UseCaseDefinition
    CaseDefinition <|-- AnalysisCaseDefinition
    CaseDefinition <|-- VerificationCaseDefinition
    Definition <|-- AllocationDefinition
    Definition <|-- ViewDefinition
    Definition <|-- MetadataDefinition
    AttributeDefinition <|-- EnumerationDefinition
```

## 4. Modeling relationships

```mermaid
classDiagram
    class Relationship
    class Satisfy
    class Verify
    class Refine
    class Trace
    class DeriveRequirement
    class Copy
    Relationship <|-- Satisfy
    Relationship <|-- Verify
    Relationship <|-- Refine
    Relationship <|-- Trace
    Relationship <|-- DeriveRequirement
    Relationship <|-- Copy

    class PartUsage
    class RequirementDefinition
    class VerificationCaseDefinition

    PartUsage --> RequirementDefinition : Satisfy
    VerificationCaseDefinition --> RequirementDefinition : Verify
```

## 5. Engine services

```mermaid
flowchart LR
    SRC[".sysml source"] -->|tokenize + parse| PARSER[Parser]
    PARSER -->|metamodel objects| REPO[(Repository<br/>containment tree)]
    REPO -->|register_tree| REG[ElementRegistry<br/>UUID → Element]

    REPO --> VALID[Validator]
    VALID --> ISSUES["ValidationIssue list<br/>(severity, rule, message, element)"]

    REPO --> SER[Serializer]
    SER -->|to_json| JSON["project.json"]
    JSON -->|from_json| REPO

    REPO --> RES["resolve(qname) /<br/>by_id / by_kind / find"]
```

## 6. GUI runtime

```mermaid
flowchart TB
    subgraph TK["Tkinter window (gui.app.SysMLApp)"]
        MENU["Menu bar<br/>File / Edit / Model"]
        TOOL["Toolbar<br/>New | Open | Save | Validate | Add ..."]
        TREE["Containment Tree<br/>(ttk.Treeview)"]
        PROPS["Properties pane<br/>(form for selected element)"]
        LOG["Output / Validation log<br/>(tk.Text)"]
        STATUS["Status bar"]
    end

    USER((User)) --> MENU
    USER --> TOOL
    USER --> TREE
    USER --> PROPS

    MENU  -->|cmd_*| CTRL[Controller methods]
    TOOL  -->|cmd_add_element| CTRL
    TREE  -->|select / right-click| CTRL
    PROPS -->|on_apply| CTRL

    CTRL --> REPO[(Repository)]
    CTRL --> PARSER[Parser]
    CTRL --> VALID[Validator]
    CTRL --> SER[Serializer]

    REPO  -->|owned_elements| TREE
    REPO  -->|element data| PROPS
    VALID -->|issues| LOG
    PARSER -->|errors| LOG
    SER   -->|file IO result| LOG
    CTRL  -->|status text| STATUS
```

## 7. Typical user flow — “add a Part and validate”

```mermaid
sequenceDiagram
    actor U as User
    participant G as Tkinter GUI
    participant R as Repository
    participant M as SysML v2 Metamodel
    participant V as Validator

    U->>G: click "Part Def", name = "Vehicle"
    G->>M: PartDefinition(name="Vehicle")
    G->>R: parent.own(Vehicle); registry.register_tree
    R-->>G: ok
    G->>G: insert tree node, select it

    U->>G: edit properties (mass : Mass [1..1])
    G->>M: AttributeUsage(name="mass", typed_by=Mass)
    G->>R: Vehicle.own(usage)

    U->>G: F5 (Validate)
    G->>V: validate(repo)
    V->>R: iterate all elements
    V-->>G: list[ValidationIssue]
    G->>U: render issues in log + status bar
```

## 8. Persistence format (JSON)

```mermaid
flowchart LR
    REPO[(Repository)] -->|to_dict| MAP[/"{<br/>  format: 'sysmlv2-core/1',<br/>  name, root,<br/>  elements: [ {id, class, kind,<br/>    name, owner, ...payload} ]<br/>}"/]
    MAP -->|json.dumps| FILE[(project.json)]
    FILE -->|json.loads → from_dict| REPO2[(Repository′)]
    REPO2 -->|element ids preserved| ROUND["round-trip: ids,<br/>names, types,<br/>multiplicities, specializations"]
```

## 9. Module map

```mermaid
flowchart LR
    subgraph kerml
        kE[elements.py]
        kN[namespaces.py]
        kT[types.py]
        kF[features.py]
        kX[expressions.py]
        kL[library.py]
    end
    subgraph sysmlv2
        sD[definitions.py]
        sR[relationships.py]
        sL[library.py]
    end
    subgraph engine
        eR[repository.py]
        eP[parser.py]
        eV[validator.py]
        eS[serializer.py]
        eC[cli.py]
    end
    subgraph gui
        gA[app.py]
    end

    kN --> kE
    kT --> kN
    kF --> kT
    kX --> kF
    kL --> kT
    sD --> kF
    sD --> kT
    sR --> kE
    sL --> sD
    eR --> kN
    eR --> sL
    eP --> sD
    eV --> sD
    eS --> sD
    eC --> eR
    eC --> eP
    eC --> eV
    eC --> eS
    gA --> eR
    gA --> eP
    gA --> eV
    gA --> eS
    gA --> sD
```
