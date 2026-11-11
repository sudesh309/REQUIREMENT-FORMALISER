"""Every library and example file of the OMG release parses with no diagnostics (Phase 2a target)."""
import time
import unittest

import sysml_spec
from tools.conformance.metrics import parse as parse_metric


class CorpusTests(unittest.TestCase):

    def test_whole_corpus_parses_without_diagnostics(self):
        started = time.perf_counter()
        metrics = {m["name"]: m for m in parse_metric.collect()}
        seconds = time.perf_counter() - started
        # the failing files with their first diagnostic, if any
        self.assertEqual(metrics["parse.library.files_ok"]["detail"], [])
        self.assertEqual(metrics["parse.examples.files_ok"]["detail"], [])
        self.assertEqual(metrics["parse.library.files_ok"]["value"], 1.0)
        self.assertEqual(metrics["parse.examples.files_ok"]["value"], 1.0)
        self.assertEqual(metrics["parse.library.diagnostics"]["value"], 0)
        self.assertEqual(metrics["parse.examples.diagnostics"]["value"], 0)
        self.assertLess(seconds, 60)

    def test_corpus_is_present(self):
        self.assertEqual(len(sysml_spec.library_files()), 94)
        self.assertGreaterEqual(len(sysml_spec.example_files()), 310)


if __name__ == "__main__":
    unittest.main()
