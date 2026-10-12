"""Render a drawing-only preview; never show or position a desktop time strip."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from timelight.taskbar_clock import TaskbarClock


def text(painter, x, y, value, pixels=15, *, bold=False, color="#172d35"):
    font = QFont("Microsoft YaHei")
    font.setPixelSize(pixels)
    font.setBold(bold)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(x, y, value)


def render_clock(widget, minutes, scale=1):
    widget.set_duration(minutes, "今日已记录时长")
    image = QPixmap(widget.width() * scale, widget.height() * scale)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.GlobalColor.transparent)
    widget.render(image)
    return image


def main():
    app = QApplication.instance() or QApplication([])
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisb.ttf"):
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    target = ROOT / "assets" / "taskbar-clock"
    target.mkdir(parents=True, exist_ok=True)
    widget = TaskbarClock()
    widget.set_enabled(False)
    board = QImage(1220, 690, QImage.Format.Format_ARGB32)
    board.fill(QColor("#f4f5ef"))
    painter = QPainter(board)
    text(painter, 36, 48, "任务栏最左侧 · 稳定显示今日时长", 28, bold=True)
    text(painter, 36, 80, "约 88 × 32 逻辑像素 · Segoe UI 24 px 半粗体 · 黑字透明底 · 不再跟随通知区变化移动", color="#536762")

    painter.fillRect(36, 110, 1148, 118, QColor("#e8ebef"))
    text(painter, 58, 139, "任务栏整行示意：时间条距左边缘 8 px（按逻辑像素原尺寸绘制）", 13, color="#536762")
    painter.fillRect(36, 158, 1148, 50, QColor("#eef0f3"))
    painter.drawPixmap(44, 167, render_clock(widget, 155))
    text(painter, 215, 188, "← 固定左侧起点", 14, color="#536762")
    text(painter, 530, 188, "任务栏应用区", 14, color="#536762")
    text(painter, 915, 188, "系统通知区", 14)
    text(painter, 1096, 180, "21:45", 15)
    text(painter, 1084, 201, "2026/10/12", 12)

    cases = ((0, "0:00"), (155, "2:35"), (599, "9:59"), (600, "10:00"),
             (1439, "23:59"), (1440, "24:00"), (None, "不可读取"))
    text(painter, 36, 274, "不同时间 · 原尺寸", 20, bold=True)
    for index, (minutes, caption) in enumerate(cases):
        x = 36 + index * 166
        painter.fillRect(x, 296, 150, 108, QColor("#ffffff"))
        pixmap = render_clock(widget, minutes)
        painter.drawPixmap(x + 31, 319, pixmap)
        text(painter, x + 20, 387, caption, 13, color="#536762")
        token = "unavailable" if minutes is None else str(minutes)
        pixmap.save(str(target / f"clock-{token}-1x.png"))
        render_clock(widget, minutes, 2).save(str(target / f"clock-{token}-2x.png"))

    text(painter, 36, 454, "透明文字在不同背景上的效果", 20, bold=True)
    for left, background, caption, caption_color in ((36, "#eef0f3", "浅色任务栏", "#536762"),
                                                     (620, "#252932", "深色任务栏：黑字对比度较低", "#d3d9de")):
        painter.fillRect(left, 478, 564, 100, QColor(background))
        painter.drawPixmap(left + 32, 507, render_clock(widget, 1439))
        text(painter, left + 153, 531, caption, 14, color=caption_color)
    text(painter, 36, 620, "左键向右拖动可调整位置，左侧不超出任务栏边缘；通知图标增加、减少或探测缺失不会改变左侧位置。", 14, color="#536762")
    text(painter, 36, 649, "双击打开主窗口，右键显示菜单。全屏或任务栏隐藏时自动隐藏；任务栏放不下时暂放可用区域左下角。", 13, color="#536762")
    painter.end()
    output = target / "横向任务栏时间条预览.png"
    if not board.save(str(output)):
        raise OSError(f"Cannot save preview: {output}")
    widget.stop()
    widget.deleteLater()
    app.processEvents()
    print(str(output))


if __name__ == "__main__":
    main()
