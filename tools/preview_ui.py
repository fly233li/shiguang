"""Render every page against isolated demo data for layout review."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from timelight.storage import Store
from timelight.demo import seed_demo
from timelight.ui import MainWindow

app=QApplication([])
for filename in ("msyh.ttc","msyhbd.ttc","segoeui.ttf","seguisb.ttf"):
    font=Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/filename
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
output=Path(__file__).resolve().parents[1]/"artifacts"/"aligned"
output.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    store=Store(Path(tmp)/"usage.sqlite3")
    seed_demo(store)
    window=MainWindow(store,Path(tmp),demo=True)
    window.data_label.setText(r"%LOCALAPPDATA%\Shiguang")
    window.show()
    for width,height,suffix in [(1260,880,""),(1040,700,"-small")]:
        window.resize(width,height)
        for index,name in enumerate(["overview","apps","history","settings"]):
            window.navigate(index)
            app.processEvents()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
            window.grab().save(str(output/(name+suffix+".png")))
    window.close()
    store.close()
print(output)
