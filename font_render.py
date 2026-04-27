"""
font_render.py — Render CJK characters as PNG images in three typeface styles.

Sans and Serif are located via fontconfig (fc-match), so they work on any
system where Noto CJK or equivalent fonts are installed.  The Kai (regular
script / handwriting-like) font is downloaded once from GitHub and cached in
data/fonts/.

Images are cached per (character, style) in data/font_cache/ and returned as
a flat list of Paths ready to pass to genanki as media files.
"""

import subprocess
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_BASE      = Path(__file__).parent
_FONT_DIR  = _BASE / "data" / "fonts"
_CACHE_DIR = _BASE / "data" / "font_cache"
_KAI_PATH  = _FONT_DIR / "_font_kai.ttf"
_KAI_URL   = "https://github.com/lxgw/LxgwWenKai/releases/download/v1.501/LXGWWenKai-Regular.ttf"

# Render size in pixels; images are square with this padding on each side.
_CHAR_SIZE = 120
_IMG_SIZE  = 140

STYLE_LABELS = {
    "sans":  "Sans",
    "serif": "Serif",
    "kai":   "Kai",
}


def _is_cjk(char: str) -> bool:
    cp = ord(char)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


# ---------------------------------------------------------------------------
# Font resolution
# ---------------------------------------------------------------------------

def _fc_match(query: str) -> tuple[str, int] | None:
    """Return (file_path, ttc_index) for a fontconfig query, or None."""
    try:
        out = subprocess.check_output(
            ["fc-match", "--format=%{file}:%{index}", query],
            timeout=5, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        path, _, idx = out.rpartition(":")
        return path, int(idx)
    except Exception:
        return None


def _ensure_kai() -> tuple[str, int]:
    if not _KAI_PATH.exists():
        _FONT_DIR.mkdir(parents=True, exist_ok=True)
        print("  Downloading LXGW WenKai (regular-script font) …")
        req = urllib.request.Request(
            _KAI_URL,
            headers={"User-Agent": "chinese-anki-pipeline/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            _KAI_PATH.write_bytes(resp.read())
        print(f"  ✓ Saved {_KAI_PATH.name} ({_KAI_PATH.stat().st_size // 1024} KB)")
    return str(_KAI_PATH), 0


def _resolve_fonts() -> dict[str, tuple[str, int]]:
    """Return {style: (font_path, ttc_index)} for all three styles."""
    fonts: dict[str, tuple[str, int]] = {}

    for style, query in [
        ("sans",  "Noto Sans CJK SC:style=Regular"),
        ("serif", "Noto Serif CJK SC:style=Regular"),
    ]:
        result = _fc_match(query)
        if result is None:
            raise RuntimeError(
                f"Could not find font for style '{style}' via fc-match. "
                f"Install a CJK sans/serif font (e.g. noto-fonts-cjk)."
            )
        fonts[style] = result

    fonts["kai"] = _ensure_kai()
    return fonts


# ---------------------------------------------------------------------------
# Image rendering
# ---------------------------------------------------------------------------

def _render_char(char: str, style: str, font_path: str, ttc_index: int) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = _CACHE_DIR / f"_char_{ord(char):05x}_{style}.png"
    if out.exists():
        return out

    fnt = ImageFont.truetype(font_path, _CHAR_SIZE, index=ttc_index)
    img = Image.new("RGBA", (_IMG_SIZE, _IMG_SIZE), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    bb = fnt.getbbox(char)
    x = (_IMG_SIZE - (bb[2] - bb[0])) // 2 - bb[0]
    y = (_IMG_SIZE - (bb[3] - bb[1])) // 2 - bb[1]
    draw.text((x, y), char, font=fnt, fill=(26, 26, 26, 255))

    img.save(out, "PNG")
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_char_images(words: list[str]) -> list[Path]:
    """
    Render every unique CJK character from *words* in Sans, Serif, and Kai.
    Returns the list of PNG paths to bundle into the .apkg media.
    """
    chars = sorted({ch for word in words for ch in word if _is_cjk(ch)})
    if not chars:
        return []

    font_map = _resolve_fonts()
    paths: list[Path] = []
    for ch in chars:
        for style, (fpath, fidx) in font_map.items():
            paths.append(_render_char(ch, style, fpath, fidx))

    print(f"  ✓ Font images ready: {len(chars)} chars × 3 styles")
    return paths
