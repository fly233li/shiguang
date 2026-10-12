"""Small, privacy-preserving Windows integration for 时光.

Only executable identity and session/timer state are sampled.  This module never
reads window titles, document names, keyboard content, URLs, or screen pixels.
It can be imported on other platforms for tests; native operations require
Windows 10/11.  Importing it does not change startup settings.
"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "Shiguang"
_instance_handle = None
_show_handle = None
_instance_lock = threading.RLock()

_FRIENDLY_NAMES = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "code.exe": "Visual Studio Code",
    "cursor.exe": "Cursor",
    "codex.exe": "Codex",
    "devenv.exe": "Visual Studio",
    "explorer.exe": "Windows 资源管理器",
    "windowsterminal.exe": "Windows 终端",
    "powershell.exe": "Windows PowerShell",
    "pwsh.exe": "PowerShell",
    "cmd.exe": "命令提示符",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "outlook.exe": "Microsoft Outlook",
    "onenote.exe": "Microsoft OneNote",
    "wps.exe": "WPS 文字",
    "et.exe": "WPS 表格",
    "wpp.exe": "WPS 演示",
    "wechat.exe": "微信",
    "weixin.exe": "微信",
    "qq.exe": "QQ",
    "tim.exe": "TIM",
    "dingtalk.exe": "钉钉",
    "feishu.exe": "飞书",
    "lark.exe": "飞书 / Lark",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "spotify.exe": "Spotify",
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ 音乐",
    "steam.exe": "Steam",
    "notepad.exe": "记事本",
    "taskmgr.exe": "任务管理器",
    "systemsettings.exe": "Windows 设置",
    "applicationframehost.exe": "Windows 应用宿主",
    "shiguang.exe": "时光",
    "时光.exe": "时光",
}


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class _LanguageAndCodePage(ctypes.Structure):
    _fields_ = [("language", wintypes.WORD), ("codepage", wintypes.WORD)]


class _WindowsAPI:
    """Explicit signatures prevent HANDLE truncation on 64-bit Python."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("时光的系统采集功能仅支持 Windows 10 / 11。")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.version = ctypes.WinDLL("version", use_last_error=True)
        self.wts = ctypes.WinDLL("wtsapi32", use_last_error=True)

        def bind(dll, name, args, result):
            fn = getattr(dll, name)
            fn.argtypes = args
            fn.restype = result
            setattr(self, name, fn)

        k, u, v, w = self.kernel32, self.user32, self.version, self.wts
        ptr_dword = ctypes.POINTER(wintypes.DWORD)
        bind(k, "GetTickCount64", [], ctypes.c_ulonglong)
        bind(k, "QueryUnbiasedInterruptTime", [ctypes.POINTER(ctypes.c_ulonglong)], wintypes.BOOL)
        bind(k, "OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE)
        bind(k, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
        bind(k, "QueryFullProcessImageNameW", [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ptr_dword], wintypes.BOOL)
        bind(k, "CreateMutexW", [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE)
        bind(k, "CreateEventW", [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE)
        bind(k, "OpenEventW", [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE)
        bind(k, "SetEvent", [wintypes.HANDLE], wintypes.BOOL)
        bind(k, "WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD)
        bind(u, "GetLastInputInfo", [ctypes.POINTER(_LastInputInfo)], wintypes.BOOL)
        bind(u, "GetForegroundWindow", [], wintypes.HWND)
        bind(u, "GetWindowThreadProcessId", [wintypes.HWND, ptr_dword], wintypes.DWORD)
        bind(u, "OpenInputDesktop", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE)
        bind(u, "CloseDesktop", [wintypes.HANDLE], wintypes.BOOL)
        bind(u, "SwitchDesktop", [wintypes.HANDLE], wintypes.BOOL)
        bind(u, "GetUserObjectInformationW", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ptr_dword], wintypes.BOOL)
        bind(u, "IsWindowVisible", [wintypes.HWND], wintypes.BOOL)
        self.window_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        bind(u, "EnumChildWindows", [wintypes.HWND, self.window_callback, wintypes.LPARAM], wintypes.BOOL)
        bind(v, "GetFileVersionInfoSizeW", [wintypes.LPCWSTR, ptr_dword], wintypes.DWORD)
        bind(v, "GetFileVersionInfoW", [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL)
        bind(v, "VerQueryValueW", [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)], wintypes.BOOL)
        bind(w, "WTSQuerySessionInformationW", [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ptr_dword], wintypes.BOOL)
        bind(w, "WTSFreeMemory", [ctypes.c_void_p], None)


@lru_cache(maxsize=1)
def _api():
    return _WindowsAPI()


def _awake_seconds() -> float:
    value = ctypes.c_ulonglong()
    if not _api().QueryUnbiasedInterruptTime(ctypes.byref(value)):
        # A wall-clock fallback would silently count sleep as computer use.
        raise ctypes.WinError(ctypes.get_last_error())
    return value.value / 10_000_000.0


def boot_elapsed() -> float:
    """Elapsed time since Windows boot, including sleep and hibernation.

    Windows Fast Startup may retain the kernel session across a shutdown.  This
    value is context for display only, not a measure of recorded active use.
    """
    return _api().GetTickCount64() / 1000.0


def _idle_delta(now_ms: int, last_input_ms: int) -> float:
    # LASTINPUTINFO is a 32-bit millisecond count and wraps every 49.7 days.
    return ((now_ms - last_input_ms) & 0xFFFFFFFF) / 1000.0


def _idle_seconds() -> float | None:
    api = _api()
    value = _LastInputInfo()
    value.cbSize = ctypes.sizeof(value)
    if not api.GetLastInputInfo(ctypes.byref(value)):
        return None  # Missing input information must not imply activity.
    return _idle_delta(api.GetTickCount64(), value.dwTime)


def _session_is_active() -> bool:
    api = _api()
    data, size = ctypes.c_void_p(), wintypes.DWORD()
    # WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTSConnectState.
    if not api.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 8, ctypes.byref(data), ctypes.byref(size)):
        return False
    try:
        return bool(data.value and size.value >= ctypes.sizeof(ctypes.c_int)
                    and ctypes.cast(data, ctypes.POINTER(ctypes.c_int)).contents.value == 0)
    finally:
        if data.value:
            api.WTSFreeMemory(data)


def _is_locked() -> bool:
    """Treat locked, secure, disconnected, and unknown desktops as inactive."""
    if not _session_is_active():
        return True
    api = _api()
    # READOBJECTS | SWITCHDESKTOP.  Opening the input desktop never changes it.
    desktop = api.OpenInputDesktop(0, False, 0x0001 | 0x0100)
    if not desktop:
        return True
    try:
        name = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if not api.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)):
            return True
        if name.value.casefold() != "default":
            return True
        # This is the already-active input desktop, so the call does not move
        # the user to another desktop.  Secure/invisible desktops reject it.
        return not bool(api.SwitchDesktop(desktop))
    finally:
        api.CloseDesktop(desktop)


def _process_path(pid: int) -> str:
    if not pid:
        return ""
    api = _api()
    process = api.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION.
    if not process:
        return ""
    try:
        capacity = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(capacity.value)
        if api.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(capacity)):
            return path.value
        return ""
    finally:
        api.CloseHandle(process)


def _foreground_path() -> str:
    api = _api()
    window = api.GetForegroundWindow()
    if not window:
        return ""
    pid = wintypes.DWORD()
    if not api.GetWindowThreadProcessId(window, ctypes.byref(pid)):
        return ""
    path = _process_path(pid.value)
    # Some Windows 10 UWP windows belong to the frame host.  Resolve a single
    # visible hosted executable without inspecting any window title/content.
    if Path(path).name.casefold() == "applicationframehost.exe":
        hosted_pids = set()

        @api.window_callback
        def child_callback(child, _):
            child_pid = wintypes.DWORD()
            if api.IsWindowVisible(child):
                api.GetWindowThreadProcessId(child, ctypes.byref(child_pid))
                if child_pid.value and child_pid.value != pid.value:
                    hosted_pids.add(child_pid.value)
            return True

        api.EnumChildWindows(window, child_callback, 0)
        hosted_paths = {p for p in (_process_path(p) for p in hosted_pids) if p}
        if len(hosted_paths) == 1:
            path = hosted_paths.pop()
    # Do not attribute a sample to a window that changed while resolving it.
    if api.GetForegroundWindow() != window:
        return ""
    return path


@lru_cache(maxsize=512)
def _file_description(path: str) -> str:
    api = _api()
    ignored = wintypes.DWORD()
    size = api.GetFileVersionInfoSizeW(path, ctypes.byref(ignored))
    if not size or size > 4 * 1024 * 1024:
        return ""
    resource = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(path, 0, size, resource):
        return ""
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    translations = []
    if api.VerQueryValueW(resource, r"\VarFileInfo\Translation", ctypes.byref(pointer), ctypes.byref(length)) and pointer.value:
        count = length.value // ctypes.sizeof(_LanguageAndCodePage)
        array = ctypes.cast(pointer, ctypes.POINTER(_LanguageAndCodePage))
        translations = [(array[i].language, array[i].codepage) for i in range(min(count, 64))]
    # Prefer Simplified Chinese or English when the file supplies alternatives.
    translations.sort(key=lambda pair: 0 if pair[0] == 0x0804 else (1 if pair[0] == 0x0409 else 2))
    for language, codepage in translations + [(0x0409, 0x04B0), (0x0409, 0x04E4)]:
        key = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\FileDescription"
        if api.VerQueryValueW(resource, key, ctypes.byref(pointer), ctypes.byref(length)) and pointer.value and length.value:
            text = ctypes.wstring_at(pointer, min(length.value, 512)).rstrip("\x00").strip()
            if text:
                return " ".join(text.split())[:160]
    return ""


def _application_name(path: str) -> str:
    if not path:
        return "未识别应用"
    return _FRIENDLY_NAMES.get(Path(path).name.casefold()) or _file_description(path) or Path(path).stem


def sample_system() -> dict:
    """Return one fresh sample; app identity is empty if it is unavailable.

    ``awake`` is monotonic working-state time, excluding sleep/hibernation.
    ``idle`` refers to the current Windows session; it reads no input content.
    ``locked`` also covers UAC, disconnected sessions, and uncertain state.
    """
    wall = time.time()
    awake = _awake_seconds()
    idle = _idle_seconds()
    locked = _is_locked() or idle is None
    path = "" if locked else _foreground_path()
    return {
        "wall": wall,
        "awake": awake,
        "idle": 0.0 if idle is None else idle,
        "locked": locked,
        "app_key": path.casefold(),
        "app_name": _application_name(path),
        "exe_path": path,
    }


def data_directory() -> Path:
    """Stable user data location, independent of executable, cwd and release.

    Compatibility contract: never add a version or change 'Shiguang' here when
    renaming the product or releasing an update. Installation files contain no
    usage database. Any future location change requires explicit migration.
    """
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    directory = base / "Shiguang"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _launch_command() -> str:
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        args = [str(executable), "--background"]
    else:
        windowed_python = executable.with_name("pythonw.exe")
        if windowed_python.is_file():
            executable = windowed_python
        main = Path(__file__).resolve().parents[1] / "main.py"
        args = [str(executable), str(main), "--background"]
    return subprocess.list2cmdline(args)


def set_autostart(enabled: bool) -> None:
    """Configure this user's Run entry. Called only after a UI setting change."""
    if os.name != "nt":
        raise OSError("开机启动设置仅支持 Windows。")
    import winreg

    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, _RUN_VALUE)
        except FileNotFoundError:
            pass


