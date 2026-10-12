"""Native smoke and privacy/accuracy regression checks; no registry writes."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

from timelight import win32


class SamplingTests(unittest.TestCase):
    def test_idle_timer_wrap(self):
        self.assertEqual(win32._idle_delta(1250, 1000), 0.25)
        self.assertEqual(win32._idle_delta(2**32 + 50, 2**32 - 50), 0.1)

    def test_locked_desktop_never_queries_foreground(self):
        with patch.object(win32, "_awake_seconds", return_value=120.0), \
             patch.object(win32, "_idle_seconds", return_value=15.0), \
             patch.object(win32, "_is_locked", return_value=True), \
             patch.object(win32, "_foreground_path") as foreground:
            sample = win32.sample_system()
        foreground.assert_not_called()
        self.assertTrue(sample["locked"])
        self.assertEqual(sample["app_key"], "")
        self.assertEqual(sample["exe_path"], "")

    def test_missing_input_information_is_finite_but_inactive(self):
        with patch.object(win32, "_awake_seconds", return_value=120.0), \
             patch.object(win32, "_idle_seconds", return_value=None), \
             patch.object(win32, "_is_locked", return_value=False), \
             patch.object(win32, "_foreground_path") as foreground:
            sample = win32.sample_system()
        self.assertTrue(sample["locked"])
        self.assertTrue(math.isfinite(sample["idle"]))
        self.assertEqual(sample["awake"], 120.0)
        foreground.assert_not_called()

    def test_inaccessible_foreground_does_not_reuse_previous_application(self):
        with patch.object(win32, "_awake_seconds", return_value=120.0), \
             patch.object(win32, "_idle_seconds", return_value=0.0), \
             patch.object(win32, "_is_locked", return_value=False), \
             patch.object(win32, "_foreground_path", side_effect=[r"C:\Apps\chrome.exe", ""]):
            first = win32.sample_system()
            second = win32.sample_system()
        self.assertTrue(first["app_key"])
        self.assertEqual(second["app_key"], "")
        self.assertEqual(second["exe_path"], "")


@unittest.skipUnless(os.name == "nt", "Windows native integration")
class NativeWindowsTests(unittest.TestCase):
    def test_real_sampling_and_process_identity(self):
        sample = win32.sample_system()
        for field in ("wall", "awake", "idle"):
            self.assertTrue(math.isfinite(sample[field]), field)
            self.assertGreaterEqual(sample[field], 0, field)
        self.assertLessEqual(sample["awake"], win32.boot_elapsed())
        self.assertEqual(set(sample), {"wall", "awake", "idle", "locked", "app_key", "app_name", "exe_path"})
        image = win32._process_path(os.getpid())
        # A Windows virtualenv's launcher may run the base Python executable.
        expected = {sys.executable, getattr(sys, "_base_executable", sys.executable)}
        self.assertTrue(any(os.path.samefile(image, candidate) for candidate in expected))

    def test_version_resource_decoding(self):
        self.assertTrue(win32._file_description(sys.executable))

    def test_named_mutex_across_processes_and_show_event(self):
        identity = uuid.uuid4().hex
        prefix = f"Local\\ShiguangTest_{identity}_"
        code = (
            "import json; from timelight import win32; "
            f"win32._object_name=lambda suffix: {prefix!r}+suffix; "
            "print(json.dumps([win32.acquire_instance(),win32.signal_show()])); "
            "win32.release_instance()"
        )
        # Test-only names cannot collide with a running copy of the real app.
        with patch.object(win32, "_object_name", side_effect=lambda suffix: prefix + suffix):
            try:
                self.assertTrue(win32.acquire_instance())
                self.assertFalse(win32.consume_show_request())
                child = subprocess.run([sys.executable, "-c", code],
                                       cwd=str(Path(__file__).resolve().parents[1]),
                                       capture_output=True, text=True, timeout=10, check=True)
                self.assertEqual(json.loads(child.stdout), [False, True])
                self.assertTrue(win32.consume_show_request())
                self.assertFalse(win32.consume_show_request())
            finally:
                win32.release_instance()
            self.assertTrue(win32.acquire_instance())
            win32.release_instance()


if __name__ == "__main__":
    unittest.main()
