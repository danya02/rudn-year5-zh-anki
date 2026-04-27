"""
deck.py — Build Anki .apkg files from notes.json.

Note types
----------
  WordNote  — Character | Pronunciation | Meaning
    8 card directions: 6 standard + 2 stroke-order (Character→Draw, Meaning→Draw)

  SentNote  — Sentence | Pronunciation | Gloss | Meaning
    6 card directions: comprehension, production, tones

The model IDs are fixed so Anki merges on re-import rather than duplicating.
"""

import json
import genanki

# ---------------------------------------------------------------------------
# Fixed IDs
# ---------------------------------------------------------------------------

DECK_ID       = 1_900_000_001
WORD_MODEL_ID = 1_900_000_002
SENT_MODEL_ID = 1_900_000_003

# ---------------------------------------------------------------------------
# Shared CSS
# ---------------------------------------------------------------------------

CARD_CSS = """
.card {
    font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 1.4em;
    text-align: center;
    color: #1a1a1a;
    background: #fafaf8;
    padding: 1.5em;
}
.hanzi   { font-size: 2.8em; line-height: 1.3; }
.pinyin  { font-size: 1.1em; color: #c0392b; margin: 0.3em 0; }
.meaning { font-size: 0.95em; color: #2c3e50; }
.gloss   { font-size: 0.85em; color: #7f8c8d; font-style: italic; }
.label   { font-size: 0.7em; color: #bdc3c7; text-transform: uppercase;
           letter-spacing: 0.1em; margin-bottom: 0.8em; }
hr       { border: none; border-top: 1px solid #ddd; margin: 0.8em 0; }

/* Three-font image row */
.fonts-row  { display: flex; justify-content: center; gap: 1.4em; margin-top: 0.6em; }
.font-item  { text-align: center; }
.font-img   { width: 70px; height: 70px; display: inline-block;
              vertical-align: middle; }
.font-label { font-size: 0.4em; color: #bdc3c7; display: block; margin-top: 0.2em; }

/* Stroke-order container */
.stroke-row { display: flex; justify-content: center; gap: 0.4em;
              flex-wrap: wrap; margin-top: 0.8em; }
"""

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _ref(field: str) -> str:
    """Anki field reference: {{FieldName}}"""
    return "{{" + field + "}}"


def _div(css_cls: str, field: str) -> str:
    return f'<div class="{css_cls}">{_ref(field)}</div>'


def _tmpl(name: str, front: str, back: str) -> dict:
    return {"name": name, "qfmt": front, "afmt": back}


def _front(label: str, css_cls: str, field: str) -> str:
    return f'<div class="label">{label}</div>{_div(css_cls, field)}'


# JS template: FIELD_REF is replaced with the Anki {{FieldName}} reference.
# For each CJK character in the field, three pre-rendered PNGs are displayed
# side-by-side — one per style — so the card always shows the correct images
# regardless of which fonts the reviewer's device has installed.
_MULTI_FONT_JS = """\
<div class="fonts-row" id="mf-container"></div>
<script>
(function() {
  var chars = Array.from('FIELD_REF').filter(function(c) {
    var cp = c.codePointAt(0);
    return (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0x3400 && cp <= 0x4DBF);
  });
  var styles = [['sans','Sans'],['serif','Serif'],['kai','Kai']];
  var container = document.getElementById('mf-container');
  styles.forEach(function(s) {
    var item = document.createElement('div');
    item.className = 'font-item';
    chars.forEach(function(c) {
      var hex = c.codePointAt(0).toString(16).padStart(5,'0');
      var img = document.createElement('img');
      img.src = '_char_' + hex + '_' + s[0] + '.png';
      img.className = 'font-img';
      item.appendChild(img);
    });
    var lbl = document.createElement('small');
    lbl.className = 'font-label';
    lbl.textContent = s[1];
    item.appendChild(lbl);
    container.appendChild(item);
  });
})();
</script>"""


def _multi_font(field: str) -> str:
    return _MULTI_FONT_JS.replace("FIELD_REF", _ref(field))


# The JS template uses FIELD_REF as a placeholder replaced per call-site.
# All {{ }} in the JS are literal braces (not Anki references), so we keep
# them as plain strings — no f-string escaping needed here.
_STROKE_JS = """\
<div class="stroke-row" id="stroke-container"></div>
<script src="_hanzi_data.js"></script>
<script src="_hanzi_writer.js"></script>
<script>
(function() {
  var chars = 'FIELD_REF'.split('').filter(function(c) {
    var cp = c.codePointAt(0);
    return (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0x3400 && cp <= 0x4DBF);
  });
  var container = document.getElementById('stroke-container');
  chars.forEach(function(char) {
    var div = document.createElement('div');
    container.appendChild(div);
    HanziWriter.create(div, char, {
      width: 140, height: 140, padding: 5,
      showOutline: true,
      strokeAnimationSpeed: 0.8,
      delayBetweenStrokes: 80,
      charDataLoader: function(c, onComplete) {
        onComplete(window._HANZI_DATA && window._HANZI_DATA[c]);
      }
    }).animateCharacter();
  });
})();
</script>"""


def _stroke_order(field: str) -> str:
    return _STROKE_JS.replace("FIELD_REF", _ref(field))


# ---------------------------------------------------------------------------
# Word note templates (8 directions)
# ---------------------------------------------------------------------------

