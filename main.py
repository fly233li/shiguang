"""Run the local Windows app; --demo never accesses the real usage database."""
from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QTimer, QLocale, QLibraryInfo, QTranslator, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from timelight import win32, __version__
from timelight.storage import Store
from timelight.ui import MainWindow


def main():
    parser = argparse.ArgumentParser(description="时光计 · Windows 本地使用时长记录")
    parser.add_argument("--background", action="store_true", help="启动到系统托盘")
    parser.add_argument("--demo", action="store_true", help="使用独立临时演示数据，不记录本机使用")
    parser.add_argument("--data-dir", type=Path, help="使用指定数据目录（用于测试/便携数据）")
    parser.add_argument("--quit-after", type=int, help="测试用：指定毫秒后退出")
    parser.add_argument("--screenshot", type=Path, help="测试用：保存窗口截图")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("时光计")
    app.setOrganizationName("Shiguang")
    app.setQuitOnLastWindowClosed(False)
    QLocale.setDefault(QLocale(QLocale.Language.Chinese,QLocale.Country.China))
    translator = QTranslator(app)
    if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    if os.name != "nt":
        QMessageBox.warning(None,"仅支持 Windows","时光计的系统统计需要 Windows 10 或 Windows 11。")
        return 1
    temporary = None
    data_dir = None
    store = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix="shiguang-demo-") if args.demo else None
        data_dir = Path(temporary.name) if temporary else (args.data_dir or win32.data_directory())
        data_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
            data_dir/"app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")],
            format="%(asctime)s %(levelname)s %(message)s")
        isolated = args.demo or args.data_dir is not None
        if not isolated and not win32.acquire_instance():
            win32.signal_show()
            return 0
        store = Store(data_dir/"usage.sqlite3", app_version=None if args.demo else __version__)
        if args.demo:
            from timelight.demo import seed_demo
            seed_demo(store)
        window = MainWindow(store,data_dir,demo=args.demo)
        app.aboutToQuit.connect(lambda: window.sample() if not window.quitting else None)
        def on_exception(kind, value, trace):
            logging.error("Unhandled application error", exc_info=(kind,value,trace))
            window.footer.setText("操作发生错误，详情已写入本机 app.log。")
        sys.excepthook = on_exception
        if not args.background or args.demo or not QSystemTrayIcon.isSystemTrayAvailable():
            window.show()
        if args.screenshot:
            def save_screenshot():
                args.screenshot.parent.mkdir(parents=True,exist_ok=True)
                window.grab().save(str(args.screenshot))
            QTimer.singleShot(900,save_screenshot)
        if args.quit_after:
            QTimer.singleShot(args.quit_after,window.quit_app)
        return app.exec()
    except Exception as error:
        logging.exception("Startup failed")
        location = f"\n\n数据目录：{data_dir}" if data_dir is not None else ""
        QMessageBox.critical(None,"时光计无法启动",
            f"为保护已有记录，程序已停止启动。\n\n原因：{error}{location}\n\n"
            "请保留现有数据文件；如有备份，可按使用说明恢复。详情见数据目录中的 app.log。")
        return 1
    finally:
        if store:
            store.close()
        win32.release_instance()
        if temporary:
            logging.shutdown()
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
