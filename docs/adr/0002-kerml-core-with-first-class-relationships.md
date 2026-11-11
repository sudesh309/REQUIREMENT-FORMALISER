# ADR 0002: KerML core with first-class relationships (Phase 1)

Status: accepted. Applies to `kerml/`, `sysmlv2/`, `engine/serializer.py`,
`engine/repository.py`.

## Context

The engine stores many relationships as Python attributes (`ends`,
`end_contexts`, `transition_source`, `allocate_from`, `req_id`, `text`,
`featuring_type`, `exposed`, ...), owns features through `OwningMembership`
only, and has no n-ary relationships, annotations as relationships,
dependencies, or most KerML relationship kinds. Interchange, the API, the
printer and spec name resolution all walk relationships, so the core must
change. About 65,000 lines of application code and 728 tests depend on the
current API (`owner` alone has more than 200 uses).

## Decisions

### 1. The metamodel registry is generated

`tools/metagen.py` reads the reflective models `KerML.kerml` and `SysML.sysml`
in `sysml_spec/` and writes a registry of every metaclass: package, abstract
flag, supertypes, and properties with type, multiplicity, `ordered`,
`nonunique`, `derived`, `composite`, `subsets` and `redefines`. The registry
is data, not classes. Python classes declare their metaclass through `kind`
(the spec metaclass name). Application subclasses that are not spec
metaclasses (for example `RequirementSet`, `DataInterface`, `AllocationSet`)
keep their own `kind` and set `spec_metaclass` to the metaclass they are
interchanged as.

### 2. Python names follow one rule

A spec property becomes `snake_case(name)`, pluralized when its upper
multiplicity is greater than 1 (`ownedRelationship` → `owned_relationships`,
`type` → `types`, `isAbstract` → `is_abstract`). Irregular plurals and the few
clashes are listed in one override table in `kerml/metamodel.py`, which both
the coverage metric and the code use.

### 3. Ownership is through relationships

- `Element.owned_relationships` (ordered) and `Element.owning_relationship`.
- `Relationship.owned_related_elements` (ordered), `owning_related_element`,
  and ordered `sources` / `targets`. `source` / `target` remain as singular
  conveniences (the first element), because the application uses them widely.
- `Element.owner` and `Element.owned_elements` are the spec's derived `owner`
  and `ownedElement`. They may be cached, but only the mutation API changes
  them.
- `Namespace.own(child)` picks the membership: `FeatureMembership` when a type
  owns a feature, `EndFeatureMembership` for an end feature,
  `ParameterMembership` / `ReturnParameterMembership` for parameters of
  behaviors and functions, `OwningMembership` otherwise. A `membership=`
  argument overrides the choice; SysML-specific memberships (subject, actor,
  stakeholder, requirement constraint, objective, state subaction, transition
  feature, variant, view rendering, framed concern, requirement verification)
  are created by the APIs that need them.
- Annotations split into `AnnotatingElement` (`Comment`, `Documentation`,
  `TextualRepresentation`, `MetadataFeature`) and the `Annotation`
  relationship, so a comment can be `about` several elements.
  `add_annotation()` and `annotations` keep working.
- `Dependency` (n-ary client and supplier) is added.

### 4. Specialization and features

- `Type.specialize()` creates `Subclassification` between classifiers and
  `Specialization` otherwise; `Feature.add_type()` creates `FeatureTyping`;
  `subset()`, `redefine()`, `reference_subset()`, `cross_subset()`,
  `conjugate()`, `disjoin()`, unioning, intersecting, differencing,
  `FeatureChaining` and `FeatureInverting` and `TypeFeaturing` all exist as
  relationship kinds.
- `specializations`, `feature_typings`, `subsettings`, `redefinitions` and
  `conjugations` become read-only views over `owned_relationships`.
- Feature flags `is_unique` (default true), `is_ordered`, `is_variable`,
  `is_constant` are added; `is_readonly` remains as an alias of `is_constant`.
- Inherited features follow the spec: redefined features are hidden and
  private members are not inherited.
- Name resolution follows the KerML name-resolution rules: visibility,
  membership and namespace imports (recursive, `all`, filtered), inherited
  members, aliases, short names, quoted names, and the library scope.

### 5. Value-like sub-elements stay values in memory

Multiplicity ranges with literal bounds and literal feature values stay
Python values (`feature.multiplicity`, `default_value`). When a spec view is
needed (interchange, API, derived properties) they are materialized as
`MultiplicityRange` / `FeatureValue` elements with literal expressions and
deterministic ids (UUID v5 of the owner's id and a role name). Non-literal
bounds and values are real elements. This keeps element trees, which the
application walks constantly, free of thousands of trivial elements while the
interchange view stays exact.

### 6. SysML relationships held as attributes move to the spec structure

| Attribute (kept as a compatible property) | Spec structure |
|---|---|
| `ConnectionUsage.ends`, `end_contexts` | End features (`EndFeatureMembership`) with `ReferenceSubsetting` to the connected feature, using `FeatureChaining` for `part.port` |
| `TransitionUsage.transition_source`, `transition_target`, `trigger`, `guard`, `effect` | Source and target memberships, `TransitionFeatureMembership` of kind trigger (`AcceptActionUsage`), guard (`Expression`) and effect (`ActionUsage`). Guard and effect text is kept as the expression or action's source text until Phase 3 evaluates it |
| `AllocationUsage.allocate_from`, `allocate_to` | Connection ends of the allocation |
| `subject`, `actors`, `stakeholders`, `assumed_constraints`, `required_constraints` | `SubjectMembership`, `ActorMembership`, `StakeholderMembership`, `RequirementConstraintMembership` |
| `req_id` | `declared_short_name` |
| `text` | The `Documentation` of the requirement |
| `ViewUsage.exposed` | `MembershipExpose` / `NamespaceExpose` |
| `Usage.featuring_type` | The owning type, or `TypeFeaturing` |

Application-specific attributes that the spec models as metadata (requirement
`rationale`, `req_type`, `priority`, `req_status`, `verification_method`,
`port_kind`, stereotype applications) stay as extension attributes in Phase 1;
Phase 4 maps them to metadata.

### 7. Native file format `sysmlv2-core/2` is shaped like the standard JSON

Each element is saved as an object with `@id`, `@type` (spec metaclass), the
non-derived spec properties under their spec (camelCase) names with
`{"@id": ...}` references, and an `ext` object for the application's own data
(`ext_type`, tool data, extension attributes). Serialization is driven by the
registry, not by per-class code. `sysmlv2-core/1` files are migrated on load.
Phase 5 adds derived properties and schema validation to produce standard JSON.

### 8. Compatibility rules

- Spec-named properties match the specification exactly. Compatibility
  properties keep their current meaning and are documented as such.
- The existing tests are the regression gate. A test may change only where it
  asserts the old internal representation; each such change is listed in the
  merge notes.
- Performance budget: building, saving, loading and checking the avionics
  example may not get more than 30% slower.

## Consequences

- Phase 2b can build models from the parser's AST mechanically: the AST is
  shaped by the same metaclass and property names.
- Phase 5's standard JSON becomes an extension of the native format rather than
  a separate exporter.
