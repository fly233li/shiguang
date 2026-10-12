# 时光计 · 第三方组件与许可声明

本清单对应 2026-10-12 构建的 Windows x64 文件夹版。第三方组件保持其各自的版权与许可。许可证原文、上游归属信息和下载来源保存在随附的 `licenses/` 中。

| 组件 | 本次版本 / 用途 | 许可与随附文件 |
| --- | --- | --- |
| CPython | 3.13.14，Python 运行时与标准库 | PSF 许可及历史许可；`licenses/Python-3.13.14-LICENSE.txt`，标准库相关归属见 `Python-3.13.14-license.html` |
| PySide6 Essentials / Shiboken6 | 6.12.0，Qt 的 Python 绑定 | 本包使用 LGPL-3.0-only 许可选项；原文见 `licenses/Qt-6.12.0/pyside/LICENSES/`，组件声明见其 `sources/` |
| Qt | 6.12.0，Core、Gui、Widgets、Network、Svg，以及平台、样式与图片插件 | LGPL-3.0-only 及各第三方组件许可；见 `licenses/Qt-6.12.0/qtbase/`、`qtsvg/`、`qtimageformats/` |
| SQLite | 3.50.4，本地数据库 | Public Domain；`licenses/SQLite-copyright.html` |
| OpenSSL | 3.0.21，Python 随带运行库 | Apache-2.0；`licenses/OpenSSL-3.0.21-LICENSE.txt` |
| Mesa llvmpipe | Qt wheel 随带的 `opengl32sw.dll` | MIT、BSL-1.0；`licenses/Mesa-llvmpipe-NOTICES.txt` |
| Microsoft 运行库 | Visual C++ / Universal CRT 与相关 API DLL | Microsoft Distributable Code；见 `licenses/Python-3.13.14-LICENSE.txt` 中的 Microsoft 声明 |
| PyInstaller | 6.22.3，构建工具及嵌入式启动器 | GPL-2.0-or-later，带启动器例外；运行时钩子使用 Apache-2.0。见 `licenses/PyInstaller-6.22.3-COPYING.txt` |

Qt/PySide6 的版权属于 The Qt Company Ltd. 及其贡献者。Python 的版权归属与历史许可见 PSF 原文。Qt 内使用的第三方代码包括字体与文本处理、图片编解码、正则表达式、压缩和 Unicode 数据等；本包保留上游 `qt_attribution.json` 中的组件名称、版本、版权声明和许可证引用，并附相关原文。`LICENSES/` 也保留上游提供的其他许可选项；这些文件的存在不表示本应用包含每个 Qt 模块或采用商业许可。

本次实际打包的 DLL / PYD 列表见 `licenses/bundled-runtime-files.txt`。`licenses/package-metadata/` 保留安装包元数据，`licenses/sources.json` 记录各声明的来源和 SHA-256。Qt Network、OpenSSL 等由依赖收集进入分发目录，不表示时光计会上传使用记录。

## 上游源码与说明

- [PySide6 / Shiboken 6.12.0 源码](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/)；[对应 Git 标签](https://github.com/pyside/pyside-setup/tree/v6.12.0)。
- Qt 6.12.0 对应源码：[qtbase](https://github.com/qt/qtbase/tree/v6.12.0)、[qtsvg](https://github.com/qt/qtsvg/tree/v6.12.0)、[qtimageformats](https://github.com/qt/qtimageformats/tree/v6.12.0)；[Qt 官方发布目录](https://download.qt.io/official_releases/qt/6.12/6.12.0/)。
- [Qt 第三方归属清单](https://doc.qt.io/qt-6/licenses-used-in-qt.html)。本地保存的源码声明固定来自 `v6.12.0`，在线文档会随 Qt 更新。
- [CPython 3.13.14 源码](https://github.com/python/cpython/tree/v3.13.14)、[SQLite 版权说明](https://www.sqlite.org/copyright.html)、[OpenSSL 3.0.21 源码](https://github.com/openssl/openssl/tree/openssl-3.0.21)。
- [PyInstaller 6.22.3 源码](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3)、[启动器许可说明](https://pyinstaller.org/en/stable/license.html)。

## 动态库与部署说明

本程序以文件夹形式分发。Qt、PySide6、Shiboken 等动态库位于 `_internal/`，未被合并为不可替换的单文件程序。对这些组件，保留相应许可证授予的修改、替换及为调试修改而进行逆向工程的权限。替换时应保持 Windows x64、Qt/PySide6 版本及二进制接口兼容；也可以使用随附应用源码和构建脚本重新构建。替换或重建前请退出程序并备份数据。

移动程序时须移动整个 `Shiguang` 文件夹，包括 `_internal/`、本声明和 `licenses/`。开机启动设置保存的是当前 `Shiguang.exe` 的绝对路径：应先把程序放到固定位置，再启用开机启动。之后若移动或重命名目录，请从新位置打开程序，并重新关闭、开启一次开机启动以更新路径。直接从源码运行时，启动项保存的是当前 Python 解释器和 `main.py` 的路径。Windows 任务管理器还可以独立禁用已经配置的启动项。
