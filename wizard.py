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
    print("    4. Paste it below, then type <<<END>>> on its own line\n")

    if not _confirm("Ready to paste the reply?", default=True):
        print("  You can resume later by picking 'Generate example sentences' again.")
        return

    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "<<<END>>>":
            break
        lines.append(line)

    raw = "\n".join(lines).strip()
    if not raw:
        print("  Nothing pasted — cancelled.")
        return

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        f.write(raw)
        tmp = f.name
    try:
        pl.cmd_add_sentences(tmp)
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
    print("    4. Paste it below, then type <<<END>>> on its own line\n")

    if not _confirm("Ready to paste the reply?", default=True):
        print("  You can resume later by picking 'Generate word glosses' again.")
        return

    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "<<<END>>>":
            break
        lines.append(line)

    raw = "\n".join(lines).strip()
    if not raw:
        print("  Nothing pasted — cancelled.")
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


def action_add_audio() -> None:
    _title("Add pronunciation audio")
    if not _confirm(
        "This downloads TTS audio for every new note. Continue?", default=True
    ):
        return
    pl.cmd_add_audio()


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
    for stem, data in lessons:
        n_w = len(data.get("words", []))
        n_s = len(data.get("sentences", []))
        n_no_sent = n_w - len(pl.words_with_sentences(data))
        n_audio = sum(
            1
            for n in data.get("words", []) + data.get("sentences", [])
            if n.get("audio")
        )
        total_words += n_w
        total_sentences += n_s
        print(
            f"  {stem}: {n_w} words, {n_s} sentences, "
            f"{n_no_sent} word(s) without sentence, {n_audio} note(s) with audio"
        )
    print(
        f"\n  Total: {total_words} words, {total_sentences} sentences across {len(lessons)} lesson(s)."
    )
    print(f"  Deck: {'built' if pl.APKG_PATH.exists() else 'not built yet'}")


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
