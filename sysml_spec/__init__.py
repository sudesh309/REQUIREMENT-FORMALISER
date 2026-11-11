"""Normative OMG SysML v2 / KerML artifacts, vendored unchanged.

The files under this package come from the Systems-Modeling SysML-v2-Release
repository (see ``NOTICE.md``) and are licensed under the Eclipse Public
License 2.0 (``LICENSE``); the rest of this project is MIT licensed.

- ``library/``: the normative model libraries in textual notation (Kernel,
  Systems and Domain libraries), with their ``.meta.json`` / ``.project.json``
  project descriptors. ``Kernel Semantic Library/KerML.kerml`` and
  ``Systems Library/SysML.sysml`` are the reflective models of the abstract
  syntax that the metamodel registry is generated from.
- ``bnf/``: the textual (``.kebnf``) and graphical (``.kgbnf``) grammars.
- ``examples/``: the published example, training and validation models, used
  as the conformance corpus (not installed with the package).
"""
from __future__ import annotations

from pathlib import Path

RELEASE = "2026-09.1"
SOURCE = "https://github.com/Systems-Modeling/SysML-v2-Release"
SOURCE_COMMIT = "9546486"
METAMODEL_URI = {"KerML": "https://www.omg.org/spec/KerML/20250201",
                 "SysML": "https://www.omg.org/spec/SysML/20250201"}

ROOT = Path(__file__).resolve().parent
LIBRARY_DIR = ROOT / "library"
BNF_DIR = ROOT / "bnf"
EXAMPLES_DIR = ROOT / "examples"

KERML_REFLECTIVE = LIBRARY_DIR / "Kernel Libraries" / "Kernel Semantic Library" / "KerML.kerml"
SYSML_REFLECTIVE = LIBRARY_DIR / "Systems Library" / "SysML.sysml"
KERML_GRAMMAR = BNF_DIR / "KerML-textual-bnf.kebnf"
SYSML_GRAMMAR = BNF_DIR / "SysML-textual-bnf.kebnf"
SYSML_GRAPHICAL_GRAMMAR = BNF_DIR / "SysML-graphical-bnf.kgbnf"


def _models(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.suffix in (".kerml", ".sysml"))


def library_files() -> list[Path]:
    """Every model file of the normative libraries, in a stable order."""
    return _models(LIBRARY_DIR)


def example_files() -> list[Path]:
    """Every published example / training / validation model (empty in an installed package)."""
    return _models(EXAMPLES_DIR) if EXAMPLES_DIR.is_dir() else []
