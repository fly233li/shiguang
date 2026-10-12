"""Isolated acceptance scenarios for the always-visible today's-duration tray.

No native system sampling, machine-clock changes, registry writes, or real
usage database access. Real SQLite/Tracker behavior is used where it matters.
"""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, time, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QDate, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from timelight.icons import application_icon
from timelight.storage import Store
from timelight.taskbar_clock import TaskbarClock
from timelight.tracking import Sample
from timelight.ui import MainWindow


class ControlledDate(date):
    current = date(2024, 1, 3)

    @classmethod
    def today(cls):
        return cls.current


class TrayDurationGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        ControlledDate.current = date(2024, 1, 3)
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "usage.sqlite3"
        self.store = Store(self.path)
        self.windows = []
        self.date_patch = patch("timelight.ui.date", ControlledDate)
        self.date_patch.start()
        self.qt_date_patch = patch("timelight.ui.QDate", wraps=QDate)
        self.qt_date = self.qt_date_patch.start()
        self.qt_date.currentDate.side_effect = lambda: self.qdate(ControlledDate.current)
        self.boot_patch = patch("timelight.ui.win32.boot_elapsed", return_value=7200)
        self.boot_patch.start()
        self.startup_patch = patch("timelight.ui.win32.set_autostart")
        self.startup = self.startup_patch.start()
        self.native_patch = patch("timelight.ui.win32.sample_system")
        self.native_sample = self.native_patch.start()
        self.taskbar_patch = patch("timelight.taskbar_clock.read_taskbar_state", return_value=None)
        self.taskbar_read = self.taskbar_patch.start()

    def tearDown(self):
        for window in self.windows:
            window.quit_app()
            window.close()
            window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.store.close()
        self.native_sample.assert_not_called()
        self.startup.assert_not_called()
        self.taskbar_read.assert_not_called()
        self.taskbar_patch.stop()
        self.native_patch.stop()
        self.startup_patch.stop()
        self.boot_patch.stop()
        self.qt_date_patch.stop()
        self.date_patch.stop()
        self.temporary.cleanup()

    @staticmethod
    def qdate(day):
        return QDate(day.year, day.month, day.day)

    @staticmethod
    def timestamp(day, hour=10):
        return datetime.combine(day, time(hour)).timestamp()

    def seed(self, seconds, *, day=None, hour=10, state="active"):
        start = self.timestamp(day or ControlledDate.current, hour)
        self.store.add_interval(start, start + seconds, state,
                                "fixture.exe", "Synthetic editor", r"C:\Fixture\editor.exe")
        return start

    def window(self):
        window = MainWindow(self.store, self.directory, demo=True)
        self.windows.append(window)
        return window

    def assert_tray_minutes(self, window, expected):
        self.assertEqual(window.tray_duration_minutes, expected)
        self.assertIn(window.tray_duration_text, window.tray.toolTip())
        self.assertIn(window.tray_duration_text, window.tray_duration_action.text())
        self.assertIn(window.tray_duration_text, window.windowTitle())
        self.assertEqual(window.taskbar_clock.text(), f"{expected // 60}:{expected % 60:02d}")
        self.assertIn(window.tray_duration_text, window.taskbar_clock.toolTip())
        self.assertFalse(window.taskbar_clock.isVisible(), "Demo must not create a real desktop overlay")

    def test_startup_and_restart_read_today_total_independent_of_history_selection(self):
        today = ControlledDate.current
        yesterday = today - timedelta(days=1)
        self.seed(61, hour=9)
        self.seed(119, hour=12, state="idle")
        self.seed(599, day=yesterday)
        first = self.window()
        self.assert_tray_minutes(first, 3)
        first.quit_app()
        self.store.close()
        self.store = Store(self.path)
        restarted = self.window()
        restarted.day.setDate(self.qdate(yesterday))
        restarted.refresh_tray_duration()
        self.assertEqual(restarted.selected_date(), yesterday)
        self.assert_tray_minutes(restarted, 3)
        self.assertEqual(self.store.get_summary(yesterday, yesterday)["awake"], 599)

    def test_minute_boundaries_are_floored_and_never_rounded_up(self):
        window = self.window()
        start = self.timestamp(ControlledDate.current)
        previous = 0
        for seconds, minutes in ((59.9, 0), (60, 1), (3599, 59), (3600, 60)):
            with self.subTest(seconds=seconds):
                self.store.add_interval(start + previous, start + seconds, "idle")
                window.refresh_tray_duration()
                self.assert_tray_minutes(window, minutes)
                previous = seconds

    def test_hidden_window_still_refreshes_from_its_independent_tray_timer(self):
        window = self.window()
        window.show()
        self.app.processEvents()
        window.hide()
        window.refresh_timer.stop()
        self.assertFalse(window.isVisible())
        self.assertFalse(window.timer.isActive(), "Demo must not sample the real desktop")
        self.assertTrue(window.tray_timer.isActive())
        self.assert_tray_minutes(window, 0)
        self.seed(125)
        window.tray_timer.setInterval(20)
        QTest.qWait(100)
        self.assert_tray_minutes(window, 2)

    def test_hidden_midnight_resets_today_display_without_changing_history(self):
        today = ControlledDate.current
        yesterday = today - timedelta(days=1)
        self.seed(125)
        self.seed(73, day=yesterday)
        window = self.window()
        window.day.setDate(self.qdate(yesterday))
        window.hide()
        self.assert_tray_minutes(window, 2)
        before_today = self.store.get_summary(today, today)
        before_yesterday = self.store.get_summary(yesterday, yesterday)
        ControlledDate.current = today + timedelta(days=1)
        window.tray_timer.timeout.emit()
        self.assert_tray_minutes(window, 0)
        self.assertEqual(window.selected_date(), yesterday)
        self.assertEqual(self.store.get_summary(today, today), before_today)
        self.assertEqual(self.store.get_summary(yesterday, yesterday), before_yesterday)

    def test_midnight_samples_split_daily_totals_and_sleep_does_not_fill_the_gap(self):
        today = ControlledDate.current
        yesterday = today - timedelta(days=1)
        self.seed(120, day=yesterday)
        window = self.window()
        boundary = self.timestamp(today, 0)

        def feed(offset, awake):
            window.tracker.tick(Sample(boundary + offset, awake, 0, False,
                                       "fixture.exe", "Synthetic editor", r"C:\Fixture\editor.exe"))
            window.refresh_tray_duration()

        feed(-10, 100)
        feed(10, 120)
        self.assertEqual(self.store.get_summary(yesterday, yesterday)["awake"], 130)
        self.assertEqual(self.store.get_summary(today, today)["awake"], 10)
        self.assert_tray_minutes(window, 0)
        for offset, awake in ((30, 140), (50, 160), (60, 170)):
            feed(offset, awake)
        self.assert_tray_minutes(window, 1)
        # An hour of wall time but only one second of awake time means sleep.
        feed(3660, 171)
        self.assertEqual(self.store.get_summary(today, today)["awake"], 60)
        self.assert_tray_minutes(window, 1)
        feed(3662, 173)
        self.assertEqual(self.store.get_summary(today, today)["awake"], 62)
        self.assertEqual(self.store.get_summary(yesterday, yesterday)["awake"], 130)

    def test_pausing_software_does_not_pause_the_today_awake_total(self):
        start = self.seed(40)
        window = self.window()
        window.toggle_pause()
        self.assertTrue(window.paused)
        window.tracker.tick(Sample(start + 100, 1000, 0, False, "fixture.exe"), paused=True)
        window.tracker.tick(Sample(start + 120, 1020, 0, False, "fixture.exe"), paused=True)
        window.refresh_tray_duration()
        self.assert_tray_minutes(window, 1)
        self.assertEqual(window.tray_duration_state, "paused")
        summary = self.store.get_summary(ControlledDate.current, ControlledDate.current)
        self.assertEqual(summary["awake"], 60)
        self.assertEqual(summary["active"], 40)
        self.assertEqual(summary["paused"], 20)

    def test_setting_defaults_on_persists_and_disabled_mode_keeps_tooltip_duration(self):
        self.seed(125)
        window = self.window()
        self.assertTrue(window.tray_duration_checkbox.isChecked())
        self.assertTrue(self.store.get_setting("tray_show_duration", True))
        window.tray_duration_checkbox.setChecked(False)
        self.assertFalse(self.store.get_setting("tray_show_duration"))
        self.assert_tray_minutes(window, 2)
        self.assertEqual(window.tray.icon().cacheKey(), application_icon(window.tray_duration_state).cacheKey())
        window.quit_app()
        self.store.close()
        self.store = Store(self.path)
        reopened = self.window()
        self.assertFalse(reopened.tray_duration_checkbox.isChecked())
        self.assert_tray_minutes(reopened, 2)
        self.assertEqual(reopened.tray.icon().cacheKey(), application_icon(reopened.tray_duration_state).cacheKey())
        reopened.tray_duration_checkbox.setChecked(True)
        self.assertTrue(self.store.get_setting("tray_show_duration"))
        self.assertEqual(reopened.tray.icon().cacheKey(), application_icon(reopened.tray_duration_state).cacheKey())
        self.assert_tray_minutes(reopened, 2)

    def test_read_failure_is_explicit_and_recovers_without_pretending_zero(self):
        self.seed(125)
        window = self.window()
        self.assert_tray_minutes(window, 2)
        with patch.object(self.store, "get_summary", side_effect=sqlite3.OperationalError("isolated read failure")), \
             patch("timelight.ui.logging.exception"):
            window.refresh_tray_duration()
        self.assertIsNone(window.tray_duration_minutes)
        self.assertIn("不可读取", window.tray_duration_text)
        self.assertIn(window.tray_duration_text, window.tray.toolTip())
        self.assertEqual(window.taskbar_clock.text(), "--")
        self.assertIn("不可读取", window.taskbar_clock.toolTip())
        window.refresh_tray_duration()
        self.assert_tray_minutes(window, 2)

    def test_dragged_taskbar_offset_persists_across_restart_and_reset(self):
        self.store.set_setting("taskbar_clock_offset", -320)
        first = self.window()
        first.taskbar_clock.offsetChanged.emit(64)
        self.assertEqual(self.store.get_setting("taskbar_clock_left_offset"), 64)
        self.assertEqual(self.store.get_setting("taskbar_clock_offset"), -320)
        clock_type = type(first.taskbar_clock)
        apply_offset = clock_type.set_offset
        first.quit_app()
        self.store.close()
        self.store = Store(self.path)
        with patch.object(clock_type, "set_offset", autospec=True, side_effect=apply_offset) as offset:
            reopened = self.window()
            offset.assert_called_once_with(reopened.taskbar_clock, 64)
            reopened.reset_taskbar_position()
            offset.assert_called_with(reopened.taskbar_clock, 0)
        self.assertEqual(self.store.get_setting("taskbar_clock_left_offset"), 0)
        self.assertEqual(self.store.get_setting("taskbar_clock_offset"), -320)

    def test_upgrade_ignores_old_right_anchor_offset_and_defaults_to_left_zero(self):
        apply_offset = TaskbarClock.set_offset
        for legacy_offset in (-320, 1200):
            with self.subTest(legacy_offset=legacy_offset):
                self.store.set_setting("taskbar_clock_offset", legacy_offset)
                with patch.object(TaskbarClock, "set_offset", autospec=True, side_effect=apply_offset) as offset:
                    window = self.window()
                    offset.assert_called_once_with(window.taskbar_clock, 0)
                self.assertEqual(self.store.get_setting("taskbar_clock_offset"), legacy_offset)
                window.quit_app()

    def test_recording_error_keeps_known_duration_and_has_error_state(self):
        self.seed(125)
        window = self.window()
        window.failure = True
        window.refresh_tray_duration()
        self.assert_tray_minutes(window, 2)
        self.assertEqual(window.tray_duration_state, "error")
        self.assertIn("出错", window.tray.toolTip())

    def test_quit_stops_the_new_tray_timer(self):
        window = self.window()
        self.assertTrue(window.tray_timer.isActive())
        with patch.object(window.taskbar_clock, "stop", wraps=window.taskbar_clock.stop) as stop:
            window.quit_app()
            stop.assert_called_once()
        self.assertFalse(window.tray_timer.isActive())
        self.assertFalse(window.timer.isActive())
        self.assertFalse(window.refresh_timer.isActive())
        self.assertFalse(window.taskbar_clock.isVisible())


if __name__ == "__main__":
    unittest.main()
