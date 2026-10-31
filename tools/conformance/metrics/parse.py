"""How much of the spec corpus the textual parser (``sysml_text``, Phase 2a) reads without diagnostics.

``parse.library.files_ok`` / ``parse.examples.files_ok`` are the fractions of
files that parse with no diagnostics; ``parse.*.diagnostics`` count the
diagnostics. ``detail`` lists each failing file with its first diagnostic.
The runner adds ``parse.seconds`` (the time for the whole corpus).
"""
from __future__ import annotations

from sysml_spec import ROOT, example_files, library_files


def _run(files) -> tuple[float, int, list[str]]:
    from sysml_text import parse_file
    failures = []
    count = 0
    for path in files:
        try:
            diagnostics = parse_file(path).diagnostics
        except Exception as exc:  # noqa: BLE001 - a crash counts as a failure, not a broken collector
            failures.append(f"{path.relative_to(ROOT)}: crash: {exc!r}"[:200])
            count += 1
            continue
        if diagnostics:
            d = diagnostics[0]
            failures.append(f"{path.relative_to(ROOT)}:{d.line}:{d.col}: {d.message}"[:200])
            count += len(diagnostics)
    ok = (1 - len(failures) / len(files)) if files else 0.0
    return ok, count, failures


def collect() -> list[dict]:
    lib_ok, lib_n, lib_fail = _run(library_files())
    ex_ok, ex_n, ex_fail = _run(example_files())
    return [
        {"name": "parse.library.files_ok", "value": round(lib_ok, 4), "better": "higher", "detail": lib_fail},
        {"name": "parse.examples.files_ok", "value": round(ex_ok, 4), "better": "higher", "detail": ex_fail},
        {"name": "parse.library.diagnostics", "value": lib_n, "better": "lower"},
        {"name": "parse.examples.diagnostics", "value": ex_n, "better": "lower"},
    ]
