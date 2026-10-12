import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from timelight.storage import Store
from timelight.tracking import Sample, Tracker


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "usage.db")
        self.tracker = Tracker(self.store, idle_seconds=300)
        self.start = datetime(2024, 1, 15, 10).timestamp()
        self.day = date(2024, 1, 15)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def sample(self, seconds=0, *, awake=None, idle=0, locked=False, app="editor"):
        return Sample(self.start + seconds, 1000 + (seconds if awake is None else awake),
                      idle, locked, app, app.title(), f"C:\\{app}.exe" if app else "")

    def summary(self):
        return self.store.get_summary(self.day, self.day)

    def test_first_tick_does_not_backfill_system_uptime(self):
        self.tracker.tick(self.sample(0, awake=50000))
        self.assertEqual(self.summary()["awake"], 0)
        self.assertEqual(self.tracker.status, "active")

    def test_interval_belongs_to_previous_foreground(self):
        self.tracker.tick(self.sample(0, app="editor"))
        self.tracker.tick(self.sample(1, app="browser"))
        self.tracker.tick(self.sample(2, app="browser"))
        apps = {row["key"]: row["seconds"] for row in self.store.get_apps(self.day, self.day)}
        self.assertEqual(apps, {"editor": 1, "browser": 1})

    def test_idle_threshold_splits_last_foreground_interval(self):
        self.tracker.tick(self.sample(0, idle=299))
        self.tracker.tick(self.sample(2, idle=301))
        self.assertEqual(self.summary()["active"], 1)
        self.assertEqual(self.summary()["idle"], 1)
        self.assertEqual(self.tracker.status, "idle")

    def test_input_after_idle_does_not_relabel_entire_interval_as_active(self):
        self.tracker.tick(self.sample(0, idle=500))
        self.tracker.tick(self.sample(5, idle=2))
        self.assertEqual(self.summary()["idle"], 3)
        self.assertEqual(self.summary()["active"], 2)
        self.assertEqual(self.tracker.status, "active")

    def test_sleep_and_long_sampler_gaps_are_not_attributed_to_stale_app(self):
        self.tracker.tick(self.sample(0))
        self.tracker.tick(self.sample(3600, awake=1))
        self.assertEqual(self.summary()["awake"], 0)
        self.tracker.tick(self.sample(3601, awake=2))
        self.assertEqual(self.summary()["active"], 1)
        self.tracker.tick(self.sample(7201, awake=3602))
        self.assertEqual(self.summary()["awake"], 1)

    def test_short_suspend_detected_by_awake_clock(self):
        self.tracker.tick(self.sample(0))
        self.tracker.tick(self.sample(10, awake=1))
        self.assertEqual(self.summary()["awake"], 0)

    def test_restart_does_not_count_stopped_period(self):
        self.tracker.tick(self.sample(0))
        self.tracker.tick(self.sample(1))
        restarted = Tracker(self.store)
        restarted.tick(self.sample(3600))
        restarted.tick(self.sample(3601))
        self.assertEqual(self.summary()["awake"], 2)

    def test_paused_and_locked_remain_awake_but_do_not_attribute_software(self):
        self.tracker.tick(self.sample(0), paused=True)
        self.tracker.tick(self.sample(1, locked=True), paused=False)
        self.assertEqual(self.tracker.status, "locked")
        self.tracker.tick(self.sample(2, locked=False))
        summary = self.summary()
        self.assertEqual(summary["paused"], 1)
        self.assertEqual(summary["locked"], 1)
        self.assertEqual(summary["awake"], 2)
        self.assertEqual(self.store.get_apps(self.day, self.day), [])

    def test_missing_process_is_unknown_and_recovers(self):
        self.tracker.tick(self.sample(0, app=""))
        self.tracker.tick(self.sample(1))
        self.tracker.tick(self.sample(2))
        self.assertEqual(self.summary()["unknown"], 1)
        self.assertEqual(self.summary()["active"], 1)

    def test_clock_change_does_not_poison_following_ticks(self):
        self.tracker.tick(self.sample(0))
        self.tracker.tick(self.sample(-60, awake=1))
        self.tracker.tick(self.sample(-59, awake=2))
        self.assertEqual(self.summary()["awake"], 1)

    def test_backward_clock_waits_until_saved_history_catches_up(self):
        self.tracker.tick(self.sample(0))
        self.tracker.tick(self.sample(1))
        self.tracker.tick(self.sample(-2, awake=2))
        self.tracker.tick(self.sample(-1, awake=3))
        self.tracker.tick(self.sample(0, awake=4))
        self.tracker.tick(self.sample(1, awake=5))
        self.tracker.tick(self.sample(2, awake=6))
        self.assertEqual(self.summary()["awake"], 2)

    def test_restart_after_backward_clock_does_not_duplicate_history(self):
        self.tracker.tick(self.sample(0))
        self.tracker.tick(self.sample(1))
        restarted = Tracker(self.store)
        restarted.tick(self.sample(0, awake=2))
        restarted.tick(self.sample(1, awake=3))
        restarted.tick(self.sample(2, awake=4))
        self.assertEqual(self.summary()["awake"], 2)

    def test_invalid_sample_resets_continuity(self):
        self.tracker.tick(self.sample(0))
        with self.assertRaises(ValueError):
            self.tracker.tick(self.sample(1, idle=float("nan")))
        self.tracker.tick(self.sample(2))
        self.tracker.tick(self.sample(3))
        self.assertEqual(self.summary()["awake"], 1)

    def test_tiny_clock_sampling_skew_does_not_fragment_database(self):
        for second in range(101):
            self.tracker.tick(self.sample(second, awake=second + (0.001 if second % 2 else 0)))
        count = self.store._db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(self.summary()["awake"], 100)


if __name__ == "__main__":
    unittest.main()
