#!/usr/bin/env python3
"""
fetch_hanzi.py — Download the full hanzi-writer asset set for bundling.

Pulls every stroke-order JSON (~9.5k characters) from the hanzi-writer-data npm
package plus the hanzi-writer runtime, into hanzi_assets/. CI runs this before
PyInstaller; the spec bundles the directory and hanzi_data.py reads from it, so
the packaged app can build decks fully offline (no per-character CDN fetches).

Files are renamed to {codepoint:05x}.json — matching hanzi_data's cache naming
and avoiding Unicode filenames in the bundle (safer on Windows). Re-running is a
no-op once hanzi_assets/ is populated.
"""

import io
import sys
import tarfile
import urllib.request
from pathlib import Path

from paths import force_utf8

ASSETS_DIR = Path(__file__).resolve().parent / "hanzi_assets"

_DATA_TARBALL = "https://registry.npmjs.org/hanzi-writer-data/-/hanzi-writer-data-2.0.1.tgz"
_HW_JS_URL = "https://cdn.jsdelivr.net/npm/hanzi-writer@3.5/dist/hanzi-writer.min.js"


def _download(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "chinese-anki-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def main() -> int:
    force_utf8()
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    js_dest = ASSETS_DIR / "_hanzi_writer.js"
    if not (js_dest.exists() and js_dest.stat().st_size > 0):
        print("  Downloading hanzi-writer.min.js …")
        js_dest.write_bytes(_download(_HW_JS_URL))
        print("  ✓ hanzi-writer.min.js")

    # If we already have a healthy pile of stroke files, assume we're done.
    if sum(1 for _ in ASSETS_DIR.glob("?????.json")) > 9000:
        print("  ✓ stroke data already present")
        return 0

    print("  Downloading stroke data (~13 MB) …")
    raw = _download(_DATA_TARBALL)
    written = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for member in tar:
            name = Path(member.name).name  # e.g. "一.json"
            if not member.isfile() or not name.endswith(".json"):
                continue
            stem = name[:-5]
            if len(stem) != 1:  # skip package.json and friends
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            dest = ASSETS_DIR / f"{ord(stem):05x}.json"
            dest.write_bytes(f.read())
            written += 1
    print(f"  ✓ Extracted stroke data for {written} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
