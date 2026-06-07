#!/usr/bin/env python3
"""
fetch_fonts.py — Download the CJK fonts that get bundled into the packaged app.

The three typefaces (sans, serif, kai) total ~60 MB, so they're not committed to
git. CI runs this before PyInstaller, and you can run it locally too — it drops
the files into fonts/, which chinese-anki.spec bundles and which font_render
prefers over system fonts. Re-running skips files already present.
"""

import sys
import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# style filename → download URL. Filenames must match font_render.BUNDLED_FONTS.
FONTS = {
    "NotoSansSC.ttf": "https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
    "NotoSerifSC.ttf": "https://github.com/google/fonts/raw/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf",
    "LXGWWenKai.ttf": "https://github.com/lxgw/LxgwWenKai/releases/download/v1.501/LXGWWenKai-Regular.ttf",
}


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS.items():
        dest = FONTS_DIR / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  ✓ {name} already present")
            continue
        print(f"  Downloading {name} …")
        req = urllib.request.Request(url, headers={"User-Agent": "chinese-anki-pipeline/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())
        print(f"  ✓ {name} ({dest.stat().st_size // 1024 // 1024} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
