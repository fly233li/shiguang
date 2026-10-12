from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QTimer, QUrl, QSignalBlocker, QSize, QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame, QStackedWidget, QButtonGroup, QDateEdit, QComboBox,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QProgressBar, QCheckBox, QFileDialog, QMessageBox, QSystemTrayIcon,
    QMenu, QScrollArea, QSizePolicy, QGridLayout,
)

from . import win32
from .tracking import Sample, Tracker
from .widgets import Card, Metric, BarChart, RatioRing, NavigationButton, ChevronComboBox, CalendarDateEdit, duration, make_icon
from .icons import application_icon, symbol_icon
from .tray_clock import duration_text, whole_minutes
from .taskbar_clock import TaskbarClock
from . import __version__

GAP = 16
GUTTER = 12
CONTROL_HEIGHT = 40

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #172d35; }
QMainWindow, QWidget#canvas { background: #f4f5ef; }
QFrame#sidebar { background: #182f35; border: none; }
QLabel#brand { color: #f4f6e9; font-size: 24px; font-weight: 700; }
QLabel#brandSub { color: #9eb3b3; font-size: 11px; }
QLabel#sideNote { color: #b5c6c4; font-size: 12px; line-height: 1.5; }
QPushButton#nav { text-align: left; padding: 13px 17px; border: none; border-radius: 8px;
    color: #bdccca; background: transparent; font-size: 14px; }
