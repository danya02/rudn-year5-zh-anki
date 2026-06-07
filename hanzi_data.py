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

from paths import CACHE_DIR, RESOURCE_DIR

_CACHE_DIR = CACHE_DIR / "hanzi_cache"
_HW_JS     = CACHE_DIR / "_hanzi_writer.js"
_HW_DATA   = CACHE_DIR / "_hanzi_data.js"

_HW_JS_URL   = "https://cdn.jsdelivr.net/npm/hanzi-writer@3.5/dist/hanzi-writer.min.js"
_HW_DATA_URL = "https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0/{char}.json"

# Assets bundled with the app (populated by fetch_hanzi.py, shipped in the
# PyInstaller build). When present, the build runs fully offline — no CDN.
_BUNDLED_DIR = RESOURCE_DIR / "hanzi_assets"


def _bundled_stroke(char: str) -> Path | None:
    p = _BUNDLED_DIR / f"{ord(char):05x}.json"
    return p if p.exists() else None


def _is_cjk(char: str) -> bool:
    cp = ord(char)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def _fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=15) as resp:
        dest.write_bytes(resp.read())


def _ensure_hw_js() -> Path:
    bundled = _BUNDLED_DIR / "_hanzi_writer.js"
    if bundled.exists():
        return bundled
    if not _HW_JS.exists():
        print("  Downloading hanzi-writer.js …")
        _fetch(_HW_JS_URL, _HW_JS)
        print(f"  ✓ Saved {_HW_JS.name}")
    return _HW_JS


def _char_data(char: str) -> dict | None:
    bundled = _bundled_stroke(char)
    if bundled is not None:
        return json.loads(bundled.read_text(encoding="utf-8"))
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


def stroke_count(char: str) -> int | None:
    """Number of strokes for *char*, read from the local cache only (no network).

    Returns None when the character hasn't been cached yet. Call build_assets
    first to populate the cache, then this is cheap and offline.
    """
    src = _bundled_stroke(char) or (_CACHE_DIR / f"{ord(char):05x}.json")
    if not src.exists():
        return None
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        return len(data.get("strokes", [])) or None
    except (OSError, json.JSONDecodeError):
        return None


def build_assets(words: list[str]) -> tuple[Path, list[Path]]:
    """
    Ensure hanzi-writer.js is cached and write one _stroke_XXXXX.json media
    file per CJK character that appears in *words*.

    Returns (hw_js_path, [stroke_json_path, ...]).
    """
    hw_js = _ensure_hw_js()

    chars = sorted({ch for word in words for ch in word if _is_cjk(ch)})
    stroke_files: list[Path] = []
    ok = 0
    for ch in chars:
        data = _char_data(ch)
        if data is None:
            continue
        dest = CACHE_DIR / f"_stroke_{ord(ch):05x}.json"
        dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        stroke_files.append(dest)
        ok += 1

    print(f"  ✓ Stroke data bundled for {ok}/{len(chars)} characters")
    return hw_js, stroke_files
