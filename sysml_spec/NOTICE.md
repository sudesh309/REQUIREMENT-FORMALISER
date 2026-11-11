# Third-party notice

The model libraries (`library/`), grammars (`bnf/`) and example models
(`examples/`) in this directory are copied unchanged from the
[SysML v2 Release](https://github.com/Systems-Modeling/SysML-v2-Release)
repository of the OMG Systems Modeling Community, release **2026-09.1**
(commit `9546486`). They implement the OMG specifications KerML 1.0,
SysML 2.0 and Systems Modeling API and Services 1.0
(metamodel URIs `https://www.omg.org/spec/KerML/20250201` and
`https://www.omg.org/spec/SysML/20250201`).

They are distributed under the **Eclipse Public License 2.0**; see `LICENSE`
in this directory. The rest of this project is MIT licensed.

To update: copy `sysml.library/`, `bnf/*.kebnf`, `bnf/*.kgbnf`,
`kerml/src/` and `sysml/src/` from a newer release, update `RELEASE` and
`SOURCE_COMMIT` in `__init__.py` and this notice, then run
`python -m tools.gate` and review the conformance changes.
