"""Backup UI checks with isolated data; no native startup or folder changes."""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from timelight.storage import Store
from timelight.ui import MainWindow


class BackupGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.store = Store(self.directory / "usage.sqlite3")
        start = time.time() - 120
        self.store.add_interval(start, start + 60, "active", "editor", "Editor", r"C:\Apps\editor.exe")
        self.window = MainWindow(self.store, self.directory, demo=True)
        self.window.navigate(3)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.store.close()
        self.temporary.cleanup()

    def wait_for_backup(self):
        deadline=time.monotonic()+5
        while self.window._backup_worker is not None and time.monotonic()<deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertIsNone(self.window._backup_worker,"Backup worker did not finish")

    def test_unbacked_state_is_explicit(self):
        self.assertIn("尚未备份", self.window.backup_status.text())
        self.assertEqual(self.window.backup_status.toolTip(), "")
        self.assertTrue(self.window.backup_button.isEnabled())

    def test_backup_saves_boundary_first_and_keeps_sampling_timers(self):
        calls = []
        create = self.store.create_backup

        def capture_backup(*, reason):
            calls.append("backup:" + reason)
            return create(reason=reason)

        # Demo sampling is inert, allowing timer behavior to be checked safely.
        self.window.timer.start()
        with patch.object(self.window, "sample", side_effect=lambda: calls.append("sample")), \
             patch.object(self.store, "create_backup", side_effect=capture_backup), \
             patch("timelight.ui.QMessageBox.information") as information:
            self.window.backup_button.click()
            self.assertFalse(self.window.backup_button.isEnabled())
            self.wait_for_backup()
        self.assertEqual(calls, ["sample", "backup:manual"])
        self.assertTrue(self.window.timer.isActive())
        self.assertTrue(self.window.refresh_timer.isActive())
        self.assertFalse(self.window.paused)
        self.assertTrue(self.window.backup_button.isEnabled())
        latest = self.store.latest_backup()
        self.assertIsNotNone(latest)
        self.assertTrue(latest.is_file())
        self.assertEqual(latest.parent, self.directory / "backups")
        self.assertIn("最近备份：", self.window.backup_status.text())
        self.assertEqual(self.window.backup_status.toolTip(), str(latest))
        self.assertIn("演示", information.call_args.args[1])
        self.assertIn("临时目录", information.call_args.args[2])
        self.assertIn(str(latest), information.call_args.args[2])

    def test_failure_reports_error_and_preserves_existing_backup(self):
        previous = self.store.create_backup()
        self.window.refresh_backup_status()
        old_status = self.window.backup_status.text()
        self.window.timer.start()
        with patch.object(self.store, "create_backup", side_effect=PermissionError("Permission denied")), \
             patch("timelight.ui.QMessageBox.warning") as warning, \
             patch("timelight.ui.QMessageBox.information") as information, \
             self.assertLogs(level="ERROR"):
            self.window.backup_button.click()
            self.wait_for_backup()
        warning.assert_called_once()
        information.assert_not_called()
        self.assertIn("备份未完成", warning.call_args.args[1])
        self.assertTrue(previous.is_file())
        self.assertEqual(self.window.backup_status.text(), old_status)
        self.assertTrue(self.window.backup_button.isEnabled())
        self.assertTrue(self.window.timer.isActive())
        self.assertTrue(self.window.refresh_timer.isActive())

    def test_open_folder_works_before_first_backup(self):
        with patch("timelight.ui.QDesktopServices.openUrl", return_value=True) as open_url:
            self.window.backup_folder_button.click()
        self.assertTrue(self.store.backup_directory.is_dir())
        self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(self.store.backup_directory).replace("\\", "/"))
        self.assertIsNone(self.store.latest_backup())

    def test_open_folder_failure_shows_usable_path(self):
        with patch("timelight.ui.QDesktopServices.openUrl", return_value=False), \
             patch("timelight.ui.QMessageBox.warning") as warning:
            self.window.backup_folder_button.click()
        self.assertIn(str(self.store.backup_directory), warning.call_args.args[2])

    def test_backup_timestamp_is_read_from_file(self):
        latest = self.store.create_backup()
        stamp = 1_700_000_000.0
        os.utime(latest, (stamp, stamp))
        self.window.refresh_backup_status()
        expected = datetime.fromtimestamp(stamp).strftime("%Y/%m/%d %H:%M:%S")
        self.assertIn(expected, self.window.backup_status.text())

    def test_unreadable_backup_state_is_not_presented_as_no_backup(self):
        with patch.object(self.store, "latest_backup", side_effect=PermissionError("Permission denied")):
            self.window.refresh_backup_status()
        self.assertIn("无法读取", self.window.backup_status.text())
        self.assertNotIn("尚未备份", self.window.backup_status.text())

    def test_sampling_runs_while_backup_is_in_progress(self):
        release=threading.Event()
        original=self.store.create_backup

        def slow_backup(*,reason):
            release.wait(3)
            return original(reason=reason)

        self.window.demo=False
        self.window.timer.setInterval(20)
        self.window.timer.start()
        sample={"wall":time.time(),"awake":120.0,"idle":0.0,"locked":False,
                "app_key":"editor","app_name":"Editor","exe_path":r"C:\Apps\editor.exe"}
        with patch.object(self.store,"create_backup",side_effect=slow_backup), \
             patch("timelight.ui.win32.sample_system",return_value=sample), \
             patch("timelight.ui.win32.consume_show_request",return_value=False), \
             patch.object(self.window.tracker,"tick") as tick, \
             patch("timelight.ui.QMessageBox.information"):
            try:
                self.window.backup_button.click()
                self.assertIsNotNone(self.window._backup_worker)
                QTest.qWait(120)
                self.assertGreaterEqual(tick.call_count,3)
                self.assertFalse(self.window.backup_button.isEnabled())
            finally:
                release.set()
                self.wait_for_backup()
                self.window.demo=True

    def test_exit_waits_for_backup_without_late_result_dialog(self):
        release=threading.Event()
        started=threading.Event()
        original=self.store.create_backup

        def slow_backup(*,reason):
            started.set()
            release.wait(3)
            return original(reason=reason)

        with patch.object(self.store,"create_backup",side_effect=slow_backup), \
             patch("timelight.ui.QMessageBox.information") as information, \
             patch("timelight.ui.QMessageBox.warning") as warning:
            self.window.backup_button.click()
            self.assertTrue(started.wait(1))
            threading.Timer(0.05,release.set).start()
            self.window.quit_app()
            self.assertEqual(self.window._backup_pool.activeThreadCount(),0)
            self.app.processEvents()
            information.assert_not_called()
            warning.assert_not_called()
            self.assertTrue(self.store.latest_backup().is_file())


if __name__ == "__main__":
    unittest.main()
