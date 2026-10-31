# Grammar notes

`sysml_text` follows `sysml_spec/bnf/KerML-textual-bnf.kebnf` and
`SysML-textual-bnf.kebnf` (release 2026-09.1). The published libraries and
examples (the corpus, accepted by the OMG pilot implementation) are the
arbiter where the grammar and the corpus disagree. This page lists every such
deviation, the places where the grammar has to be interpreted, and the AST
conventions Phase 2b builds on.

The counts in brackets are occurrences in the corpus (94 library files, 310
example files), measured when the deviation was introduced.

## 1. Deviations the corpus requires

| # | Grammar (kebnf) | Parser | Corpus evidence |
|---|---|---|---|
| D1 | KerML `Invariant = FeaturePrefix 'inv' ( 'true' \| isNegated ?= 'false' )? FeatureDeclaration ...`: a declaration is required | The FeatureDeclaration of an `inv` is optional | `inv { flattenedSize == size(elements) }` (Collections.kerml) [45] |
| D2 | `LibraryPackage = ( isStandard ?= 'standard' ) 'library' ...` reads as `standard` required | `standard` is optional; `isStandard` is set only when present | `library package AHFCoreLib` [9] |
| D3 | `SatisfyRequirementUsage = OccurrenceUsagePrefix 'assert' ( isNegated ?= 'not' ) 'satisfy' ...` | `( 'assert' )? ( isNegated ?= 'not' )? 'satisfy'` | `satisfy R by p;` [20], `not satisfy r1 by p;` [1] |
| D4 | `OccurrenceUsagePrefix` starts with `BasicUsagePrefix` only, so `end` cannot precede an occurrence usage | `EndUsagePrefix` (with its optional `OwnedCrossFeatureMember`) is accepted in place of `BasicUsagePrefix` before every usage keyword | `end occurrence source: Occurrence :>> Transfer::source;` (Flows.sysml), `end touches [0..*] item touchedItem ...` [37] |
| D5 | No production for an end feature written without a usage keyword (`DefaultReferenceUsage = RefPrefix Usage` has no `end`) | `end` + `Usage` is a `ReferenceUsage` with `isEnd`; in an interface body it is `DefaultInterfaceEnd : PortUsage = isEnd ?= 'end' Usage` | `end source: Anything :>> BinaryConnection::source;` (Allocations.sysml) [45], `end source : ~PublicationPort;` in interfaces [36] |
| D6 | `EnumeratedValue : EnumerationUsage = 'enum'? Usage` | `UsageExtensionKeyword* 'enum'? Usage` (prefix metadata on enumerated values) | `#Security enum secret : ClassificationLevel = 2;` (MetadataTest.sysml) [1] |
| D7 | `FlowEndSubsetting : ReferenceSubsetting = referencedFeature = [QualifiedName] \| referencedFeature = FeatureChainPrefix ...`: the first alternative lacks the `'.'` that separates it from the flow feature | `referencedFeature = [QualifiedName] '.'`: in `a.b` the subsetting is `a`, the flow feature `b`; in `a.b.c` the subsetting is the chain `a.b` (KerML's `FlowEnd` already reads this way) | `flow from tank.fuelOut to engine.fuelIn;` [117] |
| D8 | `CaseBodyItem` has no `ReturnParameterMember` | `return` members are accepted in case bodies as in calculation bodies (a case definition is a calculation definition) | `abstract case def Case :> Calculation { ... return ... }` (Cases.sysml) [28] |
| D9 | `InitialNodeMember : FeatureMembership = MemberPrefix 'first' memberFeature = [QualifiedName] RelationshipBody`: a FeatureMembership owns its feature, and `memberFeature` is not a property | A `Membership` with `memberElement = Ref` | `first start;` [13] |
| D10 | `SendNode = OccurrenceUsagePrefix ActionUsageDeclaration? 'send' ...`: a declaration without the `action` keyword | `ActionNodeUsageDeclaration?` (`'action' UsageDeclaration?`) as for every other action node | `action publish send new Publish(...) via publicationPort;` [11] |
| D11 | SysML `DefinitionElement` omits `AllocationDefinition` | `allocation def` is a definition element | `allocation def` [6] |
| D12 | KerML reserved words omit `new`, used by `ConstructorExpression`; the symbols omit `@@`, used by `MetaclassificationTestOperator` | `new` is reserved in KerML too; `@@` is a symbol | `new ChangeSignal(condition, monitor)` (Triggers.kerml) [4] |

## 2. Grammar errors fixed by reading

These are typos or internal inconsistencies of the kebnf; the parser builds
what the grammar evidently means.

- `EntryTransitionMember = MemberPrefix ( GuardedTargetSuccession | 'then' TargetSuccession ) ';'`
  repeats `'then'`, which `TargetSuccession` already starts with. `then off;`
  after `entry` is parsed with one `then`.
- SysML `OwnedSubclassification : Subclassification = superClassifier = ...`:
  the property is `superclassifier`.
- KerML `TypeFeaturingPart = 'featured' 'by' ownedRelationship += OwnedTypeFeaturing
  ( ',' ownedTypeFeaturing += OwnedTypeFeaturing )*`: every one is added to
  `ownedRelationship` (`ownedTypeFeaturing` is derived).
- KerML `FeatureInverting ... | ownedRelatedElement += OwnedFeatureChain { ownedRelatedElement += invertingFeature }`:
  `invertingFeature` is the owned chain, which is also in `ownedRelatedElement`.
- `TypeResultMember : ResultParameterMembership`: no such metaclass; the node is
  a `ReturnParameterMembership`.
- `LiteralReal`: the metaclass is `LiteralRational`.
- `NonFeatureChainPrimaryArgumentMember ... ownedMemberParameter = PrimaryArgument`:
  same shape as `NonFeatureChainPrimaryArgument`.
- SysML has no `ExpressionBody` production of its own; the KerML one,
  `'{' FunctionBodyPart '}'`, would admit KerML members. In SysML the body of an
  expression `{ ... }` is a `CalculationBodyPart` (SysML members, then an
  optional result expression).
- `RealValue = DECIMAL_VALUE? '.' ( DECIMAL_VALUE | EXPONENTIAL_VALUE ) | EXPONENTIAL_VALUE`
  is syntax in the grammar; the lexer reads a real literal as one `REAL`
  token, so white space inside `1.5` is not accepted.

## 3. Spec rules reported but not fatal

Where the grammar is stricter than the corpus needs, the rule is enforced: the
parser reports an error diagnostic but still builds the tree, so editors and
importers keep working. No corpus file triggers these.

- `Import = visibility = VisibilityIndicator 'import' ...`: an import without
  `private`/`public`/`protected` (every corpus import has one; the default
  visibility of an import was public, hence the rule).
- KerML `TypeDeclaration`: `( SpecializationPart | ConjugationPart )+`, so
  `type T;` is reported.
- KerML `step`, `expr`, `bool` need a FeatureDeclaration (`inv` does not: D1).

## 4. Interpretations (bounded lookahead and backtracking)

The grammar is not LL(1); these are resolved deterministically:

- **Result expressions.** In function, calculation, case and expression
  bodies, an item that can start an expression is first tried as the
  `ResultExpressionMember`; it is one only if the closing `}` follows.
  Otherwise the item is parsed as a member (`x : T;`, `if g { ... }`).
- **Connector and flow ends vs. declarations.** `connector a to b`,
  `binding a = b`, `succession a then b`, `flow a.x to b.y`, `interface a.p to b.q`,
  `message a to b` try the end-only form first, then a declaration.
- **`end` cross features.** After `end`, a `UsageDeclaration` followed by a
  usage keyword (`end [1] feature x`, `end touches [0..*] item y`) is the
  `OwnedCrossFeatureMember`; otherwise it is the end feature's own declaration.
- **`then` in bodies.** In action bodies `then target;` is an
  `ActionTargetSuccessionMember`; `then <usage>` is a `SourceSuccessionMember`
  followed by the usage member (whose visibility comes after `then`). In state
  bodies `then`/`if ... then` directly after an `entry` member is an
  `EntryTransitionMember`, otherwise a `TargetTransitionUsageMember`.
- **`first` in action bodies.** `first x;` is the `InitialNodeMember`,
  `first x if g then y;` a `GuardedSuccession`, `first x then y;` a
  `SuccessionAsUsage`.
- **`if` in action bodies.** `if g then x;` is a `GuardedTargetSuccession`,
  otherwise an `IfNode`.
- **`transition`.** `transition (UsageDeclaration 'first')?` is tried with
  backtracking; `transition accept ... then` (no source) is a
  `TargetTransitionUsage`. Transitions are accepted only in state bodies and
  action nodes (`accept`, `send`, `assign`, `if`, `while`, `loop`, `for`,
  `terminate`) only in action, calculation and case bodies.
- **Assignment targets.** In `assign a.b.c := v` the target binding is `a`
  (a `NonFeatureChainPrimaryExpression`) and the assigned feature the chain
  `b.c`; in `assign x := v` there is no binding.
- **Payloads.** `of T`, `of T[1]` are a typed payload; `of x : T`,
  `of x [1] : T` declare a payload feature.
- **Invocations.** `a.b(x)` invokes the feature chain `a.b`
  (`InstantiatedTypeMember = OwnedFeatureChainMember`); `a.b` alone is a
  `FeatureChainExpression`.

## 5. AST conventions (for Phase 2b)

- **Node types** are the metaclass names of `KerML.kerml` / `SysML.sysml`
  (production names that are not metaclasses are mapped: see 2). The root of
  every parse is a `Namespace`.
- **Ownership** is carried only by `ownedRelationship` (element to
  relationship) and `ownedRelatedElement` (relationship to element), in source
  order. Grammar assignments to derived composite properties are stored under
  `ownedRelatedElement`: `ownedMemberFeature`, `ownedMemberParameter`,
  `ownedMemberElement`, `ownedFeatureMember`, `value` (FeatureValue),
  `condition` (ElementFilterMembership), `ownedVariantUsage`,
  `annotatingElement` (PrefixMetadataAnnotation). `Node.walk()` follows these
  two properties only.
- **Relationship ends.** KerML's `GeneralType`/`SpecificType` assign
  `general`/`specific`; the parser uses the property the relationship's
  metaclass redefines them with, as the SysML grammar does, so both languages
  give the same tree: `FeatureTyping.type`/`typedFeature`,
  `Subsetting.subsettedFeature`/`subsettingFeature`,
  `Redefinition.redefinedFeature`/`redefiningFeature`,
  `ReferenceSubsetting.referencedFeature`, `CrossSubsetting.crossedFeature`,
  `Subclassification.superclassifier`/`subclassifier`,
  `Conjugation.originalType`/`conjugatedType`,
  `Disjoining.disjoiningType`/`typeDisjoined`,
  `FeatureInverting.invertingFeature`/`featureInverted`. A plain
  `Specialization` keeps `general`/`specific`.
- **Feature chains.** When an end is a feature chain (`a.b.c`), the property
  holds the chain `Feature` node, which is also owned through
  `ownedRelatedElement`; its `ownedRelationship` are `FeatureChaining`s with
  `chainingFeature` refs. `Unioning`/`Intersecting`/`Differencing` with a chain
  have only `ownedRelatedElement` (as the grammar says).
- **Cross references** are `Ref(text, span, names)`: `text` as written with
  segments joined by `::` (quoted names keep their quotes), `names` the
  unescaped segment names, `is_global` for `$::`. One special case:
  `ConjugatedPortTyping.originalPortDefinition` (the kebnf's name, not a
  metamodel property) names the *original* `PortDefinition`; the typing's
  `conjugatedPortDefinition` is that definition's `ConjugatedPortDefinition`
  (kebnf note on `~[QualifiedName]`).
- **Implied elements of the grammar are present**: `EmptyResultMember`
  (`ReturnParameterMembership` owning an empty `Feature`) after operator and
  invocation expressions, `EmptyParameterMember`, `EmptyMultiplicityMember`
  of individuals, the `ConjugatedPortDefinition` member (with its
  `PortConjugation`) at the end of every `PortDefinition`, the empty source end
  of successions and transitions. They have zero-length spans. The
  `PortConjugation.originalPortDefinition` back-reference of the grammar's
  action is not stored: it is always the owning `PortDefinition`.
- **Expression operands** follow the grammar's wrappers: an argument is a
  `ParameterMembership` owning a `Feature` owning a `FeatureValue` owning the
  expression. The lazy operand of `and`, `or`, `implies`, `??` and the branches
  of `if` are wrapped once more as a `FeatureReferenceExpression` owning a
  `FeatureMembership` owning the expression; that outer member is a
  `FeatureMembership` in KerML and a `ParameterMembership` in SysML, as each
  grammar's `ArgumentExpressionMember` says.
- **Grammar actions** are applied: `isVariable = true` with `const`,
  `isUnique = false` with `nonunique`, `isPortion = true` with a portion kind,
  `isAbstract = true` on messages, `isComposite = true` on control nodes
  (`isComposite ?= 'merge'`), `kind` on state subaction, transition feature,
  requirement constraint and verification memberships and trigger
  expressions, `visibility = 'public'` on the import inside a filter package.
- **Memberships** are the grammar's: members of packages (and root
  namespaces) are `OwningMembership`s, usages included; in types, features are
  owned through `FeatureMembership`. Directed features of KerML behaviors and
  functions (`in x : T;`) are therefore `FeatureMembership`s, not
  `ParameterMembership`s: the grammar does not distinguish parameters, so
  Phase 2b decides.
