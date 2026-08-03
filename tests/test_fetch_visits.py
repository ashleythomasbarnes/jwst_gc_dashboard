import json
from pathlib import Path
import tempfile
import unittest

from scripts.fetch_visits import parse_report, status_group, write_json_atomic


FIXTURES = Path(__file__).parent / "fixtures"


class ParseReportTests(unittest.TestCase):
    def parse_fixture(self, name: str):
        return parse_report((FIXTURES / name).read_bytes(), fetched_at="2026-08-03T10:00:00Z")

    def test_current_flight_ready_shape_and_natural_sort(self):
        report = self.parse_fixture("program_10678.xml")

        self.assertEqual(report["program"]["id"], "10678")
        self.assertEqual(report["visit_count"], 2)
        self.assertEqual([visit["targets"][0] for visit in report["visits"]], ["GC_2", "GC_10"])
        self.assertEqual(report["status_counts"]["neutral"], 2)

        first = report["visits"][0]
        self.assertEqual(first["targets"], ["GC_2", "GC_2-BACKGROUND"])
        self.assertEqual(first["plan_windows"], ["Aug 5, 2027 - Sep 24, 2027 (2027.217 - 2027.267)"])

        second = report["visits"][1]
        self.assertEqual(second["configurations"], ["NIRCam Imaging", "MIRI Imaging"])
        self.assertEqual(second["hours"], 0.93)

    def test_completed_and_other_real_world_states(self):
        visits = self.parse_fixture("program_2107.xml")["visits"]
        by_status = {visit["status"]: visit for visit in visits}

        self.assertEqual(by_status["Archived"]["status_group"], "completed")
        self.assertEqual(by_status["Archived"]["start_time"], "Jul 6, 2022 16:30:40")
        self.assertEqual(by_status["Archived"]["end_time"], "Jul 6, 2022 18:11:07")
        self.assertEqual(by_status["Skipped"]["status_group"], "neutral")
        self.assertEqual(by_status["Withdrawn"]["status_group"], "neutral")

    def test_failed_takes_precedence_and_unknown_is_neutral(self):
        visits = self.parse_fixture("status_cases.xml")["visits"]
        by_status = {visit["status"]: visit["status_group"] for visit in visits}

        self.assertEqual(by_status["Scheduled"], "scheduled")
        self.assertEqual(by_status["Failed - Archived"], "failed")
        self.assertEqual(by_status["Future Status"], "neutral")

    def test_status_group_handles_whitespace_and_case(self):
        self.assertEqual(status_group("  FAILED - archived "), "failed")
        self.assertEqual(status_group("collecting"), "completed")
        self.assertEqual(status_group("Unscheduled"), "neutral")

    def test_rejects_wrong_program(self):
        xml = b'<visitStatusReport id="99999"><visit observation="1" visit="1"><status>Scheduled</status><target>X</target></visit></visitStatusReport>'
        with self.assertRaisesRegex(ValueError, "Expected program 10678"):
            parse_report(xml)

    def test_rejects_empty_report(self):
        with self.assertRaisesRegex(ValueError, "empty visit report"):
            parse_report(b'<visitStatusReport id="10678" />')

    def test_atomic_writer_produces_valid_deterministic_json(self):
        report = self.parse_fixture("program_10678.xml")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "visits.json"
            write_json_atomic(report, output)
            first_write = output.read_text()
            write_json_atomic(report, output)

            self.assertEqual(output.read_text(), first_write)
            self.assertEqual(json.loads(first_write)["visit_count"], 2)
            self.assertTrue(first_write.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
