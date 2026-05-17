# Chinese Anki Pipeline

Builds Anki flashcard decks for Chinese vocabulary from a word list.

## Quick start (recommended)

**Linux / macOS**
```bash
./start.sh
```

**Windows**
```
start.bat
```

The script creates a local Python environment, installs all dependencies, and
launches a guided wizard. Follow the prompts — it will walk you through adding
words, choosing definitions, generating example sentences with Claude, adding
audio, and building the deck.

When the deck (`chinese.apkg`) is ready, import it in Anki via **File → Import**.

---

## Wizard overview

The wizard (re-run with `./start.sh` or `python pipeline.py wizard`) presents
a menu:

| Action | What it does |
|--------|-------------|
| **Add a new lesson** | Paste or type a word list; for each word, pick the right definition from a searchable list |
| **Generate sentences** | Creates a Claude prompt, copies it to your clipboard, then reads Claude's JSON reply from stdin |
| **Add audio** | Downloads TTS pronunciation audio for all notes |
| **Build & export deck** | Writes `chinese.apkg` — import it into Anki |
| **Show status** | Overview of lessons, word counts, and coverage |

### Picking definitions

When you add words interactively, each word shows all definitions found in
Wiktionary and CC-CEDICT. Use the checkbox list (or numbers if running without
`questionary`) to select only the meanings your course uses:

- Select multiple definitions with space / arrow keys (or type `1,3`)
- Press `e` (or choose "edit in $EDITOR") to hand-tune the wording
- Choose "skip this word" to add it later
- Previously-chosen definitions are pre-selected automatically next time the
  same character appears in another lesson

---

## Advanced / power-user commands

All the original subcommands still work directly:

### Add words from a file
```bash
python pipeline.py add-words lesson_data/my_lesson.txt         # auto mode
python pipeline.py add-words -i lesson_data/my_lesson.txt      # interactive picker
```

### Build the deck
```bash
python pipeline.py build
```

### Generate a Claude prompt
```bash
python pipeline.py gen-prompt
# paste prompt.txt into Claude → save reply as sentences.json
python pipeline.py add-sentences sentences.json
```

### Add TTS audio
```bash
python pipeline.py add-audio
```

---

## Notes file format (`notes/<lesson>.json`)

Each lesson is a JSON file you can also edit by hand:

```json
{
  "words": [
    {"character": "你", "pronunciation": "nǐ", "meaning": "you (informal)"},
    ...
  ],
  "sentences": [
    {"sentence": "你好", "pronunciation": "nǐ hǎo",
     "gloss": "you good", "meaning": "Hello!"},
    ...
  ]
}
```

## Card types

**Word notes** — 6 cards (character ↔ pronunciation ↔ meaning, all directions).

**Sentence notes** — 12 cards (sentence ↔ pronunciation ↔ gloss ↔ meaning,
all pairs).

## Notes

- Words with multiple readings: the pipeline picks the most common non-surname
  entry. Override by editing the lesson JSON directly.
- CC-CEDICT definitions may include classifier references like `CL:匹[pi3]` —
  these are stripped automatically; tidy anything else in the JSON.
- Definition picks are cached in `.processed/picks.json` so repeated words
  across lessons reuse your previous choice without re-prompting.
