"""Pure duration checks plus deterministic offscreen bitmap validation."""
import math
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from timelight.tray_clock import ICON_SIZES, _cached_icon, duration_icon, duration_text, whole_minutes


class DurationHelpersTests(unittest.TestCase):
    def test_complete_minutes_never_round_up(self):
        for seconds, expected in ((0, 0), (59.9, 0), (math.nextafter(60, 0), 0),
                                  (60, 1), (119.999, 1), (3599.9, 59), (3600, 60),
                                  (86399.9, 1439), (86400, 1440)):
            with self.subTest(seconds=seconds):
                self.assertEqual(whole_minutes(seconds), expected)

    def test_text_does_not_wrap_at_twenty_four_hours(self):
        self.assertEqual(duration_text(0), "0小时0分")
        self.assertEqual(duration_text(59.9), "0小时0分")
        self.assertEqual(duration_text(9300), "2小时35分")
        self.assertEqual(duration_text(86399.9), "23小时59分")
        self.assertEqual(duration_text(86400), "24小时0分")
        self.assertEqual(duration_text(3600 * 105 + 60 * 7), "105小时7分")

    def test_negative_and_nonfinite_values_are_rejected(self):
        for invalid in (-1, -0.01, float("nan"), float("inf"), -float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    whole_minutes(invalid)
                with self.assertRaises(ValueError):
                    duration_text(invalid)

    def test_large_integer_duration_keeps_exact_minutes(self):
        self.assertEqual(whole_minutes(10**30 + 59), (10**30 + 59) // 60)


class DurationIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def ink(image):
        return {(x, y) for y in range(image.height()) for x in range(image.width())
                if image.pixelColor(x, y).alpha() > 0}

    def test_all_native_sizes_have_only_black_ink_on_a_transparent_background(self):
        for state in ("recording", "paused", "idle", "error", "default"):
            for minutes in (0, 59, 60, 599, 600, 1439, 1440, None, 99999):
                icon = duration_icon(minutes, state)
                self.assertEqual([size.width() for size in icon.availableSizes()], list(ICON_SIZES))
                for size in ICON_SIZES:
                    with self.subTest(state=state, minutes=minutes, size=size):
                        image = icon.pixmap(size, size).toImage()
                        self.assertEqual((image.width(), image.height()), (size, size))
                        self.assertTrue(image.hasAlphaChannel())
                        ink = self.ink(image)
                        self.assertTrue(ink)
                        self.assertLess(len(ink), size * size // 2, "No opaque plate behind the text")
                        # Two-digit hours may use the full width of the 16 px slot.
                        # Top and bottom remain clear, rather than clipping tall digits.
                        self.assertTrue(all(0 < y < size - 1 for _, y in ink))
                        for x, y in ink:
                            pixel = image.pixelColor(x, y)
                            self.assertEqual((pixel.red(), pixel.green(), pixel.blue()), (0, 0, 0))

    def test_clock_is_one_large_horizontal_line_with_a_complete_colon(self):
        for minutes in (0, 6, 8, 9, 359, 539, 599, 600, 659, 1380, 1439, 1440):
            for size in ICON_SIZES:
                with self.subTest(minutes=minutes, size=size):
                    ink = self.ink(duration_icon(minutes).pixmap(size, size).toImage())
                    rows = {y for _, y in ink}
                    first, last = min(rows), max(rows)
                    self.assertGreaterEqual(last - first + 1, int(size * 0.55))
                    self.assertEqual(rows, set(range(first, last + 1)), "Hours and minutes must share one line")

                    # Locate a real two-dot separator between the hour and minute
                    # glyphs from the rendered pixels, independent of font tables.
                    columns = [{y for x, y in ink if x == column} for column in range(size)]
                    separators = []
                    column = 0
                    while column < size:
                        if not columns[column]:
                            column += 1
                            continue
                        left = column
                        ys = set()
                        while column < size and columns[column]:
                            ys.update(columns[column])
                            column += 1
                        right = column - 1
                        ys = sorted(ys)
                        runs = 1 + sum(b > a + 1 for a, b in zip(ys, ys[1:]))
                        if (runs == 2 and first < ys[0] < ys[-1] < last
                                and any(px < left for px, _ in ink) and any(px > right for px, _ in ink)):
                            separators.append((left, right))
                    self.assertEqual(len(separators), 1, "Both colon dots must be visible between hours and minutes")

    def test_every_minute_through_24_hours_is_distinct_at_small_native_sizes(self):
        # A missing or cropped digit can silently show the same image for two
        # different times. Cover all valid daily H:MM values, including 0/6/8/9.
        seen = {size: {} for size in (16, 20, 24)}
        for minutes in range(24 * 60 + 1):
            icon = duration_icon(minutes)
            for size, bitmaps in seen.items():
                image = icon.pixmap(size, size).toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                pixels = bytes(image.constBits())
                self.assertNotIn(pixels, bitmaps, f"{size} px minute {minutes} collides with {bitmaps.get(pixels)}")
                bitmaps[pixels] = minutes

    def test_unavailable_is_visibly_distinct_from_zero_and_24_hours_from_zero(self):
        for size in (16, 20, 24, 32):
            zero = duration_icon(0).pixmap(size, size).toImage()
            self.assertNotEqual(duration_icon(None).pixmap(size, size).toImage(), zero)
            self.assertNotEqual(duration_icon(1440).pixmap(size, size).toImage(), zero)

    def test_minute_and_hour_boundaries_change_the_bitmap(self):
        for before, after in ((0, 59), (59, 60), (1439, 1440)):
            self.assertNotEqual(duration_icon(before).pixmap(16, 16).toImage(),
                                duration_icon(after).pixmap(16, 16).toImage())

    def test_existing_state_api_keeps_the_requested_black_transparent_appearance(self):
        # State remains in the tooltip; pausing or a read error must not bring
        # back the old colored plate or change the requested black text.
        for size in ICON_SIZES:
            expected = duration_icon(155, "recording").pixmap(size, size).toImage()
            for state in ("paused", "idle", "error", "default"):
                self.assertEqual(duration_icon(155, state).pixmap(size, size).toImage(), expected)
        self.assertEqual(duration_icon(155, "default").cacheKey(), duration_icon(155, "recording").cacheKey())

    def test_same_integer_minute_reuses_cached_icon(self):
        _cached_icon.cache_clear()
        first = duration_icon(whole_minutes(120))
        second = duration_icon(whole_minutes(179.99))
        self.assertEqual(first.cacheKey(), second.cacheKey())
        self.assertEqual(_cached_icon.cache_info().hits, 1)
        self.assertEqual(_cached_icon.cache_info().maxsize, 256)

    def test_invalid_icon_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            duration_icon(-1)
        with self.assertRaises(ValueError):
            duration_icon(1, "invalid")
        with self.assertRaises(TypeError):
            duration_icon(1.5)
        with self.assertRaises(TypeError):
            duration_icon(True)


if __name__ == "__main__":
    unittest.main()
