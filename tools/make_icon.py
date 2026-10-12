"""Export and verify the shared Shiguang vector icon system.

Run with the project's virtualenv: .venv/Scripts/python.exe tools/make_icon.py
Additional files under assets/icons (for example contact sheets) are preserved
and included in the ZIP and manifest on every run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from timelight.icons import PALETTE, SYMBOLS, brand_svg, svg_pixmap, symbol_svg


ICON_ROOT = ROOT / "assets" / "icons"
ARCHIVE_PATH = ROOT / "release" / "时光计-图标资源包.zip"
SYMBOL_SIZES = (24, 48)
APP_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256, 512)
APP_ICO_SIZES = APP_SIZES[:-1]
TRAY_SIZES = (16, 20, 24, 32, 48)
VARIANTS = ("green", "ink", "light")
TRAY_STATES = {
    "recording": "正在记录",
    "paused": "已暂停软件统计",
    "idle": "离开电脑",
    "error": "记录异常",
}


def write_svg(path: Path, svg: str) -> None:
    """Reject malformed XML and SVG that the actual Qt renderer cannot load."""
    root = ET.fromstring(svg)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError(f"Not an SVG document: {path}")
    if not QSvgRenderer(QByteArray(svg.encode("utf-8"))).isValid():
        raise ValueError(f"Qt cannot render SVG: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg + "\n", encoding="utf-8")


def verify_png(data: bytes, size: int, label: str) -> None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Invalid PNG signature: {label}")
    if len(data) < 33 or data[12:16] != b"IHDR":
        raise ValueError(f"Missing PNG IHDR: {label}")
    width, height = struct.unpack_from(">II", data, 16)
    if (width, height) != (size, size):
        raise ValueError(f"Incorrect PNG dimensions {width}x{height}: {label}")
    image = QImage.fromData(data, "PNG")
    if image.isNull() or image.width() != size or image.height() != size:
        raise ValueError(f"Qt cannot decode PNG at its expected size: {label}")
    if not image.hasAlphaChannel():
        raise ValueError(f"PNG lacks transparency: {label}")
    alphas = {image.pixelColor(x, y).alpha() for y in range(size) for x in range(size)}
    if 0 not in alphas or max(alphas) == 0:
        raise ValueError(f"PNG is empty or has no transparent pixels: {label}")
    if size >= 24 and 255 not in alphas:
        raise ValueError(f"PNG has no solid artwork: {label}")


def write_png(path: Path, svg: str, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = svg_pixmap(svg, size)
    if not pixmap.save(str(path), "PNG"):
        raise OSError(f"Unable to save PNG: {path}")
    verify_png(path.read_bytes(), size, str(path))


def make_ico(frames: list[tuple[int, bytes]]) -> bytes:
    """Write an actual ICO directory containing distinct PNG-encoded frames."""
    header = struct.pack("<HHH", 0, 1, len(frames))
    directory = bytearray()
    payload = bytearray()
    offset = 6 + 16 * len(frames)
    for size, png in frames:
        if not 1 <= size <= 256:
            raise ValueError(f"ICO frame size outside 1..256: {size}")
        verify_png(png, size, f"ICO {size} px frame")
        dimension = 0 if size == 256 else size
        directory.extend(struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(png), offset))
        payload.extend(png)
        offset += len(png)
    return header + directory + payload


def verify_ico(data: bytes, sizes: tuple[int, ...], label: str) -> None:
    if len(data) < 6:
        raise ValueError(f"Truncated ICO: {label}")
    reserved, kind, count = struct.unpack_from("<HHH", data)
    if (reserved, kind, count) != (0, 1, len(sizes)):
        raise ValueError(f"Incorrect ICO header/frame count: {label}")
    expected_offset = 6 + 16 * count
    for index, expected_size in enumerate(sizes):
        w, h, colors, reserved, planes, bpp, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * index)
        width, height = w or 256, h or 256
        if (width, height, colors, reserved, planes, bpp) != (expected_size, expected_size, 0, 0, 1, 32):
            raise ValueError(f"Invalid ICO directory entry {index}: {label}")
        if offset != expected_offset or offset + length > len(data):
            raise ValueError(f"Invalid ICO frame bounds: {label}")
        verify_png(data[offset:offset + length], expected_size, f"{label}, frame {index}")
        expected_offset += length
    if expected_offset != len(data):
        raise ValueError(f"Unexpected trailing ICO bytes: {label}")


def write_ico(path: Path, frames: list[tuple[int, bytes]]) -> None:
    data = make_ico(frames)
    verify_ico(data, tuple(size for size, _ in frames), str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


README = """# 时光计 · 图标资源包

