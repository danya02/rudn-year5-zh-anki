# Chinese Anki Pipeline

Builds rich Anki flashcard decks for Chinese vocabulary from a plain word list.
Each character gets stroke-order practice, three typeface styles, pronunciation,
meanings, AI-generated example sentences, morpheme glosses, and optional audio.

## Easiest start — download the app

1. Go to the [**Releases**](../../releases) page and download the file for your
   system:
   - Windows → `chinese-anki-windows.exe`
   - macOS → `chinese-anki-macos`
   - Linux → `chinese-anki-linux`
2. Put it in a folder of its own (it creates a `chinese-anki-data/` folder
   beside itself for your lessons and the finished deck).
3. Run it and follow the guided wizard. It walks you through adding words,
   picking definitions, generating sentences, adding audio, and building the deck.
4. When `chinese.apkg` is ready, open Anki and choose **File → Import**.

> macOS/Linux: you may need to allow the binary to run
> (`chmod +x chinese-anki-macos`, and on macOS right-click → Open the first time).

No Python, no setup, no API keys — the AI step is copy-paste into any chatbot
you already use.

## Run from source

Requires Python 3.10+.

**Linux / macOS**
```bash
./start.sh
```
**Windows**
```
start.bat
```

These create a local virtualenv, install dependencies, and launch the wizard.
You can also drive it directly:

```bash
python pipeline.py wizard      # the guided menu
```

## Wizard overview

| Action | What it does |
|--------|-------------|
| **Add words to a lesson** | Paste or type a word list; for each new word, pick the right definition(s) |
| **Generate example sentences** | Builds a prompt (copied to your clipboard), you paste it into a chatbot, then paste the JSON reply back |
| **Generate word glosses** | Same flow, for morpheme-by-morpheme breakdowns of compound words |
| **Add pronunciation audio** | Downloads TTS audio for all notes |
| **Build & export deck** | Writes `chinese.apkg` |
| **Show status** | Lessons, word/sentence counts, coverage |

### The AI step (no account required)

"Generate sentences"/"Generate glosses" never call an API. They write a prompt,
copy it to your clipboard, and wait. Paste it into **any** chatbot (Claude,
ChatGPT, Gemini, …), copy the reply — pasting the whole ```json code block is
fine, surrounding chatter is tolerated — and paste it back, ending with
`<<<END>>>` on its own line.

## Where your data lives

`notes/<lesson>.json` is the **single source of truth** — one file per lesson,
hand-editable:

```json
{
  "version": 1,
  "words": [
    {"character": "你", "pronunciation": "nǐ", "meaning": "you (informal)"}
  ],
  "sentences": [
    {"sentence": "你好", "pronunciation": "nǐ hǎo",
     "gloss": "you good", "meaning": "Hello!"}
  ]
}
```

Optional per-note fields: `gloss` (morpheme breakdown for words), `audio`
(filename), `priority` (higher = studied earlier; default 100).

The deck (`chinese.apkg`), prompts, and caches are all **generated** — when
running from source they sit in the project folder; in the packaged app they
live in `chinese-anki-data/`. None of them are a source you edit.

## Card types & study order

- **Word notes** — 8 cards: character ↔ pronunciation ↔ meaning, plus two
  stroke-order quiz directions where you draw the character.
- **Sentence notes** — 9 cards across sentence / pronunciation / gloss / meaning.
- **Gloss notes** — 2 cards for compound-word etymology (e.g. 手机 → hand-device).

New cards are ordered **simplest first**: by character count, then total stroke
count, so single characters come before the compounds and sentences built from
them. Within that, lessons keep their course order and an explicit `priority`
wins.

## Advanced / power-user CLI

```bash
python pipeline.py add-words notes_input.txt        # auto-pick definitions
python pipeline.py add-words -i notes_input.txt     # interactive picker
python pipeline.py gen-prompt                        # → prompt.txt
python pipeline.py add-sentences sentences.json      # ingest reply, rebuild
python pipeline.py gen-gloss-prompt                  # → gloss_prompt.txt
python pipeline.py add-glosses glosses.json
python pipeline.py add-audio
python pipeline.py build
```

## Building the executable yourself

```bash
pip install -r requirements-build.txt
python fetch_fonts.py                 # CJK fonts to bundle (~60 MB → fonts/)
python fetch_hanzi.py                 # full stroke-order set (~13 MB → hanzi_assets/)
pyinstaller chinese-anki.spec         # → dist/chinese-anki[.exe]
```

The two fetch steps are optional but recommended: they bundle the fonts and the
complete hanzi-writer stroke data into the binary, so the packaged app builds
decks **fully offline** (dictionary, stroke data, and fonts all travel with it —
only TTS audio still needs a connection). Without them the app still works but
downloads those assets on first build. The fetched files are git-ignored.

CI ([.github/workflows/build.yml](.github/workflows/build.yml)) runs both fetch
steps and builds all three platforms automatically when you push a version tag
(`git tag v1.0 && git push --tags`), attaching the binaries to a GitHub Release.

## Notes

- Multiple readings: auto mode picks the most common non-surname entry. Override
  in the lesson JSON, or use the interactive picker.
- CC-CEDICT classifier references like `CL:匹[pi3]` are stripped automatically.
- Definition picks are cached in `.processed/picks.json`, so a character you've
  already chosen a meaning for is pre-selected next time it appears.
