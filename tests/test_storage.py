import csv
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from timelight.storage import Store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "usage.sqlite3"
        self.store = Store(self.path)
        self.day = date(2024, 1, 15)
        self.start = datetime(2024, 1, 15, 10).timestamp()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_midnight_split_has_exact_elapsed_totals(self):
        start = datetime(2024, 1, 15, 23, 59, 58).timestamp()
        self.store.add_interval(start, start + 5, "active", "app", "软件")
        tomorrow = self.day + timedelta(days=1)
        self.assertEqual(self.store.get_summary(self.day, self.day)["active"], 2)
        self.assertEqual(self.store.get_summary(tomorrow, tomorrow)["active"], 3)
        self.assertEqual(self.store.get_hourly(self.day)[23]["active"], 2)
        self.assertEqual(self.store.get_hourly(tomorrow)[0]["active"], 3)

    def test_summary_partitions_awake_and_apps_only_include_active(self):
        for index, state in enumerate(("active", "idle", "locked", "paused", "unknown")):
            self.store.add_interval(self.start + index * 10, self.start + (index + 1) * 10,
                                    state, "app", "软件", "C:\\app.exe")
        summary = self.store.get_summary(self.day, self.day)
        self.assertEqual(summary["awake"], 50)
        self.assertEqual(sum(value for key, value in summary.items() if key != "awake"), 50)
        self.assertEqual(self.store.get_apps(self.day, self.day), [
            {"key": "app", "name": "软件", "path": "C:\\app.exe", "seconds": 10}])

    def test_second_by_second_capture_stays_compact(self):
        for second in range(100):
            self.store.add_interval(self.start + second, self.start + second + 1, "active", "app", "App")
        count = self.store._db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(self.store.get_summary(self.day, self.day)["awake"], 100)

    def test_empty_ranges_have_stable_zeros(self):
        self.assertIsNone(self.store.first_recorded)
        self.assertEqual(self.store.get_summary(self.day, self.day)["awake"], 0)
        self.assertEqual(self.store.get_apps(self.day, self.day), [])
        hours = self.store.get_hourly(self.day)
        self.assertEqual(len(hours), 24)
        self.assertEqual([row["hour"] for row in hours], list(range(24)))
        self.assertTrue(all(row["awake"] == row["active"] == 0 for row in hours))
        days = self.store.get_daily(self.day, self.day + timedelta(days=2))
        self.assertEqual(len(days), 3)
        self.assertTrue(all(row["awake"] == row["active"] == 0 for row in days))

    def test_reopen_keeps_intervals_and_json_settings(self):
        self.store.add_interval(self.start, self.start + 10, "active", "app")
        self.store.set_setting("window", {"width": 1100, "enabled": True, "name": "时光"})
        self.store.close()
        self.store = Store(self.path)
        self.store.add_interval(self.start + 10, self.start + 20, "idle")
        self.assertEqual(self.store.first_recorded, self.start)
        self.assertEqual(self.store.get_summary(self.day, self.day)["awake"], 20)
        self.assertEqual(self.store.get_setting("window")["name"], "时光")
        self.assertIs(self.store.get_setting("absent", False), False)

    def test_rejects_overlap_future_and_invalid_intervals_without_partial_writes(self):
        self.store.add_interval(self.start, self.start + 10, "active")
        for start, end, state in ((self.start + 5, self.start + 15, "idle"),
                                  (self.start, self.start, "idle"),
                                  (float("nan"), self.start, "idle"),
                                  (self.start + 20, float("inf"), "idle"),
                                  (time.time() + 100, time.time() + 200, "idle"),
                                  (self.start + 20, self.start + 30, "invalid")):
            with self.subTest(start=start, end=end, state=state):
                with self.assertRaises(ValueError):
                    self.store.add_interval(start, end, state)
        self.assertEqual(self.store.get_summary(self.day, self.day)["awake"], 10)

    def test_application_ranking_and_inclusive_date_filter(self):
        self.store.add_interval(self.start, self.start + 5, "active", "a", "A")
        self.store.add_interval(self.start + 5, self.start + 20, "active", "b", "B")
        self.store.add_interval(self.start + 86400, self.start + 86410, "active", "a", "A")
        self.assertEqual([a["key"] for a in self.store.get_apps(self.day, self.day)], ["b", "a"])
        tomorrow = self.day + timedelta(days=1)
        self.assertEqual(self.store.get_summary(self.day, tomorrow)["active"], 30)

    def test_csv_preserves_unicode_quotes_and_limits_range(self):
        self.store.add_interval(self.start, self.start + 3, "active", "app", '编辑器,"甲"', "C:\\软件.exe")
        self.store.add_interval(self.start + 86400, self.start + 86410, "idle")
        target = Path(self.temp.name) / "report.csv"
        self.store.export_csv(target, self.day, self.day)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][5], '编辑器,"甲"')
        self.assertEqual(float(rows[1][-1]), 3)

    def test_inverted_date_range_rejected(self):
        with self.assertRaises(ValueError):
            self.store.get_summary(self.day + timedelta(days=1), self.day)


if __name__ == "__main__":
    unittest.main()