def _word_templates() -> list[dict]:
    # 6 standard directions among Character, Pronunciation, Meaning
    std = [
        ("CharPron",  "hanzi",   "Character",    [("pinyin",  "Pronunciation")]),
        ("CharMean",  "hanzi",   "Character",    [("meaning", "Meaning")]),
        ("PronChar",  "pinyin",  "Pronunciation",[("hanzi",   "Character")]),
        ("PronMean",  "pinyin",  "Pronunciation",[("meaning", "Meaning")]),
        ("MeanChar",  "meaning", "Meaning",      [("hanzi",   "Character")]),
        ("MeanPron",  "meaning", "Meaning",      [("pinyin",  "Pronunciation")]),
    ]
    templates = []
    for name, f_cls, f_fld, back_rows in std:
        front = _front(f_fld, f_cls, f_fld)
        back  = front + "<hr>\n"
        back += "\n".join(_div(cls, fld) for cls, fld in back_rows)
        back += "\n" + _multi_font("Character")
        templates.append(_tmpl(name, front, back))

    # 2 stroke-order directions
    stroke = [
        ("CharStroke", "hanzi",   "Character",
         [("pinyin", "Pronunciation"), ("meaning", "Meaning")]),
        ("MeanStroke", "meaning", "Meaning",
         [("hanzi", "Character"), ("pinyin", "Pronunciation")]),
    ]
    for name, f_cls, f_fld, back_rows in stroke:
        front = _front(f_fld, f_cls, f_fld)
        back  = front + "<hr>\n"
        back += "\n".join(_div(cls, fld) for cls, fld in back_rows)
        back += "\n" + _multi_font("Character")
        back += "\n" + _stroke_order("Character")
        templates.append(_tmpl(name, front, back))

    return templates


WORD_MODEL = genanki.Model(
    WORD_MODEL_ID,
    "Chinese word (character-pronunciation-meaning)",
    fields=[
        {"name": "Character"},
        {"name": "Pronunciation"},
        {"name": "Meaning"},
    ],
    templates=_word_templates(),
    css=CARD_CSS,
)

# ---------------------------------------------------------------------------
# Sentence note templates (6 directions)
#
# Directions chosen for a beginner:
#   Sent↔Mean   — core reading / production
#   Sent↔Pron   — tones and dictation
#   Pron↔Mean   — listening comprehension analog
# Gloss directions omitted; useful for grammar analysis, not for fluency drills.
# ---------------------------------------------------------------------------

def _sent_templates() -> list[dict]:
    pairs = [
        ("SentMean", "hanzi",   "Sentence",     [("meaning", "Meaning")]),
        ("MeanSent", "meaning", "Meaning",       [("hanzi",   "Sentence")]),
        ("SentPron", "hanzi",   "Sentence",      [("pinyin",  "Pronunciation")]),
        ("PronSent", "pinyin",  "Pronunciation", [("hanzi",   "Sentence")]),
        ("PronMean", "pinyin",  "Pronunciation", [("meaning", "Meaning")]),
        ("MeanPron", "meaning", "Meaning",       [("pinyin",  "Pronunciation")]),
    ]
    templates = []
    for name, f_cls, f_fld, back_rows in pairs:
        front = _front(f_fld, f_cls, f_fld)
        back  = front + "<hr>\n"
        back += "\n".join(_div(cls, fld) for cls, fld in back_rows)
        back += "\n" + _multi_font("Sentence")
        templates.append(_tmpl(name, front, back))
    return templates


SENT_MODEL = genanki.Model(
    SENT_MODEL_ID,
    "Chinese sentence (sentence-pronunciation-gloss-meaning)",
    fields=[
        {"name": "Sentence"},
        {"name": "Pronunciation"},
        {"name": "Gloss"},
        {"name": "Meaning"},
    ],
    templates=_sent_templates(),
    css=CARD_CSS,
)

# ---------------------------------------------------------------------------
# Note constructors
# ---------------------------------------------------------------------------

def word_note(character: str, pronunciation: str, meaning: str) -> genanki.Note:
    return genanki.Note(
        model=WORD_MODEL,
        fields=[character, pronunciation, meaning],
        tags=["word"],
    )


def sentence_note(sentence: str, pronunciation: str,
                  gloss: str, meaning: str) -> genanki.Note:
    return genanki.Note(
        model=SENT_MODEL,
        fields=[sentence, pronunciation, gloss, meaning],
        tags=["sentence"],
    )


# ---------------------------------------------------------------------------
# Build .apkg
# ---------------------------------------------------------------------------

def build_apkg(
    notes_path: str,
    output_path: str,
    media_files: list[str] | None = None,
    deck_name: str = "Chinese",
) -> None:
    """
    Read notes.json and write an Anki .apkg file.

    Pass media_files with paths to _hanzi_writer.js and _hanzi_data.js
    (and optionally audio .mp3s) so they are bundled into the package.
    """
    with open(notes_path, encoding="utf-8") as f:
        data = json.load(f)

    deck = genanki.Deck(DECK_ID, deck_name)

    for w in data.get("words", []):
        pron = w["pronunciation"]
        if w.get("audio"):
            pron += f" [sound:{w['audio']}]"
        deck.add_note(word_note(w["character"], pron, w["meaning"]))

    for s in data.get("sentences", []):
        pron = s["pronunciation"]
        if s.get("audio"):
            pron += f" [sound:{s['audio']}]"
        deck.add_note(sentence_note(s["sentence"], pron, s["gloss"], s["meaning"]))

    package = genanki.Package(deck)
    package.media_files = list(media_files or [])
    package.write_to_file(output_path)

    n_w = len(data.get("words", []))
    n_s = len(data.get("sentences", []))
    print(f"✓ Wrote {output_path}  ({n_w} word notes, {n_s} sentence notes)")
