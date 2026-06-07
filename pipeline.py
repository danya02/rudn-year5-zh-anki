#!/usr/bin/env python3
"""
pipeline.py — Chinese Anki deck pipeline.

Subcommands
-----------
  add-words   <word_list.txt>
      Look up each word in CC-CEDICT, append to notes.json,
      print any words not found.

  build
      Read notes.json, fetch/update hanzi-writer assets, write chinese.apkg.

  gen-prompt
      Read notes.json, write prompt.txt ready to paste into Claude.
      Targets words that have no sentence yet, plus a small random sample
      of already-covered words for variety.  Use --all to target every word.

  add-sentences  <sentences.json>
      Parse Claude's JSON output, append sentence notes to notes.json,
      then rebuild the .apkg.

  add-audio
      Generate pronunciation audio for all notes using edge-tts, store mp3s
      in data/audio/, update notes.json, then rebuild the .apkg.

Usage examples
--------------
  python pipeline.py add-words lesson_data/lesson_1.txt
  python pipeline.py build
  python pipeline.py gen-prompt
  # … paste prompt.txt into Claude, save reply to sentences.json …
  python pipeline.py add-sentences sentences.json
  python pipeline.py add-audio
"""

import argparse
import asyncio
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import cedict
import deck as deckmod
import definition_picker
import hanzi_data as hzmod
import wiktionary as wkt
from paths import (
    APKG_PATH,
    AUDIO_DIR,
    CURRENT_LESSON_PATH,
    DATA_DIR,
    DICT_PATH,
    GLOSS_PROMPT_PATH,
    NOTES_DIR,
    NOTES_PATH,
    PROCESSED_DIR,
    PROMPT_PATH,
    ensure_dirs,
)

# `BASE` historically meant "the writable project dir"; keep it pointing at the
# user-data root so any lingering references stay correct.
BASE = DATA_DIR

# ---------------------------------------------------------------------------
# Per-lesson notes helpers
# ---------------------------------------------------------------------------


# Bump when the on-disk lesson shape changes in a non-backward-compatible way.
SCHEMA_VERSION = 1


def _lesson_path(stem: str) -> Path:
    return NOTES_DIR / f"{stem}.json"


def _normalize_lesson(data: dict) -> dict:
    """Coerce a loaded lesson into the canonical shape (tolerant of hand-edits
    and older files that predate the version field)."""
    data.setdefault("version", SCHEMA_VERSION)
    data.setdefault("words", [])
    data.setdefault("sentences", [])
    if not isinstance(data["words"], list) or not isinstance(data["sentences"], list):
        raise ValueError("'words' and 'sentences' must be lists")
    return data


REQUIRED_WORD_FIELDS = ("character", "pronunciation", "meaning")
REQUIRED_SENT_FIELDS = ("sentence", "pronunciation", "gloss", "meaning")


def _valid_word(w: dict) -> bool:
    return all(w.get(f) for f in REQUIRED_WORD_FIELDS)


def _valid_sentence(s: dict) -> bool:
    return all(s.get(f) for f in REQUIRED_SENT_FIELDS)


def validate_lesson(stem: str, data: dict) -> list[str]:
    """Return a list of human-readable problems with a lesson (empty = OK).

    Catches the mistakes a hand-editor is likely to make so 'build' can warn
    instead of producing a broken deck.
    """
    problems: list[str] = []
    for i, w in enumerate(data.get("words", [])):
        missing = [f for f in REQUIRED_WORD_FIELDS if not w.get(f)]
        if missing:
            problems.append(f"{stem}: word #{i + 1} missing {missing}: {w}")
    for i, s in enumerate(data.get("sentences", [])):
        missing = [f for f in REQUIRED_SENT_FIELDS if not s.get(f)]
        if missing:
            problems.append(f"{stem}: sentence #{i + 1} missing {missing}: {s}")
    return problems


def load_lesson(stem: str) -> dict:
    path = _lesson_path(stem)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return _normalize_lesson(json.load(f))
    return {"version": SCHEMA_VERSION, "words": [], "sentences": []}