QPushButton#nav:hover { background: #294249; color: white; }
QPushButton#nav:checked { background: #e4edbe; color: #213b32; font-weight: 600; }
QLabel#eyebrow { color: #7b8a77; font-size: 10px; font-weight: 700; }
QLabel#title { font-size: 27px; font-weight: 700; }
QLabel#muted, QLabel#metricCaption { color: #7a8782; font-size: 12px; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; min-height: 28px; max-height: 28px; }
QLabel#metricLabel { color: #697c74; font-size: 13px; }
QLabel#metricValue { font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 24px; font-weight: 600; }
QFrame#card { border: 1px solid #e5e9df; border-radius: 13px; background: #ffffff; }
QFrame#accentCard { border: 1px solid #dfe8bd; border-radius: 13px; background: #e5edc5; }
QPushButton { border: 1px solid #dce2d7; background: white; border-radius: 7px; padding: 0px 12px; }
QPushButton:hover { border-color: #7a9d89; background: #f0f4e9; }
QPushButton:pressed { background: #dfe9d5; }
QPushButton:disabled { color: #b5bfb7; background: #f3f5f0; }
QPushButton#primary { background: #227660; color: white; border: 1px solid #227660; }
QPushButton#primary:hover { background: #195d4c; }
QPushButton#link { color: #227660; border: none; background: transparent; padding: 0px; }
QPushButton:focus, QLineEdit:focus, QDateEdit:focus, QComboBox:focus { border: 1px solid #227660; }
QLabel#live { color: #227660; background: #e5efe2; border-radius: 13px; padding: 6px 12px; }
QLabel#notice { background: #edf0e2; color: #6b795f; border-radius: 7px; padding: 8px 16px; font-size: 12px; }
QLineEdit, QComboBox, QDateEdit { background: white; border: 1px solid #dce2d7; border-radius: 7px; padding: 0px 12px; }
QComboBox::drop-down, QDateEdit::drop-down { border: none; width: 24px; }
QComboBox::down-arrow, QDateEdit::down-arrow { image: none; border: none; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e2ecd7; }
QTableWidget { background: transparent; alternate-background-color: #f7f9f3; border: none; gridline-color: transparent; selection-background-color: #e9f0df; selection-color: #172d35; }
QHeaderView::section { background: transparent; color: #839085; border: none; border-bottom: 1px solid #ecf0e7; padding: 9px 10px; font-size: 12px; text-align: left; }
QTableWidget::item { padding: 8px 10px; border-bottom: 1px solid #f0f2ec; }
QProgressBar { background: #edf1e7; border: none; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: #5e947c; border-radius: 3px; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: #f4f5ef; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 0 0 0 4px; }
QScrollBar::handle:vertical { background: #cbd5c8; min-height: 25px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QCheckBox { spacing: 10px; padding: 6px 0; }
QCheckBox::indicator { width: 18px; height: 18px; }
QToolTip { background: #172f35; color: white; border: none; padding: 8px; }
QMenu { background: white; border: 1px solid #dce2d7; padding: 5px; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: #e5edc5; }
"""


def label(text, name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def button(text, callback, name=None, icon=None):
    w = QPushButton(text)
    if name:
        w.setObjectName(name)
    if icon:
        w.setIcon(symbol_icon(icon,"#ffffff" if name=="primary" else "#227660"))
        w.setIconSize(QSize(18,18))
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.setFixedHeight(28 if name=="link" else CONTROL_HEIGHT)
    w.clicked.connect(callback)
    return w


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setShowGrid(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    t.horizontalHeader().setFixedHeight(36)
    t.verticalHeader().setDefaultSectionSize(40)
    for column in range(1,len(headers)):
        t.horizontalHeader().setSectionResizeMode(column,QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(column,240 if len(headers)==3 and column==2 else (112 if len(headers)==4 and column==3 else 164))
        t.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    t.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return t


class _BackupSignals(QObject):
    finished = Signal(object,str)


class _BackupTask(QRunnable):
    def __init__(self,create_backup):
        super().__init__()
        self.create_backup = create_backup
        self.signals = _BackupSignals()

    @Slot()
    def run(self):
        try:
            output=self.create_backup(reason="manual")
        except Exception as e:
            logging.exception("Manual backup failed")
            self.signals.finished.emit(None,str(e))
        else:
            self.signals.finished.emit(output,"")


class MainWindow(QMainWindow):
    def __init__(self, store, data_dir: Path, demo=False):
        super().__init__()
        self.store = store
        self.data_dir = data_dir
        self.demo = demo
        self.paused = False
        self.quitting = False
        self.failure = False
        self._tray_show_duration = bool(store.get_setting("tray_show_duration", True))
        self._backup_pool = QThreadPool(self)
        self._backup_pool.setMaxThreadCount(1)
        self._backup_worker = None
        self.current_app = "正在识别"
        self._calendar_today = QDate.currentDate()
        self._follow_today = True
        self.tracker = Tracker(store, idle_seconds=int(store.get_setting("idle_seconds", 300)))
        self.setWindowTitle("时光计 · 看见时间的去向" + (" [演示数据]" if demo else ""))
        self.setWindowIcon(make_icon())
        self.resize(1260, 880)
        self.setMinimumSize(1040, 700)
        self.setStyleSheet(STYLE)
        self._build()
        self._tray()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.sample)
        if not demo:
            self.sample()
            if not self.failure:
                self.timer.start()
        # A read-only clock stays active independently of sampling and the page
        # refresh, including when hidden, paused, or viewing another date.
        self.tray_timer = QTimer(self)
        self.tray_timer.setInterval(1000)
        self.tray_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.tray_timer.timeout.connect(self.refresh_tray_duration)
        self.tray_timer.start()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(5000)
        self.refresh_timer.timeout.connect(lambda: self.refresh() if self.isVisible() else None)
        self.refresh_timer.start()
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.navigate(0))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.navigate(1))
        QShortcut(QKeySequence("Ctrl+3"), self, activated=lambda: self.navigate(2))
        QShortcut(QKeySequence("Ctrl+4"), self, activated=lambda: self.navigate(3))
        self.navigate(0)

    def _build(self):
        root = QWidget()
        root.setObjectName("canvas")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(208)
        sb = QVBoxLayout(side)
        sb.setContentsMargins(20,32,20,24)
        sb.setSpacing(8)
        brand = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(make_icon().pixmap(36,36))
        brand.addWidget(icon)
        brand.addWidget(label("时光计", "brand"))
        brand.addStretch()
        sb.addLayout(brand)
        sb.addWidget(label("TIME, WELL NOTICED", "brandSub"))
        sb.addSpacing(68)
        self.nav = QButtonGroup(self)
        for i, title in enumerate(["今日概览", "软件统计", "历史趋势", "设置"]):
            b = NavigationButton(title,i)
            b.clicked.connect(lambda checked=False,n=i:self.navigate(n))
            self.nav.addButton(b, i)
            sb.addWidget(b)
        sb.addStretch()
        sb.addWidget(label("每一段时间\n都有自己的去向。", "sideNote"))
        sb.addSpacing(16)
        sb.addWidget(label("●  本地记录 · 无需登录", "brandSub"))
        sb.addWidget(label("v"+__version__, "brandSub"))
        outer.addWidget(side)
        body = QWidget()
        vb = QVBoxLayout(body)
        vb.setContentsMargins(32,24,32,16)
        vb.setSpacing(GAP)
        top = QHBoxLayout()
        top.setContentsMargins(0,0,GUTTER,0)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        heading.addWidget(label("YOUR DIGITAL DAY", "eyebrow"))
        self.heading = label("今日概览", "title")
        heading.addWidget(self.heading)
        self.subtitle = label("看清时间的去向，也给自己一点留白。", "muted")
        heading.addWidget(self.subtitle)
        top.addLayout(heading)
        top.addStretch()
        self.live = label("●  正在记录", "live")
        self.live.setFixedHeight(32)
        top.addWidget(self.live, 0, Qt.AlignmentFlag.AlignTop)
        vb.addLayout(top)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.setContentsMargins(0,0,GUTTER,0)
        self.previous = button("", lambda: self.change_day(-1), icon="chevron-left")
        self.previous.setFixedWidth(CONTROL_HEIGHT)
        self.previous.setStyleSheet("padding:0;")
        self.previous.setAccessibleName("前一天")
        self.previous.setToolTip("前一天")
        self.day = CalendarDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("yyyy 年 MM 月 dd 日")
        self.day.setMaximumDate(QDate.currentDate())
        self.day.setMinimumDate(QDate(2020,1,1))
        self.day.setFixedSize(208,CONTROL_HEIGHT)
        self.day.setAccessibleName("统计日期")
        self.day.dateChanged.connect(self.date_changed)
        self.next = button("", lambda: self.change_day(1), icon="chevron-right")
        self.next.setFixedWidth(CONTROL_HEIGHT)
        self.next.setStyleSheet("padding:0;")
        self.next.setAccessibleName("后一天")
        self.next.setToolTip("后一天")
        self.today_button = button("回到今天", lambda: self.day.setDate(QDate.currentDate()))
        for w in [self.previous,self.day,self.next,self.today_button]:
            tools.addWidget(w)
        self.settings_toolbar_label=label("记录偏好与本地数据","muted")
        self.settings_toolbar_label.setFixedHeight(CONTROL_HEIGHT)
        tools.addWidget(self.settings_toolbar_label)
        tools.addStretch()
        self.pause_button = button("暂停软件统计", self.toggle_pause, icon="pause")
        self.pause_button.setToolTip("暂停记录前台软件；电脑运行时长仍会记录。重启应用后自动恢复。")
        tools.addWidget(self.pause_button)
        self.export_button = button("导出 CSV", self.export, "primary", icon="export")
        tools.addWidget(self.export_button)
        vb.addLayout(tools)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._overview())
        self.stack.addWidget(self._apps())
        self.stack.addWidget(self._history())
        self.stack.addWidget(self._settings())
        vb.addWidget(self.stack, 1)
        self.footer = label("记录器运行期间自动统计 · 休眠不计入 · 页面每 5 秒刷新 · 时长每秒更新", "muted")
        vb.addWidget(self.footer)
        outer.addWidget(body, 1)
        self.setCentralWidget(root)

    def _overview(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0,0,0,0)
        box.setSpacing(16)
        self.notice = label("", "notice", True)
        box.addWidget(self.notice)
        grid = QGridLayout()
        grid.setSpacing(GAP)
        for column in range(4):
            grid.setColumnStretch(column,1)
        self.awake_card = Metric("电脑运行", "已记录的唤醒时间", True)
        self.active_card = Metric("实际操作", "前台使用 · 排除离开")
        self.idle_card = Metric("离开 / 锁屏", "给生活留一点空隙")
        self.count_card = Metric("使用软件", "这一天的前台应用")
        for column,w in enumerate([self.awake_card,self.active_card,self.idle_card,self.count_card]):
            grid.addWidget(w,0,column)
        time_card = Card()
        time_card.setFixedHeight(224)
        chart_header = QWidget()
        chart_header.setFixedHeight(28)
        chart_title = QHBoxLayout(chart_header)
        chart_title.setContentsMargins(0,0,0,0)
        chart_title.addWidget(label("一天的节奏", "sectionTitle"))
        chart_title.addStretch()
        chart_title.addWidget(label("● 实际操作    ○ 电脑运行", "muted"))
        time_card.box.addWidget(chart_header)
        self.hourly = BarChart(hourly=True)
        time_card.box.addWidget(self.hourly)
        grid.addWidget(time_card,1,0,1,3)
        ratio = Card()
        ratio.setMinimumWidth(160)
        ratio.setFixedHeight(224)
        ratio.box.addWidget(label("时间构成", "sectionTitle"))
        self.ring = RatioRing()
        ratio.box.addWidget(self.ring)
        self.ratio_note = label("", "muted", True)
        self.ratio_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ratio_note.setFixedHeight(20)
        ratio.box.addWidget(self.ratio_note)
        grid.addWidget(ratio,1,3)
        box.addLayout(grid)
        apps = Card()
        row = QHBoxLayout()
        row.addWidget(label("时间花在哪", "sectionTitle"))
        row.addStretch()
        view_all=button("查看全部", lambda: self.navigate(1), "link", icon="arrow-right")
        view_all.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        row.addWidget(view_all)
        apps.box.addLayout(row)
        self.top_table = table(["软件", "使用时长", "占操作时间"])
        self.top_table.verticalHeader().setDefaultSectionSize(36)
        self.top_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        apps.box.addWidget(self.top_table)
        box.addWidget(apps)
        box.addStretch()
        return self._scroll(page)

    def _apps(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0,0,GUTTER,0)
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(GAP)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索软件名称或进程…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(symbol_icon("search","#788783"),QLineEdit.ActionPosition.LeadingPosition)
        self.search.setAccessibleName("搜索软件")
        self.search.setFixedHeight(CONTROL_HEIGHT)
        self.search.textChanged.connect(self.refresh_apps)
        row.addWidget(self.search,1)
        self.app_range = ChevronComboBox()
        self.app_range.setFixedSize(208,CONTROL_HEIGHT)
        self.app_range.addItems(["所选日期", "截至所选日 · 7 天", "截至所选日 · 30 天"])
        self.app_range.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.app_range)
        card.box.addLayout(row)
        self.apps_note = label("", "muted",True)
        card.box.addWidget(self.apps_note)
        self.app_table = table(["软件 / 进程", "前台使用时长", "使用占比"])
        self.app_table.itemSelectionChanged.connect(self.select_app)
        card.box.addWidget(self.app_table,1)
        self.app_detail = label("选择一行查看应用路径。仅统计前台窗口；后台播放不会单独计时。", "muted",True)
        self.app_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.box.addWidget(self.app_detail)
        box.addWidget(card,1)
        return page

    def _history(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0,0,GUTTER,0)
        box.setSpacing(16)
        chart = Card()
        row = QHBoxLayout()
        row.addWidget(label("把视线放远一点", "sectionTitle"))
        row.addStretch()
        self.history_range = ChevronComboBox()
        self.history_range.setFixedSize(208,CONTROL_HEIGHT)
        self.history_range.addItems(["最近 7 天", "最近 30 天"])
        self.history_range.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.history_range)
        chart.box.addLayout(row)
        self.history_note = label("", "muted",True)
        chart.box.addWidget(self.history_note)
        self.daily_chart = BarChart()
        self.daily_chart.setMinimumHeight(220)
        chart.box.addWidget(self.daily_chart)
        box.addWidget(chart)
        card = Card()
        card.box.addWidget(label("每日记录  ·  双击某一天查看详情", "sectionTitle"))
        self.history_table = table(["日期", "电脑运行", "实际操作", "操作占比"])
        self.history_table.cellDoubleClicked.connect(self.open_history_day)
        card.box.addWidget(self.history_table,1)
        box.addWidget(card,1)
        return page

    def _settings(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0,0,0,0)
        box.setSpacing(16)
        card = Card()
        card.box.addWidget(label("让记录自然发生", "sectionTitle"))
        self.startup = QCheckBox("登录 Windows 时启动，并留在托盘")
        self.startup.setChecked(win32.is_autostart() if not self.demo else False)
        self.startup.setEnabled(not self.demo)
        self.startup.toggled.connect(self.set_startup)
        card.box.addWidget(self.startup)
        startup_help=label("开启后，日常使用记录更完整；无需管理员权限。", "muted")
        startup_help.setContentsMargins(28,0,0,0)
        card.box.addWidget(startup_help)
        self.close_tray = QCheckBox("关闭窗口时继续在系统托盘记录")
        self.close_tray.setChecked(self.store.get_setting("close_to_tray", True))
        self.close_tray.toggled.connect(lambda v: self.store.set_setting("close_to_tray",v))
        card.box.addWidget(self.close_tray)
        self.tray_duration_checkbox = QCheckBox("在任务栏左侧显示今日时长")
        self.tray_duration_checkbox.setChecked(self._tray_show_duration)
        self.tray_duration_checkbox.toggled.connect(self.set_tray_duration)
        card.box.addWidget(self.tray_duration_checkbox)
        tray_help = label("时间固定在任务栏最左侧，不随右侧托盘图标变化移动。黑色大字、透明背景；可拖动微调，双击打开主窗口，右键可恢复左侧默认位置。全屏或任务栏隐藏时自动收起。", "muted", True)
        tray_help.setContentsMargins(28,0,0,0)
        card.box.addWidget(tray_help)
        row = QHBoxLayout()
        row.addWidget(label("多久没有键盘或鼠标输入，视为离开"))
        row.addStretch()
        self.idle_combo = ChevronComboBox()
        self.idle_combo.setFixedSize(208,CONTROL_HEIGHT)
        for m in [1,3,5,10,15,30]:
            self.idle_combo.addItem(f"{m} 分钟",m*60)
        self.idle_combo.setCurrentIndex(max(0,self.idle_combo.findData(self.tracker.idle_seconds)))
        self.idle_combo.currentIndexChanged.connect(self.set_idle)
        row.addWidget(self.idle_combo)
        card.box.addLayout(row)
        card.box.addWidget(label("观看视频、阅读时也可能被视为离开，可按习惯调长阈值。", "muted",True))
        box.addWidget(card)
        privacy = Card()
        privacy.box.addWidget(label("数据保护", "sectionTitle"))
        privacy.box.addWidget(label("程序和历史记录分开存放。覆盖更新程序会保留记录；请勿删除下面的数据文件夹。",None,True))
        self.data_label = label(str(self.data_dir), "muted", True)
        self.data_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        privacy.box.addWidget(self.data_label)
        privacy.box.addWidget(label("更新版本前会先备份已有数据，备份失败则停止升级。备份不会自动清理，可自行管理或复制到其他位置。","muted",True))
        self.backup_status = label("尚未备份", "muted", True)
        self.backup_status.setAccessibleName("最近备份状态")
        privacy.box.addWidget(self.backup_status)
        if self.demo:
            privacy.box.addWidget(label("演示模式：备份仅含临时示例数据，退出演示后会随临时目录清理。","notice",True))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.backup_button = button("立即备份",self.create_backup,"primary",icon="export")
        self.backup_button.setToolTip("备份当前已保存的历史记录和设置，不暂停记录。")
        row.addWidget(self.backup_button)
        self.backup_folder_button = button("打开备份文件夹",self.open_backup_folder,icon="folder")
        row.addWidget(self.backup_folder_button)
        row.addWidget(button("打开数据文件夹",lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir))),icon="folder"))
        row.addStretch()
        privacy.box.addLayout(row)
        privacy.box.addWidget(label("仅在本机记录日期、应用名称、程序路径和使用时长。不记录网页地址、窗口标题、键盘内容或屏幕画面，也不上传使用记录。","muted",True))
        box.addWidget(privacy)
        definitions = Card()
        definitions.box.addWidget(label("怎样理解这些数字", "sectionTitle"))
        definitions.box.addWidget(label(
            "电脑运行：记录器运行期间，电脑处于唤醒状态的时间，包含离开和锁屏。\n"
            "实际操作：尚未达到离开阈值、且能够识别前台应用的时间。\n"
            "软件使用：按前台窗口归属，每秒采样一次；软件在后台运行不会累加。\n"
            "暂停软件统计：暂停应用归属统计，电脑运行仍继续记录。\n"
            "休眠、关机、记录器退出期间不会补记；首次启动之前的数据无法还原。",
            None,True))
        self.boot_label = label("", "muted",True)
        definitions.box.addWidget(self.boot_label)
        box.addWidget(definitions)
        box.addStretch()
        return self._scroll(page)

    def _scroll(self, page):
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        s.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        s.setWidget(page)
        return s

    def _tray(self):
        self._tray_icon_state = "default" if self.demo else "recording"
        self._tray_icon_key = None
        self._tray_seconds = None
        self._tray_minutes = None
        self._tray_read_error = False
        self.tray = QSystemTrayIcon(self)
        menu = QMenu()
        self.tray_menu = menu
        self.tray_duration_action = menu.addAction("今日使用 · 正在读取")
        self.tray_duration_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction(symbol_icon("show"),"打开时光计",self.show_window)
        self.pause_action = menu.addAction(symbol_icon("pause"),"暂停软件统计",self.toggle_pause)
        menu.addAction("恢复任务栏最左侧",self.reset_taskbar_position)
        menu.addSeparator()
        menu.addAction(symbol_icon("power"),"退出并停止记录",self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        # A separate tool window can use a normal-width font. Notification icons
        # themselves are square and cannot reserve a wider text region.
        self.taskbar_clock = TaskbarClock()
        self.destroyed.connect(self.taskbar_clock.deleteLater)
        self.taskbar_clock.activated.connect(self.show_window)
        self.taskbar_clock.contextMenuRequested.connect(menu.popup)
        try:
            # The previous offset was relative to the changing right-side tray.
            # Preserve that preference, but start the new left anchor at zero.
            offset = int(self.store.get_setting("taskbar_clock_left_offset",0))
        except (TypeError,ValueError,OverflowError):
            offset = 0
        self.taskbar_clock.set_offset(offset)
        self.taskbar_clock.offsetChanged.connect(self.save_taskbar_position)
        self.refresh_tray_duration()
        self.taskbar_clock.set_enabled(self._tray_show_duration and not self.demo)
        if not self.demo and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    @property
    def tray_duration_minutes(self) -> int | None:
        return self._tray_minutes

    @property
    def tray_duration_text(self) -> str:
        return "不可读取" if self._tray_seconds is None else duration_text(self._tray_seconds)

    @property
    def tray_duration_state(self) -> str:
        return self._tray_icon_state

    def refresh_tray_duration(self):
        if self.quitting:
            return
        try:
            today = date.today()
            seconds = float(self.store.get_summary(today,today)["awake"])
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError("Today's awake duration is invalid")
            self._tray_seconds = seconds
            self._tray_minutes = whole_minutes(seconds)
            self._tray_read_error = False
        except Exception:
            # A persistent failure must remain visible without logging every
            # second or presenting yesterday's value as today's duration.
            if not self._tray_read_error:
                logging.exception("Could not read today's tray duration")
            self._tray_read_error = True
            self._tray_seconds = None
            self._tray_minutes = None
        self._render_tray_duration()
        self.taskbar_clock.refresh_placement()

    def _render_tray_duration(self):
        status = self.tracker.status
        status_text = {"active":"正在记录", "idle":"已离开", "locked":"已锁屏",
                       "paused":"软件统计已暂停", "unknown":"正在记录 · 未识别"}.get(status,"正在记录")
        if self.failure:
            status_text = "记录出错"
        elif self.demo:
            status_text = "演示数据 · 不记录本机使用"
        elif self.paused:
            status_text = "软件统计已暂停 · 电脑运行仍计时"
        state = ("error" if self.failure or self._tray_read_error else "paused" if self.paused else
                 "default" if self.demo else "idle" if status in ("idle","locked") else "recording")
        key = state
        if key != self._tray_icon_key:
            self.tray.setIcon(application_icon(state))
            self._tray_icon_key = key
        self._tray_icon_state = state
        today_text = "今日使用 " + self.tray_duration_text
        self.tray_duration_action.setText(("示例数据 · " if self.demo else "") + today_text)
        detail = "今日统计不可读取；请检查 app.log 或重启应用。" if self._tray_read_error else "电脑运行时长，含离开、锁屏和暂停软件统计。"
        tooltip = "时光计 · " + today_text + "\n" + status_text + "\n" + detail
        self.tray.setToolTip(tooltip)
        self.taskbar_clock.set_duration(self._tray_minutes,tooltip)
        self.setWindowTitle(today_text + " · 时光计" + (" [演示数据]" if self.demo else ""))

    def set_tray_duration(self,enabled):
        try:
            self.store.set_setting("tray_show_duration",bool(enabled))
        except Exception as e:
            with QSignalBlocker(self.tray_duration_checkbox):
                self.tray_duration_checkbox.setChecked(self._tray_show_duration)
            QMessageBox.warning(self,"设置未保存",f"无法保存托盘显示设置：{e}")
            return
        self._tray_show_duration = bool(enabled)
        with QSignalBlocker(self.tray_duration_checkbox):
            self.tray_duration_checkbox.setChecked(self._tray_show_duration)
        self._render_tray_duration()
        self.taskbar_clock.set_enabled(self._tray_show_duration and not self.demo)

    def save_taskbar_position(self,offset):
        try:
            self.store.set_setting("taskbar_clock_left_offset",int(offset))
        except Exception as e:
            logging.exception("Could not save taskbar clock position")
            self.footer.setText(f"时间条已移动，但位置未保存：{e}")

    def reset_taskbar_position(self):
        self.taskbar_clock.set_offset(0)
        self.save_taskbar_position(0)
        self.taskbar_clock.refresh_placement()

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        self.nav.button(index).setChecked(True)
        titles = ["今日概览","软件统计","历史趋势","设置"]
        subtitles = ["看清时间的去向，也给自己一点留白。","了解每一个应用，花去了多少时间。",
                     "在更长的时间里，发现自己的使用习惯。","按照自己的节奏，安排记录方式。"]
        self.heading.setText(titles[index])
        self.subtitle.setText(subtitles[index])
        for w in [self.previous,self.next,self.day,self.today_button,self.export_button]:
            w.setVisible(index!=3)
        self.settings_toolbar_label.setVisible(index==3)
        self.refresh()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"daily_chart"):
            self.daily_chart.setMinimumHeight(152 if self.height()<800 else 220)

    def selected_date(self):
        return self.day.date().toPython()

    def date_changed(self,*_):
        self._follow_today = self.day.date() == QDate.currentDate()
        self.refresh()

    def change_day(self, delta):
        self.day.setDate(self.day.date().addDays(delta))

    def selected_range(self):
        end = self.selected_date()
        index = self.stack.currentIndex()
        days = [1,7,30][self.app_range.currentIndex()] if index==1 else (
            [7,30][self.history_range.currentIndex()] if index==2 else 1)
        return end-timedelta(days=days-1), end

    def sample(self):
        if self.failure or self.demo:
            return
        try:
            self.tracker.tick(Sample(**win32.sample_system()), paused=self.paused)
            if win32.consume_show_request():
                self.show_window()
            self.update_status()
        except Exception:
            logging.exception("Tracking failed")
            self.failure = True
            self.timer.stop()
            self.live.setText("●  记录出错")
            self.refresh_tray_duration()
            self.footer.setText("记录已停止：请检查磁盘空间，并重启应用。详情见 app.log。")
            self.tray.showMessage("时光计：记录已停止", "数据写入或系统采样失败，请打开应用检查。")

    def update_status(self):
        status = self.tracker.status
        text = {"active":"正在记录", "idle":"已离开", "locked":"已锁屏", "paused":"软件统计已暂停", "unknown":"正在记录 · 未识别"}.get(status,"正在记录")
        self.live.setText("●  " + ("演示数据" if self.demo else text))
        self._render_tray_duration()

    def refresh(self, *_):
        if not hasattr(self,"boot_label"):
            return
        try:
            today = QDate.currentDate()
            with QSignalBlocker(self.day):
                self.day.setMaximumDate(today)
                if self._follow_today and today != self._calendar_today:
                    self.day.setDate(today)
            self._calendar_today = today
            self.next.setEnabled(self.selected_date()<date.today())
            d = self.selected_date()
            if self.stack.currentIndex()==0:
                self.heading.setText("今日概览" if d==date.today() else "每日概览")
            summary = self.store.get_summary(d,d)
            apps = self.store.get_apps(d,d)
            for card,seconds in [(self.awake_card,summary["awake"]),(self.active_card,summary["active"]),
                                 (self.idle_card,summary["idle"]+summary["locked"])]:
                value=duration(seconds)
                if seconds>=3600:
                    value=value.replace(" 小时 ","小时 ").replace(" 分","分")
                card.value.setText(value)
            self.count_card.value.setText(f"{len(apps):02d} 个")
            self.hourly.set_data(self.store.get_hourly(d))
            self.ring.ratio = summary["active"] / summary["awake"] if summary["awake"] else 0
            self.ring.update()
            other = summary["paused"] + summary["unknown"]
            self.ratio_note.setText("其他时长 " + duration(other,compact=True) if other else "投入与休息，都是时间")
            self.ratio_note.setToolTip("暂停软件统计或未识别应用的时间："+duration(other) if other else "实际操作占电脑运行时长的比例")
            self.fill_apps(self.top_table,apps[:5],summary["active"])
            first = self.store.first_recorded
            if self.demo:
                note = "演示模式 · 以下为示例数据，不代表本机实际使用记录。"
            elif not summary["awake"]:
                note = "当天尚无记录。打开时光计后才会开始积累；可在设置中开启登录启动。"
            else:
                started = datetime.fromtimestamp(first).strftime("%m 月 %d 日 %H:%M") if first else "现在"
                note = f"从 {started} 开始记录 · 仅统计记录器运行期间，休眠和退出期间不计入。"
            self.notice.setText(note)
            self.refresh_apps()
            end = self.selected_date()
            start = end-timedelta(days=[7,30][self.history_range.currentIndex()]-1)
            rows = self.store.get_daily(start,end)
            self.daily_chart.set_data(rows)
            total = sum(r["active"] for r in rows)
            covered = sum(r["awake"]>0 for r in rows)
            self.history_note.setText(f"{start:%m/%d} — {end:%m/%d}   ·   {covered} 天有记录   ·   实际操作共 {duration(total)}   ·   浅色：运行 / 深色：操作")
            self.history_table.setRowCount(len(rows))
            for i,r in enumerate(reversed(rows)):
                values=[r["date"],duration(r["awake"]) if r["awake"] else "暂无记录",
                        duration(r["active"]),f"{r['active']/r['awake']:.0%}" if r["awake"] else "—"]
                for c,v in enumerate(values):
                    item=QTableWidgetItem(v)
                    if c:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                    self.history_table.setItem(i,c,item)
            self.boot_label.setText("系统本轮启动已过去 " + duration(win32.boot_elapsed()) + "（含休眠；仅供参考，不作为每日统计）。")
            if self.stack.currentIndex()==3:
                self.refresh_backup_status()
            if not self.failure:
                self.update_status()
        except Exception:
            logging.exception("Dashboard refresh failed")
            self.footer.setText("读取统计失败，请检查 app.log 或重启应用。")

    def fill_apps(self,t,rows,total):
        t.setRowCount(max(1,len(rows)))
        if t is self.top_table:
            t.setFixedHeight(36+max(1,len(rows))*36+2)
        if not rows:
            for c,v in enumerate(["暂无前台使用记录","—","—"]):
                t.setItem(0,c,QTableWidgetItem(v))
                t.removeCellWidget(0,c)
            return
        for i,r in enumerate(rows):
            name = QTableWidgetItem(f"{i+1:02d}   {r['name']}")
            name.setData(Qt.ItemDataRole.UserRole,r["path"])
            name.setToolTip(r["path"] or r["name"])
            t.setItem(i,0,name)
            time_item=QTableWidgetItem(duration(r["seconds"]))
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
            t.setItem(i,1,time_item)
            share = r["seconds"]/total if total else 0
            w = QWidget()
            hb = QHBoxLayout(w)
            hb.setContentsMargins(16,0,0,0)
            hb.setSpacing(12)
            bar = QProgressBar()
            bar.setRange(0,1000)
            bar.setValue(round(share*1000))
            bar.setTextVisible(False)
            hb.addWidget(bar,1)
            pct = label(f"{share:.0%}","muted")
            pct.setFixedWidth(40)
            pct.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
            hb.addWidget(pct)
            t.setCellWidget(i,2,w)

    def refresh_apps(self,*_):
        if not hasattr(self,"app_table"):
            return
        end = self.selected_date()
        start = end-timedelta(days=[1,7,30][self.app_range.currentIndex()]-1)
        all_rows = self.store.get_apps(start,end)
        q = self.search.text().strip().casefold()
        rows = [r for r in all_rows if q in (r["name"]+r["path"]).casefold()]
        total = sum(r["seconds"] for r in all_rows)
        selected = self.app_table.item(self.app_table.currentRow(),0)
        selected_path = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        with QSignalBlocker(self.app_table):
            self.fill_apps(self.app_table,rows,total)
            selected_index = next((i for i,r in enumerate(rows) if selected_path and r["path"]==selected_path),None)
            if selected_index is not None:
                self.app_table.selectRow(selected_index)
                self.app_detail.setText(rows[selected_index]["path"])
            else:
                self.app_table.clearSelection()
                self.app_table.setCurrentCell(-1,-1)
                self.app_detail.setText("选择一行查看应用路径。仅统计前台窗口；后台播放不会单独计时。")
        self.apps_note.setText(f"{start:%Y/%m/%d} — {end:%Y/%m/%d}   ·   {len(rows)} 个软件   ·   合计 {duration(total)}")
        if q and not rows:
            self.app_table.item(0,0).setText("没有匹配的软件")

    def select_app(self):
        row = self.app_table.currentRow()
        item = self.app_table.item(row,0)
        if item:
            self.app_detail.setText(item.data(Qt.ItemDataRole.UserRole) or "暂无应用路径")

    def open_history_day(self,row,column):
        item = self.history_table.item(row,0)
        if item:
            self.day.setDate(QDate.fromString(item.text(),"yyyy-MM-dd"))
            self.navigate(0)

    def toggle_pause(self):
        self.sample()
        self.paused = not self.paused
        # Prime the new mode at this boundary; next interval follows it.
        self.sample()
        text = "继续软件统计" if self.paused else "暂停软件统计"
        self.pause_button.setText(text)
        self.pause_action.setText(text)
        icon=symbol_icon("play" if self.paused else "pause")
        self.pause_button.setIcon(icon)
        self.pause_action.setIcon(icon)
        self.refresh()

    def set_startup(self,enabled):
        try:
            win32.set_autostart(enabled)
        except OSError as e:
            with QSignalBlocker(self.startup):
                self.startup.setChecked(not enabled)
            QMessageBox.warning(self,"设置未保存",f"无法修改登录启动：{e}")

    def set_idle(self):
        self.sample()
        value=self.idle_combo.currentData()
        self.tracker.idle_seconds=value
        self.store.set_setting("idle_seconds",value)

    def refresh_backup_status(self):
        try:
            latest=self.store.latest_backup()
            if latest is None:
                self.backup_status.setText("尚未备份 · 可随时创建一份完整备份")
                self.backup_status.setToolTip("")
            else:
                timestamp=datetime.fromtimestamp(latest.stat().st_mtime)
                self.backup_status.setText(f"最近备份：{timestamp:%Y/%m/%d %H:%M:%S}")
                self.backup_status.setToolTip(str(latest))
        except Exception as e:
            self.backup_status.setText("暂时无法读取备份状态，请检查备份文件夹。")
            self.backup_status.setToolTip(str(e))

    def create_backup(self):
        if self.quitting or self._backup_worker is not None:
            return
        self.backup_button.setEnabled(False)
        self.backup_button.setText("正在备份…")
        try:
            # Save this boundary before the worker opens its read connection.
            # The UI event loop and sampling timers stay active during backup.
            self.sample()
            worker=_BackupTask(self.store.create_backup)
            worker.signals.finished.connect(self._backup_finished)
            self._backup_worker=worker
            self._backup_pool.start(worker)
        except Exception as e:
            logging.exception("Could not start manual backup")
            self._backup_finished(None,str(e))

    @Slot(object,str)
    def _backup_finished(self,output,error):
        self._backup_worker=None
        if self.quitting:
            return
        self.backup_button.setEnabled(True)
        self.backup_button.setText("立即备份")
        if output is None:
            QMessageBox.warning(self,"备份未完成",f"本次备份未完成。请检查磁盘空间和文件夹权限后重试。\n\n{error or '没有生成备份文件。'}")
        else:
            self.refresh_backup_status()
            detail=("这是演示数据备份，位于临时目录；退出演示后会被清理。" if self.demo else
                    "已备份当前保存的历史记录和设置。可将此文件复制到其他位置妥善保存。")
            QMessageBox.information(self,"演示备份已创建" if self.demo else "备份已创建",f"{detail}\n\n{output}")

    def open_backup_folder(self):
        try:
            directory=self.store.backup_directory
            directory.mkdir(parents=True,exist_ok=True)
            opened=QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
            if not opened:
                QMessageBox.warning(self,"无法打开文件夹",f"系统未能打开备份文件夹，可复制以下路径手动打开：\n\n{directory}")
        except OSError as e:
            QMessageBox.warning(self,"无法打开文件夹",f"无法访问备份文件夹，请检查文件夹权限。\n\n{e}")

    def export(self):
        start,end=self.selected_range()
        output,_=QFileDialog.getSaveFileName(self,"导出当前日期范围",str(Path.home()/"Desktop"/f"时光计_{start}_{end}.csv"),"CSV 文件 (*.csv)")
        if not output:
            return
        try:
            self.store.export_csv(output,start,end)
            QMessageBox.information(self,"导出完成",f"已保存 {start} 至 {end} 的统计：\n{output}")
        except Exception as e:
            QMessageBox.warning(self,"导出失败",str(e))

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def closeEvent(self,event):
        if not self.quitting and not self.demo and self.store.get_setting("close_to_tray",True) and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self.store.get_setting("tray_explained",False):
                self.tray.showMessage("时光计仍在记录", "窗口已收起到系统托盘。右键图标可暂停或完全退出。")
                self.store.set_setting("tray_explained",True)
        else:
            self.quit_app()
            event.accept()

    def quit_app(self):
        if self.quitting:
            return
        self.quitting=True
        self.sample()
        self.timer.stop()
        self.refresh_timer.stop()
        self.tray_timer.stop()
        self.taskbar_clock.stop()
        self.tray.hide()
        # Finish any in-progress file safely before main closes the Store or
        # removes a demo directory. Queued results see quitting and stay quiet.
        self._backup_pool.waitForDone()
        QApplication.instance().quit()
