"""Model comparison and three-way merge."""
import json
import unittest

from engine import create_link, from_json, to_json
from engine.interop import InteropError
from engine.interop.diff import compare, merge_to_repo, project_data, three_way_merge
from kerml.features import FeatureDirection
from kerml.stereotypes import stereotypes_on
from sysmlv2 import ConnectionUsage, PartUsage, PortUsage
from tests.test_interop_fixtures import avionics_repo


def _changes(diff):
    return {c["qualified_name"]: c for c in diff["changes"]}


def _props(change):
    return {p["property"]: (p["old"], p["new"]) for p in change["properties"]}


class CompareTests(unittest.TestCase):

    def setUp(self):
        self.repo = avionics_repo()
        self.saved = to_json(self.repo)

    def test_identical(self):
        diff = compare(self.saved, self.repo)
        self.assertTrue(diff["identical"])
        self.assertEqual(diff["summary"], {"added": 0, "removed": 0, "modified": 0})
        self.assertEqual(diff["tree"], [])

    def test_property_level_differences(self):
        r = self.repo
        r.resolve("FlightDeck::gps").name = "gnss"
        r.resolve("Components::GPSReceiver::navOut").direction = FeatureDirection.INOUT
        pfd = r.resolve("FlightDeck::pfd")
        pfd.feature_typings = []
        pfd.add_type(r.resolve("Components::GPSReceiver"))
        fmc = r.resolve("Components::FlightManagementComputer")
        stereotypes_on(fmc)[0].values["mass"] = 5.0
        part = r.resolve("FlightDeck::ims::partition1")
        from engine.interop.common import move_element
        move_element(part, r.resolve("FlightDeck"))
        create_link("satisfy", r.resolve("FlightDeck"), r.resolve("Requirements::AttitudeDisplay"))
        diff = compare(self.saved, r)
        ch = _changes(diff)
        self.assertEqual(_props(ch["FlightDeck::gnss"])["name"], ("gps", "gnss"))
        self.assertEqual(_props(ch["Components::GPSReceiver::navOut"])["direction"], ("out", "inout"))
        self.assertEqual(_props(ch["FlightDeck::pfd"])["type"],
                         (["Components::PrimaryFlightDisplay"], ["Components::GPSReceiver"]))
        self.assertEqual(_props(ch["Components::FlightManagementComputer"])["LRU.mass"], (4.2, 5.0))
        self.assertEqual(_props(ch["FlightDeck::partition1"])["owner (moved)"],
                         ("FlightDeck::ims", "FlightDeck"))
        self.assertEqual(_props(ch["FlightDeck"])["link"],
                         (None, "satisfy -> Requirements::AttitudeDisplay"))
        self.assertEqual(diff["summary"]["modified"], 6)

    def test_added_removed_and_tree(self):
        r = self.repo
        ims = r.resolve("FlightDeck::ims")
        new = PortUsage(name="maint", direction=FeatureDirection.IN)
        ims.own(new)
        r.registry.register(new)
        r.remove(r.resolve("Requirements::LateralGuidance"))
        diff = compare(self.saved, r)
        ch = _changes(diff)
        self.assertEqual(ch["FlightDeck::ims::maint"]["change"], "added")
        self.assertEqual(ch["Requirements::LateralGuidance"]["change"], "removed")
        # The derive link left with the requirement: shown on its old source only.
        top = {n["name"]: n for n in diff["tree"]}
        self.assertIsNone(top["FlightDeck"]["change"])
        ims_node = top["FlightDeck"]["children"][0]
        self.assertEqual((ims_node["name"], ims_node["change"]), ("ims", None))
        self.assertEqual(ims_node["children"][0]["change"], "added")
        self.assertEqual(diff["summary"], {"added": 1, "removed": 1, "modified": 0})

    def test_layout_ignored_unless_asked(self):
        self.repo.resolve("FlightDeck").tool_data["layout"] = {"x": 5}
        self.assertTrue(compare(self.saved, self.repo)["identical"])
        self.assertFalse(compare(self.saved, self.repo, include_layout=True)["identical"])

    def test_inputs(self):
        self.assertTrue(compare(json.loads(self.saved), self.saved.encode())["identical"])
        with self.assertRaises(InteropError):
            compare("{not json", self.repo)
        with self.assertRaises(InteropError):
            compare('{"hello": 1}', self.repo)
        self.assertEqual(project_data(self.repo)["name"], "FlightDeck")