def save_lesson(stem: str, data: dict) -> None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    data = _normalize_lesson(data)
    # Keep version first for readability when users open the file.
    ordered = {"version": data["version"], **{k: v for k, v in data.items() if k != "version"}}
    with open(_lesson_path(stem), "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)


def load_all_lessons() -> list[tuple[str, dict]]:
    """Return [(stem, data), ...] for every notes/<stem>.json file.

    Falls back to the legacy notes.json with a warning when notes/ is empty.
    """
    if NOTES_DIR.exists():
        lessons = []
        for path in sorted(NOTES_DIR.glob("*.json")):
            with open(path, encoding="utf-8") as f:
                lessons.append((path.stem, _normalize_lesson(json.load(f))))
        if lessons:
            return lessons

    if NOTES_PATH.exists():
        print("  ⚠ Using legacy notes.json — run 'migrate-notes' to split by lesson.")
        with open(NOTES_PATH, encoding="utf-8") as f:
            return [("legacy", json.load(f))]

    return []


def merge_lessons(lessons: list[tuple[str, dict]]) -> dict:
    """Merge all lesson data into a single dict, deduplicating by character/sentence."""
    words: list[dict] = []
    sentences: list[dict] = []
    seen_chars: set[str] = set()
    seen_sents: set[str] = set()
    for _, data in lessons:
        for w in data.get("words", []):
            if w["character"] not in seen_chars:
                words.append(w)
                seen_chars.add(w["character"])
        for s in data.get("sentences", []):
            if s["sentence"] not in seen_sents:
                sentences.append(s)
                seen_sents.add(s["sentence"])
    return {"words": words, "sentences": sentences}


def existing_characters(data: dict) -> set[str]:
    return {w["character"] for w in data["words"]}


def existing_sentences(data: dict) -> set[str]:
    return {s["sentence"] for s in data["sentences"]}


def words_with_sentences(data: dict) -> set[str]:
    """Return word characters that appear in at least one existing sentence."""
    sentence_text = "".join(s["sentence"] for s in data["sentences"])
    return {w["character"] for w in data["words"] if w["character"] in sentence_text}


# ---------------------------------------------------------------------------
# Subcommand: add-words
# ---------------------------------------------------------------------------


def _remove_from_pending(pending_file: Path, word: str) -> None:
    """Remove the first occurrence of *word* from the pending file."""
    if not pending_file.exists():
        return
    lines = pending_file.read_text(encoding="utf-8").splitlines()
    removed = False
    kept = []
    for line in lines:
        if not removed and line.strip() == word:
            removed = True
        else:
            kept.append(line)
    if kept:
        pending_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    else:
        pending_file.unlink(missing_ok=True)


def add_words(
    words: list[str],
    stem: str,
    interactive: bool = False,
    pending_file: Path | None = None,
) -> dict:
    """Programmatic API: add *words* to lesson *stem*.

    Returns {"added": [...], "skipped": [...], "not_found": [...]}.
    If *pending_file* is given, each word is removed from it after processing
    so an interrupted session can be resumed.
    """
    print(f"Loading dictionary from {DICT_PATH} …")
    index = cedict.load(DICT_PATH)
    print("Dictionary loaded.")

    lesson_data = load_lesson(stem)
    all_data = merge_lessons(load_all_lessons())
    already = existing_characters(all_data)

    added, skipped, not_found = [], [], []
    session_notes: list[dict] = []

    for word in words:
        if word in already:
            skipped.append(word)
            if pending_file:
                _remove_from_pending(pending_file, word)
            continue

        if interactive:
            result = definition_picker.pick(word, index)
            if result.skipped or not result.meaning:
                not_found.append(word)
                if pending_file:
                    _remove_from_pending(pending_file, word)
                continue
            pinyin, meaning = result.pinyin, result.meaning
        else:
            entries = cedict.lookup(index, word)
            if entries:
                entry = cedict.best_entry(entries)
                pinyin = entry.pinyin.lower()
                meaning = cedict.clean_meaning(entry.meaning)
                print(f"  + {word}  [{pinyin}]  {meaning}  (cedict)")
            else:
                print(f"  '{word}' not in CEDICT, trying Wiktionary …")
                wkt_entries = wkt.lookup(word)
                if not wkt_entries:
                    not_found.append(word)
                    if pending_file:
                        _remove_from_pending(pending_file, word)
                    continue
                pinyin = wkt_entries[0].pinyin
                meaning = cedict.clean_meaning(wkt_entries[0].meaning)
                print(f"  + {word}  [{pinyin}]  {meaning}  (wiktionary)")

        note = {"character": word, "pronunciation": pinyin, "meaning": meaning}
        lesson_data["words"].append(note)
        session_notes.append(note)
        added.append(word)
        save_lesson(stem, lesson_data)
        if pending_file:
            _remove_from_pending(pending_file, word)
        if interactive:
            print(f"  + {word}  [{pinyin}]  {meaning}")

    if interactive and session_notes:

        def _on_correction():
            save_lesson(stem, lesson_data)

        definition_picker.review_session(session_notes, index, _on_correction)

    print(f"\n✓ Added {len(added)} new words to notes/{stem}.json.")
    if skipped:
        print(f"  Already present (skipped): {', '.join(skipped)}")
    if not_found:
        print(
            f"\n⚠ Not added (no definition / skipped) — edit notes/{stem}.json manually if needed:"
        )
        for w in not_found:
            print(f"    {w}")

    return {"added": added, "skipped": skipped, "not_found": not_found}


def cmd_add_words(word_list_path: str, interactive: bool = False) -> None:
    stem = Path(word_list_path).stem
    words_raw = Path(word_list_path).read_text(encoding="utf-8").splitlines()
    words = [w.strip() for w in words_raw if w.strip() and not w.startswith("#")]
    add_words(words, stem, interactive=interactive)


# ---------------------------------------------------------------------------
# Subcommand: build
# ---------------------------------------------------------------------------


def _is_cjk(char: str) -> bool:
    cp = ord(char)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def _complexity(text: str, stroke_counts: dict[str, int | None]) -> tuple[int, int]:
    """A "simpler first" sort key for a word or sentence.

    Returns (number of Chinese characters, total stroke count). Fewer
    characters is simpler; among equal-length items, fewer strokes is simpler.
    Because a phrase is always at least as long as a word it contains, this
    key naturally orders component words ahead of the phrases built from them.
    Characters without cached stroke data fall back to a high count so they
    sort last rather than masquerading as simple.
    """
    chars = [c for c in text if _is_cjk(c)]
    strokes = sum(stroke_counts.get(c) or 99 for c in chars)
    return (len(chars), strokes)


def cmd_build() -> None:
    lessons = load_all_lessons()
    if not lessons:
        print("No lesson notes found. Run 'add-words' first.")
        sys.exit(1)

    problems = [p for stem, d in lessons for p in validate_lesson(stem, d)]
    if problems:
        print("⚠ Found issues in your lesson files (those notes are skipped):")
        for p in problems:
            print(f"    {p}")
        # Drop the incomplete notes so the build can still produce a valid deck.
        lessons = [
            (
                stem,
                {
                    **d,
                    "words": [w for w in d.get("words", []) if _valid_word(w)],
                    "sentences": [
                        s for s in d.get("sentences", []) if _valid_sentence(s)
                    ],
                },
            )
            for stem, d in lessons
        ]

    data = merge_lessons(lessons)
    all_chars = [w["character"] for w in data["words"]]
    all_chars += [s["sentence"] for s in data["sentences"]]

    print("Fetching hanzi-writer assets …")
    hw_js, stroke_files = hzmod.build_assets(all_chars)

    print("Rendering font images …")
    import font_render as fntmod

    font_imgs = fntmod.build_char_images(all_chars)

    media = [str(hw_js)] + [str(p) for p in stroke_files] + [str(p) for p in font_imgs]
    for note in data["words"] + data["sentences"]:
        if note.get("audio"):
            audio_path = AUDIO_DIR / note["audio"]
            if audio_path.exists():
                media.append(str(audio_path))

    stroke_counts = {
        c: hzmod.stroke_count(c)
        for text in all_chars
        for c in text
        if _is_cjk(c)
    }

    # Collect every note with the metadata needed to order it. `due` is just a
    # sort position in Anki's new-card queue, so we sort all notes by a single
    # key and hand out sequential due numbers afterwards.
    #
    # Sort key (earlier = studied first):
    #   1. kind: words, then sentences, then gloss cards — so you always meet a
    #      word before the phrases/sentences built from it.
    #   2. lesson order — keep the course's own progression.
    #   3. priority (descending) — explicit per-note override still wins.
    #   4. complexity (ascending) — simpler (shorter, fewer strokes) first.
    #   5. text — stable, deterministic tiebreak.
    KIND_WORD, KIND_SENT, KIND_GLOSS = 0, 1, 2

    def _pron(note: dict) -> str:
        pron = note["pronunciation"]
        if note.get("audio"):
            pron += f" [sound:{note['audio']}]"
        return pron

    entries: list[tuple[tuple, deckmod.genanki.Note]] = []
    seen_chars: set[str] = set()
    seen_sents: set[str] = set()
    seen_gloss_chars: set[str] = set()

    for lesson_index, (stem, lesson_data) in enumerate(lessons):
        for w in lesson_data.get("words", []):
            char = w["character"]
            if char in seen_chars:
                continue
            seen_chars.add(char)
            key = (
                KIND_WORD,
                lesson_index,
                -w.get("priority", 100),
                _complexity(char, stroke_counts),
                char,
            )
            note = deckmod.word_note(
                char, _pron(w), w["meaning"], tags=[stem]
            )
            entries.append((key, note))

    for lesson_index, (stem, lesson_data) in enumerate(lessons):
        for s in lesson_data.get("sentences", []):
            sent = s["sentence"]
            if sent in seen_sents:
                continue
            seen_sents.add(sent)
            key = (
                KIND_SENT,
                lesson_index,
                -s.get("priority", 100),
                _complexity(sent, stroke_counts),
                sent,
            )
            note = deckmod.sentence_note(
                sent, _pron(s), s["gloss"], s["meaning"], tags=[stem]
            )
            entries.append((key, note))

    for lesson_index, (stem, lesson_data) in enumerate(lessons):
        for w in lesson_data.get("words", []):
            char = w["character"]
            if char in seen_gloss_chars or not w.get("gloss") or len(char) < 2:
                continue
            seen_gloss_chars.add(char)
            key = (
                KIND_GLOSS,
                lesson_index,
                -w.get("priority", 100),
                _complexity(char, stroke_counts),
                char,
            )
            note = deckmod.gloss_note(
                char, _pron(w), w["gloss"], w["meaning"], tags=[stem]
            )
            entries.append((key, note))

    entries.sort(key=lambda e: e[0])
    anki_notes = []
    for due, (_, note) in enumerate(entries):
        note.due = due
        anki_notes.append(note)

    deckmod.build_apkg(anki_notes, str(APKG_PATH), media_files=media)
    n_w = sum(1 for n in anki_notes if "word" in n.tags)
    n_s = sum(1 for n in anki_notes if "sentence" in n.tags)
    print(f"✓ Wrote {APKG_PATH}  ({n_w} word notes, {n_s} sentence notes)")


# ---------------------------------------------------------------------------
# Subcommand: gen-prompt
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """\
You are helping me build Anki flashcards for my Chinese language course.
I will give you a list of words I have learned. For each target word, please
generate one or more example sentences that:
  - use ONLY the vocabulary words listed below (no other Chinese words),
  - is grammatically correct,
  - is appropriate for a beginner.

For each sentence, return a JSON object with exactly these four fields:
  "sentence"      — the Chinese characters,
  "pronunciation" — pinyin with tone diacritics (e.g. nǐ hǎo),
  "gloss"         — word-by-word English gloss, underscore for multi-word
                    equivalents (e.g. "you good" or "you(vos) good"),
  "meaning"       — natural English translation.

Return a JSON array of these objects in a code block.
The array must be valid JSON parseable by Python's
json.loads(). If you have any questions, please ask;
if you have any comments about your output,
please write it outside of the code block.

If you can't come up with any examples that only use the given words,
you may propose adding a word to the vocabulary --
in that case, write it in plain text outside of the code block.

Known vocabulary (character — pronunciation — meaning):
{vocab_lines}

Please try to generate sentences, at least one for each of the following target words:
{target_lines}
"""


def cmd_gen_prompt(target_all: bool = False, sample_covered: int = 2) -> None:
    lessons = load_all_lessons()
    data = merge_lessons(lessons)
    if not data["words"]:
        print("No words found. Run 'add-words' first.")
        sys.exit(1)

    covered = words_with_sentences(data)
    uncovered = [w for w in data["words"] if w["character"] not in covered]
    already_covered = [w for w in data["words"] if w["character"] in covered]

    if target_all:
        target_words = data["words"]
    else:
        sample = random.sample(
            already_covered, min(sample_covered, len(already_covered))
        )
        target_words = uncovered + sample

    if not target_words:
        print("All words already have sentences and --all was not passed.")
        sys.exit(0)

    vocab_lines = "\n".join(
        f"  {w['character']} — {w['pronunciation']} — {w['meaning']}"
        for w in data["words"]
    )
    target_lines = "\n".join(f"  {w['character']}" for w in target_words)

    prompt = PROMPT_TEMPLATE.format(vocab_lines=vocab_lines, target_lines=target_lines)
    PROMPT_PATH.write_text(prompt, encoding="utf-8")

    # Record the lesson with the most uncovered words so add-sentences can find it.
    target_chars = {w["character"] for w in uncovered}
    primary_stem = (
        max(
            lessons,
            key=lambda pair: sum(
                1 for w in pair[1]["words"] if w["character"] in target_chars
            ),
        )[0]
        if lessons
        else "unknown"
    )
    CURRENT_LESSON_PATH.write_text(primary_stem, encoding="utf-8")

    n_new = len(uncovered)
    n_sample = len(target_words) - n_new
    print(f"✓ Prompt written to {PROMPT_PATH}")
    print(
        f"  Targeting {n_new} new word(s) + {n_sample} resample(s) → notes/{primary_stem}.json"
    )
    print(f"  Paste its contents into Claude, save the reply as sentences.json, then:")
    print(f"    make add-sentences")


# ---------------------------------------------------------------------------
# Subcommand: add-sentences
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.S)