一套与 Windows 桌面应用共用源文件的原创矢量图标。时间环与光点构成应用标志，功能图标采用统一圆头、圆角线条。

## 目录与用法

- `symbols/green/`、`symbols/ink/`、`symbols/light/`：28 枚功能图标的三种配色 SVG；各目录下 `png-24/`、`png-48/` 提供透明 PNG。
- `app/app.svg`、`app/app-尺寸.png`：应用标志；`app/app.ico` 为 Windows 多尺寸图标。
- `tray/`：`recording`（记录）、`paused`（暂停）、`idle`（离开）、`error`（异常）的 SVG、透明 PNG 和多尺寸 ICO。
- `manifest.json`：图标名称、中文含义、尺寸规格、文件清单和 SHA-256。额外放入本目录的预览板会一并打包。

## 设计规范

功能图标使用 **24 × 24** 的绘制网格、**1.8 px** 描边、圆形端点和圆角连接，保持统一视觉重量。建议在界面中显示为 20–24 个逻辑像素；使用 SVG 或按系统缩放选择 PNG，避免将小位图放大。图标按钮应保留文字标签或工具提示。

| 配色 | 色值 | 建议用途 |
| --- | --- | --- |
| green | #227660 | 主操作、当前状态 |
| ink | #172d35 | 浅色背景上的常规功能 |
| light | #e5efbf | 深绿色或其他深色背景 |

应用标志使用深绿色渐变和浅黄绿色光点。托盘状态同时通过图形及配色区分：时钟、双竖线、月亮、感叹号。所有 PNG 背景透明；标志自身保留圆角底板。功能 SVG 24 px 网格下的描边为 1.8 px，标志 SVG 的独立画布为 128 × 128。

## 实际像素尺寸

- 功能 PNG：24 × 24、48 × 48。
- 应用 PNG：16、20、24、32、40、48、64、128、256、512 px，均为正方形。
- 应用 ICO：16、20、24、32、40、48、64、128、256 px 共 **9 帧**，每一帧都包含对应实际尺寸的 PNG 图像。
- 各状态托盘 PNG：16、20、24、32、48 px；各状态 ICO 同样包含这 **5 帧**。
- 512 px 应用 PNG 用于展示；Windows ICO 不包含 512 px 帧。

