"""Render the original vector system as a design board and true-size proof."""
from pathlib import Path
import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage,QPainter,QColor,QPen,QFont,QFontDatabase
from PySide6.QtWidgets import QApplication
from timelight.icons import SYMBOLS,PALETTE,brand_svg,svg_pixmap,paint_symbol

app=QApplication.instance() or QApplication([])
for name in ["msyh.ttc","msyhbd.ttc","segoeui.ttf","seguisb.ttf"]:
    path=Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/name
    if path.exists(): QFontDatabase.addApplicationFont(str(path))
output=ROOT/"assets"/"icons"
output.mkdir(parents=True,exist_ok=True)


def text(p,x,y,value,size=18,color="#172d35",bold=False):
    font=QFont("Microsoft YaHei UI")
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    p.setFont(font)
    p.setPen(QColor(color))
    p.drawText(int(x),int(y),value)


def box(p,x,y,w,h,color="#ffffff",border=True,radius=18):
    p.setPen(QPen(QColor("#e1e7db"),1) if border else Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(x,y,w,h),radius,radius)


def canvas(w,h,bg):
    image=QImage(w,h,QImage.Format.Format_ARGB32)
    image.fill(QColor(bg))
    painter=QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return image,painter


sheet,p=canvas(1600,1392,"#f4f5ef")
text(p,64,61,"SHIGUANG  /  ICON SYSTEM",16,"#788783",True)
text(p,64,123,"时光计 · 图标设计",46,bold=True)
text(p,64,164,"以时钟环记录时间，以光点标记当下。",20,"#697b73")
box(p,64,196,944,288)
box(p,1032,196,504,288)
p.drawPixmap(96,236,svg_pixmap(brand_svg(),208))
text(p,340,300,"时光计",50,bold=True)
text(p,342,339,"TIME, WELL NOTICED",18,"#788783")
text(p,342,385,"时钟环  /  光点  /  圆角方形",20)
text(p,342,430,"应用主标 · 16—512px · 多尺寸 Windows ICO",16,"#788783")
text(p,1064,242,"托盘状态",22,bold=True)
states=[("recording","记录中"),("paused","已暂停"),("idle","已离开"),("error","异常")]
for i,(state,name) in enumerate(states):
    x=1072+i*112
    p.drawPixmap(x,282,svg_pixmap(brand_svg(state),64))
    text(p,x+8,377,name,16)
text(p,1064,434,"形状与颜色同时变化，小尺寸下也能分辨。",16,"#788783")
text(p,64,537,f"{len(SYMBOLS)} 枚功能图标",26,bold=True)
text(p,941,535,"24px 网格 · 1.8px 描边 · 圆头圆角",18,"#788783")
cellw=(1472-6*16)/7
for index,(name,(caption,_)) in enumerate(SYMBOLS.items()):
    x=64+(index%7)*(cellw+16)
    y=568+(index//7)*154
    box(p,x,y,cellw,138,radius=14)
    paint_symbol(p,name,QRectF(x+20,y+22,30,30),PALETTE["green"])
    box(p,x+cellw-53,y+21,32,32,"#172d35",False,8)
    paint_symbol(p,name,QRectF(x+cellw-49,y+25,24,24),PALETTE["light"])
    text(p,x+20,y+83,caption,17,bold=True)
    text(p,x+20,y+113,name,13,"#788783")
for i,(name,hexcode) in enumerate([("松绿",PALETTE["green"]),("深青",PALETTE["ink"]),("浅芽绿",PALETTE["light"]),("中性灰",PALETTE["muted"]) ]):
    x=64+i*366
    box(p,x,1227,24,24,hexcode,False,7)
    text(p,x+38,1246,f"{name}  {hexcode.upper()}",16,"#697b73")
text(p,64,1340,"时光计 1.0.2  ·  原创矢量图标",16,"#788783")
text(p,1246,1340,"SVG  /  PNG  /  ICO",17,"#227660",True)
p.end()
sheet.save(str(output/"图标总览.png"))

proof,p=canvas(1400,650,"#f4f5ef")
text(p,40,50,"真实像素尺寸检查",28,bold=True)
text(p,790,48,"在 100% 缩放下查看，图标未经放大。",18,"#788783")
for i,size in enumerate([16,20,24,32,48,64,128]):
    x=56+i*188
    p.drawPixmap(x+(128-size)//2,92+(128-size)//2,svg_pixmap(brand_svg(),size))
    text(p,x+40,253,f"{size}px",16,"#788783")
for panelx,dark in [(40,False),(712,True)]:
    box(p,panelx,286,648,324,"#172d35" if dark else "#ffffff",not dark)
    fg="#e5efbf" if dark else "#172d35"
    muted="#bdccca" if dark else "#788783"
    text(p,panelx+24,326,"深色任务栏" if dark else "浅色任务栏",20,fg,True)
    for i,size in enumerate([16,20,24,32]):
        text(p,panelx+174+i*112,363,f"{size}px",14,muted)
    for row,(state,name) in enumerate(states):
        y=392+row*52
        text(p,panelx+24,y+17,name,16,muted)
        for i,size in enumerate([16,20,24,32]):
            p.drawPixmap(panelx+188+i*112-size//2,y+6-size//2,svg_pixmap(brand_svg(state),size))
p.end()
proof.save(str(output/"图标小尺寸检查.png"))
print(output)
