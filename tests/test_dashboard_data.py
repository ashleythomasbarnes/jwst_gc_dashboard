import json
from pathlib import Path
import unittest

from scripts.fetch_visits import natural_key


DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "visits.json"
ALLOWED_GROUPS = {"neutral", "scheduled", "completed", "failed"}


class DashboardDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DATA_FILE.read_text())

    def test_snapshot_is_nonempty_program_10678_data(self):
        self.assertEqual(self.data["program"]["id"], "10678")
        self.assertGreater(self.data["visit_count"], 0)
        self.assertEqual(self.data["visit_count"], len(self.data["visits"]))

    def test_counts_and_identifiers_are_consistent(self):
        visits = self.data["visits"]
        self.assertEqual(sum(self.data["status_counts"].values()), len(visits))
        self.assertEqual(len({visit["id"] for visit in visits}), len(visits))
        self.assertTrue({visit["status_group"] for visit in visits} <= ALLOWED_GROUPS)

    def test_every_visit_has_display_fields(self):
        for visit in self.data["visits"]:
            self.assertTrue(visit["observation"])
            self.assertTrue(visit["visit"])
            self.assertTrue(visit["status"])
            self.assertTrue(visit["targets"])
            self.assertIsInstance(visit["configurations"], list)
            self.assertIsInstance(visit["plan_windows"], list)

    def test_snapshot_is_naturally_sorted_by_target(self):
        targets = [visit["targets"][0] for visit in self.data["visits"]]
        self.assertEqual(targets, sorted(targets, key=natural_key))


if __name__ == "__main__":
    unittest.main()
