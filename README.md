# Chinese Anki Pipeline

Builds Anki flashcard decks for Chinese vocabulary from a simple word list.

## Setup (one time)

```bash
pip install -r requirements.txt
```

The CC-CEDICT dictionary (`data/cedict.txt.gz`) is included.

## Workflow

### Step 1 — Add words from a lesson

Create a plain text file with one word per line (lines starting with `#` are comments):

```
# Lesson 2
老师
学生
书
```

Run:
```bash
python pipeline.py add-words my_lesson.txt
```

This looks up each word in CC-CEDICT, adds it to `notes.json`, and prints
anything it couldn't find (so you can add those manually).

### Step 2 — Build the deck

```bash
python pipeline.py build
```

Produces `chinese.apkg`. Import it into Anki (File → Import).
You can re-run this any time to rebuild from the current `notes.json`.

### Step 3 — Generate example sentences (optional but recommended)

```bash
python pipeline.py gen-prompt
```

This writes `prompt.txt`. Paste its contents into Claude at claude.ai.
Claude will return a JSON array — save it as `sentences.json`, then:

```bash
python pipeline.py add-sentences sentences.json
```

This adds the sentences to `notes.json` and rebuilds `chinese.apkg`.

## notes.json

This is the source of truth. It accumulates across lessons. Structure:

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

You can edit this file directly to fix definitions, pronunciations, or meanings.

## Card types

**Word notes** generate 6 cards (all directions):
- Character → Pronunciation
- Character → Meaning
- Pronunciation → Character
- Pronunciation → Meaning
- Meaning → Character
- Meaning → Pronunciation

**Sentence notes** generate 12 cards (all 4 fields against each other).

## Notes

- If a word has multiple readings (多音字), the pipeline picks the most common
  non-surname entry. You can override by editing `notes.json` directly.
- CC-CEDICT definitions sometimes include measure word references like
  `CL:匹[pi3]` — feel free to tidy these up in `notes.json`.
