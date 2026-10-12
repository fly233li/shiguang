"""Font-independent, minute-accurate clocks for Windows' small notification area.

Each icon is drawn on its actual pixel grid. The single horizontal H:MM line
uses tall, condensed digits, pure black ink and a fully transparent background.
"""
from __future__ import annotations

from functools import lru_cache
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


STATE_COLORS = {
    # Kept as a compatible state inventory; status is expressed by the tooltip,
    # while every visible glyph stays black as requested by the user.
    state: ("#00000000", "#000000")
    for state in ("recording", "paused", "idle", "error")
}
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64)

# Seven-segment topology makes 0/6/8/9 distinct even at three pixels wide.
# Segment heights are rendered directly at the requested native pixel size.
SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg",
    "4": "bcfg", "5": "acdfg", "6": "acdefg", "7": "abc",
    "8": "abcdefg", "9": "abcdfg",
}


def whole_minutes(seconds: float) -> int:
    """Count completed minutes; never round a partial minute up."""
    if isinstance(seconds, int):
        if seconds < 0:
            raise ValueError("时长不能为负数")
        return seconds // 60
    value = float(seconds)
    if not math.isfinite(value) or value < 0:
        raise ValueError("时长必须是非负有限数值")
    return math.floor(value / 60)


def duration_text(seconds: float) -> str:
    """Describe total elapsed duration without wrapping at midnight."""
    hours, minutes = divmod(whole_minutes(seconds), 60)
    return f"{hours}小时{minutes}分"


def _label(total_minutes: int | None) -> str:
    if total_minutes is None:
        return "--"
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}" if hours <= 99 else "99+"


def _glyph(character: str, width: int, height: int) -> tuple[str, ...]:
    pixels = [["0"] * width for _ in range(height)]
    middle = height // 2
    if character == ":":
        dot_height = max(1, height // 8)
        for top in (height // 3, height * 2 // 3):
            for y in range(top, top + dot_height):
                pixels[y] = ["1"] * width
    elif character in ("-", "+"):
        pixels[middle] = ["1"] * width
        if character == "+":
            for y in range(middle - 2, middle + 3):
                pixels[y][width // 2] = "1"
    elif character == "1":
        for y in range(height):
            pixels[y][-1] = "1"
    else:
        segments = SEGMENTS[character]
        for segment, y in (("a", 0), ("g", middle), ("d", height - 1)):
            if segment in segments:
                pixels[y] = ["1"] * width
        for segment, x, top, bottom in (("f", 0, 0, middle), ("b", width - 1, 0, middle),
                                       ("e", 0, middle, height - 1), ("c", width - 1, middle, height - 1)):
            if segment in segments:
                for y in range(top, bottom + 1):
                    pixels[y][x] = "1"
    return tuple("".join(row) for row in pixels)


def _layout(text: str, size: int) -> tuple[int, int, list[int], list[int]]:
    """Return scale, digit height, widths and following gaps on a native grid."""
    if size in (16, 32, 64):
        base, scale, height = 16, size // 16, 11
    elif size in (20, 40):
        base, scale, height = 20, size // 20, 15
    elif size in (24, 48):
        base, scale, height = 24, size // 24, 17
    else:
        raise ValueError(f"不支持的托盘图标尺寸：{size}")
    double_hour = ":" in text and len(text.split(":")[0]) == 2
    digit_width = (3 if double_hour else 4) if base == 20 else (4 if double_hour else 5) if base == 24 else 3
    widths = [1 if character == ":" else digit_width for character in text]
    gaps = [1] * (len(text) - 1) + [0]
    if base == 16 and double_hour:
        if text[0] == "1":
            widths[0] = 1
        elif text[0] == "2":
            widths[0] = 2
        else:
            # Daily uptime is normally <= 25 hours. Longer totals retain the
            # exact value through 99 h; only their hour-to-hour gap is tightened.
            gaps[0] = 0
    if sum(widths) + sum(gaps) > base:
        raise ValueError("时长字形超出托盘可用宽度")
    return scale, height, widths, gaps


def _render(total_minutes: int | None, state: str, size: int) -> QPixmap:
    text = _label(total_minutes)
    scale, height, widths, gaps = _layout(text, size)
    x = (size - (sum(widths) + sum(gaps)) * scale) // 2
    y = (size - height * scale) // 2
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    ink = QColor("#000000")
    for character, width, gap in zip(text, widths, gaps):
        bitmap = _glyph(character, width, height)
        for row, pixels in enumerate(bitmap):
            for column, value in enumerate(pixels):
                if value == "1":
                    painter.fillRect(x + column * scale, y + row * scale, scale, scale, ink)
        x += (width + gap) * scale
    painter.end()
    return pixmap


@lru_cache(maxsize=256)
def _cached_icon(total_minutes: int | None, state: str) -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(_render(total_minutes, state, size))
    return icon


def duration_icon(total_minutes: int | None, state: str = "recording") -> QIcon:
    """Return a cached, natively rasterized duration icon; requires QApplication.

    None means unavailable data, represented by dashes. Never substitute zero
    after a database error. State remains valid for callers and caching; the
    tooltip expresses it because the user requested uniform black text.
    """
    if total_minutes is not None and (isinstance(total_minutes, bool) or not isinstance(total_minutes, int)):
        raise TypeError("托盘时长必须为整数分钟或 None")
    if total_minutes is not None and total_minutes < 0:
        raise ValueError("托盘时长不能为负数")
    if state == "default":
        state = "recording"
    if state not in STATE_COLORS:
        raise ValueError(f"未知托盘状态：{state}")
    return _cached_icon(total_minutes, state)