def _extract_json(raw: str) -> str:
    """Pull JSON out of a chatbot reply.

    Handles the common cases: a fenced ```json ... ``` block possibly
    surrounded by prose, or a bare array/object. Falls back to the whole
    string so a clean paste still works.
    """
    raw = raw.strip()
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()
    # No fence: trim any leading/trailing prose around the outermost [ ] / { }.
    start = min(
        (i for i in (raw.find("["), raw.find("{")) if i != -1),
        default=-1,
    )
    if start != -1:
        end = max(raw.rfind("]"), raw.rfind("}"))
        if end > start:
            return raw[start : end + 1].strip()
    return raw


def _resolve_lesson_stem(lesson_stem: str | None) -> str:
    if lesson_stem:
        return lesson_stem
    if CURRENT_LESSON_PATH.exists():
        stem = CURRENT_LESSON_PATH.read_text(encoding="utf-8").strip()
        print(f"  Using lesson: {stem} (from last gen-prompt)")
        return stem
    # Fall back to the most recently modified lesson file.
    lessons = load_all_lessons()
    if not lessons:
        print("✗ No lesson notes found. Run 'add-words' first.")
        sys.exit(1)
    stem = max(
        lessons,
        key=lambda pair: _lesson_path(pair[0]).stat().st_mtime,
    )[0]
    print(
        f"  Using lesson: {stem} (most recently modified — run gen-prompt for better targeting)"
    )
    return stem


