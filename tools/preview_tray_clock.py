"""Make actual-size and nearest-neighbour inspection boards for tray clocks."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from timelight.tray_clock import STATE_COLORS, duration_icon


SIZES = (16, 20, 24, 32)
CASES = ((0, "0:00"), (155, "2:35"), (599, "9:59"), (600, "10:00"),
         (1439, "23:59"), (1440, "24:00"), (None, "-- / 不可读取"))
STATES = {"recording": "记录中", "paused": "已暂停", "idle": "已离开", "error": "异常"}


def font(pixels, bold=False):
    result = QFont("Microsoft YaHei")
    result.setPixelSize(pixels)
    result.setBold(bold)
    return result


def text(painter, x, y, value, pixels=14, color="#172d35", bold=False):
    painter.setFont(font(pixels, bold))
    painter.setPen(QColor(color))
    painter.drawText(x, y, value)


def main():
    app = QApplication.instance() or QApplication([])
    for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
        file = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
        if file.exists():
            QFontDatabase.addApplicationFont(str(file))
    target = ROOT / "assets" / "tray-clock"
    target.mkdir(parents=True, exist_ok=True)

    board = QImage(1280, 990, QImage.Format.Format_ARGB32)
    board.fill(QColor("#f1f3eb"))
    painter = QPainter(board)
    text(painter, 36, 49, "横向时间 · 黑字 · 透明背景", 28, bold=True)
    text(painter, 36, 80, "单个 Windows 托盘图标 · H:MM 不补小时零 · 16 px 下数字高 11 px（原双排为 5 px）", 15, "#536762")

    for section, (background, foreground, caption) in enumerate((
        ("#f7f8fa", "#172d35", "浅色任务栏"), ("#20242a", "#eef1e9", "深色任务栏 · 黑字对比度较低"))):
        left = 36 + section * 622
        top = 110
        painter.fillRect(left, top, 586, 442, QColor(background))
        text(painter, left + 20, top + 30, caption, 16, foreground, True)
        for column, size in enumerate(SIZES):
            text(painter, left + 178 + column * 103, top + 64, f"{size} px", 14, foreground)
        for row, (minutes, label) in enumerate(CASES):
            y = top + 100 + row * 46
            text(painter, left + 20, y + 5, label, 14, foreground)
            for column, size in enumerate(SIZES):
                x = left + 184 + column * 103
                painter.drawPixmap(x, y - size // 2, duration_icon(minutes).pixmap(size, size))

    text(painter, 36, 594, "状态由悬停文字说明，图标统一黑字透明底", 20, bold=True)
    for index, (state, label) in enumerate(STATES.items()):
        left = 36 + index * 310
        painter.fillRect(left, 615, 282, 98, QColor("#ffffff"))
        text(painter, left + 16, 641, label, 16, "#172d35", True)
        for column, size in enumerate(SIZES):
            painter.drawPixmap(left + 18 + column * 62, 665, duration_icon(155, state).pixmap(size, size))

    text(painter, 36, 762, "16 px 字形放大检查", 20, bold=True)
    text(painter, 310, 760, "左侧为原尺寸，右侧仅按最近邻放大 6 倍；无背景块、无描边。", 14, "#536762")
    for column, (minutes, label) in enumerate(CASES):
        x = 36 + column * 178
        pixmap = duration_icon(minutes).pixmap(16, 16)
        painter.drawPixmap(x, 817, pixmap)
        painter.drawPixmap(x + 28, 786, pixmap.scaled(96, 96, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation))
        text(painter, x, 911, label, 13, "#536762")
    text(painter, 36, 949, "单个托盘图标受系统方形区域限制：双位小时使用窄首位字形；大于 99 小时显示 99+，悬停可看准确值。", 13, "#536762")
    text(painter, 36, 973, "透明黑字在浅色任务栏上更清晰。深色任务栏仍保留用户指定的纯黑，不自动变白，也不添加底板。", 13, "#536762")
    painter.end()
    filename = target / "托盘时长预览.png"
    if not board.save(str(filename)):
        raise OSError(f"Cannot save preview: {filename}")

    # Save every inspected frame as a useful, transparent implementation asset.
    # Refresh every earlier duration frame too; no old colored plate remains.
    export_minutes = {minutes for minutes, _ in CASES} | {59, 60, 6000}
    for existing in target.glob("duration-*.png"):
        token = existing.stem.removeprefix("duration-").rsplit("-", 1)[0]
        if token == "unavailable":
            export_minutes.add(None)
        elif token.isdigit():
            export_minutes.add(int(token))
    for minutes in export_minutes:
        name = "unavailable" if minutes is None else str(minutes)
        for size in SIZES:
            duration_icon(minutes).pixmap(size, size).save(str(target / f"duration-{name}-{size}.png"))
    for state in STATES:
        for size in SIZES:
            duration_icon(155, state).pixmap(size, size).save(str(target / f"state-{state}-{size}.png"))
    app.processEvents()
    print(str(filename))


if __name__ == "__main__":
    main()
