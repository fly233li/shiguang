from __future__ import annotations

import math
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QIcon
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QLabel, QToolTip, QPushButton, QSizePolicy, QComboBox, QDateEdit
from .icons import application_icon, paint_symbol

INK = "#172d35"
GREEN = "#227660"
MUTED = "#788783"


def paint_chevron(widget):
    p=QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_symbol(p,"chevron-down",QRectF(widget.width()-28,(widget.height()-20)/2,20,20),MUTED)
    p.end()


class ChevronComboBox(QComboBox):
    def paintEvent(self,event):
        super().paintEvent(event)
        paint_chevron(self)


class CalendarDateEdit(QDateEdit):
    def paintEvent(self,event):
        super().paintEvent(event)
        paint_chevron(self)


class NavigationButton(QPushButton):
    """Fixed icon/text lanes, independent of font fallback or emoji metrics."""
    def __init__(self, text, kind):
        super().__init__(text)
        self.kind = kind
        self.keyboard_focus = False
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def focusInEvent(self,event):
        self.keyboard_focus=event.reason() in (Qt.FocusReason.TabFocusReason,Qt.FocusReason.BacktabFocusReason,Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isChecked()
        background = "#e4edbe" if selected else ("#294249" if self.underMouse() else "#182f35")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(background))
        p.drawRoundedRect(QRectF(self.rect()),8,8)
        color=QColor("#213b32" if selected else "#bdccca")
        p.setPen(QPen(color,1.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.save()
        kind=("overview","apps","history","settings")[self.kind]
        paint_symbol(p,kind,QRectF(16,(self.height()-20)/2,20,20),color.name())
        p.restore()
        font=QFont(self.font())
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        p.setFont(font)
        p.drawText(QRectF(48,0,self.width()-64,self.height()),Qt.AlignmentFlag.AlignVCenter,self.text())
        if self.hasFocus() and self.keyboard_focus:
            p.setPen(QPen(color,1,Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(3,3,-3,-3),6,6)
        p.end()


def duration(seconds: float, compact=False) -> str:
    seconds = max(0, int(seconds))
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h {m:02d}m" if compact else f"{h} 小时 {m:02d} 分"
    if m:
        return f"{m}m" if compact else f"{m} 分钟"
    return f"{seconds} 秒"


def make_icon(size=64) -> QIcon:
    """Compatibility wrapper; QIcon chooses the requested pixmap resolution."""
    return application_icon()


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(24, 16, 24, 16)
        self.box.setSpacing(8)


class Metric(Card):
    def __init__(self, title, caption, accent=False):
        super().__init__()
        if accent:
            self.setObjectName("accentCard")
        self.label = QLabel(title)
        self.label.setObjectName("metricLabel")
        self.value = QLabel("0 秒")
        self.value.setObjectName("metricValue")
        self.value.setMinimumWidth(0)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.value.setFixedHeight(36)
        self.caption = QLabel(caption)
        self.caption.setObjectName("metricCaption")
        self.label.setFixedHeight(20)
        self.caption.setFixedHeight(18)
        self.caption.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.caption.setToolTip(caption)
        self.box.addWidget(self.label)
        self.box.addWidget(self.value)
        self.box.addWidget(self.caption)
        self.setFixedHeight(122)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)


class BarChart(QWidget):
    """Awake background with active foreground; hover reveals exact values."""
    def __init__(self, hourly=False):
        super().__init__()
        self.hourly = hourly
        self.rows = []
        self.setMinimumHeight(148)
        self.setMouseTracking(True)
        self.setAccessibleName("时长分布图，绿色为实际操作，浅绿色为电脑运行")

    def set_data(self, rows):
        self.rows = rows
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(QFont("Microsoft YaHei UI", 9))
        left, top, bottom = 44, 16, self.height() - 28
        width = self.width() - left - 12
        maximum = max([r["awake"] for r in self.rows] + [3600 if self.hourly else 7200])
        maximum = math.ceil(maximum / 3600) * 3600
        for i in range(4):
            y = top + (bottom - top) * i / 3
            p.setPen(QPen(QColor("#e8ede8"), 1))
            p.drawLine(int(left), int(y), self.width()-8, int(y))
            p.setPen(QColor(MUTED))
            value = maximum*(3-i)/3
            text = f"{value/60:.0f}m" if self.hourly else f"{value/3600:.1f}h"
            p.drawText(QRectF(0, y-8, 36, 20), Qt.AlignmentFlag.AlignRight, text)
        n = len(self.rows)
        if n:
            step = width / n
            bw = min(30, step * .57)
            for i, row in enumerate(self.rows):
                x = left + step * i + (step-bw)/2
                for key, color in [("awake", "#dce8dd"), ("active", GREEN)]:
                    h = (bottom-top)*row[key]/maximum
                    if h > 0:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor(color))
                        p.drawRoundedRect(QRectF(x, bottom-max(2,h), bw, max(2,h)), 3, 3)
                label = f"{row['hour']:02d}" if self.hourly else row["date"][5:].replace("-", "/")
                if (self.hourly and i % 3 == 0) or (not self.hourly and (n <= 7 or i % 5 == 0)):
                    p.setPen(QColor(MUTED))
                    p.drawText(QRectF(x-15, bottom+7, bw+30, 20), Qt.AlignmentFlag.AlignHCenter, label)
        if not any(r["awake"] for r in self.rows):
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(left, top, width, bottom-top), Qt.AlignmentFlag.AlignCenter,
                       "还没有记录，让时间慢慢留下痕迹")
        p.end()

    def mouseMoveEvent(self, event):
        width = self.width()-56
        i = int((event.position().x()-44) / max(1, width) * len(self.rows))
        if 0 <= i < len(self.rows) and event.position().x() >= 44:
            row = self.rows[i]
            label = f"{row['hour']:02d}:00—{row['hour']+1:02d}:00" if self.hourly else row["date"]
            QToolTip.showText(event.globalPosition().toPoint(),
                f"{label}\n电脑运行：{duration(row['awake'])}\n实际操作：{duration(row['active'])}", self)


class RatioRing(QWidget):
    def __init__(self):
        super().__init__()
        self.ratio = 0
        self.setMinimumSize(110, 120)
        self.setFixedHeight(128)
        self.setAccessibleName("实际操作占电脑运行的比例")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 26
        rect = QRectF((self.width()-side)/2, (self.height()-side)/2, side, side)
        p.setPen(QPen(QColor("#e9eee4"), 10))
        p.drawEllipse(rect)
        p.setPen(QPen(QColor(GREEN), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 90*16, -int(self.ratio*360*16))
        p.setPen(QColor(INK))
        p.setFont(QFont("Segoe UI", 23, QFont.Weight.DemiBold))
        p.drawText(rect.adjusted(0,-8,0,-8), Qt.AlignmentFlag.AlignCenter, f"{self.ratio:.0%}")
        p.setPen(QColor(MUTED))
        p.setFont(QFont("Microsoft YaHei UI", 9))
        p.drawText(rect.adjusted(0,42,0,0), Qt.AlignmentFlag.AlignCenter, "操作占比")
        p.end()