class MergeTests(unittest.TestCase):

    def setUp(self):
        self.base = to_json(avionics_repo())
        self.mine = from_json(self.base)
        self.theirs = from_json(self.base)

    def test_non_conflicting_changes_merge_automatically(self):
        m, t = self.mine, self.theirs
        m.resolve("FlightDeck::gps").name = "gnss"                       # mine renames
        port = t.resolve("Components::GPSReceiver::navOut")
        port.direction = FeatureDirection.INOUT                           # theirs edits a port
        new = PartUsage(name="adc")
        t.resolve("FlightDeck").own(new)                                  # theirs adds
        t.registry.register(new)
        m.remove(m.resolve("Requirements::LateralGuidance"))              # mine deletes
        create_link("satisfy", t.resolve("FlightDeck"), t.resolve("Requirements::AttitudeDisplay"))
        res = three_way_merge(self.base, to_json(t), to_json(m))
        self.assertEqual(res.conflicts, [])
        repo = merge_to_repo(res)
        self.assertIsNotNone(repo.resolve("FlightDeck::gnss"))
        self.assertIsNotNone(repo.resolve("FlightDeck::adc"))
        self.assertIsNone(repo.resolve("Requirements::LateralGuidance"))
        self.assertIs(repo.resolve("Components::GPSReceiver::navOut").direction,
                      FeatureDirection.INOUT)
        self.assertIn(repo.resolve("FlightDeck"),
                      repo.resolve("Requirements::AttitudeDisplay").satisfied_by)
        sources = {a["from"] for a in res.auto}
        self.assertEqual(sources, {"mine", "theirs"})

    def test_conflicts_resolved_per_choice(self):
        self.mine.resolve("FlightDeck::gps").name = "gnssMine"
        self.theirs.resolve("FlightDeck::gps").name = "gnssTheirs"
        fm = stereotypes_on(self.mine.resolve("Components::FlightManagementComputer"))[0]
        ft = stereotypes_on(self.theirs.resolve("Components::FlightManagementComputer"))[0]
        fm.values["mass"], ft.values["mass"] = 5.0, 6.0
        res = three_way_merge(self.base, to_json(self.theirs), to_json(self.mine))
        by_prop = {c.property: c for c in res.conflicts}
        self.assertEqual(set(by_prop), {"name", "«LRU».mass"})
        name = by_prop["name"]
        self.assertEqual((name.base, name.mine, name.theirs), ("gps", "gnssMine", "gnssTheirs"))
        repo = merge_to_repo(res, {name.id: "theirs"})
        self.assertIsNotNone(repo.resolve("FlightDeck::gnssTheirs"))
        app = stereotypes_on(repo.resolve("Components::FlightManagementComputer"))[0]
        self.assertEqual(app.values["mass"], 5.0)            # default: mine
        repo = merge_to_repo(res, default="theirs")
        self.assertEqual(stereotypes_on(repo.resolve("Components::FlightManagementComputer"))[0]
                         .values["mass"], 6.0)
        self.assertEqual(res.to_dict()["summary"]["conflicts"], 2)

    def test_delete_modify_conflict(self):
        self.mine.remove(self.mine.resolve("FlightDeck::ims"))
        self.theirs.resolve("FlightDeck::ims::health").direction = FeatureDirection.IN
        res = three_way_merge(self.base, to_json(self.theirs), to_json(self.mine))
        kinds = {(c.element, c.kind) for c in res.conflicts}
        self.assertIn(("FlightDeck::ims", "delete-modify"), kinds)
        mine_wins = merge_to_repo(res, default="mine")
        self.assertIsNone(mine_wins.resolve("FlightDeck::ims"))
        self.assertIsNone(mine_wins.resolve("FlightDeck::ims::health"))
        theirs_wins = merge_to_repo(res, default="theirs")
        self.assertIs(theirs_wins.resolve("FlightDeck::ims::health").direction, FeatureDirection.IN)

    def test_connectors_to_deleted_ports_are_dropped(self):
        self.mine.remove(self.mine.resolve("Components::GPSReceiver::navOut"))   # cascades navBus
        bus = self.theirs.resolve("FlightDeck::displayBus")
        bus.name = "displayBus2"
        res = three_way_merge(self.base, to_json(self.theirs), to_json(self.mine))
        self.assertEqual(res.conflicts, [])
        repo = merge_to_repo(res)
        conns = {c.name for c in repo.resolve("FlightDeck").owned_elements
                 if isinstance(c, ConnectionUsage)}
        self.assertEqual(conns, {"displayBus2"})

    def test_bad_choices(self):
        self.mine.resolve("FlightDeck::gps").name = "a"
        self.theirs.resolve("FlightDeck::gps").name = "b"
        res = three_way_merge(self.base, to_json(self.theirs), to_json(self.mine))
        with self.assertRaises(InteropError):
            res.resolve({"c1": "both"})
        with self.assertRaises(InteropError):
            res.resolve({"nope": "mine"})
        with self.assertRaises(InteropError):
            three_way_merge(self.base, "garbage", to_json(self.mine))

    def test_project_name_and_identity(self):
        self.theirs.name = "Renamed"
        self.theirs.root_package.name = "Renamed"
        res = three_way_merge(self.base, to_json(self.theirs), self.base)
        repo = merge_to_repo(res)
        self.assertEqual(repo.name, "Renamed")
        same = merge_to_repo(three_way_merge(self.base, self.base, self.base))
        self.assertTrue(compare(self.base, same)["identical"])


if __name__ == "__main__":
    unittest.main()
