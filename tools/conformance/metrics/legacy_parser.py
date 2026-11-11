"""How much of the spec corpus the original subset parser (``engine.parse``) reads.

This is the Phase 0 baseline. It is retired, with an explicit baseline update,
when the full parser replaces ``engine.parse``.
"""
from __future__ import annotations

from sysml_spec import example_files, library_files


def _rate(files) -> tuple[float, list[str]]:
    from engine.parser import parse
    from kerml.namespaces import Package
    failures = []
    for path in files:
        try:
            parse(path.read_text(encoding="utf-8"), into=Package(name="corpus"))
        except Exception as exc:  # noqa: BLE001 - any failure counts
            failures.append(f"{path.name}: {str(exc).splitlines()[0][:120]}")
    return (1 - len(failures) / len(files) if files else 0.0), failures


def collect() -> list[dict]:
    lib, lib_fail = _rate(library_files())
    ex, ex_fail = _rate(example_files())
    return [
        {"name": "legacy_parser.library.files_ok", "value": round(lib, 4), "better": "higher",
         "detail": lib_fail},
        {"name": "legacy_parser.examples.files_ok", "value": round(ex, 4), "better": "higher",
         "detail": ex_fail},
    ]
