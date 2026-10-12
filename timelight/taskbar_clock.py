"""A naturally proportioned, transparent time strip at the taskbar's left edge.

This is one small, non-activating tool window. It is positioned from the real
taskbar rectangle; it does not inject into Explorer or reserve extra tray slots.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QFont, QFontMetrics, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from .taskbar_native import read_taskbar_state


MARGIN = 8
DEFAULT_WIDTH = 88
DEFAULT_HEIGHT = 32


def _screen_for_monitor(monitor):
    screens = QApplication.screens()
    if not screens:
        return QApplication.primaryScreen()
    left, top, right, bottom = monitor

    def score(screen):
        geometry = screen.geometry()
        dpr = float(screen.devicePixelRatio()) or 1.0
        size_error = abs(geometry.width() * dpr - (right - left)) + abs(geometry.height() * dpr - (bottom - top))
        # Qt screen origins may preserve native Windows positions or expose a
        # scaled logical origin. Match either convention, then convert locally.
        origin_error = min(abs(geometry.x() - left) + abs(geometry.y() - top),
                           abs(geometry.x() * dpr - left) + abs(geometry.y() * dpr - top))
        return size_error * 2 + origin_error

    return min(screens, key=score)


def _logical_rect(rect, monitor, screen, *, inside=False):
    """Convert physical monitor-relative coordinates, preserving screen origin."""
    geometry = screen.geometry()
    dpr = float(screen.devicePixelRatio()) or 1.0
    left = geometry.x() + (rect[0] - monitor[0]) / dpr
    top = geometry.y() + (rect[1] - monitor[1]) / dpr
    right = geometry.x() + (rect[2] - monitor[0]) / dpr
    bottom = geometry.y() + (rect[3] - monitor[1]) / dpr
    # Keep the time strip inside the bar, including at fractional display scale.
    start, end = (math.ceil, math.floor) if inside else (math.floor, math.ceil)
    x, y, r, b = start(left), start(top), end(right), end(bottom)
    return QRect(x, y, max(0, r - x), max(0, b - y))


class TaskbarClock(QWidget):
    offsetChanged = Signal(int)
    activated = Signal()
    contextMenuRequested = Signal(QPoint)

    def __init__(self, parent=None):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(parent, flags)
        self.setObjectName("taskbarClock")
        self.setWindowTitle("时光计 · 今日时长")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setStyleSheet("#taskbarClock { background: transparent; }")
        self._clock_font = QFont("Segoe UI")
        self._clock_font.setPixelSize(24)
        self._clock_font.setWeight(QFont.Weight.DemiBold)
        self._clock_font.setStretch(QFont.Stretch.Unstretched)
        self.setFont(self._clock_font)
        self.setFixedSize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._enabled = False
        self._stopped = False
        self._offset = 0
        self._default_x = 0
        self._minimum_x = 0
        self._maximum_x = 0
        self._display_text = "--"
        self.duration_minutes = None
        self._base_tooltip = ""
        self._drag_anchor = None
        self._drag_offset_before = 0
        self.placement_mode = "hidden"
        self.hide()

    def text(self) -> str:
        return self._display_text

    def set_duration(self, minutes: int | None, tooltip: str) -> None:
        if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, int)):
            raise TypeError("时间条时长必须为整数分钟或 None")
        if minutes is not None and minutes < 0:
            raise ValueError("时间条时长不能为负数")
        self.duration_minutes = minutes
        self._display_text = "--" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"
        self._base_tooltip = str(tooltip)
        # Normal daily values retain exactly 88 px. Unusually long durations
        # widen the strip instead of squeezing the font or dropping digits.
        width = max(DEFAULT_WIDTH, QFontMetrics(self._clock_font).horizontalAdvance(self._display_text) + 16)
        self.setFixedSize(width, DEFAULT_HEIGHT)
        self._update_tooltip()
        self.update()

    def _update_tooltip(self) -> None:
        note = ""
        if self.placement_mode == "fallback":
            note = "任务栏空间不足，时间条暂放在屏幕可用区域左下角。"
        self.setToolTip("\n".join(part for part in (self._base_tooltip, note) if part))

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._hide_clock()

    def set_offset(self, value: int) -> None:
        self._offset = int(value)

    def _hide_clock(self) -> None:
        self.placement_mode = "hidden"
        self._drag_anchor = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.hide()

    def _place(self, default_x: int, minimum_x: int, maximum_x: int, y: int, mode: str) -> None:
        if maximum_x < minimum_x:
            self._hide_clock()
            return
        self._default_x, self._minimum_x, self._maximum_x = default_x, minimum_x, maximum_x
        x = max(minimum_x, min(maximum_x, default_x + self._offset))
        self._offset = x - default_x
        self.placement_mode = mode
        self._update_tooltip()
        if self.x() != x or self.y() != y:
            self.move(x, y)
        if not self.isVisible():
            self.show()
        # Explorer can raise its taskbar above an already-visible tool window.
        # Restore z-order without activateWindow() or requesting keyboard focus.
        if QApplication.activePopupWidget() is None:
            self.raise_()

    def _fallback(self, screen, bar) -> None:
        area = QRect(screen.availableGeometry())
        # Auto-hide bars can overlap Qt's availableGeometry while temporarily
        # visible. Exclude the known bar too, even without notification bounds.
        if area.intersects(bar):
            if bar.width() >= bar.height():
                if bar.center().y() >= area.center().y():
                    area.setBottom(min(area.bottom(), bar.top() - 1))
                else:
                    area.setTop(max(area.top(), bar.bottom() + 1))
            elif bar.center().x() >= area.center().x():
                area.setRight(min(area.right(), bar.left() - 1))
            else:
                area.setLeft(max(area.left(), bar.right() + 1))
        if self.width() + MARGIN * 2 > area.width() or self.height() + MARGIN * 2 > area.height():
            self._hide_clock()
            return
        minimum_x = area.x() + MARGIN
        maximum_x = area.x() + area.width() - MARGIN - self.width()
        self._place(minimum_x, minimum_x, maximum_x,
                    area.y() + area.height() - MARGIN - self.height(), "fallback")

    def refresh_placement(self) -> None:
        if self._stopped or not self._enabled:
            self._hide_clock()
            return
        try:
            state = read_taskbar_state()
        except Exception:
            state = None
        # A failed probe cannot rule out a full-screen foreground application.
        # Wait for the next existing application tick rather than floating over it.
        if state is None or not state.visible or state.fullscreen:
            self._hide_clock()
            return
        screen = _screen_for_monitor(state.monitor)
        if screen is None:
            self._hide_clock()
            return
        bar = _logical_rect(state.bar, state.monitor, screen, inside=True)
        minimum_x = bar.x() + MARGIN
        maximum_x = bar.x() + bar.width() - MARGIN - self.width()
        if bar.height() < self.height() or maximum_x < minimum_x:
            self._fallback(screen, bar)
            return
        # The anchor and drag range depend only on the taskbar itself. Explorer
        # frequently changes notification bounds as tray icons appear; those
        # unrelated changes must never move this left-anchored clock.
        if bar.width() >= bar.height():
            y = bar.y() + (bar.height() - self.height()) // 2
        else:
            y = bar.y() + MARGIN
        self._place(minimum_x, minimum_x, maximum_x, y, "taskbar")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self._clock_font)
        painter.setPen(QColor("#000000"))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine, self._display_text)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_anchor = event.globalPosition().toPoint() - self.pos()
            self._drag_offset_before = self._offset
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        # Qt emits this for right-click and keyboard context-menu requests.
        # Emitting only here avoids opening a second menu on mouse release.
        self.contextMenuRequested.emit(event.globalPos())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            x = event.globalPosition().toPoint().x() - self._drag_anchor.x()
            x = max(self._minimum_x, min(self._maximum_x, x))
            self._offset = x - self._default_x
            if self.x() != x:
                self.move(x, self.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_anchor is not None:
            self._drag_anchor = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if self._offset != self._drag_offset_before:
                self.offsetChanged.emit(self._offset)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_anchor = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.activated.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def stop(self) -> None:
        self._stopped = True
        self._enabled = False
        self._hide_clock()
