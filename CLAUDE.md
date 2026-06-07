# CLAUDE.md — Chinese Anki Pipeline

Project notes for working in this repo. Builds Anki flashcard decks for Chinese
vocabulary from word lists, enriched with stroke-order animation/quiz, multi-font
glyph images, AI-generated example sentences, morpheme glosses, and TTS audio.
Distributed both as source and as a standalone PyInstaller executable.

## How to run

- Packaged app: download from GitHub Releases, run it — drops into the wizard,
  creates `chinese-anki-data/` beside the executable for all user data.
- From source: `./start.sh` / `start.bat` (bootstraps `.venv`, launches wizard),
  or `python pipeline.py wizard`, or the `python pipeline.py <subcommand>` CLI.

Output deck: `chinese.apkg` → Anki File → Import.

## Architecture

Data flow: **word list → lessons (`notes/*.json`) → merged → genanki → `.apkg`**.

| File | Role |
|------|------|
| [paths.py](paths.py) | **Single source of every path.** Splits read-only `RESOURCE_DIR` (bundled assets; `sys._MEIPASS` when frozen) from writable `DATA_DIR` (lessons, caches, output). When frozen, `DATA_DIR` is `chinese-anki-data/` beside the exe (override via `CHINESE_DECK_DATA`); from source both roots are the project dir, so behaviour is unchanged. |
| [app.py](app.py) | PyInstaller entry point — runs the wizard, keeps the console open on Windows. |
| [pipeline.py](pipeline.py) | Orchestrator + CLI. Lesson load/save/merge/validate, `cmd_*` subcommands, AI prompt templates, card ordering. |
| [wizard.py](wizard.py) | Interactive menu wrapping the `cmd_*` functions. Paste/file/one-at-a-time input, clipboard, resumable sessions. |
| [definition_picker.py](definition_picker.py) | Interactive definition selection (questionary checkbox or numbered fallback). Merges + dedups Wiktionary/CC-CEDICT candidates, caches picks. |
| [cedict.py](cedict.py) | CC-CEDICT parser/lookup, tone-number→diacritic pinyin, and the shared `clean_meaning`/`best_entry` helpers. |
| [wiktionary.py](wiktionary.py) | English Wiktionary lookup; follows one `{{zh-see}}` redirect; parses `{{zh-pron m=}}` + top definitions. |
| [hanzi_data.py](hanzi_data.py) | Provides hanzi-writer JS + per-char stroke JSON: **bundled `hanzi_assets/` first**, then local cache, then CDN download. `stroke_count()` (used by the ordering heuristic) reads the same sources. |
| [font_render.py](font_render.py) | Renders each CJK char as PNG in Sans/Serif/Kai. Resolves **bundled `fonts/` first**, then `fc-match`, then the always-present Kai — never crashes, never needs network when bundled. |
| [deck.py](deck.py) | genanki models + templates. Word (9 cards), sentence (10), gloss (2). Each model has an `Audio` field (separate from pronunciation text) so audio plays once on the answer side; a `_listen_template` adds a front-audio listening card, gated by `{{#Audio}}` so it only exists when the note has audio. Stroke cards reveal the animated answer instead of re-running the quiz; animations are click-to-replay. Embeds the hanzi-writer animation/quiz JS and multi-font JS. |

### Data layout

- `notes/<stem>.json` — **the only source the user edits.** Shape:
  `{"version": 1, "words": [...], "sentences": [...]}`.
  Word: `{character, pronunciation, meaning, gloss?, audio?, priority?}`.
  Sentence: `{sentence, pronunciation, gloss, meaning, audio?, priority?}`.
  Each file carries a `"version"` marker. Loading runs `_migrate_lesson`, which
  chains registered `_MIGRATIONS` (vN→vN+1) up to `SCHEMA_VERSION`, rewrites the
  file if it changed (so users never hand-fix old lessons), treats a missing
  marker as the earliest version, and refuses files newer than the app. To
  evolve the schema: bump `SCHEMA_VERSION` and add a migration fn to
  `_MIGRATIONS`. `validate_lesson` warns about and `cmd_build` skips notes
  missing required fields.
