"""Spec-conformance metrics must never get worse than tools/conformance/baseline.json.

Phase targets are checked by ``python -m tools.gate --phase <id>``, not here:
an unfinished phase is not a test failure, a regression is.
"""
import unittest

from tools import conformance


class ConformanceBaselineTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = conformance.run()

    def test_every_collector_runs(self):
        broken = {k: v.get("detail") for k, v in self.report.items()
                  if k.endswith(".collector_ok") and v["value"] < 1}
        self.assertEqual(broken, {})

    def test_no_regression_against_baseline(self):
        self.assertEqual(conformance.regressions(self.report, conformance.load_baseline()), [])

    def test_targets_reference_known_phases(self):
        targets = conformance.load_targets()
        for phase in (p for p in targets if not p.startswith("_")):
            self.assertIsInstance(conformance.unmet_targets(self.report, [phase]), list)


if __name__ == "__main__":
    unittest.main()
