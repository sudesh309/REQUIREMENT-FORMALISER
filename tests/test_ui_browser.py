"""Runs the headless-browser UI scenarios in tests/ui/scenarios/.

Skipped when Node.js or the Playwright package is not available. Set
PLAYWRIGHT_MODULE to the package's index.mjs to point at a specific install.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.webapp_harness import WebAppTestCase

RUNNER = Path(__file__).resolve().parent / "ui" / "run_scenarios.mjs"


def _playwright_module():
    explicit = os.environ.get("PLAYWRIGHT_MODULE")
    if explicit:
        return explicit if Path(explicit).is_file() else None
    if not shutil.which("node") or not shutil.which("npm"):
        return None
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    candidate = Path(root) / "playwright" / "index.mjs"
    return str(candidate) if candidate.is_file() else None


PLAYWRIGHT = _playwright_module()


@unittest.skipUnless(PLAYWRIGHT, "node + playwright not available")
class BrowserScenarioTests(WebAppTestCase):

    def test_ui_scenarios(self):
        artifacts = tempfile.mkdtemp(prefix="ui-artifacts-")
        env = {**os.environ, "PLAYWRIGHT_MODULE": PLAYWRIGHT, "UI_ARTIFACT_DIR": artifacts,
               "UI_FILTER": os.environ.get("UI_FILTER", "")}
        proc = subprocess.run(["node", str(RUNNER), self.base, env["UI_FILTER"]],
                              capture_output=True, text=True, env=env, timeout=600)
        results = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
        failures = [r for r in results if not r["ok"]]
        self.assertTrue(results, f"no scenarios ran: {proc.stderr[-2000:]}")
        self.assertEqual(failures, [], json.dumps(failures, indent=2))


if __name__ == "__main__":
    unittest.main()
