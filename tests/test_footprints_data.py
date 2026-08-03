import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FOOTPRINTS_FILE = ROOT / "data" / "footprints.json"
VISITS_FILE = ROOT / "data" / "visits.json"
BACKGROUND_FILE = ROOT / "assets" / "spitzer-irac4.webp"


class FootprintDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.footprints = json.loads(FOOTPRINTS_FILE.read_text())
        cls.visits = json.loads(VISITS_FILE.read_text())

    def test_geometry_matches_dashboard_observations(self):
        self.assertEqual(self.footprints["program_id"], "10678")
        fields = self.footprints["fields"]
        visits_by_observation = {visit["observation"]: visit for visit in self.visits["visits"]}
        fields_by_observation = {field["observation"]: field for field in fields}

        self.assertEqual(len(fields_by_observation), len(fields))
        self.assertEqual(set(fields_by_observation), set(visits_by_observation))
        for observation, field in fields_by_observation.items():
            self.assertIn(field["target"], visits_by_observation[observation]["targets"])

    def test_each_field_has_two_nircam_modules_and_one_miri_aperture(self):
        for field in self.footprints["fields"]:
            self.assertEqual(len(field["nircam"]), 2)
            self.assertEqual(len(field["miri"]), 1)
            for polygon in field["nircam"] + field["miri"]:
                self.assertGreaterEqual(len(polygon), 4)
                for x, y in polygon:
                    self.assertGreaterEqual(x, 0)
                    self.assertLessEqual(x, 1)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(y, 1)

    def test_geometry_records_nominal_attitude_and_reference_data(self):
        self.assertEqual(self.footprints["nominal_v3pa_degrees"], 87.0)
        self.assertEqual(self.footprints["approved_v3pa_range_degrees"], [79.0, 95.0])
        self.assertEqual(self.footprints["apt_prd_version"], "PRDOPSSOC-072")
        self.assertEqual(self.footprints["view"]["frame"], "galactic")

    def test_background_is_a_small_webp_asset(self):
        content = BACKGROUND_FILE.read_bytes()
        self.assertEqual(content[:4], b"RIFF")
        self.assertEqual(content[8:12], b"WEBP")
        self.assertLess(len(content), 100_000)


if __name__ == "__main__":
    unittest.main()
