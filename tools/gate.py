"""Stage gate: is the code ready to move to the next stage?

    python -m tools.gate                    # tests + JS syntax + conformance regressions
    python -m tools.gate --phase 1          # ... plus the phase 1 targets (repeatable)
    python -m tools.gate --package          # ... plus a clean-venv install check
    python -m tools.gate --skip-tests       # conformance only (fast, while iterating)

Steps, all of which must pass:

1. the unit test suite (``python -m unittest discover -s tests``), which
   includes the headless-browser scenarios when Node.js and Playwright exist;
2. ``node --check`` on every studio script (vendored libraries excluded);
3. conformance metrics: no regression against ``tools/conformance/baseline.json``
   and every target of the named phases met (``tools/conformance/targets.json``);
4. with ``--package``: ``pip install .`` into a fresh virtual environment, then
   import the packages and check that the web studio files and the standard
   model libraries were installed.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _step(title: str, cmd: list[str], **kw) -> bool:
    print(f"\n=== {title} ===\n$ {' '.join(cmd)}", flush=True)
    ok = subprocess.run(cmd, cwd=kw.pop("cwd", ROOT), **kw).returncode == 0
    print(f"--- {title}: {'PASS' if ok else 'FAIL'}", flush=True)
    return ok


def _js_check() -> bool:
    node = shutil.which("node")
    if node is None:
        print("\n=== JavaScript syntax ===\nnode not found: skipped")
        return True
    scripts = sorted(p for p in (ROOT / "webapp" / "static").rglob("*.js") if "vendor" not in p.parts)
    bad = [p for p in scripts
           if subprocess.run([node, "--check", str(p)], capture_output=True).returncode != 0]
    print(f"\n=== JavaScript syntax ===\n{len(scripts)} scripts, {len(bad)} with errors")
    for p in bad:
        print(f"  {p.relative_to(ROOT)}")
    return not bad


_PACKAGE_CHECK = r"""
import importlib, pathlib, sys
for mod in ("kerml", "sysmlv2", "engine", "webapp", "mcp_server", "sysml_spec"):
    importlib.import_module(mod)
import sysml_spec, webapp
static = pathlib.Path(webapp.__file__).parent / "static"
assert (static / "index.html").exists(), "web studio files missing"
assert len(sysml_spec.library_files()) >= 90, "standard model libraries missing"
assert sysml_spec.KERML_REFLECTIVE.exists() and sysml_spec.SYSML_GRAMMAR.exists()
print("installed package OK:", len(sysml_spec.library_files()), "library files")
"""


def _package_check() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "venv"
        py = venv / "bin" / "python"
        return (_step("Package: create venv", [sys.executable, "-m", "venv", str(venv)])
                and _step("Package: pip install .", [str(py), "-m", "pip", "install", "-q", str(ROOT)])
                # Run from the temp dir so the source tree is not on sys.path.
                and _step("Package: import check", [str(py), "-c", _PACKAGE_CHECK], cwd=tmp))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.gate")
    ap.add_argument("--phase", action="append", default=[], help="phase targets to check")
    ap.add_argument("--package", action="store_true", help="also check a clean install")
    ap.add_argument("--skip-tests", action="store_true", help="skip the unit test suite")
    args = ap.parse_args(argv)

    results = {}
    if not args.skip_tests:
        results["unit tests"] = _step("Unit tests", [sys.executable, "-m", "unittest", "discover",
                                                     "-s", "tests"])
    results["JavaScript syntax"] = _js_check()
    conf = [sys.executable, "-m", "tools.conformance"]
    for p in args.phase:
        conf += ["--phase", p]
    results["conformance"] = _step("Conformance", conf)
    if args.package:
        results["package"] = _package_check()

    print("\n=== Gate summary ===")
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    passed = all(results.values())
    print(f"\nGate {'PASSED' if passed else 'FAILED'}"
          + (f" for phase {', '.join(args.phase)}" if args.phase else ""))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
