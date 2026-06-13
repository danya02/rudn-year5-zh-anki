"""Pure helpers: chatbot-reply JSON extraction, card ordering, validation,
and the word tokenizer."""

import pipeline as pl
import wizard


def test_extract_json_from_fenced_block_with_prose():
    assert pl._extract_json("here you go:\n```json\n[1, 2]\n```\nhope that helps") == "[1, 2]"


def test_extract_json_from_plain_fence():
    assert pl._extract_json("```\n{\"a\": 1}\n```") == '{"a": 1}'


def test_extract_json_bare_with_surrounding_prose():
    assert pl._extract_json('sure: [{"a": 1}] done') == '[{"a": 1}]'


def test_extract_json_already_clean():
    assert pl._extract_json("[1, 2, 3]") == "[1, 2, 3]"


def test_complexity_orders_simpler_first():
    sc = {"好": 6, "你": 7, "图": 8, "书": 4, "馆": 14}
    assert pl._complexity("好", sc) == (1, 6)
    assert pl._complexity("你好", sc) == (2, 13)
    assert pl._complexity("图书馆", sc) == (3, 26)
    # The whole point: shorter, then fewer strokes, sorts earlier.
    assert pl._complexity("好", sc) < pl._complexity("你好", sc) < pl._complexity("图书馆", sc)


def test_complexity_unknown_cjk_sorts_last_within_length():
    # No stroke data → high fallback so it doesn't masquerade as simple.
    assert pl._complexity("鿿", {}) == (1, 99)


def test_validate_lesson_flags_missing_fields():
    problems = pl.validate_lesson("t", {"words": [{"character": "好"}], "sentences": []})
    assert any("pronunciation" in p for p in problems)


def test_validate_lesson_accepts_complete_notes():
    data = {
        "words": [{"character": "好", "pronunciation": "hǎo", "meaning": "good"}],
        "sentences": [],
    }
    assert pl.validate_lesson("t", data) == []


def test_tokenize_dedups_and_splits_on_separators():
    assert wizard._tokenize_words("一, 二，三、四") == ["一", "二", "三", "四"]
    assert wizard._tokenize_words("一 一 二") == ["一", "二"]


def test_tokenize_skips_comments_and_blank_lines():
    assert wizard._tokenize_words("# header\n一\n\n二") == ["一", "二"]


def test_tokenize_keeps_non_han_token_whole():
    assert wizard._tokenize_words("OK 好") == ["OK", "好"]


def test_audio_filename_encodes_voice():
    a = pl._audio_filename("你好", "zh-CN-XiaoxiaoNeural")
    b = pl._audio_filename("你好", "zh-CN-YunxiNeural")
    # Same text in different voices → distinct files, both naming their voice.
    assert a != b
    assert "zh-CN-XiaoxiaoNeural" in a
    assert "zh-CN-YunxiNeural" in b
    assert a.endswith(".mp3")


def test_audio_filename_stable_for_same_text_and_voice():
    voice = "zh-CN-XiaoxiaoNeural"
    assert pl._audio_filename("学生", voice) == pl._audio_filename("学生", voice)


def test_audio_filename_digest_independent_of_voice():
    # The text digest (last segment) is shared across voices so renames line up.
    a = pl._audio_filename("学生", "zh-CN-XiaoxiaoNeural")
    b = pl._audio_filename("学生", "zh-CN-YunxiNeural")
    assert a.rsplit("_", 1)[1] == b.rsplit("_", 1)[1]


def _lesson(words, sentences=None):
    return {"version": 1, "words": words, "sentences": sentences or []}


def test_canonical_words_prefers_richer_later_entry():
    lessons = [
        ("l2", _lesson([{"character": "学", "pronunciation": "x", "meaning": "auto"}])),
        ("l5", _lesson([{"character": "学", "pronunciation": "xué",
                         "meaning": "corrected", "gloss": "study"}])),
    ]
    canonical, warnings = pl.canonical_words(lessons)
    # Richer (has gloss) corrected entry wins, and the conflict is reported.
    assert canonical["学"]["meaning"] == "corrected"
    assert any("学" in w and "meaning" in w for w in warnings)


def test_canonical_words_no_warning_when_consistent():
    lessons = [
        ("l2", _lesson([{"character": "好", "pronunciation": "hǎo", "meaning": "good"}])),
        ("l5", _lesson([{"character": "好", "pronunciation": "hǎo", "meaning": "good"}])),
    ]
    canonical, warnings = pl.canonical_words(lessons)
    assert canonical["好"]["meaning"] == "good"
    assert warnings == []


def test_find_vocab_violations_flags_unknown_chars():
    known = set("你好我是")
    violations = pl.find_vocab_violations(["你好", "我是谁"], known)
    assert violations == [("我是谁", ["谁"])]


def test_find_vocab_violations_ignores_punctuation_and_known():
    known = set("你好")
    assert pl.find_vocab_violations(["你好！"], known) == []


def test_hsk_tags_traditional_and_unknown():
    import hsk
    assert hsk.tags("學生") == ["hsk2-1", "hsk3-1"]
    assert hsk.tags("乜嘢冇") == []  # not in either standard
