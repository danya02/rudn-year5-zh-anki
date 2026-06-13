"""
hsk.py — HSK proficiency-level lookup.

Reads the bundled `data/hsk.json.gz` (built by fetch_hsk.py from the
complete-hsk-vocabulary dataset): a map from a Chinese word — keyed by both its
simplified and traditional forms — to its level under each standard:

    word -> [hsk2_level | null, hsk3_level | null]

HSK 2.0 is the older 6-level standard; HSK 3.0 is the 2021 9-level standard
(its advanced bands 7-9 are grouped as level 7 in the source data). Either may
be absent for a given word. The deck build tags word notes from this so a
learner can filter by band, without storing anything in the lesson files.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache

from paths import HSK_PATH


@lru_cache(maxsize=1)
def _table() -> dict[str, list]:
    if not HSK_PATH.exists():
        return {}
    with gzip.open(HSK_PATH, "rt", encoding="utf-8") as f:
        return json.load(f)


def lookup(word: str) -> tuple[int | None, int | None]:
    """Return (hsk2_level, hsk3_level) for *word*; either may be None.

    *word* may be in simplified or traditional form — both are indexed.
    Unknown words return (None, None).
    """
    entry = _table().get(word)
    if not entry:
        return (None, None)
    return (entry[0], entry[1])


def tags(word: str) -> list[str]:
    """Anki tags for *word*'s HSK bands, e.g. ['hsk2-1', 'hsk3-1'].

    Empty when the word isn't in either standard. Tags are deliberately
    space-free and lowercase so they behave well in Anki's tag filters.
    """
    h2, h3 = lookup(word)
    out = []
    if h2 is not None:
        out.append(f"hsk2-{h2}")
    if h3 is not None:
        out.append(f"hsk3-{h3}")
    return out
