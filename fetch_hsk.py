#!/usr/bin/env python3
"""
fetch_hsk.py — (Re)build the bundled HSK level lookup, data/hsk.json.gz.

Downloads the combined word list from the complete-hsk-vocabulary dataset and
derives a slim map keyed by both simplified and traditional forms:

    word -> [hsk2_level | null, hsk3_level | null]

HSK 2.0 levels come from the dataset's `o1..o6` codes, HSK 3.0 from `n1..n7`
(its advanced 7-9 bands are grouped as 7). The result is ~80 KB gzipped and is
committed as a bundled resource, so the packaged app resolves HSK levels fully
offline. hsk.py reads it. Re-run this to refresh against an updated dataset.
"""

import gzip
import json
import urllib.request
from pathlib import Path

from paths import force_utf8

OUT_PATH = Path(__file__).resolve().parent / "data" / "hsk.json.gz"
SOURCE_URL = (
    "https://raw.githubusercontent.com/drkameleon/"
    "complete-hsk-vocabulary/main/complete.min.json"
)


def _min_band(codes: list[str], prefix: str) -> int | None:
    levels = [int(c[1:]) for c in codes if c.startswith(prefix)]
    return min(levels) if levels else None


def build() -> None:
    print(f"Downloading {SOURCE_URL} …")
    req = urllib.request.Request(
        SOURCE_URL, headers={"User-Agent": "chinese-anki-pipeline/1.0"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        src = json.loads(resp.read().decode("utf-8"))

    table: dict[str, list] = {}
    for entry in src:
        codes = entry.get("l", [])
        h2 = _min_band(codes, "o")  # old HSK 2.0 (6 levels)
        h3 = _min_band(codes, "n")  # new HSK 3.0 (7 = bands 7-9)
        if h2 is None and h3 is None:
            continue
        forms = {entry["s"]} | {
            f.get("t") for f in entry.get("f", []) if f.get("t")
        }
        for word in forms:
            if not word:
                continue
            cur = table.setdefault(word, [None, None])
            if h2 is not None:
                cur[0] = h2 if cur[0] is None else min(cur[0], h2)
            if h3 is not None:
                cur[1] = h3 if cur[1] is None else min(cur[1], h3)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT_PATH, "wt", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ Wrote {OUT_PATH}  ({len(table)} forms, {OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    force_utf8()
    build()
