"""Original Shiguang vector icon system; shared by the UI and asset exporter."""
from __future__ import annotations

from functools import lru_cache
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PALETTE = {"green":"#227660", "ink":"#172d35", "light":"#e5efbf", "muted":"#788783"}

# 24 px drawing grid; 1.8 px strokes, rounded joins, generous open counters.
SYMBOLS = {
    "overview": ("今日概览", '<circle cx="12" cy="12" r="8.5"/><path d="M12 6.5V12l4 2.5"/>'),
    "apps": ("软件统计", '<rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1.5"/><rect x="14" y="3.5" width="6.5" height="6.5" rx="1.5"/><rect x="3.5" y="14" width="6.5" height="6.5" rx="1.5"/><rect x="14" y="14" width="6.5" height="6.5" rx="1.5"/>'),
    "history": ("历史趋势", '<path d="M3.5 20.5h17M6 16.5v-5M12 16.5v-12M18 16.5v-8"/>'),
    "settings": ("偏好设置", '<path d="M3.5 6h3m5 0h9M3.5 12h10m5 0h2M3.5 18h3m5 0h9"/><circle cx="9" cy="6" r="2.5"/><circle cx="16" cy="12" r="2.5"/><circle cx="9" cy="18" r="2.5"/>'),
    "computer": ("电脑运行", '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M12 16.5v4m-4 0h8"/>'),
    "activity": ("实际操作", '<path d="m5 3.5 14 9-6.5 1.2L9 20.5Z"/>'),
    "idle": ("离开电脑", '<path d="M19.8 15.4A8.5 8.5 0 0 1 8.6 4.2a8.5 8.5 0 1 0 11.2 11.2Z"/>'),
    "lock": ("锁屏状态", '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5M12 14.5v2"/>'),
    "calendar": ("选择日期", '<rect x="3.5" y="5.5" width="17" height="15" rx="2"/><path d="M7.5 3v5m9-5v5m-13 3h17m-12 4h2m3 0h2"/>'),
    "search": ("搜索软件", '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/>'),
    "export": ("导出记录", '<path d="M12 3.5v11m-4-4 4 4 4-4M4 15v4a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 19v-4"/>'),
    "folder": ("数据目录", '<path d="M3 8V5.5A1.5 1.5 0 0 1 4.5 4h5l2 3h8A1.5 1.5 0 0 1 21 8.5v10a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5Z"/><path d="M3 10h18"/>'),
    "pause": ("暂停统计", '<rect x="5.5" y="4" width="4" height="16" rx="1"/><rect x="14.5" y="4" width="4" height="16" rx="1"/>'),
    "play": ("继续统计", '<path d="m7 4 13 8-13 8Z"/>'),
    "chevron-left": ("前一天", '<path d="m14.5 5-7 7 7 7"/>'),
    "chevron-right": ("后一天", '<path d="m9.5 5 7 7-7 7"/>'),
    "chevron-down": ("展开选项", '<path d="m6 9 6 6 6-6"/>'),
    "arrow-right": ("查看全部", '<path d="M3.5 12h17m-6-6 6 6-6 6"/>'),
    "refresh": ("回到今天", '<path d="M20 10a8 8 0 0 0-13.7-4L3.5 8.5m0-5v5h5M4 14a8 8 0 0 0 13.7 4l2.8-2.5m0 5v-5h-5"/>'),
    "show": ("打开窗口", '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18m-13.5-3h.1m3.5 0h.1"/>'),
    "power": ("退出记录", '<path d="M12 3v8m-5.5-6a8.5 8.5 0 1 0 11 0"/>'),
    "startup": ("登录启动", '<path d="M6 8.5H4.5A1.5 1.5 0 0 0 3 10v9A1.5 1.5 0 0 0 4.5 20.5h15A1.5 1.5 0 0 0 21 19v-9a1.5 1.5 0 0 0-1.5-1.5H18M12 15V3.5m-4 4 4-4 4 4"/>'),
    "check": ("已完成", '<path d="m4.5 12.5 5 5 10-11"/>'),
    "info": ("统计说明", '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v6m0-10v.1"/>'),
    "warning": ("记录异常", '<path d="m10.7 4.5-8 14A1.3 1.3 0 0 0 3.8 20.5h16.4a1.3 1.3 0 0 0 1.1-2l-8-14a1.5 1.5 0 0 0-2.6 0ZM12 9v4.5m0 3.5v.1"/>'),
    "privacy": ("本地隐私", '<path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6Z"/><path d="m8.5 11.5 2.5 2.5 4.5-5"/>'),
    "close": ("关闭窗口", '<path d="m5 5 14 14M19 5 5 19"/>'),
    "record": ("正在记录", '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>'),
}


def symbol_svg(name: str, color: str = PALETTE["green"]) -> str:
    content = SYMBOLS[name][1]
    color = QColor(color).name()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" color="{color}" stroke-width="1.8" stroke-linecap="round" '
            f'stroke-linejoin="round">{content}</svg>')


def brand_svg(state: str = "default") -> str:
    """Clock ring and light point. State glyphs replace the clock, never tiny badges."""
    if state not in ("default", "recording", "paused", "idle", "error"):
        raise ValueError(f"Unknown icon state: {state}")
    if state in ("default", "recording"):
        mark = ('<path d="M82 33A36 36 0 1 0 100 65"/>'
                '<path d="M64 43v22l17 11"/>'
                '<circle cx="98" cy="39" r="5.5" fill="#e5efbf" stroke="none"/>')
        highlight, shadow, foreground = "#287661", "#153e38", "#e5efbf"
    elif state == "paused":
        mark = '<path d="M51 42v44M77 42v44" stroke-width="12"/>'
        highlight, shadow, foreground = "#886e3b", "#53482f", "#f5dea1"
    elif state == "idle":
        mark = '<path d="M96 77A34 34 0 0 1 51 32a34 34 0 1 0 45 45Z"/>'
        highlight, shadow, foreground = "#4e747a", "#284950", "#d6eeee"
    else:
        mark = '<path d="M64 37v32" stroke-width="11"/><circle cx="64" cy="88" r="6" fill="#ffe4d8" stroke="none"/>'
        highlight, shadow, foreground = "#a55c4f", "#6b3638", "#ffe4d8"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
<defs><linearGradient id="surface" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{highlight}"/><stop offset="1" stop-color="{shadow}"/></linearGradient></defs>
<rect x="4" y="4" width="120" height="120" rx="31" fill="url(#surface)"/>
<g fill="none" stroke="{foreground}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">{mark}</g>
</svg>'''


@lru_cache(maxsize=128)
def _renderer(svg: str) -> QSvgRenderer:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("Invalid SVG icon")
    return renderer


def paint_symbol(painter: QPainter, name: str, rect: QRectF, color: str = PALETTE["green"]) -> None:
    _renderer(symbol_svg(name,color)).render(painter,rect)


def svg_pixmap(svg: str, size: int) -> QPixmap:
    pix = QPixmap(size,size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _renderer(svg).render(painter,QRectF(0,0,size,size))
    painter.end()
    return pix


@lru_cache(maxsize=96)
def symbol_icon(name: str, color: str = PALETTE["green"], size: int = 20) -> QIcon:
    icon = QIcon()
    for resolution in sorted({size, size*2, size*3}):
        icon.addPixmap(svg_pixmap(symbol_svg(name,color),resolution))
    return icon


@lru_cache(maxsize=5)
def application_icon(state: str = "default") -> QIcon:
    icon = QIcon()
    for size in (16,20,24,32,40,48,64,128,256):
        icon.addPixmap(svg_pixmap(brand_svg(state),size))
    return icon