def cmd_add_sentences(sentences_path: str, lesson_stem: str | None = None) -> None:
    lesson_stem = _resolve_lesson_stem(lesson_stem)
    raw = _extract_json(Path(sentences_path).read_text(encoding="utf-8"))

    try:
        sentences = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"✗ Could not parse JSON: {e}")
        sys.exit(1)

    required = {"sentence", "pronunciation", "gloss", "meaning"}
    lesson_data = load_lesson(lesson_stem)
    all_data = merge_lessons(load_all_lessons())
    already = existing_sentences(all_data)
    added = 0

    for item in sentences:
        missing = required - item.keys()
        if missing:
            print(f"  ⚠ Skipping item missing fields {missing}: {item}")
            continue
        if item["sentence"] in already:
            print(f"  Already present: {item['sentence']}")
            continue
        lesson_data["sentences"].append(
            {
                "sentence": item["sentence"],
                "pronunciation": item["pronunciation"],
                "gloss": item["gloss"],
                "meaning": item["meaning"],
            }
        )
        added += 1
        print(f"  + {item['sentence']}  ({item['meaning']})")

    save_lesson(lesson_stem, lesson_data)
    print(f"\n✓ Added {added} sentence notes to notes/{lesson_stem}.json.")
    cmd_build()


# ---------------------------------------------------------------------------
# Subcommand: add-audio
# ---------------------------------------------------------------------------

