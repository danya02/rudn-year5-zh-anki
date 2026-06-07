"""CC-CEDICT parsing: pinyin tone placement and meaning/entry helpers."""

import cedict


def test_pinyin_basic_tone_placement():
    assert cedict.pinyin_numbers_to_diacritics("ni3 hao3") == "nǐ hǎo"


def test_pinyin_preserves_capitalization():
    assert cedict.pinyin_numbers_to_diacritics("Zhong1 guo2") == "Zhōng guó"


def test_pinyin_umlaut_from_v_and_colon():
    assert cedict.pinyin_numbers_to_diacritics("lv4") == "lǜ"
    assert cedict.pinyin_numbers_to_diacritics("nu:3") == "nǚ"


def test_pinyin_neutral_tone_has_no_mark():
    assert cedict.pinyin_numbers_to_diacritics("ma5") == "ma"
    assert cedict.pinyin_numbers_to_diacritics("xue2 sheng5") == "xué sheng"


def test_clean_meaning_strips_classifiers():
    assert cedict.clean_meaning("to be; CL:个[ge4]; good") == "to be; good"
    assert cedict.clean_meaning("CL:本[ben3]; book") == "book"


def test_best_entry_skips_surname_then_falls_back():
    surname = cedict.Entry("x", "x", "", "", ["surname Li"])
    plum = cedict.Entry("x", "x", "", "", ["plum"])
    assert cedict.best_entry([surname, plum]) is plum
    # Only deprioritized entries available → first is returned.
    assert cedict.best_entry([surname]) is surname
