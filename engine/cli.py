"""Tiny CLI: parse, validate, and dump a SysML v2 source file."""
from __future__ import annotations

import sys
from pathlib import Path

from .parser import parse
from .repository import Repository
from .serializer import to_json
from .validator import Severity, Validator


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print("usage: python -m engine.cli <file.sysml> [--json] [--no-validate]")
        return 2

    src_path = Path(argv[0])
    flags = set(argv[1:])

    repo = Repository(name=src_path.stem)
    parse(src_path.read_text(encoding="utf-8"), into=repo.root_package)
    repo.registry.register_tree(repo.root_package)

    if "--no-validate" not in flags:
        issues = Validator().validate(repo)
        for i in issues:
            print(i)
        if any(i.severity is Severity.ERROR for i in issues):
            return 1

    if "--json" in flags:
        print(to_json(repo))
    else:
        print(f"Parsed {repo}")
        for e in repo.root_package.walk():
            depth = 0
            n = e
            while n.owner is not None and n.owner is not repo.root_package:
                depth += 1
                n = n.owner
            if e is repo.root_package:
                continue
            print("  " * depth + f"- {e.kind} {e.name or ''}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
