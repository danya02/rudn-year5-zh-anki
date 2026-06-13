# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Chinese Anki Pipeline.

Builds a single-file executable that drops the user into the wizard. The
CC-CEDICT dictionary is bundled as read-only data (resolved via paths.py at
runtime); lessons, caches, and the output .apkg are written next to the
executable (see paths.DATA_DIR), so the bundle stays read-only and portable.

Build locally with:   pyinstaller chinese-anki.spec
"""

import os

from PyInstaller.utils.hooks import collect_all

# The dictionary and HSK level lookup must travel with the app; stroke data and
# audio are downloaded/generated into the user-data dir on first build.
datas = [("data/cedict.txt.gz", "data"), ("data/hsk.json.gz", "data")]
binaries = []
hiddenimports = []

# Bundle the CJK fonts if fetch_fonts.py has populated fonts/ (CI does this
# before building). Without them the app still runs but font variety degrades.
if os.path.isdir("fonts"):
    for _f in sorted(os.listdir("fonts")):
        if _f.lower().endswith((".ttf", ".otf")):
            datas.append((os.path.join("fonts", _f), "fonts"))

# Bundle the full hanzi-writer stroke set if fetch_hanzi.py has populated
# hanzi_assets/. With it, building a deck needs no network for stroke data.
if os.path.isdir("hanzi_assets"):
    datas.append(("hanzi_assets", "hanzi_assets"))

# These packages ship data files / lazy imports PyInstaller can miss.
for pkg in ("edge_tts", "genanki", "questionary", "pyperclip"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden


a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="chinese-anki",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,
)
