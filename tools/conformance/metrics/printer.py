"""AST round trip of the textual printer (``sysml_text.printer``, Phase 2b).

For every corpus file, ``parse(print(parse(file)))`` must equal ``parse(file)``
structurally (node types, properties, reference texts; spans ignored) and the
reprinted text must parse with no diagnostics. ``print.*.ast_roundtrip_ok``
are the fractions of files that do; ``detail`` lists each failing file with
its first structural difference (or the first diagnostic, or the crash). The
runner adds ``printer.seconds`` (the time for the whole corpus).
"""
from __future__ import annotations

from sysml_spec import ROOT, example_files, library_files


def roundtrip(path) -> str | None:
    """None when the file round trips, else why not."""
    from sysml_text import parse, parse_file
    from sysml_text.ast import diff
    from sysml_text.printer import print_tree

    first = parse_file(path)
    text = print_tree(first.root, first.language)
    second = parse(text, first.language)
    if second.diagnostics:
        d = second.diagnostics[0]
        return f"reprinted text {d.line}:{d.col}: {d.message}"
    return diff(first.root, second.root)


def _run(files) -> tuple[float, list[str]]:
    failures = []
    for path in files:
        try:
            problem = roundtrip(path)
        except Exception as exc:  # noqa: BLE001 - a crash counts as a failure, not a broken collector
            problem = f"crash: {exc!r}"
        if problem:
            failures.append(f"{path.relative_to(ROOT)}: {problem}"[:300])
    ok = (1 - len(failures) / len(files)) if files else 0.0
    return ok, failures


def collect() -> list[dict]:
    lib_ok, lib_fail = _run(library_files())
    ex_ok, ex_fail = _run(example_files())
    return [
        {"name": "print.library.ast_roundtrip_ok", "value": round(lib_ok, 4), "better": "higher",
         "detail": lib_fail},
        {"name": "print.examples.ast_roundtrip_ok", "value": round(ex_ok, 4), "better": "higher",
         "detail": ex_fail},
    ]
