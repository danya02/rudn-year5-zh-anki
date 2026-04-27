"""
hanzi_data.py — Download and cache hanzi-writer assets for Anki media.

Fetches hanzi-writer.min.js (once) and per-character stroke JSON from the
hanzi-writer-data CDN, caching both under data/.  Call build_assets(words)
from pipeline.py before building the .apkg; it returns the two media-file
paths that genanki needs to bundle.
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

_BASE      = Path(__file__).parent
_CACHE_DIR = _BASE / "data" / "hanzi_cache"
_HW_JS     = _BASE / "data" / "_hanzi_writer.js"
_HW_DATA   = _BASE / "data" / "_hanzi_data.js"

_HW_JS_URL   = "https://cdn.jsdelivr.net/npm/hanzi-writer@3.5/dist/hanzi-writer.min.js"
_HW_DATA_URL = "https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0/{char}.json"


def _is_cjk(char: str) -> bool:
    cp = ord(char)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def _fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=15) as resp:
        dest.write_bytes(resp.read())


def _ensure_hw_js() -> Path:
    if not _HW_JS.exists():
        print("  Downloading hanzi-writer.js …")
        _fetch(_HW_JS_URL, _HW_JS)
        print(f"  ✓ Saved {_HW_JS.name}")
    return _HW_JS


def _char_data(char: str) -> dict | None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _CACHE_DIR / f"{ord(char):05x}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        with urllib.request.urlopen(_HW_DATA_URL.format(char=urllib.parse.quote(char)), timeout=10) as resp:
            data = json.loads(resp.read())
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception as exc:
        print(f"  ⚠ Stroke data unavailable for '{char}': {exc}")
        return None


def build_assets(words: list[str]) -> tuple[Path, Path]:
    """
    Ensure hanzi-writer.js is cached and build _hanzi_data.js for every CJK
    character that appears in *words*.  Returns (hw_js_path, data_js_path).
    """
    hw_js = _ensure_hw_js()

    chars = sorted({ch for word in words for ch in word if _is_cjk(ch)})
    bundle: dict[str, dict] = {}
    for ch in chars:
        data = _char_data(ch)
        if data:
            bundle[ch] = data

    _HW_DATA.write_text(
        "window._HANZI_DATA=" + json.dumps(bundle, ensure_ascii=False) + ";",
        encoding="utf-8",
    )
    print(f"  ✓ Stroke data bundled for {len(bundle)}/{len(chars)} characters")
    return hw_js, _HW_DATA