TTS_VOICE = "zh-CN-XiaoxiaoNeural"


async def _generate_audio(lessons: list[tuple[str, dict]]) -> int:
    try:
        import edge_tts
    except ImportError:
        print("  ⚠ edge-tts not installed — skipping audio (run: pipenv install)")
        return 0

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    added = 0

    for stem, data in lessons:
        all_notes = [(note, note.get("character")) for note in data["words"]] + [
            (note, note.get("sentence")) for note in data["sentences"]
        ]
        lesson_added = 0
        for note, text in all_notes:
            if not text or note.get("audio"):
                continue
            slug = re.sub(r"[^\w]", "_", text)[:20]
            # Deterministic digest so the same text always maps to the same file
            # across runs (Python's hash() is salted per-process and would not).
            digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:5]
            filename = f"{slug}_{digest}.mp3"
            audio_path = AUDIO_DIR / filename
            if not audio_path.exists():
                communicate = edge_tts.Communicate(text, TTS_VOICE)
                await communicate.save(str(audio_path))
            note["audio"] = filename
            lesson_added += 1
            print(f"  + {text} → {filename}")
        if lesson_added:
            save_lesson(stem, data)
        added += lesson_added

    return added


def cmd_add_audio() -> None:
    lessons = load_all_lessons()
    added = asyncio.run(_generate_audio(lessons))
    print(f"\n✓ Generated audio for {added} notes.")
    cmd_build()


