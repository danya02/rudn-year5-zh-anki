"""
wiktionary.py — Look up Chinese words on English Wiktionary.

Simplified-character pages redirect via {{zh-see|Traditional}}; the
module follows one level of redirect automatically.  Pinyin comes from the
{{zh-pron|m=...}} template (Mandarin reading, already in diacritic form).
Note: Wiktionary pinyin for multi-syllable words is often written without
spaces (e.g. 'lǎoshī'); this is left as-is.
"""

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

_API = "https://en.wiktionary.org/w/api.php"

# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    word: str
    pinyin: str
    definitions: list[str]

    @property
    def meaning(self) -> str:
        return '; '.join(self.definitions[:3])


# ---------------------------------------------------------------------------
# Wikitext fetching
# ---------------------------------------------------------------------------

def _fetch(title: str) -> str | None:
    params = urllib.parse.urlencode({
        "action":      "query",
        "titles":      title,
        "prop":        "revisions",
        "rvprop":      "content",
        "rvslots":     "main",
        "format":      "json",
        "formatversion": "2",
    })
    req = urllib.request.Request(
        f"{_API}?{params}",
        headers={"User-Agent": "chinese-anki-pipeline/1.0 (language learning tool)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        page = data["query"]["pages"][0]
        if page.get("missing"):
            return None
        return page["revisions"][0]["slots"]["main"]["content"]
    except Exception as exc:
        raise LookupError(f"Wiktionary request failed for '{title}': {exc}") from exc


# ---------------------------------------------------------------------------
# Wikitext parsing
# ---------------------------------------------------------------------------

_CHINESE_SEC = re.compile(r'==Chinese==(.*?)(?:\n==[^=]|\Z)', re.S)
_ZH_SEE      = re.compile(r'\{\{zh-see\|([^|}]+)')
_ZH_PRON     = re.compile(r'\{\{zh-pron(.*?)\}\}', re.S)
_M_PARAM     = re.compile(r'(?:^|\|)\s*m=([^|\n}]+)', re.M)
_TOP_DEF     = re.compile(r'^# (.+)', re.M)
_TEMPLATE_NG = re.compile(r'\{\{(?:n-g|non-gloss definition)\|([^}]+)\}\}')
_TEMPLATE    = re.compile(r'\{\{[^}]*\}\}')
_WIKILINK    = re.compile(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]')


def _clean_def(raw: str) -> str:
    text = _TEMPLATE_NG.sub(r'\1', raw)       # keep n-g inner text
    text = _TEMPLATE.sub('', text)             # drop all other templates
    text = _WIKILINK.sub(r'\1', text)          # unwrap [[links]]
    text = re.sub(r'\s+', ' ', text).strip(' ;,.')
    return text


def _parse(original_word: str, wikitext: str, _depth: int = 0) -> Entry | None:
    """Parse the Chinese section; follows one {{zh-see}} redirect."""
    m = _CHINESE_SEC.search(wikitext)
    if not m:
        return None
    section = m.group(1)

    # Follow zh-see redirect (simplified → traditional)
    see = _ZH_SEE.search(section)
    if see and _depth == 0:
        target = see.group(1).strip()
        redirected = _fetch(target)
        if redirected:
            return _parse(original_word, redirected, _depth=1)
        return None

    # Pinyin: m= parameter of {{zh-pron ...}}
    pinyin = ""
    pron_block = _ZH_PRON.search(section)
    if pron_block:
        mp = _M_PARAM.search(pron_block.group(1))
        if mp:
            # strip sub-parameters after comma (e.g. ",tl=y")
            pinyin = mp.group(1).strip().split(',')[0].strip()

    if not pinyin:
        return None

    defs = [_clean_def(d) for d in _TOP_DEF.findall(section) if _clean_def(d)]
    if not defs:
        return None

    return Entry(original_word, pinyin, defs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup(word: str) -> list[Entry]:
    """Return Wiktionary entries for *word*, or [] if not found/parseable."""
    try:
        wikitext = _fetch(word)
    except LookupError as exc:
        print(f"  ⚠ {exc}")
        return []
    if not wikitext:
        return []
    entry = _parse(word, wikitext)
    return [entry] if entry else []
