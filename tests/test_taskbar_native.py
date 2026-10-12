"""Taskbar geometry checks; never change Explorer or taskbar settings."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import FrozenInstanceError
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from timelight import taskbar_native as native


class GeometryTests(unittest.TestCase):
    monitor = (0, 0, 1920, 1080)

    def test_visible_bars_on_every_edge(self):
        for bar in ((0, 1040, 1920, 1080), (0, 0, 1920, 40),
                    (0, 0, 48, 1080), (1872, 0, 1920, 1080)):
            with self.subTest(bar=bar):
                self.assertTrue(native._taskbar_is_visible(bar, self.monitor))
                self.assertFalse(native._taskbar_is_visible(bar, self.monitor, False))

    def test_auto_hidden_reveal_strip_on_every_edge(self):
        for bar in ((0, 1078, 1920, 1118), (0, -38, 1920, 2),
                    (-46, 0, 2, 1080), (1918, 0, 1966, 1080)):
            with self.subTest(bar=bar):
                self.assertFalse(native._taskbar_is_visible(bar, self.monitor))
        self.assertTrue(native._taskbar_is_visible((0, 1077, 1920, 1117), self.monitor))

    def test_offscreen_and_invalid_bars_are_hidden(self):
        for bar in ((0, 1080, 1920, 1120), (0, -40, 1920, 0),
                    (1920, 0, 1960, 1080), (-40, 0, 0, 1080),
                    (0, 0, 0, 40), (5, 5, 3, 40)):
            with self.subTest(bar=bar):
                self.assertFalse(native._taskbar_is_visible(bar, self.monitor))

    def test_negative_monitor_coordinates_and_intersection(self):
        monitor = (-2560, -200, 0, 1240)
        self.assertTrue(native._taskbar_is_visible((-2560, 1180, 0, 1240), monitor))
        self.assertFalse(native._taskbar_is_visible((-2560, 1238, 0, 1298), monitor))
        self.assertEqual(native._intersection((-5, -5, 10, 10), (0, 0, 20, 20)), (0, 0, 10, 10))
        self.assertIsNone(native._intersection((0, 0, 10, 10), (10, 0, 20, 10)))

    def test_fullscreen_covers_monitor_even_when_spanning_displays(self):
        self.assertTrue(native._covers_monitor(self.monitor, self.monitor))
        self.assertTrue(native._covers_monitor((-1920, -100, 3840, 1440), self.monitor))
        self.assertFalse(native._covers_monitor((0, 0, 1920, 1040), self.monitor))
        self.assertFalse(native._covers_monitor((1920, 0, 3840, 1080), self.monitor))
        self.assertFalse(native._covers_monitor((0, 0, 0, 1080), self.monitor))

    def test_snapshot_is_immutable(self):
        state = native.NativeTaskbarState((0, 1040, 1920, 1080), None, self.monitor, True, False)
        with self.assertRaises(FrozenInstanceError):
            state.visible = False


class ForegroundTests(unittest.TestCase):
    def setUp(self):
        self.api = SimpleNamespace(
            GetForegroundWindow=Mock(return_value=10),
            GetShellWindow=Mock(return_value=20),
            GetDesktopWindow=Mock(return_value=30),
            IsWindowVisible=Mock(return_value=True),
            IsIconic=Mock(return_value=False),
            GetWindowThreadProcessId=Mock(side_effect=self._other_pid),
            DwmGetWindowAttribute=Mock(return_value=-1),
        )

    @staticmethod
    def _other_pid(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = os.getpid() + 1
        return 1

    def test_shell_and_own_process_do_not_count_as_fullscreen(self):
        for foreground in (None, 1, 20, 30):
            with self.subTest(foreground=foreground):
                self.api.GetForegroundWindow.return_value = foreground
                self.assertFalse(native._foreground_is_fullscreen(self.api, 1, GeometryTests.monitor))
        self.api.GetForegroundWindow.return_value = 10

        def own_pid(hwnd, pointer):
            ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = os.getpid()
            return 1

        self.api.GetWindowThreadProcessId.side_effect = own_pid
        self.assertFalse(native._foreground_is_fullscreen(self.api, 1, GeometryTests.monitor))
        self.api.DwmGetWindowAttribute.assert_not_called()

    def test_worker_desktop_and_minimized_windows_are_excluded(self):
        with patch.object(native, "_window_class", return_value="WorkerW"):
            self.assertFalse(native._foreground_is_fullscreen(self.api, 1, GeometryTests.monitor))
        self.api.IsIconic.return_value = True
        with patch.object(native, "_window_class") as class_name:
            self.assertFalse(native._foreground_is_fullscreen(self.api, 1, GeometryTests.monitor))
            class_name.assert_not_called()

    def test_dwm_frame_avoids_invisible_border_false_positive(self):
        def dwm_bounds(hwnd, attribute, pointer, size):
            value = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            value.left, value.top, value.right, value.bottom = (0, 0, 1920, 1040)
            return 0

        self.api.DwmGetWindowAttribute.side_effect = dwm_bounds
        with patch.object(native, "_window_class", return_value="Chrome_WidgetWin_1"), \
             patch.object(native, "_window_rect", return_value=(-8, -8, 1928, 1088)) as fallback:
            self.assertFalse(native._foreground_is_fullscreen(self.api, 1, GeometryTests.monitor))
            fallback.assert_not_called()

    def test_native_bounds_fallback_detects_spanning_fullscreen(self):
        with patch.object(native, "_window_class", return_value="Application"), \
             patch.object(native, "_window_rect", return_value=(-1920, 0, 1920, 1080)):
            self.assertTrue(native._foreground_is_fullscreen(self.api, 1, GeometryTests.monitor))


@unittest.skipUnless(os.name == "nt", "Windows-only query")
class NativeQueryTests(unittest.TestCase):
    def test_missing_shell_restores_thread_context(self):
        api = SimpleNamespace(SetThreadDpiAwarenessContext=Mock(return_value=321),
                              FindWindowW=Mock(return_value=None))
        with patch.object(native, "_api", return_value=api):
            self.assertIsNone(native.read_taskbar_state())
        self.assertEqual(api.SetThreadDpiAwarenessContext.call_count, 2)
        api.SetThreadDpiAwarenessContext.assert_called_with(321)
        api.FindWindowW.assert_called_once_with("Shell_TrayWnd", None)

    def test_dpi_failure_does_not_return_virtualized_coordinates(self):
        api = SimpleNamespace(SetThreadDpiAwarenessContext=Mock(return_value=None),
                              FindWindowW=Mock())
        with patch.object(native, "_api", return_value=api):
            self.assertIsNone(native.read_taskbar_state())
        api.FindWindowW.assert_not_called()

    def test_real_read_only_snapshot_and_context_restore(self):
        api = native._api()
        before = api.GetThreadDpiAwarenessContext()
        state = native.read_taskbar_state()
        self.assertEqual(api.GetThreadDpiAwarenessContext(), before)
        if state is None:
            self.skipTest("Explorer main taskbar is unavailable in this session")
        self.assertTrue(native._valid_rect(state.bar))
        self.assertTrue(native._valid_rect(state.monitor))
        self.assertIsInstance(state.visible, bool)
        self.assertIsInstance(state.fullscreen, bool)
        self.assertTrue(all(isinstance(value, int) for value in (*state.bar, *state.monitor)))
        if state.notification is not None:
            self.assertTrue(native._valid_rect(state.notification))
            self.assertIsNotNone(native._intersection(state.bar, state.notification))


if __name__ == "__main__":
    unittest.main()