# ---------------------------------------------------------------------------
# Subcommand: gen-gloss-prompt / add-glosses
# ---------------------------------------------------------------------------

GLOSS_PROMPT_TEMPLATE = """\
You are helping build a Chinese vocabulary Anki deck.

For each compound word below, provide a morpheme-by-morpheme gloss: break the
word into its component characters and give a brief English equivalent for each.
Use hyphens to join components (e.g. 手机 → "hand-device", 老师 → "old-master",
学生 → "study-born", 图书馆 → "picture-book-building").

Rules:
- Keep each component gloss to 1-2 English words.
- Prefer literal or etymological meanings over the compound's modern meaning.
- Do not add spaces inside the gloss; use only hyphens between components.

Return a JSON array where each element has:
  "character" — the Chinese word (exactly as given),
  "gloss"     — the morpheme gloss (hyphen-separated, all lowercase).

Return only the JSON array in a code block. Any comments should be outside the block.

If a gloss is too unnatural (for example, 俄罗斯 breaks down as "sudden-net-this",
but it actually reads as "Elosi" and means "Russia", so it's a phonetic word where the gloss is not helpful),
you can skip the word.

These are the words we don't have glosses for:
{word_lines}
"""


def cmd_gen_gloss_prompt() -> None:
    lessons = load_all_lessons()
    data = merge_lessons(lessons)
    compounds = [
        w for w in data["words"] if len(w["character"]) >= 2 and not w.get("gloss")
    ]
    if not compounds:
        print("All compound words already have glosses.")
        return

    word_lines = "\n".join(
        f"  {w['character']} — {w['pronunciation']} — {w['meaning']}" for w in compounds
    )
    prompt = GLOSS_PROMPT_TEMPLATE.format(word_lines=word_lines)
    GLOSS_PROMPT_PATH.write_text(prompt, encoding="utf-8")
    print(f"✓ Gloss prompt written to {GLOSS_PROMPT_PATH}")
    print(f"  {len(compounds)} compound word(s) without a gloss.")


