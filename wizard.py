"""
wizard.py — Guided interactive flow for the Chinese Anki pipeline.

Wraps the existing pipeline subcommands behind a single menu so a beginner
doesn't need to remember argparse incantations. First run drops straight into
"add your first lesson"; subsequent runs land on the main menu.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pipeline as pl

try:
    import questionary

    _HAS_Q = True
except ImportError:
    _HAS_Q = False

try:
    import pyperclip

    _HAS_CLIP = True
except ImportError:
    _HAS_CLIP = False


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------


def _title(text: str) -> None:
    bar = "═" * (len(text) + 4)
    print(f"\n{bar}\n  {text}\n{bar}")


def _menu(prompt: str, options: list[tuple[str, str]]) -> str:
    """Show *options* (label, value). Return chosen value (or '' on cancel)."""
    if _HAS_Q:
        choice = questionary.select(
            prompt,
            choices=[questionary.Choice(title=lbl, value=val) for lbl, val in options],
        ).ask()
        return choice or ""
    print(f"\n{prompt}")
    for i, (lbl, _) in enumerate(options, 1):
        print(f"  {i}. {lbl}")
    while True:
        raw = input("> ").strip()
        if not raw:
            return ""
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][1]
        print("  Pick a number from the list.")


def _ask_text(prompt: str, default: str = "") -> str:
    if _HAS_Q:
        out = questionary.text(prompt, default=default).ask()
        return (out or "").strip()
    suffix = f" [{default}]" if default else ""
    out = input(f"{prompt}{suffix}: ").strip()
    return out or default


def _confirm(prompt: str, default: bool = True) -> bool:
    if _HAS_Q:
        return bool(questionary.confirm(prompt, default=default).ask())
    suffix = "Y/n" if default else "y/N"
    out = input(f"{prompt} [{suffix}] ").strip().lower()
    if not out:
        return default
    return out.startswith("y")


# ---------------------------------------------------------------------------
# Lesson-name sanitization
# ---------------------------------------------------------------------------


def _slug(name: str) -> str:
    slug = re.sub(r"[^\w]+", "_", name.strip().lower()).strip("_")
    return slug or "lesson"


# ---------------------------------------------------------------------------
# Word collection
# ---------------------------------------------------------------------------


def _tokenize_words(blob: str) -> list[str]:
    """Split a paste-blob into word tokens.

    Lines may contain comma- or space-separated words, or one per line. A
    sequence of consecutive Han characters with no separator is treated as
    individual single-character words.
    """
    out: list[str] = []
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[\s,，、]+", line)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(p) > 1 and not _looks_multichar(p):
                out.extend(list(p))
            else:
                out.append(p)
    seen = set()
    deduped = []
    for w in out:
        if w not in seen:
            deduped.append(w)
            seen.add(w)
    return deduped


def _looks_multichar(token: str) -> bool:
    """Heuristic: treat a token as one word if it contains non-Han chars
    OR if the user clearly intended it (single-line entry)."""
    return bool(re.search(r"[^一-鿿]", token))


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _pending_path(stem: str) -> Path:
    return pl.PROCESSED_DIR / f"{stem}_pending.txt"


def _deck_out_of_date() -> bool:
    """True if a lesson file is newer than the built deck (or no deck yet)."""
    if not pl.APKG_PATH.exists():
        return bool(pl.load_all_lessons())
    deck_mtime = pl.APKG_PATH.stat().st_mtime
    return any(
        p.stat().st_mtime > deck_mtime for p in pl.NOTES_DIR.glob("*.json")
    )


def _offer_build() -> None:
    """Nudge the user to (re)build when their notes are ahead of the deck."""
    if _deck_out_of_date() and _confirm(
        "Build the deck now so it's ready to import?", default=True
    ):
        action_build()


def _read_ai_reply() -> str:
    """Get the chatbot's reply, preferring the clipboard over manual paste.

    The literal <<<END>>> sentinel is error-prone for non-technical users, so
    when pyperclip is available we just read what they copied. The manual paste
    path stays as a fallback.
    """
    if _HAS_CLIP and _confirm("Read the reply straight from your clipboard?", default=True):
        try:
            text = pyperclip.paste() or ""
        except Exception:
            text = ""
        if text.strip():
            print(f"  ✓ Read {len(text)} characters from the clipboard.")
            return text.strip()
        print("  Clipboard was empty — paste the reply below instead.")

    print("  Paste the reply, then type <<<END>>> on its own line.\n")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "<<<END>>>":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _review_tokens(words: list[str]) -> list[str]:
    """Show detected words and let the user re-join any that got split apart.

    The tokenizer splits a run of Han characters into single characters, which
    is wrong for a deliberately-entered compound like 你好. This lets the user
    fix that before the (slow, per-word) definition picker runs.
    """
    while True:
        print("\n  Words detected:")
        for i, w in enumerate(words, 1):
            print(f"   {i:2}. {w}")
        print(
            "\n  If a multi-character word was split into single characters, type"
            "\n  the numbers to join (e.g. '3 4' joins items 3 and 4). Enter if OK."
        )
        raw = _ask_text("Numbers to join")
        if not raw:
            return words
        idxs = sorted(
            {int(x) for x in raw.split() if x.isdigit() and 1 <= int(x) <= len(words)}
        )
        if len(idxs) < 2:
            print("  Give at least two numbers from the list to join.")
            continue
        merged = "".join(words[i - 1] for i in idxs)
        rest = idxs[1:]
        words = [
            merged if i == idxs[0] else w
            for i, w in enumerate(words, 1)
            if i == idxs[0] or i not in rest
        ]


def action_new_lesson() -> None:
    _title("Add words to a lesson")
    existing = pl.load_all_lessons()

    if existing:
        options = [(stem, stem) for stem, _ in existing]
        options.append(("── create a new lesson", "__new__"))
        stem = _menu("Which lesson?", options)
        if not stem:
            print("  Cancelled.")
            return
        if stem == "__new__":
            name = _ask_text("New lesson name (e.g. 'book lesson 5')")
            if not name:
                print("  Cancelled.")
                return
            stem = _slug(name)
    else:
        name = _ask_text("Lesson name (e.g. 'book lesson 5')")
        if not name:
            print("  Cancelled.")
            return
        stem = _slug(name)

    print(f"  → notes/{stem}.json")

    # Check for an interrupted session for this lesson
    pending = _pending_path(stem)
    if pending.exists():
        remaining = [
            l.strip()
            for l in pending.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        if remaining:
            print(
                f"\n  Found an interrupted session with {len(remaining)} word(s) still pending:"
            )
            print(f"  {' '.join(remaining[:15])}{'…' if len(remaining) > 15 else ''}")
            if _confirm("Resume from where you left off?", default=True):
                pl.add_words(remaining, stem, interactive=True, pending_file=pending)
                _offer_build()
                return
            else:
                pending.unlink(missing_ok=True)

    how = _menu(
        "How do you want to add words?",
        [
            ("Paste a block of words (recommended)", "paste"),
            ("Type words one at a time", "one"),
            ("Load from a text file", "file"),
        ],
    )

    words: list[str] = []
    if how == "paste":
        print("\n  Paste your words. Multi-character words like 你好 should be on")
        print("  their own line or separated by commas/spaces. A single line of")
        print("  Han characters with no separators is treated as one word per char.")
        print("  End with a blank line.\n")
        buf = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if not line.strip():
                if buf:
                    break
                continue
            buf.append(line)
        words = _tokenize_words("\n".join(buf))
        if words:
            words = _review_tokens(words)
    elif how == "one":
        print("  Enter one word per line. Blank line to finish.")
        while True:
            w = input("  word: ").strip()
            if not w:
                break
            words.append(w)
    elif how == "file":
        path = _ask_text("Path to text file (one word per line)")
        if not path or not Path(path).exists():
            print("  File not found — cancelled.")
            return
        words = _tokenize_words(Path(path).read_text(encoding="utf-8"))
        if words:
            words = _review_tokens(words)
    else:
        return

    if not words:
        print("  No words provided.")
        return

    print(
        f"\n  Found {len(words)} words: {' '.join(words[:10])}{' …' if len(words) > 10 else ''}"
    )
    if not _confirm("Run the definition picker for each new word?", default=True):
        return

    # Write pending file before starting — removed word-by-word as picks are saved
    pending.parent.mkdir(exist_ok=True)
    pending.write_text("\n".join(words) + "\n", encoding="utf-8")

    pl.add_words(words, stem, interactive=True, pending_file=pending)

    # Clean up if everything completed (file is already empty/gone if all processed)
    pending.unlink(missing_ok=True)

    _offer_build()


def _sentence_violation_handler(violations: list[tuple[str, list[str]]]) -> bool:
    """Surface out-of-vocabulary sentences; return True to add them anyway.

    Offers to copy a correction request to the clipboard so the user can have
    the AI fix the sentences and re-run, instead of accepting unknown characters.
    """
    print("\n  ⚠ Some sentences use characters outside your vocabulary:")
    for sent, chars in violations:
        print(f"    {sent}   (new: {' '.join(chars)})")

    choice = _menu(
        "What do you want to do?",
        [
            ("Ask the AI to fix them (copy a correction request)", "fix"),
            ("Keep them anyway", "keep"),
            ("Cancel — add nothing", "cancel"),
        ],
    )
    if choice == "keep":
        return True
    if choice == "fix":
        msg = pl.correction_prompt(violations)
        copied = False
        if _HAS_CLIP:
            try:
                pyperclip.copy(msg)
                copied = True
            except Exception:
                copied = False
        if copied:
            print("\n  ✓ Correction request copied to your clipboard.")
        else:
            print(f"\n  Paste this to the chatbot:\n\n{msg}\n")
        print(
            "  Send it to the chatbot, then choose 'Generate example sentences'"
            "\n  again and paste the corrected reply."
        )
    return False


def action_gen_sentences() -> None:
    _title("Generate example sentences")
    lessons = pl.load_all_lessons()
    if not lessons:
        print("  No lessons yet — add one first.")
        return

    pl.cmd_gen_prompt(target_all=False)

    prompt_text = pl.PROMPT_PATH.read_text(encoding="utf-8")
    if _HAS_CLIP:
        try:
            pyperclip.copy(prompt_text)
            print("\n  ✓ Prompt copied to your clipboard.")
        except Exception:
            print(f"\n  Prompt is in {pl.PROMPT_PATH}.")
    else:
        print(f"\n  Prompt is in {pl.PROMPT_PATH}.")
        print("  (Install pyperclip to auto-copy: pip install pyperclip)")

    print("\n  Next steps:")
    print("    1. Open https://claude.ai or your favorite chatbot")
    print("    2. Paste the prompt and send it")
    print("    3. Copy Claude's reply (the whole JSON code block is fine)")

    if not _confirm("\n  Ready with the reply?", default=True):
        print("  You can resume later by picking 'Generate example sentences' again.")
        return

    raw = _read_ai_reply()
    if not raw:
        print("  Nothing to read — cancelled.")
        return

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        f.write(raw)
        tmp = f.name
    try:
        pl.cmd_add_sentences(tmp, violation_handler=_sentence_violation_handler)
    finally:
        Path(tmp).unlink(missing_ok=True)


def action_gen_glosses() -> None:
    _title("Generate word morpheme glosses")
    pl.cmd_gen_gloss_prompt()

    prompt_text = pl.GLOSS_PROMPT_PATH.read_text(encoding="utf-8")
    if _HAS_CLIP:
        try:
            pyperclip.copy(prompt_text)
            print("\n  ✓ Prompt copied to your clipboard.")
        except Exception:
            print(f"\n  Prompt is in {pl.GLOSS_PROMPT_PATH}.")
    else:
        print(f"\n  Prompt is in {pl.GLOSS_PROMPT_PATH}.")

    print("\n  Next steps:")
    print("    1. Open https://claude.ai or your favorite chatbot")
    print("    2. Paste the prompt and send it")
    print("    3. Copy Claude's reply (the whole JSON code block is fine)")

    if not _confirm("\n  Ready with the reply?", default=True):
        print("  You can resume later by picking 'Generate word glosses' again.")
        return

    raw = _read_ai_reply()
    if not raw:
        print("  Nothing to read — cancelled.")
        return

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        f.write(raw)
        tmp = f.name
    try:
        pl.cmd_add_glosses(tmp)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _notes_in_other_voice(voice: str) -> int:
    """How many notes already have audio in a voice other than *voice*."""
    count = 0
    for _, data in pl.load_all_lessons():
        notes = [(w, w.get("character")) for w in data.get("words", [])] + [
            (s, s.get("sentence")) for s in data.get("sentences", [])
        ]
        for note, text in notes:
            cur = note.get("audio")
            if cur and text and cur != pl._audio_filename(text, voice):
                count += 1
    return count


def action_add_audio() -> None:
    _title("Add pronunciation audio")
    if not _confirm(
        "This downloads TTS audio for every new note. Continue?", default=True
    ):
        return
    voice = _menu(
        "Which voice?",
        [(label, key) for key, label in pl.TTS_VOICES.items()],
    )
    if not voice:
        voice = pl.TTS_VOICE

    other = _notes_in_other_voice(voice)
    revoice = False
    if other:
        revoice = _confirm(
            f"{other} note(s) already have audio in a different voice — "
            "re-generate those in this voice too?",
            default=False,
        )
    else:
        print("  (Only notes without audio yet will be generated.)")
    pl.cmd_add_audio(voice, revoice=revoice)


def action_edit_lesson() -> None:
    _title("Review / edit a lesson")
    lessons = pl.load_all_lessons()
    if not lessons:
        print("  No lessons yet — add one first.")
        return

    stem = _menu("Which lesson?", [(s, s) for s, _ in lessons])
    if not stem:
        return
    data = pl.load_lesson(stem)
    index = None  # lazily loaded CC-CEDICT, only if a word is re-picked
    changed = False

    while True:
        words = data.get("words", [])
        sentences = data.get("sentences", [])
        if not words and not sentences:
            print("  This lesson is empty.")
            break

        options: list[tuple[str, str]] = []
        for i, w in enumerate(words):
            options.append(
                (f"word: {w['character']}  [{w['pronunciation']}]  {w['meaning']}", f"w{i}")
            )
        for i, s in enumerate(sentences):
            options.append((f"sentence: {s['sentence']}  ({s['meaning']})", f"s{i}"))
        options.append(("── done", "done"))

        choice = _menu("Pick a note to edit or delete", options)
        if choice in ("", "done"):
            break

        kind, idx = choice[0], int(choice[1:])
        note = words[idx] if kind == "w" else sentences[idx]
        label = note["character"] if kind == "w" else note["sentence"]

        what = _menu(
            f"{label} —",
            [
                ("Re-pick definition" if kind == "w" else "Edit translation", "edit"),
                ("Delete", "delete"),
                ("Back", "back"),
            ],
        )
        if what == "delete":
            if _confirm(f"Delete '{label}'?", default=False):
                (words if kind == "w" else sentences).pop(idx)
                pl.save_lesson(stem, data)
                changed = True
                print("  Deleted.")
        elif what == "edit":
            if kind == "w":
                if index is None:
                    print("  Loading dictionary …")
                    index = pl.cedict.load(pl.DICT_PATH)
                result = pl.definition_picker.pick(note["character"], index)
                if not result.skipped and result.meaning:
                    note["pronunciation"] = result.pinyin
                    note["meaning"] = result.meaning
                    pl.save_lesson(stem, data)
                    changed = True
            else:
                new_meaning = _ask_text("New translation", default=note["meaning"])
                if new_meaning and new_meaning != note["meaning"]:
                    note["meaning"] = new_meaning
                    pl.save_lesson(stem, data)
                    changed = True

    if changed:
        _offer_build()


def action_build() -> None:
    _title("Build & export deck")
    pl.cmd_build()
    apkg = pl.APKG_PATH.resolve()
    print(f"\n  Deck written to: {apkg}")
    print("  Import into Anki: File → Import → select the .apkg file.")
    if _confirm("Open the folder containing the deck?", default=False):
        _open_path(apkg.parent)


def action_status() -> None:
    _title("Status")
    lessons = pl.load_all_lessons()
    if not lessons:
        print("  No lessons yet.")
        return
    total_words = 0
    total_sentences = 0
    total_no_sent = 0
    total_notes = 0
    total_audio = 0
    for stem, data in lessons:
        n_w = len(data.get("words", []))
        n_s = len(data.get("sentences", []))
        n_no_sent = n_w - len(pl.words_with_sentences(data))
        all_notes = data.get("words", []) + data.get("sentences", [])
        n_audio = sum(1 for n in all_notes if n.get("audio"))
        total_words += n_w
        total_sentences += n_s
        total_no_sent += n_no_sent
        total_notes += len(all_notes)
        total_audio += n_audio
        print(
            f"  {stem}: {n_w} words, {n_s} sentences, "
            f"{n_no_sent} word(s) without sentence, {n_audio} note(s) with audio"
        )
    print(
        f"\n  Total: {total_words} words, {total_sentences} sentences across {len(lessons)} lesson(s)."
    )
    print(f"  Deck: {'built' if pl.APKG_PATH.exists() else 'not built yet'}")

    # Turn the numbers into concrete next steps.
    suggestions: list[str] = []
    if total_no_sent:
        suggestions.append(
            f"{total_no_sent} word(s) have no example sentence → 'Generate example sentences'"
        )
    if total_audio < total_notes:
        suggestions.append(
            f"{total_notes - total_audio} note(s) have no audio → 'Add pronunciation audio'"
        )
    if _deck_out_of_date():
        suggestions.append("your notes changed since the last build → 'Build & export deck'")
    if suggestions:
        print("\n  Suggested next steps:")
        for s in suggestions:
            print(f"    • {s}")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def _open_path(path: Path) -> None:
    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(path)])
    except FileNotFoundError:
        pass


def _is_first_run() -> bool:
    return not pl.load_all_lessons()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


WELCOME = """\
  Welcome! This wizard helps you build a Chinese Anki deck.

  The flow is:
    1. Add a lesson — type or paste the words you've learned.
       For each word, you'll pick which definitions to keep.
    2. (Optional) Generate example sentences with AI.
    3. (Optional) Add audio for pronunciation.
    4. Build the deck → import the .apkg into Anki.

  You can come back to this menu any time by running the same command."""


def run() -> None:
    pl.ensure_dirs()
    if not _HAS_Q:
        print("  (Tip: pip install questionary for arrow-key menus.)")

    if _is_first_run():
        _title("Chinese Anki Pipeline")
        print(WELCOME)
        if _confirm("\nReady to add your first lesson?", default=True):
            action_new_lesson()

    while True:
        choice = _menu(
            "What now?",
            [
                ("Add words to a lesson", "new"),
                ("Review / edit a lesson", "edit"),
                ("Generate example sentences (via AI)", "sent"),
                ("Generate word morpheme glosses (via AI)", "glosses"),
                ("Add pronunciation audio", "audio"),
                ("Build & export deck", "build"),
                ("Show status", "status"),
                ("Quit", "quit"),
            ],
        )
        if choice in ("", "quit"):
            print("  Bye!")
            return
        try:
            {
                "new": action_new_lesson,
                "edit": action_edit_lesson,
                "sent": action_gen_sentences,
                "glosses": action_gen_glosses,
                "audio": action_add_audio,
                "build": action_build,
                "status": action_status,
            }[choice]()
        except KeyboardInterrupt:
            print("\n  (interrupted — back to menu)")


if __name__ == "__main__":
    run()