def is_autostart() -> bool:
    """Whether the Run entry targets this installation.

    Windows Task Manager may independently disable a configured startup entry.
    """
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, _RUN_VALUE)
        return kind == winreg.REG_SZ and value.casefold() == _launch_command().casefold()
    except (FileNotFoundError, PermissionError):
        return False


def _object_name(suffix: str) -> str:
    # Local namespace is session-scoped; the digest also scopes different users.
    user_root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    identity = hashlib.sha256(user_root.casefold().encode("utf-8")).hexdigest()[:20]
    return f"Local\\Shiguang_{identity}_{suffix}_v1"


def acquire_instance() -> bool:
    """Hold a per-user/session named mutex for this process lifetime.

    False means another instance exists. In that case call ``signal_show()``
    and exit. No application data or startup settings are changed here.
    """
    global _instance_handle, _show_handle
    with _instance_lock:
        if _instance_handle:
            return True
        api = _api()
        if not _show_handle:
            # Auto-reset event. Create it before the mutex to close the small
            # second-launch race between claiming the mutex and UI creation.
            _show_handle = api.CreateEventW(None, False, False, _object_name("Show"))
            if not _show_handle:
                raise ctypes.WinError(ctypes.get_last_error())
        ctypes.set_last_error(0)
        handle = api.CreateMutexW(None, False, _object_name("Instance"))
        error = ctypes.get_last_error()
        if not handle:
            api.CloseHandle(_show_handle)
            _show_handle = None
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            api.CloseHandle(handle)
            return False
        _instance_handle = handle
        return True


def signal_show() -> bool:
    """Ask the existing instance to restore its window without sending data."""
    with _instance_lock:
        api = _api()
        handle = _show_handle or api.OpenEventW(0x0002, False, _object_name("Show"))
        if not handle:
            return False
        try:
            return bool(api.SetEvent(handle))
        finally:
            if handle != _show_handle:
                api.CloseHandle(handle)


def consume_show_request() -> bool:
    """Poll from the UI timer; a successful wait auto-resets the event."""
    with _instance_lock:
        return bool(_instance_handle and _show_handle and _api().WaitForSingleObject(_show_handle, 0) == 0)


def release_instance() -> None:
    global _instance_handle, _show_handle
    with _instance_lock:
        if _show_handle:
            _api().CloseHandle(_show_handle)
            _show_handle = None
        if _instance_handle:
            # The mutex is an existence guard, not owned via WaitForSingleObject.
            _api().CloseHandle(_instance_handle)
            _instance_handle = None


atexit.register(release_instance)