def cmd_add_glosses(glosses_path: str) -> None:
    raw = _extract_json(Path(glosses_path).read_text(encoding="utf-8"))

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"✗ Could not parse JSON: {e}")
        sys.exit(1)

    lessons = load_all_lessons()
    # Build a map: character → (stem, word_dict) for fast lookup
    char_to_lesson: dict[str, tuple[str, dict, dict]] = {}
    for stem, data in lessons:
        for w in data.get("words", []):
            char_to_lesson[w["character"]] = (stem, data, w)

    added = 0
    for item in items:
        char = item.get("character", "")
        gloss = item.get("gloss", "").strip()
        if not char or not gloss:
            print(f"  ⚠ Skipping malformed item: {item}")
            continue
        if char not in char_to_lesson:
            print(f"  ⚠ Unknown character (not in any lesson): {char}")
            continue
        stem, lesson_data, word_dict = char_to_lesson[char]
        if word_dict.get("gloss"):
            print(f"  Already has gloss: {char} → {word_dict['gloss']}")
            continue
        word_dict["gloss"] = gloss
        save_lesson(stem, lesson_data)
        added += 1
        print(f"  + {char} → {gloss}")

    print(f"\n✓ Added glosses for {added} word(s).")
    cmd_build()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Chinese Anki pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser(
        "add-words", help="Look up words and add to notes/<lesson>.json"
    )
    p_add.add_argument("word_list", help="Plain text file, one word per line")
    p_add.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Prompt to choose definitions for each word (Wiktionary shown first)",
    )

    sub.add_parser("build", help="Build chinese.apkg from all lesson notes")

    p_gen = sub.add_parser("gen-prompt", help="Generate Claude prompt → prompt.txt")
    p_gen.add_argument(
        "--all",
        dest="target_all",
        action="store_true",
        help="Target every word, not just those without sentences",
    )
    p_gen.add_argument(
        "--resample",
        type=int,
        default=2,
        metavar="N",
        help="How many already-covered words to resample (default: 2)",
    )

    p_sent = sub.add_parser("add-sentences", help="Add Claude's sentence output")
    p_sent.add_argument("sentences_json", help="JSON file from Claude")
    p_sent.add_argument(
        "--lesson",
        default=None,
        metavar="STEM",
        help="Lesson stem to store sentences in (default: auto-detected from last gen-prompt)",
    )

    sub.add_parser("add-audio", help="Generate TTS audio with edge-tts")

    sub.add_parser(
        "gen-gloss-prompt",
        help="Generate Claude prompt for word glosses → gloss_prompt.txt",
    )

    p_gloss = sub.add_parser("add-glosses", help="Add Claude's word gloss output")
    p_gloss.add_argument("glosses_json", help="JSON file from Claude")

    sub.add_parser("wizard", help="Guided interactive flow (recommended for new users)")

    args = parser.parse_args()
    ensure_dirs()

    if args.cmd == "add-words":
        cmd_add_words(args.word_list, interactive=args.interactive)
    elif args.cmd == "build":
        cmd_build()
    elif args.cmd == "gen-prompt":
        cmd_gen_prompt(target_all=args.target_all, sample_covered=args.resample)
    elif args.cmd == "add-sentences":
        cmd_add_sentences(args.sentences_json, lesson_stem=args.lesson)
    elif args.cmd == "add-audio":
        cmd_add_audio()
    elif args.cmd == "gen-gloss-prompt":
        cmd_gen_gloss_prompt()
    elif args.cmd == "add-glosses":
        cmd_add_glosses(args.glosses_json)
    elif args.cmd == "wizard":
        import wizard

        wizard.run()


if __name__ == "__main__":
    main()
