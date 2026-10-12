"""Read-only taskbar geometry for an independent clock window.

All rectangles are physical screen pixels, with exclusive right/bottom edges.
No Explorer window is moved, resized, reparented, or sent configuration messages.
Only geometry, window class names and process IDs are read; never window titles.

API references:
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getwindowrect
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setthreaddpiawarenesscontext
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-monitorfromwindow
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-iswindowvisible
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from functools import lru_cache
import os


Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class NativeTaskbarState:
    bar: Rect
    notification: Rect | None
    monitor: Rect
    visible: bool
    fullscreen: bool


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class _API:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Taskbar geometry is only available on Windows.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

        def bind(dll, name, arguments, result):
            function = getattr(dll, name)
            function.argtypes = arguments
            function.restype = result
            setattr(self, name, function)

        u = self.user32
        bind(u, "FindWindowW", [wintypes.LPCWSTR, wintypes.LPCWSTR], wintypes.HWND)
        bind(u, "FindWindowExW", [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR], wintypes.HWND)
        bind(u, "GetWindowRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL)
        bind(u, "MonitorFromWindow", [wintypes.HWND, wintypes.DWORD], wintypes.HANDLE)
        bind(u, "GetMonitorInfoW", [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)], wintypes.BOOL)
        bind(u, "GetForegroundWindow", [], wintypes.HWND)
        bind(u, "GetShellWindow", [], wintypes.HWND)
        bind(u, "GetDesktopWindow", [], wintypes.HWND)
        bind(u, "GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD)
        bind(u, "GetClassNameW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
        bind(u, "IsWindowVisible", [wintypes.HWND], wintypes.BOOL)
        bind(u, "IsIconic", [wintypes.HWND], wintypes.BOOL)
        bind(u, "SetThreadDpiAwarenessContext", [wintypes.HANDLE], wintypes.HANDLE)
        bind(u, "GetThreadDpiAwarenessContext", [], wintypes.HANDLE)
        self.child_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        bind(u, "EnumChildWindows", [wintypes.HWND, self.child_callback, wintypes.LPARAM], wintypes.BOOL)
        bind(self.dwmapi, "DwmGetWindowAttribute", [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD], ctypes.c_long)


@lru_cache(maxsize=1)
def _api():
    return _API()


def _valid_rect(rect: Rect) -> bool:
    return rect[2] > rect[0] and rect[3] > rect[1]


def _intersection(first: Rect, second: Rect) -> Rect | None:
    result = (max(first[0], second[0]), max(first[1], second[1]),
              min(first[2], second[2]), min(first[3], second[3]))
    return result if _valid_rect(result) else None


def _taskbar_is_visible(bar: Rect, monitor: Rect, window_visible: bool = True) -> bool:
    """Ignore an auto-hidden taskbar's narrow reveal strip on any screen edge."""
    if not window_visible or not _valid_rect(bar) or not _valid_rect(monitor):
        return False
    overlap = _intersection(bar, monitor)
    if overlap is None:
        return False
    horizontal = bar[2] - bar[0] >= bar[3] - bar[1]
    thickness = overlap[3] - overlap[1] if horizontal else overlap[2] - overlap[0]
    return thickness > 2


def _covers_monitor(window: Rect, monitor: Rect) -> bool:
    """A spanning fullscreen window also covers the taskbar's monitor."""
    return (_valid_rect(window) and _valid_rect(monitor)
            and window[0] <= monitor[0] and window[1] <= monitor[1]
            and window[2] >= monitor[2] and window[3] >= monitor[3])


def _rect(value: wintypes.RECT) -> Rect:
    return value.left, value.top, value.right, value.bottom


def _window_rect(api, hwnd) -> Rect | None:
    value = wintypes.RECT()
    if api.GetWindowRect(hwnd, ctypes.byref(value)):
        result = _rect(value)
        if _valid_rect(result):
            return result
    return None


def _window_class(api, hwnd) -> str:
    value = ctypes.create_unicode_buffer(256)
    return value.value if api.GetClassNameW(hwnd, value, len(value)) else ""


def _notification_rect(api, bar_handle, bar: Rect) -> Rect | None:
    handle = api.FindWindowExW(bar_handle, None, "TrayNotifyWnd", None)
    if not handle:
        # FindWindowEx only searches direct children. Accommodate a nested
        # notification area without inspecting its content or buttons.
        matches = []

        @api.child_callback
        def find_child(child, _):
            if _window_class(api, child) == "TrayNotifyWnd":
                matches.append(child)
                return False
            return True

        api.EnumChildWindows(bar_handle, find_child, 0)
        handle = matches[0] if matches else None
    if handle and api.IsWindowVisible(handle):
        result = _window_rect(api, handle)
        if result is not None and _intersection(result, bar) is not None:
            return result
    return None


def _foreground_is_fullscreen(api, bar_handle, monitor: Rect) -> bool:
    foreground = api.GetForegroundWindow()
    if not foreground or foreground in (bar_handle, api.GetShellWindow(), api.GetDesktopWindow()):
        return False
    if not api.IsWindowVisible(foreground) or api.IsIconic(foreground):
        return False
    process = wintypes.DWORD()
    api.GetWindowThreadProcessId(foreground, ctypes.byref(process))
    if process.value == os.getpid():
        return False
    if _window_class(api, foreground) in {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
        return False
    frame = wintypes.RECT()
    # DWM frame bounds omit invisible resize borders and are physical pixels.
    # Ordinary maximized windows must not be mistaken for fullscreen windows.
    if api.DwmGetWindowAttribute(foreground, 9, ctypes.byref(frame), ctypes.sizeof(frame)) == 0 and _valid_rect(_rect(frame)):
        bounds = _rect(frame)
    else:
        bounds = _window_rect(api, foreground)
    return bounds is not None and _covers_monitor(bounds, monitor)


def read_taskbar_state() -> NativeTaskbarState | None:
    """Read the main Explorer taskbar; return None if geometry is unavailable.

    Shell class names are implementation details and may be absent when Explorer
    restarts or a different shell is installed. Callers must hide/fallback then.
    This query briefly makes only the calling thread per-monitor-DPI aware and
    restores its previous context before returning, so Qt receives no DPI change.
    """
    if os.name != "nt":
        return None
    api = _api()
    previous = api.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))  # PMv2
    if not previous:
        return None  # Do not mix virtualized and physical coordinates.
    try:
        handle = api.FindWindowW("Shell_TrayWnd", None)
        if not handle:
            return None
        bar = _window_rect(api, handle)
        if bar is None:
            return None
        monitor_handle = api.MonitorFromWindow(handle, 2)  # MONITOR_DEFAULTTONEAREST
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not monitor_handle or not api.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
            return None
        monitor = _rect(info.rcMonitor)
        if not _valid_rect(monitor):
            return None
        return NativeTaskbarState(
            bar=bar, notification=_notification_rect(api, handle, bar), monitor=monitor,
            visible=_taskbar_is_visible(bar, monitor, bool(api.IsWindowVisible(handle))),
            fullscreen=_foreground_is_fullscreen(api, handle, monitor),
        )
    finally:
        api.SetThreadDpiAwarenessContext(previous)