源文件：`timelight/icons.py`。在项目根目录运行 `.venv\\Scripts\\python.exe tools\\make_icon.py` 可重新导出并打包；添加 `--no-zip` 仅导出资源。导出器会检查每个 SVG 的可渲染性、每个 PNG 的尺寸与透明度，并验证所有 ICO 目录条目及内嵌帧。
"""


def build_manifest(generated: list[Path]) -> dict:
    files = []
    for path in sorted(ICON_ROOT.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        data = path.read_bytes()
        files.append({
            "path": path.relative_to(ICON_ROOT).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    counts = {suffix[1:]: sum(path.suffix == suffix for path in generated) for suffix in (".svg", ".png", ".ico")}
    return {
        "schema_version": 1,
        "name": "时光计图标资源包",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "timelight/icons.py",
        "source_sha256": hashlib.sha256((ROOT / "timelight" / "icons.py").read_bytes()).hexdigest(),
        "symbol_grid": [24, 24],
        "symbol_stroke_width": 1.8,
        "symbol_linecap": "round",
        "symbol_linejoin": "round",
        "palette": {variant: PALETTE[variant] for variant in VARIANTS},
        "symbols": [{"name": name, "label": label} for name, (label, _) in SYMBOLS.items()],
        "symbol_png_sizes": SYMBOL_SIZES,
        "app_svg_grid": [128, 128],
        "app_png_sizes": APP_SIZES,
        "app_ico_sizes": APP_ICO_SIZES,
        "tray_states": TRAY_STATES,
        "tray_png_sizes": TRAY_SIZES,
        "tray_ico_sizes": TRAY_SIZES,
        "png_background": "transparent",
        "ico_encoding": "ICONDIR with PNG-encoded 32-bit RGBA frames",
        "validation": {"result": "passed", "generated_assets_checked": counts, "invalid_svg_count": 0},
        "inventory_note": "All files beneath assets/icons except manifest.json itself; includes any existing contact sheets.",
        "files": files,
    }


def export_icons(*, archive: bool = True) -> dict:
    app = QApplication.instance() or QApplication([])
    generated = []
    for name in SYMBOLS:
        for variant in VARIANTS:
            svg = symbol_svg(name, PALETTE[variant])
            folder = ICON_ROOT / "symbols" / variant
            path = folder / f"{name}.svg"
            write_svg(path, svg)
            generated.append(path)
            for size in SYMBOL_SIZES:
                path = folder / f"png-{size}" / f"{name}.png"
                write_png(path, svg, size)
                generated.append(path)

    logo = brand_svg()
    folder = ICON_ROOT / "app"
    path = folder / "app.svg"
    write_svg(path, logo)
    generated.append(path)
    for size in APP_SIZES:
        path = folder / f"app-{size}.png"
        write_png(path, logo, size)
        generated.append(path)
    frames = [(size, (folder / f"app-{size}.png").read_bytes()) for size in APP_ICO_SIZES]
    path = folder / "app.ico"
    write_ico(path, frames)
    generated.append(path)
    # The executable build consumes this canonical copy outside the resource ZIP.
    (ROOT / "assets" / "app.ico").write_bytes(path.read_bytes())

    for state in TRAY_STATES:
        svg = brand_svg(state)
        folder = ICON_ROOT / "tray"
        path = folder / f"{state}.svg"
        write_svg(path, svg)
        generated.append(path)
        for size in TRAY_SIZES:
            path = folder / f"{state}-{size}.png"
            write_png(path, svg, size)
            generated.append(path)
        frames = [(size, (folder / f"{state}-{size}.png").read_bytes()) for size in TRAY_SIZES]
        path = folder / f"{state}.ico"
        write_ico(path, frames)
        generated.append(path)

    (ICON_ROOT / "README.md").write_text(README, encoding="utf-8")
    manifest = build_manifest(generated)
    (ICON_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if archive:
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ARCHIVE_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(ICON_ROOT.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(ICON_ROOT.parent).as_posix())
        with zipfile.ZipFile(ARCHIVE_PATH) as bundle:
            invalid = bundle.testzip()
            if invalid:
                raise ValueError(f"ZIP integrity failure: {invalid}")
    # Keep QApplication alive until all QPixmap and SVG work has finished.
    app.processEvents()
    return {
        "symbols": len(SYMBOLS),
        "validated": manifest["validation"]["generated_assets_checked"],
        "invalid_svg_count": 0,
        "asset_directory": str(ICON_ROOT),
        "archive": str(ARCHIVE_PATH) if archive else None,
        "archive_files": len(manifest["files"]) + 1 if archive else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-zip", action="store_true", help="Export and verify assets without rebuilding the ZIP")
    options = parser.parse_args()
    print(json.dumps(export_icons(archive=not options.no_zip), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