- `.processed/picks.json` — cached definition choices (committed).
- `.processed/<stem>_pending.txt` — resumable add-words state (gitignored).
- `.current_lesson` — stem recorded by `gen-prompt` for `add-sentences` targeting.
- `data/` — `cedict.txt.gz` is a **bundled resource**; `hanzi_cache/`,
  `font_cache/`, `fonts/`, `audio/`, `_stroke_*.json`, `_hanzi_*.js` are
  generated caches (under `CACHE_DIR`, gitignored).
- There is **no `notes_merged.json`** — it used to be written as a debug dump and
  caused confusion about the source of truth; removed.

### Card ordering (`cmd_build`)

`due` is just a position in Anki's new-card queue. Every note gets a sort key and
sequential due numbers are assigned after sorting. Key, earliest first:
1. kind — words, then sentences, then gloss cards;
2. lesson order;
3. `priority` descending (explicit override);
4. `_complexity` ascending = (CJK char count, total stroke count) — "simpler
   first", which also puts a component word ahead of any phrase containing it;
5. text (stable tiebreak).

Stroke counts come from `hanzi_data.stroke_count` (cache-only). Fixed model/deck
IDs in deck.py let re-imports merge instead of duplicating.

### AI step (manual, no API key)

`gen-prompt`/`gen-gloss-prompt` write a prompt to a `.txt` and the wizard copies
it to the clipboard. The user pastes into any chatbot and pastes the JSON reply
back. `_extract_json` pulls the first fenced ```json block (or a bare array/
object) out of the reply, tolerating surrounding prose. There is intentionally
**no API integration** — most users are on other chatbots without a Claude key.

## Packaging

- [chinese-anki.spec](chinese-anki.spec) — one-file PyInstaller build (~80 MB).
  Bundles `data/cedict.txt.gz`, plus `fonts/` and `hanzi_assets/` when present
  (PyInstaller zlib-compresses them, so the highly-compressible JSON adds little).
  `collect_all` covers edge_tts/genanki/questionary/pyperclip.
- [fetch_fonts.py](fetch_fonts.py) / [fetch_hanzi.py](fetch_hanzi.py) — download
  the bundled CJK fonts (~60 MB) and full stroke set (~13 MB) into git-ignored
  `fonts/` / `hanzi_assets/`. Run before PyInstaller (CI does). With them the
  packaged build is **fully offline** except TTS audio.
- [requirements.txt](requirements.txt) — runtime deps (single source of truth;
  the old Pipfile was removed). [requirements-build.txt](requirements-build.txt)
  adds PyInstaller.
- [.github/workflows/build.yml](.github/workflows/build.yml) — fetches assets and
  builds Windows/macOS/Linux binaries on a `v*` tag, attaching them to a Release.

## Conventions

- Python 3.10+ (`X | None`, `list[...]`). Keep that floor.
- All file I/O is UTF-8 explicit; keep `ensure_ascii=False` on JSON dumps.
- **Never hardcode paths** — import from [paths.py](paths.py) so frozen builds
  stay writable in the right place. Resources are read-only (`RESOURCE_DIR`),
  user data and caches are writable (`DATA_DIR`/`CACHE_DIR`).
- `questionary`/`pyperclip` are optional; every interactive path has a
  plain-stdin fallback guarded by `_HAS_Q`/`_HAS_CLIP`. Preserve that.
- Network calls (Wiktionary, hanzi-writer CDN, Kai font) cache to `CACHE_DIR`;
  don't add hard network deps to the core build path without a cache.

## Possible future work

- No automated tests yet; the pure functions (pinyin tone placement in cedict.py,
  `_tokenize_words`, `_complexity`, `_extract_json`) are cheap to cover.
- Packaged builds bundle real CJK fonts so glyph coverage is guaranteed. Only the
  run-from-source path without `fonts/` relies on `fc-match`, which could in
  theory return a non-CJK font and render tofu.
