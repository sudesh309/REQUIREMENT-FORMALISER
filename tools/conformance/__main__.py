"""``python -m tools.conformance``: see the package docstring."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import load_baseline, markdown, regressions, run, save_baseline, unmet_targets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.conformance")
    ap.add_argument("--phase", action="append", default=[],
                    help="also check this phase's targets (repeatable)")
    ap.add_argument("--update-baseline", action="store_true",
                    help="accept the current values as the new baseline")
    ap.add_argument("--json", type=Path, help="write the full report (with details) here")
    ap.add_argument("--markdown", type=Path, help="write a status page here")
    ap.add_argument("--details", action="store_true", help="print failure details")
    args = ap.parse_args(argv)

    report = run()
    width = max(map(len, report), default=10)
    for name in sorted(report):
        m = report[name]
        print(f"{name:<{width}}  {m['value']}")
        if args.details and m.get("detail"):
            for d in m["detail"][:20]:
                print(f"    - {d}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, default=str) + "\n")
    if args.markdown:
        args.markdown.write_text(markdown(report))

    failed = False
    if args.update_baseline:
        save_baseline(report)
        print("\nBaseline updated.")
    else:
        problems = regressions(report, load_baseline())
        if problems:
            failed = True
            print("\nRegressions against tools/conformance/baseline.json:")
            print("\n".join(f"  {p}" for p in problems))
    if args.phase:
        named = ", ".join(args.phase)
        unmet = unmet_targets(report, args.phase)
        if unmet:
            failed = True
            print(f"\nTargets not met (phase {named}):")
            print("\n".join(f"  {p}" for p in unmet))
        else:
            print(f"\nAll targets of phase {named} are met.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
