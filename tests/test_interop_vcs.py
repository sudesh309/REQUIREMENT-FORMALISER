"""Version-control friendly project files: deterministic, stable JSON."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine import Repository, from_json, to_json
from engine.interop.common import move_element
from engine.interop.xmi_import import xmi_to_project
from kerml.namespaces import Package
from tests.test_interop_fixtures import XMI_FIXTURE, avionics_repo

ROOT = Path(__file__).resolve().parent.parent


class DeterministicJsonTests(unittest.TestCase):

    def _roundtrip_files(self, repo):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d, "a.json"), Path(d, "b.json")
            repo.save(str(a))
            Repository.load(str(a)).save(str(b))
            return a.read_bytes(), b.read_bytes()

    def test_save_load_save_is_byte_identical(self):
        for repo in (avionics_repo(), xmi_to_project(XMI_FIXTURE.read_bytes())[0]):
            first, second = self._roundtrip_files(repo)
            self.assertEqual(first, second, repo.name)

    def test_two_saves_identical_and_canonical(self):
        repo = avionics_repo()
        text = to_json(repo)
        self.assertEqual(text, to_json(repo))
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(text, json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n")

    def test_order_follows_containment_not_creation(self):
        repo = avionics_repo()
        late = repo.add(Package(name="Late"))
        move_element(repo.resolve("Components::GPSReceiver"), late)
        text = to_json(repo)
        self.assertEqual(to_json(from_json(text)), text)
        names = [e["name"] for e in json.loads(text)["elements"]]
        self.assertLess(names.index("Late"), names.index("GPSReceiver"))

    def test_library_types_saved_by_name_and_restored(self):
        repo = avionics_repo()
        data = json.loads(to_json(repo))
        label = next(e for e in data["elements"] if e["name"] == "label")
        self.assertEqual(label["typed_by"], ["lib:KerML::ScalarValues::Integer"])
        loaded = from_json(json.dumps(data))
        self.assertEqual(loaded.resolve("Interfaces::A429Word::label").types[0].qualified_name,
                         "KerML::ScalarValues::Integer")

    def test_saves_identical_across_processes(self):
        script = ("import sys; sys.path.insert(0, %r); "
                  "from tests.test_interop_fixtures import avionics_repo; "
                  "from engine import to_json, from_json; "
                  "r = avionics_repo(); t = to_json(r); "
                  "sys.stdout.write(str(sorted(e['typed_by'] for e in __import__('json')"
                  ".loads(t)['elements'] if e.get('typed_by'))))") % str(ROOT)
        outs = [subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                               env={**os.environ, "PYTHONHASHSEED": str(seed)}, cwd=ROOT,
                               timeout=60).stdout for seed in (1, 2)]
        self.assertTrue(outs[0])
        lib_refs = [x for x in outs[0].split("'") if x.startswith("lib:")]
        self.assertTrue(lib_refs)
        self.assertEqual(outs[0].count("lib:"), outs[1].count("lib:"))
        self.assertEqual([x for x in outs[1].split("'") if x.startswith("lib:")], lib_refs)

    def test_root_documentation_survives(self):
        repo = avionics_repo()
        loaded = from_json(to_json(repo))
        from engine.interop.common import documentation
        self.assertIn("Flight deck", documentation(loaded.root_package))


if __name__ == "__main__":
    unittest.main()
