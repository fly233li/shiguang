"""Offscreen acceptance of the wide clock, using synthetic desktop geometry."""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QFontDatabase, QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from timelight.taskbar_clock import TaskbarClock
from timelight.taskbar_native import NativeTaskbarState


class FakeScreen:
    def __init__(self, geometry=QRect(0, 0, 1920, 1080), ratio=1.0):
        self.rectangle = geometry
        self.ratio = ratio

    def geometry(self):
        return QRect(self.rectangle)

    def availableGeometry(self):
        return self.geometry().adjusted(0, 0, 0, -48)

    def devicePixelRatio(self):
        return self.ratio


class TaskbarClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        # The Windows offscreen plugin has no automatic system font discovery.
        for name in ("segoeui.ttf", "seguisb.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))

    def setUp(self):
        self.screen = FakeScreen()
        self.other_screens = []
        self.state = NativeTaskbarState(
            bar=(0, 1032, 1920, 1080), notification=(1660, 1032, 1920, 1080),
            monitor=(0, 0, 1920, 1080), visible=True, fullscreen=False,
        )
        self.native_patch = patch("timelight.taskbar_clock.read_taskbar_state", side_effect=lambda: self.state)
        self.read_native = self.native_patch.start()
        self.screens_patch = patch("timelight.taskbar_clock.QApplication.screens", side_effect=lambda: self.other_screens + [self.screen])
        self.screens_patch.start()
        self.primary_patch = patch("timelight.taskbar_clock.QApplication.primaryScreen", side_effect=lambda: self.screen)
        self.primary_patch.start()
        self.clock = TaskbarClock()

    def tearDown(self):
        self.clock.stop()
        self.clock.close()
        self.clock.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.primary_patch.stop()
        self.screens_patch.stop()
        self.native_patch.stop()

    def enable(self):
        self.clock.set_enabled(True)
        self.clock.refresh_placement()
        self.app.processEvents()

    def test_wide_regular_font_and_transparent_black_text_for_normal_and_unavailable_values(self):
        self.assertEqual((self.clock.width(), self.clock.height()), (88, 32))
        self.assertEqual(self.clock.font().pixelSize(), 24)
        self.assertIn(self.clock.font().stretch(), (0, 100))
        self.assertTrue(self.clock.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(self.clock.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(self.clock.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        for minutes, expected in ((0, "0:00"), (59, "0:59"), (60, "1:00"), (599, "9:59"),
                                  (600, "10:00"), (1439, "23:59"), (1440, "24:00"), (None, "--")):
            with self.subTest(minutes=minutes):
                self.clock.set_duration(minutes, "Synthetic duration tooltip")
                self.assertEqual(self.clock.text(), expected)
                self.assertEqual(self.clock.toolTip(), "Synthetic duration tooltip")
                image = self.clock.grab().toImage()
                self.assertEqual((image.width(), image.height()), (88, 32))
                ink = []
                for y in range(image.height()):
                    for x in range(image.width()):
                        color = image.pixelColor(x, y)
                        if color.alpha():
                            ink.append((x, y))
                            self.assertEqual((color.red(), color.green(), color.blue()), (0, 0, 0))
                self.assertTrue(ink)
                self.assertTrue(all(0 < x < 87 and 0 < y < 31 for x, y in ink), "Text must not be clipped")
                if minutes in (0, 1439):
                    width = max(x for x, _ in ink) - min(x for x, _ in ink) + 1
                    height = max(y for _, y in ink) - min(y for _, y in ink) + 1
                    self.assertGreaterEqual(width, 35 if minutes == 0 else 45)
                    self.assertGreaterEqual(height, 14)
                    self.assertGreater(width / height, 2.0, "Keep normal-proportion horizontal text")

    def test_default_position_is_fixed_at_taskbar_left_margin(self):
        self.enable()
        self.assertTrue(self.clock.isVisible())
        self.assertEqual(self.clock.placement_mode, "taskbar")
        rectangle = self.clock.geometry()
        self.assertEqual(rectangle, QRect(8, 1040, 88, 32))
        self.assertGreaterEqual(rectangle.left(), 0)
        self.assertGreaterEqual(rectangle.top(), 1032)
        self.assertLessEqual(rectangle.bottom(), 1079)
        self.assertLessEqual(rectangle.x() + rectangle.width(), 1660 - 8)
        self.assertFalse(rectangle.intersects(QRect(1660, 1032, 260, 48)))

    def test_physical_150_percent_coordinates_map_to_logical_widget_geometry(self):
        self.screen = FakeScreen(QRect(0, 0, 1920, 1080), 1.5)
        self.state = NativeTaskbarState(
            bar=(0, 1548, 2880, 1620), notification=(2505, 1548, 2880, 1620),
            monitor=(0, 0, 2880, 1620), visible=True, fullscreen=False,
        )
        self.enable()
        self.assertEqual((self.clock.width(), self.clock.height()), (88, 32))
        self.assertEqual(self.clock.pos(), QPoint(8, 1040))

    def test_negative_origin_monitor_uses_its_logical_origin_for_dpi_mapping(self):
        self.screen = FakeScreen(QRect(-2048, 0, 2048, 1152), 1.25)
        self.other_screens = [FakeScreen(QRect(0, 0, 2048, 1152), 1.25)]
        self.state = NativeTaskbarState(
            bar=(-2560, 1380, 0, 1440), notification=(-500, 1380, 0, 1440),
            monitor=(-2560, 0, 0, 1440), visible=True, fullscreen=False,
        )
        self.enable()
        self.assertEqual(self.clock.pos(), QPoint(-2048 + 8, 1112))

    def test_fullscreen_and_hidden_taskbar_hide_clock_then_restore_it(self):
        self.enable()
        for visible, fullscreen in ((True, True), (False, False)):
            with self.subTest(visible=visible, fullscreen=fullscreen):
                self.state = NativeTaskbarState(
                    bar=self.state.bar, notification=self.state.notification, monitor=self.state.monitor,
                    visible=visible, fullscreen=fullscreen,
                )
                self.clock.refresh_placement()
                self.assertFalse(self.clock.isVisible())
                self.assertEqual(self.clock.placement_mode, "hidden")
        self.state = NativeTaskbarState(
            bar=self.state.bar, notification=self.state.notification, monitor=self.state.monitor,
            visible=True, fullscreen=False,
        )
        self.clock.refresh_placement()
        self.assertTrue(self.clock.isVisible())

    def test_offset_moves_right_from_left_anchor_and_stays_inside_taskbar(self):
        self.enable()
        original = self.clock.pos()
        self.clock.set_offset(60)
        self.clock.refresh_placement()
        self.assertEqual(self.clock.pos(), original + QPoint(60, 0))
        self.clock.set_offset(10000)
        self.clock.refresh_placement()
        self.assertLessEqual(self.clock.x() + self.clock.width(), 1920 - 8)
        self.clock.set_offset(-10000)
        self.clock.refresh_placement()
        self.assertEqual(self.clock.x(), 8)

    def test_unknown_shell_state_hides_safely_and_can_recover(self):
        known = self.state
        self.enable()
        self.state = None
        self.clock.refresh_placement()
        self.assertFalse(self.clock.isVisible())
        self.assertEqual(self.clock.placement_mode, "hidden")
        self.read_native.side_effect = OSError("Synthetic Explorer restart")
        self.clock.refresh_placement()
        self.assertFalse(self.clock.isVisible())
        self.read_native.side_effect = lambda: known
        self.clock.refresh_placement()
        self.assertTrue(self.clock.isVisible())

    def test_notification_width_changes_and_missing_bounds_do_not_move_left_clock(self):
        self.enable()
        original = self.clock.pos()
        for left in (1790, 1220, None, 900, 1800, 1660):
            with self.subTest(notification_left=left):
                notification = None if left is None else (left, 1032, 1920, 1080)
                self.state = NativeTaskbarState(
                    bar=self.state.bar, notification=notification, monitor=self.state.monitor,
                    visible=True, fullscreen=False,
                )
                self.clock.refresh_placement()
                self.assertTrue(self.clock.isVisible())
                self.assertEqual(self.clock.placement_mode, "taskbar")
                self.assertEqual(self.clock.pos(), original)

    def test_unchanged_refresh_and_duration_updates_do_not_issue_redundant_moves(self):
        self.enable()
        with patch.object(self.clock, "move", wraps=self.clock.move) as move:
            for minutes in (0, 1, 59, 60, 599, 600, 1439):
                self.clock.set_duration(minutes, "Synthetic minute update")
                self.clock.refresh_placement()
                self.clock.refresh_placement()
            move.assert_not_called()

    def test_taskbar_too_short_for_clock_falls_back_to_available_area_left(self):
        self.state = NativeTaskbarState(
            bar=(0, 1056, 1920, 1080), notification=None, monitor=self.state.monitor,
            visible=True, fullscreen=False,
        )
        self.enable()
        self.assertTrue(self.clock.isVisible())
        self.assertEqual(self.clock.placement_mode, "fallback")
        self.assertTrue(self.screen.availableGeometry().contains(self.clock.geometry()))
        self.assertEqual(self.clock.x(), 8)
        self.assertFalse(self.clock.geometry().intersects(QRect(0, 1056, 1920, 24)))
        # Auto-hide desktops may report the whole monitor as the work area even
        # while the bar is revealed. The known bar still must remain unobscured.
        with patch.object(self.screen, "availableGeometry", return_value=self.screen.geometry()):
            self.clock.refresh_placement()
            self.assertTrue(self.clock.isVisible())
            self.assertEqual(self.clock.x(), 8)
            self.assertFalse(self.clock.geometry().intersects(QRect(0, 1056, 1920, 24)))

    def test_disabled_and_stopped_clock_does_not_show_or_query_native_geometry(self):
        self.enable()
        self.clock.set_enabled(False)
        self.read_native.reset_mock()
        self.clock.set_duration(135, "Today 2:15")
        self.clock.refresh_placement()
        self.assertFalse(self.clock.isVisible())
        self.read_native.assert_not_called()
        self.clock.set_enabled(True)
        self.clock.refresh_placement()
        self.assertTrue(self.clock.isVisible())
        self.clock.stop()
        self.read_native.reset_mock()
        self.clock.set_duration(136, "Today 2:16")
        self.clock.refresh_placement()
        self.assertFalse(self.clock.isVisible())
        self.read_native.assert_not_called()
        self.assertFalse(self.clock.findChildren(QTimer), "Use the existing independent duration timer")

    def test_click_does_not_activate_but_double_click_and_context_menu_emit_intent(self):
        self.enable()
        activated = QSignalSpy(self.clock.activated)
        context = QSignalSpy(self.clock.contextMenuRequested)
        QTest.mouseClick(self.clock, Qt.MouseButton.LeftButton, pos=QPoint(30, 16))
        self.assertEqual(activated.count(), 0)
        QTest.mouseDClick(self.clock, Qt.MouseButton.LeftButton, pos=QPoint(30, 16))
        self.assertEqual(activated.count(), 1)
        position = self.clock.mapToGlobal(QPoint(30, 16))
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(30, 16), position)
        self.app.sendEvent(self.clock, event)
        self.assertEqual(context.count(), 1)
        self.assertEqual(context.at(0)[0], position)

    def test_refresh_does_not_raise_clock_above_an_open_menu(self):
        self.enable()
        with patch("timelight.taskbar_clock.QApplication.activePopupWidget", return_value=object()), \
             patch.object(self.clock,"raise_") as raise_clock:
            self.clock.refresh_placement()
            raise_clock.assert_not_called()
        with patch("timelight.taskbar_clock.QApplication.activePopupWidget", return_value=None), \
             patch.object(self.clock,"raise_") as raise_clock:
            self.clock.refresh_placement()
            raise_clock.assert_called_once()

    def test_horizontal_drag_emits_one_persistable_offset_without_activating(self):
        self.enable()
        offsets = QSignalSpy(self.clock.offsetChanged)
        activated = QSignalSpy(self.clock.activated)
        original = self.clock.pos()
        start = self.clock.mapToGlobal(QPoint(30, 16))

        def send(kind, global_point, button, buttons):
            local = self.clock.mapFromGlobal(global_point)
            event = QMouseEvent(kind, QPointF(local), QPointF(global_point), button, buttons,
                                Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(self.clock, event)

        send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        end = start + QPoint(60, -12)
        send(QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        self.assertEqual(offsets.count(), 0, "Persist only on release, not every pointer movement")
        send(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        self.assertEqual(offsets.count(), 1)
        self.assertEqual(offsets.at(0)[0], 60)
        self.assertEqual(self.clock.pos(), original + QPoint(60, 0))
        self.assertEqual(activated.count(), 0)


if __name__ == "__main__":
    unittest.main()
