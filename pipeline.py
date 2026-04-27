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
import json
import random
import re
import sys
from pathlib import Path

import cedict
import deck as deckmod
import hanzi_data as hzmod
import wiktionary as wkt

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE = Path(__file__).parent
DICT_PATH = BASE / "data" / "cedict.txt.gz"
NOTES_DIR = BASE / "notes"
NOTES_PATH = BASE / "notes.json"  # legacy single-file path
APKG_PATH = BASE / "chinese.apkg"
PROMPT_PATH = BASE / "prompt.txt"
CURRENT_LESSON_PATH = BASE / ".current_lesson"
AUDIO_DIR = BASE / "data" / "audio"

# ---------------------------------------------------------------------------
# Per-lesson notes helpers
# ---------------------------------------------------------------------------


def _lesson_path(stem: str) -> Path:
    return NOTES_DIR / f"{stem}.json"


def load_lesson(stem: str) -> dict:
    path = _lesson_path(stem)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"words": [], "sentences": []}


def save_lesson(stem: str, data: dict) -> None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    with open(_lesson_path(stem), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_all_lessons() -> list[tuple[str, dict]]:
    """Return [(stem, data), ...] for every notes/<stem>.json file.

    Falls back to the legacy notes.json with a warning when notes/ is empty.
    """
    if NOTES_DIR.exists():
        lessons = []
        for path in sorted(NOTES_DIR.glob("*.json")):
            with open(path, encoding="utf-8") as f:
                lessons.append((path.stem, json.load(f)))
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
# Meaning cleaning
# ---------------------------------------------------------------------------


def _clean_meaning(meaning: str) -> str:
    """Remove classifier (CL:) entries from a semicolon-separated meaning string."""
    parts = [p.strip() for p in meaning.split(";")]
    parts = [p for p in parts if p and not p.startswith("CL:")]
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Entry selection: prefer non-surname, non-abbreviation entries
# ---------------------------------------------------------------------------

_DEPRIORITIZE = re.compile(r"^(surname|abbr\.|variant of|old variant|see )", re.I)


def _best_entry(entries: list) -> object:
    for entry in entries:
        if not _DEPRIORITIZE.match(entry.definitions[0]):
            return entry
    return entries[0]


# ---------------------------------------------------------------------------
# Subcommand: add-words
# ---------------------------------------------------------------------------


def _collect_definitions(word: str, index: dict) -> tuple[str, list[tuple[str, str]]]:
    """
    Return (pinyin, [(label, definition), ...]) from Wiktionary then CEDICT.
    Pinyin comes from whichever source finds it first.
    """
    defs: list[tuple[str, str]] = []
    pinyin = ""

    wkt_entries = wkt.lookup(word)
    if wkt_entries:
        e = wkt_entries[0]
        pinyin = e.pinyin
        for d in e.definitions:
            cleaned = _clean_meaning(d)
            if cleaned:
                defs.append(("wiktionary", cleaned))

    cedict_entries = cedict.lookup(index, word)
    if cedict_entries:
        entry = _best_entry(cedict_entries)
        if not pinyin or re.search(r'[一-鿿]', pinyin):
            pinyin = entry.pinyin.lower()
        for d in entry.definitions:
            cleaned = _clean_meaning(d)
            if cleaned:
                defs.append(("cedict", cleaned))

    return pinyin, defs


def _prompt_word(word: str, pinyin: str, defs: list[tuple[str, str]]) -> tuple[str, str]:
    """Interactively ask the user to confirm/correct pinyin and choose definitions.

    Returns (pinyin, meaning).
    """
    print(f"\n  {word}  [{pinyin}]")
    for i, (source, d) in enumerate(defs, 1):
        print(f"    {i:2}. [{source}] {d}")

    # --- Pinyin ---
    pinyin_input = input(f"  Pinyin [Enter to keep '{pinyin}']: ").strip()
    if pinyin_input:
        pinyin = pinyin_input

    # --- Meaning ---
    default_indices = [1] if defs else []
    default_str = ",".join(str(i) for i in default_indices)

    while True:
        raw = input(
            f"  Select numbers (e.g. 1,3), type a custom meaning, or Enter for [{default_str}]: "
        ).strip()

        if not raw:
            if not defs:
                print("  No definitions available — type a custom meaning.")
                continue
            chosen = [defs[i - 1][1] for i in default_indices]
            return pinyin, "; ".join(chosen)

        parts = [p.strip() for p in raw.split(",")]
        if all(p.isdigit() for p in parts):
            indices = [int(p) for p in parts]
            invalid = [i for i in indices if i < 1 or i > len(defs)]
            if invalid:
                print(f"  Invalid numbers: {invalid}. Choose from 1–{len(defs)}.")
                continue
            chosen = [defs[i - 1][1] for i in indices]
            return pinyin, "; ".join(chosen)

        return pinyin, raw


def cmd_add_words(word_list_path: str, interactive: bool = False) -> None:
    print(f"Loading dictionary from {DICT_PATH} …")
    index = cedict.load(DICT_PATH)
    print("Dictionary loaded.")

    stem = Path(word_list_path).stem
    lesson_data = load_lesson(stem)
    all_data = merge_lessons(load_all_lessons())
    already = existing_characters(all_data)

    words_raw = Path(word_list_path).read_text(encoding="utf-8").splitlines()
    words = [w.strip() for w in words_raw if w.strip() and not w.startswith("#")]

    added, skipped, not_found = [], [], []

    for word in words:
        if word in already:
            skipped.append(word)
            continue

        if interactive:
            pinyin, defs = _collect_definitions(word, index)
            if not pinyin:
                not_found.append(word)
                print(f"  '{word}' not found in any source — skipping.")
                continue
            pinyin, meaning = _prompt_word(word, pinyin, defs)
        else:
            entries = cedict.lookup(index, word)
            if entries:
                entry = _best_entry(entries)
                pinyin = entry.pinyin.lower()
                meaning = _clean_meaning(entry.meaning)
                print(f"  + {word}  [{pinyin}]  {meaning}  (cedict)")
            else:
                print(f"  '{word}' not in CEDICT, trying Wiktionary …")
                wkt_entries = wkt.lookup(word)
                if not wkt_entries:
                    not_found.append(word)
                    continue
                pinyin = wkt_entries[0].pinyin
                meaning = _clean_meaning(wkt_entries[0].meaning)
                print(f"  + {word}  [{pinyin}]  {meaning}  (wiktionary)")

        note = {
            "character": word,
            "pronunciation": pinyin,
            "meaning": meaning,
        }
        lesson_data["words"].append(note)
        added.append(word)
        if interactive:
            print(f"  + {word}  [{pinyin}]  {meaning}")

    save_lesson(stem, lesson_data)

    print(f"\n✓ Added {len(added)} new words to notes/{stem}.json.")
    if skipped:
        print(f"  Already present (skipped): {', '.join(skipped)}")
    if not_found:
        print(f"\n⚠ Not found in dictionary — add manually to notes/{stem}.json:")
        for w in not_found:
            print(f"    {w}")


# ---------------------------------------------------------------------------
# Subcommand: build
# ---------------------------------------------------------------------------


def cmd_build() -> None:
    lessons = load_all_lessons()
    if not lessons:
        print("No lesson notes found. Run 'add-words' first.")
        sys.exit(1)

    data = merge_lessons(lessons)
    all_chars = [w["character"] for w in data["words"]]
    all_chars += [s["sentence"] for s in data["sentences"]]

    print("Fetching hanzi-writer assets …")
    hw_js, data_js = hzmod.build_assets(all_chars)

    print("Rendering font images …")
    import font_render as fntmod

    font_imgs = fntmod.build_char_images(all_chars)

    media = [str(hw_js), str(data_js)] + [str(p) for p in font_imgs]
    for note in data["words"] + data["sentences"]:
        if note.get("audio"):
            audio_path = AUDIO_DIR / note["audio"]
            if audio_path.exists():
                media.append(str(audio_path))

    # Write a merged notes file for deckmod (it expects a single JSON path)
    merged_path = BASE / "notes_merged.json"
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    deckmod.build_apkg(str(merged_path), str(APKG_PATH), media_files=media)


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
    primary_stem = max(
        lessons,
        key=lambda pair: sum(1 for w in pair[1]["words"] if w["character"] in target_chars),
    )[0] if lessons else "unknown"
    CURRENT_LESSON_PATH.write_text(primary_stem, encoding="utf-8")

    n_new = len(uncovered)
    n_sample = len(target_words) - n_new
    print(f"✓ Prompt written to {PROMPT_PATH}")
    print(f"  Targeting {n_new} new word(s) + {n_sample} resample(s) → notes/{primary_stem}.json")
    print(f"  Paste its contents into Claude, save the reply as sentences.json, then:")
    print(f"    make add-sentences")


# ---------------------------------------------------------------------------
# Subcommand: add-sentences
# ---------------------------------------------------------------------------


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
    print(f"  Using lesson: {stem} (most recently modified — run gen-prompt for better targeting)")
    return stem


def cmd_add_sentences(sentences_path: str, lesson_stem: str | None = None) -> None:
    lesson_stem = _resolve_lesson_stem(lesson_stem)
    raw = Path(sentences_path).read_text(encoding="utf-8").strip()

    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

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
            filename = f"{slug}_{abs(hash(text)) % 100000:05d}.mp3"
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

    args = parser.parse_args()

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


if __name__ == "__main__":
    main()