- **Values**: `LiteralInteger.value` is an `int`, `LiteralRational.value` a
  `float`, `LiteralString.value` the unescaped text, `LiteralBoolean.value` a
  `bool`; `Comment`/`Documentation`/`TextualRepresentation` `body` is the text
  processed as KerML 8.2.3.3.2 Note 1 says. Enumerated literals of the
  metamodel are strings (`'in'`, `'public'`, `'entry'`, `'trigger'`,
  `'snapshot'`, `'assumption'`).
- **Spans** are character offsets into the source; `line`/`col` are computed
  on demand.

## 6. Printer (`printer.py`)

`print_tree` is the inverse of the parser: for every corpus file
`parse(print_tree(parse(text).root))` gives the same tree (`ast.diff` is None;
metric `print.*.ast_roundtrip_ok`). Where several spellings parse to the same
tree, it writes one canonical form:

- symbols for keyword forms: `:>` (`specializes`, `subsets`), `:>>`
  (`redefines`), `:` (`typed by`, `defined by`), `::>` (`references`), `=>`
  (`crosses`), `~` (`conjugates`);
- names plain unless they need quotes (not a basic name, or a reserved word of
  the language); references exactly as written (`Ref.text`);
- leading plain metadata usages of an element as `#X` prefixes (`part p { @X; }`
  and `#X part p;` are the same tree); a named metadata usage as
  `metadata m : X`, an unnamed one as `@X`;
