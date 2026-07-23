# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

import playwright
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)

datas = []
binaries = []
hiddenimports = [
    "mutagen.mp3", "mutagen.flac", "mutagen.mp4",
    "mutagen.oggvorbis", "mutagen.oggopus",
]

# Playwright требует Node-драйвер и служебные файлы. Для PySide6 штатные hooks
# PyInstaller точнее собирают только реально импортированные QtCore/Gui/Widgets.
package_datas, package_binaries, package_hidden = collect_all("playwright")
datas += package_datas
binaries += package_binaries
hiddenimports += package_hidden

# При PLAYWRIGHT_BROWSERS_PATH=0 браузер устанавливается внутрь пакета.
browser_dir = Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
if browser_dir.exists():
    datas.append((str(browser_dir), "playwright/driver/package/.local-browsers"))

a = Analysis(
    [str(project_root / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TagStiller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TagStiller",
)
