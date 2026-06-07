"""
paths.py — Central location for every file path the app touches.

Two distinct roots:

  RESOURCE_DIR  read-only assets that ship *with* the program (the CC-CEDICT
                dictionary, and anything bundled into a PyInstaller build).
                When frozen this is the PyInstaller temp dir (sys._MEIPASS);
                otherwise it's the source tree.

  DATA_DIR      everything the user creates or the build caches: lessons,
                pick cache, downloaded stroke/font assets, audio, and the
                output .apkg. Must be writable.

Why this split exists: a PyInstaller .exe unpacks itself into a read-only temp
directory, so a frozen build cannot write next to its own code. When frozen we
put user data in a "chinese-anki-data" folder beside the executable (override
with the CHINESE_DECK_DATA env var). When running from source, both roots are
the project directory, so behaviour is identical to before this module existed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def force_utf8() -> None:
    """Make stdout/stderr UTF-8.

    We print ✓/⚠/✗ and Chinese text everywhere; on a Windows console (cp1252)
    that raises UnicodeEncodeError and takes the whole program down. Call this
    once at every entry point before any printing.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


# --- Read-only resource root -------------------------------------------------

if is_frozen():
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    RESOURCE_DIR = Path(__file__).resolve().parent


# --- Writable user-data root -------------------------------------------------


def _default_data_dir() -> Path:
    if is_frozen():
        # Beside the executable so users can find their lessons/deck easily.
        return Path(sys.executable).resolve().parent / "chinese-anki-data"
    return Path(__file__).resolve().parent


_env = os.environ.get("CHINESE_DECK_DATA")
DATA_DIR = Path(_env).expanduser().resolve() if _env else _default_data_dir()


# --- Resource paths (read-only) ----------------------------------------------

DICT_PATH = RESOURCE_DIR / "data" / "cedict.txt.gz"

# --- User-data paths (writable) ----------------------------------------------

NOTES_DIR = DATA_DIR / "notes"
NOTES_PATH = DATA_DIR / "notes.json"  # legacy single-file path
PROCESSED_DIR = DATA_DIR / ".processed"
CACHE_DIR = DATA_DIR / "data"  # downloaded/generated assets live here
AUDIO_DIR = CACHE_DIR / "audio"
APKG_PATH = DATA_DIR / "chinese.apkg"
PROMPT_PATH = DATA_DIR / "prompt.txt"
GLOSS_PROMPT_PATH = DATA_DIR / "gloss_prompt.txt"
CURRENT_LESSON_PATH = DATA_DIR / ".current_lesson"


def ensure_dirs() -> None:
    """Create the writable directories a fresh (e.g. frozen) install needs."""
    for d in (NOTES_DIR, PROCESSED_DIR, CACHE_DIR, AUDIO_DIR):
        d.mkdir(parents=True, exist_ok=True)
