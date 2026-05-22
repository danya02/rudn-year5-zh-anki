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

DECK_ID = 1_900_000_001
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

  .card.nightMode    { color: #e8e8e8; background: #1c1c1e; }
  .nightMode .pinyin  { color: #e05c4a; }
  .nightMode .meaning { color: #a8c0d6; }
  .nightMode .gloss   { color: #8e9aaa; }
  .nightMode .label   { color: #555e66; }
  .nightMode hr       { border-top-color: #333; }
  .nightMode .font-label { color: #555e66; }
  .nightMode .font-img   { filter: invert(1); }

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


# Shared JS helper: creates an SVG pre-drawn with a 米字格 (rice-character) grid
# — border box, centre cross, and X diagonals. Passed as a literal string block
# and embedded verbatim into each HanziWriter template.
_SVG_GRID_FN = """\
  function makeSvgGrid(size, color) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('width', size); svg.setAttribute('height', size);
    var h = size / 2;
    // border box
    var rect = document.createElementNS(ns, 'rect');
    rect.setAttribute('x','0.5'); rect.setAttribute('y','0.5');
    rect.setAttribute('width', size-1); rect.setAttribute('height', size-1);
    rect.setAttribute('fill','none'); rect.setAttribute('stroke', color);
    rect.setAttribute('stroke-width','1');
    svg.appendChild(rect);
    // centre cross + X diagonals
    [[0,h,size,h],[h,0,h,size],[0,0,size,size],[size,0,0,size]].forEach(function(c) {
      var line = document.createElementNS(ns, 'line');
      line.setAttribute('x1',c[0]); line.setAttribute('y1',c[1]);
      line.setAttribute('x2',c[2]); line.setAttribute('y2',c[3]);
      line.setAttribute('stroke', color); line.setAttribute('stroke-width','1');
      svg.appendChild(line);
    });
    return svg;
  }
"""

# The JS template uses FIELD_REF as a placeholder replaced per call-site.
# All {{ }} in the JS are literal braces (not Anki references), so we keep
# them as plain strings — no f-string escaping needed here.
_ANIM_JS = """\
<div class="stroke-row" id="STROKE_ID"></div>
<script src="_hanzi_data.js"></script>
<script src="_hanzi_writer.js"></script>
<script>
(function() {
  var containerId = 'STROKE_ID';
  var chars = Array.from('FIELD_REF').filter(function(c) {
    var cp = c.codePointAt(0);
    return (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0x3400 && cp <= 0x4DBF);
  });

  var cardElement = document.querySelector('.card');
  var dark = cardElement?.classList.contains('nightMode') ?? false;
  var strokeColor  = dark ? '#e8e8e8' : '#1a1a1a';
  var outlineColor = dark ? '#3a3a3a' : '#ddd';
  var gridColor    = dark ? '#333'    : '#ddd';

SVG_GRID_FN
  function ankiPrefix() {
    return globalThis.ankiPlatform === 'desktop' ? '' :
           globalThis.AnkiDroidJS ? 'https://appassets.androidplatform.net' : '.';
  }
  function renderWith(HanziWriter) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var writers = [];
    chars.forEach(function(char) {
      var svg = makeSvgGrid(280, gridColor);
      container.appendChild(svg);
      writers.push(HanziWriter.create(svg, char, {
        width: 280, height: 280, padding: 5,
        showOutline: true,
        strokeColor: strokeColor,
        outlineColor: outlineColor,
        strokeAnimationSpeed: 0.8,
        delayBetweenStrokes: 80,
        charDataLoader: function(c, onComplete, onError) {
          var cp = c.codePointAt(0).toString(16).padStart(5, '0');
          fetch(ankiPrefix() + '/_stroke_' + cp + '.json')
            .then(function(r) {
              if (!r.ok) throw new Error('HTTP ' + r.status);
              return r.json();
            })
            .then(onComplete)
            .catch(function(e) {
              svg.style.cssText = 'color:#c0392b;font-size:0.8em;padding:8px;';
              svg.textContent = 'No stroke data for "' + c + '" (' + e + ')';
              if (onError) onError(e);
            });
        }
      }));
    });

    function animateAt(i) {
      writers[i].animateCharacter({
        onComplete: function() {
          var next = (i + 1) % writers.length;
          var delay = next === 0 ? 1200 : 300;
          setTimeout(function() { animateAt(next); }, delay);
        }
      });
    }

    if (writers.length > 0) animateAt(0);
  }

  renderWith(HanziWriter);
})();
</script>
"""

_QUIZ_JS = """\
<div class="stroke-row" id="STROKE_ID"></div>
<script src="_hanzi_data.js"></script>
<script src="_hanzi_writer.js"></script>
<script>
(function() {
  var containerId = 'STROKE_ID';
  var chars = Array.from('FIELD_REF').filter(function(c) {
    var cp = c.codePointAt(0);
    return (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0x3400 && cp <= 0x4DBF);
  });

  var cardElement = document.querySelector('.card');
  var dark = cardElement?.classList.contains('nightMode') ?? false;
  var gridColor    = dark ? '#444'    : '#ddd';
  var strokeColor  = dark ? '#e8e8e8' : '#1a1a1a';
  var hintColor    = dark ? '#555'    : '#ccc';

SVG_GRID_FN
  function ankiPrefix() {
    return globalThis.ankiPlatform === 'desktop' ? '' :
           globalThis.AnkiDroidJS ? 'https://appassets.androidplatform.net' : '.';
  }
  function renderWith(HanziWriter) {
    var container = document.getElementById(containerId);
    if (!container) return;
    chars.forEach(function(char) {
      var wrapper = document.createElement('div');
      wrapper.style.cssText = 'display:inline-flex;flex-direction:column;align-items:center;gap:4px;';
      container.appendChild(wrapper);

      var svg = makeSvgGrid(280, gridColor);
      wrapper.appendChild(svg);

      var btn = document.createElement('button');
      btn.textContent = 'Reset';
      btn.style.cssText = 'font-size:0.5em;padding:2px 8px;cursor:pointer;';
      wrapper.appendChild(btn);

      var writer = HanziWriter.create(svg, char, {
        width: 280, height: 280, padding: 5,
        showCharacter: false,
        showOutline: false,
        showHintAfterMisses: 3,
        highlightOnComplete: true,
        drawingColor: strokeColor,
        highlightColor: '#27ae60',
        charDataLoader: function(c, onComplete, onError) {
          var cp = c.codePointAt(0).toString(16).padStart(5, '0');
          fetch(ankiPrefix() + '/_stroke_' + cp + '.json')
            .then(function(r) {
              if (!r.ok) throw new Error('HTTP ' + r.status);
              return r.json();
            })
            .then(onComplete)
            .catch(function(e) {
              svg.style.cssText = 'color:#c0392b;font-size:0.8em;padding:8px;';
              svg.textContent = 'No stroke data for "' + c + '" (' + e + ')';
              if (onError) onError(e);
            });
        }
      });
      writer.quiz();
      btn.addEventListener('click', function() { writer.quiz(); });
    });
  }

  renderWith(HanziWriter);
})();
</script>
"""

_hw_counter = 0


def _hanzi_anim(field: str) -> str:
    global _hw_counter
    _hw_counter += 1
    return (
        _ANIM_JS.replace("FIELD_REF", _ref(field))
        .replace("STROKE_ID", f"hw-anim-{_hw_counter}")
        .replace("SVG_GRID_FN", _SVG_GRID_FN)
    )


def _hanzi_quiz(field: str) -> str:
    global _hw_counter
    _hw_counter += 1
    return (
        _QUIZ_JS.replace("FIELD_REF", _ref(field))
        .replace("STROKE_ID", f"hw-quiz-{_hw_counter}")
        .replace("SVG_GRID_FN", _SVG_GRID_FN)
    )


# ---------------------------------------------------------------------------
# Word note templates (8 directions)
# ---------------------------------------------------------------------------


def _word_templates() -> list[dict]:
    # (name, front_css, front_field, front_label, back_rows)
    std = [
        (
            "CharPron",
            "hanzi",
            "Character",
            f"pronunciation for this character?",
            [("pinyin", "Pronunciation")],
        ),
        (
            "CharMean",
            "hanzi",
            "Character",
            f"meaning of this character?",
            [("meaning", "Meaning")],
        ),
        (
            "PronChar",
            "pinyin",
            "Pronunciation",
            f"character for this pronunciation",
            [("hanzi", "Character")],
        ),
        (
            "PronMean",
            "pinyin",
            "Pronunciation",
            f"meaning of this pronunciation",
            [("meaning", "Meaning")],
        ),
        (
            "MeanChar",
            "meaning",
            "Meaning",
            f"how is this meaning written?",
            [("hanzi", "Character")],
        ),
        (
            "MeanPron",
            "meaning",
            "Meaning",
            f"pronunciation for this meaning?",
            [("pinyin", "Pronunciation")],
        ),
    ]
    templates = []
    for name, f_cls, f_fld, label, back_rows in std:
        front = _front(label, f_cls, f_fld)
        back = "{{FrontSide}}<hr>\n"
        back += "\n".join(_div(cls, fld) for cls, fld in back_rows)
        back += "\n" + _hanzi_anim("Character")
        back += "\n" + _multi_font("Character")
        templates.append(_tmpl(name, front, back))

    # 2 stroke-order directions — quiz mode: user draws the strokes
    stroke = [
        (
            "CharStroke",
            "hanzi",
            "Character",
            f"stroke order for {_ref('Character')}?",
            [("pinyin", "Pronunciation"), ("meaning", "Meaning")],
        ),
        (
            "MeanStroke",
            "meaning",
            "Meaning",
            f"stroke order for &#8220;{_ref('Meaning')}&#8221;?",
            [("hanzi", "Character"), ("pinyin", "Pronunciation")],
        ),
    ]
    for name, f_cls, f_fld, label, back_rows in stroke:
        front = _front(label, f_cls, f_fld)
        front += "\n" + _hanzi_quiz("Character")
        back = "{{FrontSide}}<hr>\n"
        back += "\n".join(_div(cls, fld) for cls, fld in back_rows)
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
        (
            "SentMean",
            "hanzi",
            "Sentence",
            f"meaning of this sentence?",
            [("meaning", "Meaning")],
        ),
        (
            "MeanSent",
            "meaning",
            "Meaning",
            f"how is this meaning written?",
            [("hanzi", "Sentence")],
        ),
        (
            "SentPron",
            "hanzi",
            "Sentence",
            f"pronunciation for this sentence",
            [("pinyin", "Pronunciation")],
        ),
        (
            "PronSent",
            "pinyin",
            "Pronunciation",
            f"character that is pronounced like",
            [("hanzi", "Sentence")],
        ),
        (
            "PronMean",
            "pinyin",
            "Pronunciation",
            f"what does this mean?",
            [("meaning", "Meaning")],
        ),
        (
            "MeanPron",
            "meaning",
            "Meaning",
            f"pronunciation for this meaning",
            [("pinyin", "Pronunciation")],
        ),
    ]
    templates = []
    for name, f_cls, f_fld, label, back_rows in pairs:
        front = _front(label, f_cls, f_fld)
        back = "{{FrontSide}}<hr>\n"
        back += "\n".join(_div(cls, fld) for cls, fld in back_rows)
        back += "\n" + _hanzi_anim("Sentence")
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


def word_note(
    character: str, pronunciation: str, meaning: str, due: int = 0,
    tags: list[str] | None = None,
) -> genanki.Note:
    return genanki.Note(
        model=WORD_MODEL,
        fields=[character, pronunciation, meaning],
        tags=["word"] + (tags or []),
        guid=genanki.guid_for("word", character),
        due=due,
    )


def sentence_note(
    sentence: str, pronunciation: str, gloss: str, meaning: str, due: int = 0,
    tags: list[str] | None = None,
) -> genanki.Note:
    return genanki.Note(
        model=SENT_MODEL,
        fields=[sentence, pronunciation, gloss, meaning],
        tags=["sentence"] + (tags or []),
        guid=genanki.guid_for("sentence", sentence),
        due=due,
    )


# ---------------------------------------------------------------------------
# Build .apkg
# ---------------------------------------------------------------------------


def build_apkg(
    notes: list[genanki.Note],
    output_path: str,
    media_files: list[str] | None = None,
    deck_name: str = "Chinese",
) -> None:
    deck = genanki.Deck(DECK_ID, deck_name)
    for note in notes:
        deck.add_note(note)

    package = genanki.Package(deck)
    package.media_files = list(media_files or [])
    package.write_to_file(output_path)
