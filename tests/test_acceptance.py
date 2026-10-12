"""Offscreen interaction checks using isolated local data and no startup edits."""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QDate
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from timelight.storage import Store
from timelight.ui import MainWindow


class GuiAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        # Windows' offscreen plugin has no system font discovery.
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = Store(self.root / "usage.sqlite3")
        self.recorded_day = date.today() - timedelta(days=1)
        start = datetime.combine(self.recorded_day, time(9)).timestamp()
        self.store.add_interval(start, start + 120, "active", "chrome", "Google Chrome", r"C:\Apps\chrome.exe")
        self.store.add_interval(start + 120, start + 180, "active", "code", "Visual Studio Code", r"C:\Apps\Code.exe")
        self.store.add_interval(start + 180, start + 210, "idle")
        self.boot_patch = patch("timelight.ui.win32.boot_elapsed", return_value=3600)
        self.boot_patch.start()
        self.startup_patch = patch("timelight.ui.win32.set_autostart")
        self.startup_mutation = self.startup_patch.start()
        self.window = MainWindow(self.store, self.root, demo=True)
        self.window.day.setDate(QDate(self.recorded_day.year, self.recorded_day.month, self.recorded_day.day))
        self.window.show()
        self.application.processEvents()

    def tearDown(self):
        self.window.close()
        self.application.processEvents()
        self.window.deleteLater()
        self.application.processEvents()
        self.startup_mutation.assert_not_called()
        self.startup_patch.stop()
        self.boot_patch.stop()
        self.store.close()
        self.directory.cleanup()

    def test_all_navigation_pages_and_settings_controls(self):
        for index, title in enumerate(("每日概览", "软件统计", "历史趋势", "设置")):
            self.window.nav.button(index).click()
            self.application.processEvents()
            self.assertEqual(self.window.stack.currentIndex(), index)
            self.assertEqual(self.window.heading.text(), title)
            self.assertTrue(self.window.nav.button(index).isChecked())
        self.assertTrue(self.window.day.isHidden())
        self.assertFalse(self.window.startup.isEnabled())
        self.window.idle_combo.setCurrentIndex(3)
        self.assertEqual(self.store.get_setting("idle_seconds"), 600)
        self.assertEqual(self.window.tracker.idle_seconds, 600)
        self.window.close_tray.setChecked(False)
        self.assertFalse(self.store.get_setting("close_to_tray"))

    def test_selected_date_updates_metrics_and_disallows_future(self):
        self.assertEqual(self.window.awake_card.value.text(), "3 分钟")
        self.assertEqual(self.window.count_card.value.text(), "02 个")
        self.assertEqual(sum(row["active"] for row in self.window.hourly.rows), 180)
        self.window.today_button.click()
        self.assertEqual(self.window.selected_date(), date.today())
        self.assertFalse(self.window.next.isEnabled())
        self.assertEqual(self.window.count_card.value.text(), "00 个")
        self.window.change_day(2)
        self.assertEqual(self.window.selected_date(), date.today())
        self.window.previous.click()
        self.assertEqual(self.window.selected_date(), self.recorded_day)
        self.assertTrue(self.window.next.isEnabled())

    def test_app_search_and_export_ranges_follow_current_page(self):
        self.window.navigate(1)
        self.assertEqual(self.window.app_table.rowCount(), 2)
        self.window.search.setText("CHROME.EXE")
        self.assertEqual(self.window.app_table.rowCount(), 1)
        self.assertIn("Chrome", self.window.app_table.item(0, 0).text())
        self.window.app_table.selectRow(0)
        self.assertEqual(self.window.app_detail.text(), r"C:\Apps\chrome.exe")
        self.window.search.setText("不存在的软件")
        self.assertEqual(self.window.app_table.item(0, 0).text(), "没有匹配的软件")
        self.window.search.clear()
        self.assertEqual(self.window.app_table.rowCount(), 2)
        self.window.app_range.setCurrentIndex(2)
        self.assertEqual(self.window.selected_range(), (self.recorded_day - timedelta(days=29), self.recorded_day))
        self.window.navigate(2)
        self.assertEqual(self.window.selected_range(), (self.recorded_day - timedelta(days=6), self.recorded_day))
        self.window.history_range.setCurrentIndex(1)
        self.assertEqual(len(self.window.daily_chart.rows), 30)
        self.assertEqual(self.window.selected_range(), (self.recorded_day - timedelta(days=29), self.recorded_day))
        self.window.navigate(0)
        self.assertEqual(self.window.selected_range(), (self.recorded_day, self.recorded_day))

    def test_history_day_opens_corresponding_overview(self):
        self.window.navigate(2)
        target = self.recorded_day - timedelta(days=2)
        self.window.open_history_day(2, 1)
        self.assertEqual(self.window.selected_date(), target)
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.assertEqual(self.window.awake_card.value.text(), "0 秒")
        self.assertEqual(self.window.top_table.item(0, 0).text(), "暂无前台使用记录")

    def test_filtering_out_selected_app_does_not_leave_stale_path(self):
        self.window.navigate(1)
        self.window.app_table.selectRow(0)
        self.assertEqual(self.window.app_detail.text(), r"C:\Apps\chrome.exe")
        self.window.search.setText("Code")
        self.assertIn("Visual Studio Code", self.window.app_table.item(0, 0).text())
        self.assertNotIn("chrome.exe", self.window.app_detail.text())
        self.window.app_table.selectRow(0)
        self.assertEqual(self.window.app_detail.text(), r"C:\Apps\Code.exe")

    def test_midnight_advances_today_but_preserves_historical_selection(self):
        current = date.today()
        tomorrow = current + timedelta(days=1)
        qt_tomorrow = QDate(tomorrow.year, tomorrow.month, tomorrow.day)
        self.window.today_button.click()
        with patch("timelight.ui.QDate", wraps=QDate) as qt_date, patch("timelight.ui.date", wraps=date) as python_date:
            qt_date.currentDate.return_value = qt_tomorrow
            python_date.today.return_value = tomorrow
            self.window.refresh()
            self.assertEqual(self.window.selected_date(), tomorrow)
            self.assertEqual(self.window.heading.text(), "今日概览")
            self.assertFalse(self.window.next.isEnabled())
            self.window.day.setDate(QDate(self.recorded_day.year, self.recorded_day.month, self.recorded_day.day))
            self.assertFalse(self.window._follow_today)
            day_after = tomorrow + timedelta(days=1)
            qt_date.currentDate.return_value = qt_tomorrow.addDays(1)
            python_date.today.return_value = day_after
            self.window.refresh()
            self.assertEqual(self.window.selected_date(), self.recorded_day)
            self.assertEqual(self.window.heading.text(), "每日概览")

    def test_pause_actions_stay_synchronized_without_demo_collection(self):
        before = self.store.get_summary(self.recorded_day, self.recorded_day)
        self.assertFalse(self.window.timer.isActive())
        self.window.pause_button.click()
        self.assertTrue(self.window.paused)
        self.assertEqual(self.window.pause_button.text(), "继续软件统计")
        self.assertEqual(self.window.pause_action.text(), "继续软件统计")
        self.window.pause_action.trigger()
        self.assertFalse(self.window.paused)
        self.assertEqual(self.window.pause_button.text(), "暂停软件统计")
        self.assertEqual(self.store.get_summary(self.recorded_day, self.recorded_day), before)

    def test_close_stops_all_timers_and_does_not_leave_demo_in_tray(self):
        self.assertTrue(self.window.refresh_timer.isActive())
        self.window.close()
        self.application.processEvents()
        self.assertTrue(self.window.quitting)
        self.assertFalse(self.window.timer.isActive())
        self.assertFalse(self.window.refresh_timer.isActive())
        self.assertFalse(self.window.tray.isVisible())
        self.assertFalse(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
