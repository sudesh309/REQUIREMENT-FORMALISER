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

Run tests:

```bash
python -m unittest discover -s tests -v
```

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
