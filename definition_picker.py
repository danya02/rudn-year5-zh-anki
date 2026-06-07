"""
definition_picker.py — Interactive definition selection for Chinese words.

Gathers candidate definitions from Wiktionary and CC-CEDICT, deduplicates,
and lets the user pick which ones to keep with a checkbox UI (questionary
when available, plain numbered input otherwise). Remembers prior picks per
character so repeated words across lessons don't require re-selection.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import cedict
import wiktionary as wkt
from paths import PROCESSED_DIR

try:
    import questionary
    _HAS_Q = True
except ImportError:
    _HAS_Q = False


PICK_CACHE = PROCESSED_DIR / "picks.json"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class PickResult:
    pinyin: str
    meaning: str
    skipped: bool = False


# ---------------------------------------------------------------------------
# Definition gathering
# ---------------------------------------------------------------------------


def _wkt_lookup_with_retry(word: str) -> list:
    """Call wkt.lookup with a retry/skip prompt on HTTP 429."""
    delay = 5
    while True:
        try:
            return wkt.lookup(word)
        except wkt.RateLimitError:
            print(f"\n  ⚠ Wiktionary rate limit hit for '{word}'.")
            print(f"  Options: Enter to retry in {delay}s, 's' to skip Wiktionary for this word.")
            ans = input("  > ").strip().lower()
            if ans == "s":
                return []
            print(f"  Waiting {delay}s …")
            time.sleep(delay)
            delay = min(delay * 2, 60)


def collect_definitions(word: str, index: dict) -> tuple[str, list[tuple[str, str]]]:
    """Return (pinyin, [(source, definition), ...]) from Wiktionary then CEDICT.

    Pinyin comes from whichever source finds it first. Duplicates across sources
    are removed (Wiktionary entry kept, CEDICT one dropped).
    """
    defs: list[tuple[str, str]] = []
    seen: set[str] = set()
    pinyin = ""

    wkt_entries = _wkt_lookup_with_retry(word)
    if wkt_entries:
        e = wkt_entries[0]
        pinyin = e.pinyin
        for d in e.definitions:
            cleaned = cedict.clean_meaning(d)
            key = _normalize(cleaned)
            if cleaned and key not in seen:
                defs.append(("wiktionary", cleaned))
                seen.add(key)

    cedict_entries = cedict.lookup(index, word)
    if cedict_entries:
        entry = cedict.best_entry(cedict_entries)
        if not pinyin or re.search(r'[一-鿿]', pinyin):
            pinyin = entry.pinyin.lower()
        for d in entry.definitions:
            cleaned = cedict.clean_meaning(d)
            key = _normalize(cleaned)
            if cleaned and key not in seen:
                defs.append(("cedict", cleaned))
                seen.add(key)

    return pinyin, defs


def _normalize(s: str) -> str:
    # Strip parentheticals like "(informal)", leading "to ", articles, punctuation
    # so near-identical phrasings across sources still deduplicate.
    s = re.sub(r'\([^)]*\)', '', s.lower())
    s = re.sub(r'\b(to|a|an|the)\b', '', s)
    return re.sub(r'[^\w]+', '', s)


# ---------------------------------------------------------------------------
# Persistent pick cache
# ---------------------------------------------------------------------------


def _load_cache() -> dict[str, dict]:
    if not PICK_CACHE.exists():
        return {}
    try:
        return json.loads(PICK_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict[str, dict]) -> None:
    PICK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PICK_CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remembered_pick(word: str) -> dict | None:
    """Return the cached pick for *word* if any, else None."""
    return _load_cache().get(word)


def remember_pick(word: str, pinyin: str, meaning: str) -> None:
    cache = _load_cache()
    cache[word] = {"pinyin": pinyin, "meaning": meaning}
    _save_cache(cache)


# ---------------------------------------------------------------------------
# Editor helper
# ---------------------------------------------------------------------------


def _edit_in_editor(initial: str) -> str:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        prompt = f"  Edit meaning [{initial}]: "
        out = input(prompt).strip()
        return out or initial
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(initial)
        path = f.name
    try:
        subprocess.call([editor, path])
        with open(path, encoding="utf-8") as f:
            edited = f.read().strip()
        return edited or initial
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Picker UI
# ---------------------------------------------------------------------------


def _print_header(word: str, pinyin: str) -> None:
    bar = "─" * 40
    print()
    print(f"  {bar}")
    print(f"     {word}    [{pinyin}]")
    print(f"  {bar}")


def _default_indices(defs: list[tuple[str, str]]) -> list[int]:
    """Default selection: first wiktionary + first cedict definition (max one each)."""
    chosen = []
    seen_sources = set()
    for i, (source, _) in enumerate(defs):
        if source not in seen_sources:
            chosen.append(i)
            seen_sources.add(source)
        if len(seen_sources) == 2:
            break
    return chosen or ([0] if defs else [])


def _remembered_indices(defs: list[tuple[str, str]], remembered_meaning: str) -> list[int]:
    """Best-effort: which current defs match a previously-saved meaning string?"""
    parts = {_normalize(p) for p in remembered_meaning.split(";")}
    return [i for i, (_, d) in enumerate(defs) if _normalize(d) in parts]


def _fallback_picker(
    word: str,
    pinyin: str,
    defs: list[tuple[str, str]],
    default_idx: list[int],
    remembered_note: str,
) -> tuple[str, str, bool]:
    print(f"\n  {word}  [{pinyin}]{remembered_note}")
    for i, (source, d) in enumerate(defs, 1):
        mark = "*" if (i - 1) in default_idx else " "
        print(f"   {mark} {i:2}. [{source}] {d}")
    default_str = ",".join(str(i + 1) for i in default_idx) or "skip"

    pinyin_input = input(f"  Pinyin [Enter to keep '{pinyin}']: ").strip()
    if pinyin_input:
        pinyin = pinyin_input

    while True:
        raw = input(
            f"  Numbers (1,3), custom text, 'e' edit selected, 's' skip "
            f"[Enter = {default_str}]: "
        ).strip()
        if not raw:
            if not default_idx:
                return pinyin, "", True
            chosen = [defs[i][1] for i in default_idx]
            return pinyin, "; ".join(chosen), False
        if raw.lower() == "s":
            return pinyin, "", True
        if raw.lower() == "e":
            seed = "; ".join(defs[i][1] for i in default_idx)
            return pinyin, _edit_in_editor(seed), False
        parts = [p.strip() for p in raw.split(",")]
        if all(p.isdigit() for p in parts):
            indices = [int(p) - 1 for p in parts]
            invalid = [i + 1 for i in indices if i < 0 or i >= len(defs)]
            if invalid:
                print(f"  Invalid numbers: {invalid}. Choose 1–{len(defs)}.")
                continue
            chosen = [defs[i][1] for i in indices]
            return pinyin, "; ".join(chosen), False
        return pinyin, raw, False


def _questionary_picker(
    word: str,
    pinyin: str,
    defs: list[tuple[str, str]],
    default_idx: list[int],
    remembered_note: str,
) -> tuple[str, str, bool]:
    pinyin_in = questionary.text(
        f"Pinyin for {word}{remembered_note}:", default=pinyin
    ).ask()
    if pinyin_in is None:  # ctrl-c
        raise KeyboardInterrupt
    pinyin = pinyin_in.strip() or pinyin

    if not defs:
        custom = questionary.text(
            f"No definitions found for {word}. Enter meaning (blank = skip):"
        ).ask()
        if not custom:
            return pinyin, "", True
        return pinyin, custom.strip(), False

    while True:
        choices = [
            questionary.Choice(
                title=f"[{source}] {d}",
                value=i,
                checked=(i in default_idx),
            )
            for i, (source, d) in enumerate(defs)
        ]
        choices.append(questionary.Choice(title="── edit selection in $EDITOR", value="edit"))
        choices.append(questionary.Choice(title="── skip this word", value="skip"))
        picked = questionary.checkbox(
            f"Select definitions for {word}:",
            choices=choices,
        ).ask()
        if picked is None:
            raise KeyboardInterrupt
        if "skip" in picked:
            return pinyin, "", True
        meaning_parts = [defs[i][1] for i in picked if isinstance(i, int)]
        if "edit" in picked:
            seed = "; ".join(meaning_parts) if meaning_parts else defs[default_idx[0]][1]
            return pinyin, _edit_in_editor(seed), False
        if not meaning_parts:
            print("  Pick at least one definition (or 'skip this word').")
            continue
        return pinyin, "; ".join(meaning_parts), False


def pick(word: str, index: dict) -> PickResult:
    """Run the interactive picker for one word.

    Returns a PickResult. If the user skips, `skipped=True` and `meaning=""`.
    Caches the result for next time.
    """
    pinyin, defs = collect_definitions(word, index)

    remembered = remembered_pick(word)
    remembered_note = ""
    if remembered:
        remembered_note = "  (you picked this before)"
        if remembered.get("pinyin"):
            pinyin = remembered["pinyin"]

    default_idx = (
        _remembered_indices(defs, remembered["meaning"])
        if remembered
        else _default_indices(defs)
    )
    if not default_idx and defs:
        default_idx = _default_indices(defs)

    _print_header(word, pinyin)
    if not defs and not _HAS_Q:
        print("  No definitions found in Wiktionary or CC-CEDICT.")
        custom = input("  Enter a custom meaning (blank to skip): ").strip()
        if not custom:
            return PickResult(pinyin=pinyin, meaning="", skipped=True)
        remember_pick(word, pinyin, custom)
        return PickResult(pinyin=pinyin, meaning=custom)

    picker = _questionary_picker if _HAS_Q else _fallback_picker
    pinyin, meaning, skipped = picker(word, pinyin, defs, default_idx, remembered_note)
    if not skipped and meaning:
        remember_pick(word, pinyin, meaning)
    return PickResult(pinyin=pinyin, meaning=meaning, skipped=skipped)


# ---------------------------------------------------------------------------
# Post-session review
# ---------------------------------------------------------------------------


def review_session(
    session_notes: list[dict],
    index: dict,
    on_change: "callable[[], None]",
) -> None:
    """After the picking loop, let the user review all picks and redo any.

    *session_notes* is a list of the actual note dicts stored in lesson_data
    (mutable), so edits here are reflected in the caller's data structure.
    *on_change* is called (with no arguments) after each correction so the
    caller can persist immediately.
    """
    if not session_notes:
        return

    while True:
        print("\n  ── Review picks ──────────────────────────")
        for i, note in enumerate(session_notes, 1):
            print(f"  {i:2}. {note['character']}  [{note['pronunciation']}]  {note['meaning']}")
        print("  ──────────────────────────────────────────")

        if _HAS_Q:
            choices = [
                questionary.Choice(
                    title=f"{note['character']}  [{note['pronunciation']}]  {note['meaning']}",
                    value=i,
                )
                for i, note in enumerate(session_notes, 1)
            ]
            choices.append(questionary.Choice(title="── done, accept all", value="done"))
            choice = questionary.select("Redo a pick, or accept all?", choices=choices).ask()
            if choice is None or choice == "done":
                break
            idx = int(choice) - 1
        else:
            raw = input("\n  Number to redo (Enter to accept all): ").strip()
            if not raw:
                break
            if not raw.isdigit() or not (1 <= int(raw) <= len(session_notes)):
                print(f"  Pick a number from 1 to {len(session_notes)}.")
                continue
            idx = int(raw) - 1

        note = session_notes[idx]
        result = pick(note["character"], index)
        if not result.skipped and result.meaning:
            note["pronunciation"] = result.pinyin
            note["meaning"] = result.meaning
            on_change()
