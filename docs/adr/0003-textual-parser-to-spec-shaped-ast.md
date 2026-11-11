# ADR 0003: Full textual parser to a spec-shaped AST (Phase 2a)

Status: accepted. Applies to the new package `sysml_text/`.

## Context

The existing parser (`engine/parser.py`) reads a small subset and none of the
standard library. A full parser is needed for import, for loading the standard
libraries, and for the text editor. It can be built in parallel with the
Phase 1 core if it does not depend on the model classes.

## Decisions

1. **Separate, pure package.** `sysml_text/` imports nothing from `kerml`,
   `sysmlv2` or `engine`. It turns text into an AST and diagnostics. Building
   model elements from the AST is Phase 2b.
2. **Grammar source.** The productions follow `sysml_spec/bnf/KerML-textual-bnf.kebnf`
   and `SysML-textual-bnf.kebnf`, including the lexical rules (basic and
   quoted names with escapes, reserved words of each language, decimal and
   exponent literals, strings, `//` and `//* */` notes, `/* */` comments, which
   are elements, not whitespace).
3. **Hand-written recursive descent**, one method per production named after
   it, with a Pratt parser for expressions using the specification's operator
   precedence. Bounded lookahead or backtracking is allowed where the grammar
   is not LL(1); parsing stays deterministic.
4. **Spec-shaped AST.** A node is `Node(type, props, span)`:
   - `type` is the metaclass the production builds (`PartUsage`,
     `OwningMembership`, `FeatureTyping`, `OperatorExpression`, ...);
   - `props` uses the property names of the grammar's assignments
     (`ownedRelationship`, `declaredName`, `isAbstract`, ...): `+=` appends to
     a list, `=` sets a value, `?=` sets `True`;
   - cross references (`[QualifiedName]`) are unresolved `Ref` objects holding
     the name text and its span.

   Phase 2b can then create model elements generically from the metamodel
   registry (ADR 0002).
5. **Diagnostics, not exceptions.** Syntax errors become diagnostics with a
   line/column span; the parser recovers at `;` and `}` and keeps going, as the
   editor needs.
6. **API.** `sysml_text.parse(text, language="sysml" | "kerml", path=None)`
   returns `ParseResult(root, diagnostics)`; `parse_file(path)` chooses the
   language from the extension.
7. **Conformance metrics** in `tools/conformance/metrics/parse.py`:
   `parse.library.files_ok`, `parse.examples.files_ok` (files with no
   diagnostics), and diagnostic counts. Phase 2a target: every library and
   example file parses with no diagnostics, the whole corpus in under 60
   seconds.

## Consequences

- The old `engine.parse` stays until Phase 2b replaces it, so the application
  keeps working while the new parser grows.
- The AST doubles as the outline and folding source for the Phase 6 editor.
