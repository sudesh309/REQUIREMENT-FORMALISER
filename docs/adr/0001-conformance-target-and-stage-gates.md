# ADR 0001: Conformance target, spec artifacts and stage gates

Status: accepted. Context: `docs/SPEC_GAP_ANALYSIS.md`.

## Decisions

1. **Target.** Conformance to KerML 1.0 and SysML 2.0 abstract syntax, textual
   notation, semantics and model interchange, and to the Systems Modeling API
   REST binding. Graphical notation for the general, interconnection, state
   transition, action flow, grid and browser views first; sequence and geometry
   views later.
2. **Source of truth.** The OMG artifacts in `sysml_spec/` (release 2026-09.1,
   EPL-2.0, see `sysml_spec/NOTICE.md`): the normative libraries, the textual
   grammars (`.kebnf`) and the reflective abstract-syntax models
   `KerML.kerml` and `SysML.sysml`. The specification PDFs are not vendored;
   use a local clone of the release repository when needed.
3. **Generated metamodel.** Metaclass names, supertypes and properties are
   generated from the reflective models, not typed by hand (ADR 0002).
4. **Standard library only** at runtime. Development tools may use extra
   packages.
5. **Saved projects are migrated on load**; the `sysmlv2-core/1` format stays
   readable.
6. **Vocabulary.** Editors keep the System Composer terms (component,
   interface, stereotype); the inspector also shows the SysML v2 metaclass.

## Stage gates

A stage is ready to hand over when `python -m tools.gate --phase <id>` passes:

- the full unit test suite, including the headless-browser scenarios;
- `node --check` on every studio script;
- conformance metrics (`tools/conformance/`): no regression against
  `baseline.json`, and every target of the phase in `targets.json` met;
- for milestones, `--package` too (a clean `pip install .`).

Work streams run in parallel on `wip/<stream>` branches pushed after each
milestone. A stream adds metric collectors and tests but never edits
`baseline.json`; the baseline moves when the stream is merged into the working
branch after its gate passes. Milestones (M1 to M5 in the gap analysis) also
need a Project Owner and System User review before the next phase builds on
them.

## Consequences

- The `legacy_parser.*` metrics record the starting point: the original subset
  parser reads none of the 94 library files and none of the 310 example models.
- Phase 0's "quick wins" in the old parser and exporter are dropped: the new
  parser (stream 2a) is built in parallel with Phase 1 and supersedes them.