- `satisfy` without `assert` unless negated (`assert not satisfy`); `message`
  for an abstract flow without flow ends; `enum` before enumerated values;
  `individual x` / `snapshot x` without `occurrence`;
- KerML features without the `feature` keyword when they have a direction, are
  an end without cross feature, or are a return parameter;
- in state bodies, `transition` before a target transition only when it is
  needed (an effect without trigger or guard, or right after an `entry`
  member, where a bare `then x;` is an entry transition);
- sequences flattened (`(1, (2, 3))` is `(1, 2, 3)`), the fewest parentheses
  operator precedence allows, real literals as Python writes the float
  (`2.5e3` is `2500.0`);
- comment bodies on one line when they are one line without leading white
  space, otherwise as a `/*` block with ` * ` prefixes;
- implied elements (empty result members, empty parameters and usages, a port
  definition's conjugate, the empty multiplicity of individuals) are not
  written; the parser rebuilds them.

## 7. Known limitations

- Body contexts are enforced for keyword-introduced members (`subject`,
  `actor`, `objective`, `require`, `frame`, `verify`, `entry`/`do`/`exit`,
  `render`, `expose`, `filter`, `return`, transitions, action nodes) but not
  for every usage kind in every body: for instance a reference usage without
  keyword is accepted in an interface body (`InterfaceNonOccurrenceUsageElement`
  excludes it), and every usage element in a package or definition body.
  Metadata bodies are enforced (definitions and redefinitions only).
- Recovery drops the member that contains an error (no partial nodes) and
  resumes after the next `;` or block.
- Regular comments `/* */` are elements: one in a place the grammar does not
  allow an annotating element (inside a declaration) is a syntax error, as the
  grammar says.
- The graphical grammar (`SysML-graphical-bnf.kgbnf`) is not covered.
