"""Brief native-window smoke check; no sampling, database or Explorer changes."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from timelight.taskbar_clock import TaskbarClock
from timelight.taskbar_native import read_taskbar_state


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowRect.restype = wintypes.BOOL
    foreground = user.GetForegroundWindow()
    state = read_taskbar_state()
    if state is None or not state.visible or state.fullscreen:
        raise RuntimeError("Native taskbar check requires a visible desktop taskbar.")
    output = ROOT / "artifacts" / "taskbar-clock"
    output.mkdir(parents=True, exist_ok=True)
    clock = TaskbarClock()
    clock.set_duration(155, "时光计 · 加宽时间条测试示例，稍后自动关闭")
    clock.set_enabled(True)
    clock.refresh_placement()
    original_position = clock.pos()
    result = {}

    def verify():
        try:
            clock.refresh_placement()
            native_id = int(clock.winId())
            styles = user.GetWindowLongPtrW(native_id, -20)
            rect = wintypes.RECT()
            assert user.GetWindowRect(native_id, ctypes.byref(rect))
            actual = (rect.left, rect.top, rect.right, rect.bottom)
            ratio = clock.devicePixelRatioF()
            checks = {
                "native_windows_platform": app.platformName() == "windows",
                "visible": clock.isVisible(),
                "wide_logical_size": (clock.width(), clock.height()) == (88, 32),
                "regular_large_font": clock.font().pixelSize() == 24,
                "layered_transparency": bool(styles & 0x80000),
                "tool_window_no_task_button": bool(styles & 0x80) and not bool(styles & 0x40000),
                "does_not_activate": bool(styles & 0x08000000),
                "topmost": bool(styles & 0x8),
                "foreground_unchanged": foreground == user.GetForegroundWindow(),
                "inside_taskbar": state.bar[0] <= rect.left < rect.right <= state.bar[2]
                    and state.bar[1] <= rect.top < rect.bottom <= state.bar[3],
                "clear_of_notification_area": state.notification is not None and rect.right < state.notification[0],
                "anchored_at_taskbar_left": abs(rect.left - (state.bar[0] + round(8 * ratio))) <= 1,
                "refresh_keeps_position": original_position == clock.pos(),
            }
            assert clock.grab().save(str(output / "native-widget.png"))
            result.update(result="passed" if all(checks.values()) else "failed", checks=checks,
                          physical_rect=actual, logical_width=clock.width(),
                          device_pixel_ratio=clock.devicePixelRatioF())
        except Exception as error:
            result.update(result="failed", error=str(error))
        finally:
            clock.stop()
            result["window_closed"] = not clock.isVisible()
            app.quit()

    QTimer.singleShot(600, verify)
    app.exec()
    (output / "native-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("result") == "passed" and result["window_closed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
