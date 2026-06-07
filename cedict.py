"""
cedict.py — CC-CEDICT parser and lookup.

Loads the dictionary once and exposes lookup(word) -> list of Entry.
Handles pinyin tone-number → diacritic conversion.
"""

import gzip
import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Pinyin conversion: ni3 hao3 → nǐ hǎo
# ---------------------------------------------------------------------------

_TONE_MAP = {
    'a': ['ā', 'á', 'ǎ', 'à', 'a'],
    'e': ['ē', 'é', 'ě', 'è', 'e'],
    'i': ['ī', 'í', 'ǐ', 'ì', 'i'],
    'o': ['ō', 'ó', 'ǒ', 'ò', 'o'],
    'u': ['ū', 'ú', 'ǔ', 'ù', 'u'],
    'ü': ['ǖ', 'ǘ', 'ǚ', 'ǜ', 'ü'],
}

# Vowel priority for tone mark placement (longest match first)
_TONE_PRIORITY = ['ou', 'iu', 'ui', 'ia', 'ie', 'uo', 'ue', 'üe',
                  'ai', 'ao', 'ei', 'a', 'e', 'o', 'i', 'u', 'ü']


def _syllable_to_diacritic(syllable: str, tone: int) -> str:
    """
    Convert a single pinyin syllable + tone number to diacritic form.

    Standard rules (in priority order):
      1. If syllable contains 'a' or 'e', mark goes there.
      2. If syllable ends in 'ou', mark goes on 'o'.
      3. Otherwise, mark goes on the LAST vowel.
    """
    if tone == 5:  # neutral tone — no mark
        return syllable
    syllable = syllable.replace('v', 'ü').replace('u:', 'ü')

    VOWELS = 'aeiouü'

    # Rule 1: 'a' or 'e'
    for v in ('a', 'e'):
        idx = syllable.find(v)
        if idx != -1:
            return syllable[:idx] + _TONE_MAP[v][tone - 1] + syllable[idx + 1:]

    # Rule 2: ends in 'ou'
    if syllable.endswith('ou'):
        idx = syllable.rfind('o')
        return syllable[:idx] + _TONE_MAP['o'][tone - 1] + syllable[idx + 1:]

    # Rule 3: last vowel
    for i in range(len(syllable) - 1, -1, -1):
        if syllable[i] in VOWELS:
            v = syllable[i]
            return syllable[:i] + _TONE_MAP[v][tone - 1] + syllable[i + 1:]

    return syllable  # fallback


def pinyin_numbers_to_diacritics(pinyin_str: str) -> str:
    """
    Convert CC-CEDICT pinyin string to Unicode diacritic form.
    e.g. "ni3 hao3" → "nǐ hǎo"
         "Zhong1 guo2" → "Zhōng guó"
    """
    def convert_token(token: str) -> str:
        # Preserve non-pinyin tokens (punctuation, etc.)
        match = re.match(r'^([a-zA-Züv:]+)([1-5])$', token)
        if not match:
            return token
        syllable, tone = match.group(1), int(match.group(2))
        # Preserve capitalisation
        if syllable[0].isupper():
            return _syllable_to_diacritic(syllable.lower(), tone).capitalize()
        return _syllable_to_diacritic(syllable, tone)

    return ' '.join(convert_token(t) for t in pinyin_str.split())


# ---------------------------------------------------------------------------
# Dictionary entry
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    traditional: str
    simplified: str
    pinyin_raw: str       # "ni3 hao3"
    pinyin: str           # "nǐ hǎo"
    definitions: list[str]

    @property
    def meaning(self) -> str:
        """Top 3 non-classifier definitions joined by '; '."""
        clean = [d for d in self.definitions if not d.startswith('CL:')]
        return '; '.join(clean[:3])


# ---------------------------------------------------------------------------
# Dictionary loader
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(
    r'^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.+)/$'
)


def load(path: str | Path) -> dict[str, list[Entry]]:
    """
    Parse CC-CEDICT (plain or .gz) and return a dict mapping
    simplified (and traditional) characters to lists of Entry.
    """
    path = Path(path)
    open_fn = gzip.open if path.suffix == '.gz' else open
    index: dict[str, list[Entry]] = {}

    with open_fn(path, 'rt', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = _LINE_RE.match(line)
            if not m:
                continue
            trad, simp, pinyin_raw, defs_str = m.groups()
            pinyin = pinyin_numbers_to_diacritics(pinyin_raw)
            defs = [d.strip() for d in defs_str.split('/') if d.strip()]
            entry = Entry(trad, simp, pinyin_raw, pinyin, defs)
            for key in {simp, trad}:
                index.setdefault(key, []).append(entry)

    return index


def lookup(index: dict, word: str) -> list[Entry]:
    """Return all dictionary entries for *word* (simplified or traditional)."""
    return index.get(word, [])


# ---------------------------------------------------------------------------
# Shared meaning/entry helpers (used by pipeline and definition_picker)
# ---------------------------------------------------------------------------

# Definitions starting with these are low-value as a primary meaning, so when
# auto-picking we prefer a later entry that doesn't start this way.
_DEPRIORITIZE = re.compile(r"^(surname|abbr\.|variant of|old variant|see )", re.I)


def clean_meaning(meaning: str) -> str:
    """Drop classifier (CL:) clauses from a semicolon-separated meaning string."""
    parts = [p.strip() for p in meaning.split(";")]
    parts = [p for p in parts if p and not p.startswith("CL:")]
    return "; ".join(parts)


def best_entry(entries: list["Entry"]) -> "Entry":
    """Pick the most useful entry: first one whose top definition isn't a
    surname/abbreviation/variant pointer, else the first entry."""
    for entry in entries:
        if not _DEPRIORITIZE.match(entry.definitions[0]):
            return entry
    return entries[0]
