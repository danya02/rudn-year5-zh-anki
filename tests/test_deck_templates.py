"""Card template structure: audio placement, stroke reveal, listening cards."""

import deck


def _by_name(templates):
    return {t["name"]: t for t in templates}


def _all_template_lists():
    return (deck._word_templates(), deck._sent_templates(), deck._gloss_templates())


def test_card_counts():
    assert len(deck._word_templates()) == 9   # 6 standard + 2 stroke + listening
    assert len(deck._sent_templates()) == 10  # 9 + listening
    assert len(deck._gloss_templates()) == 2


def test_no_card_plays_audio_on_both_sides():
    # The original bug: {{FrontSide}} re-played front audio on the back.
    for tmpls in _all_template_lists():
        for t in tmpls:
            on_front = "{{Audio}}" in t["qfmt"]
            on_back = "{{Audio}}" in t["afmt"]
            assert not (on_front and on_back), f"{t['name']} plays audio twice"


def test_standard_cards_play_audio_once_on_back():
    word = _by_name(deck._word_templates())
    for name in ("CharPron", "CharMean", "PronChar", "MeanChar"):
        t = word[name]
        assert "{{Audio}}" not in t["qfmt"]
        assert t["afmt"].count("{{Audio}}") == 1


def test_listening_cards_play_audio_on_front_only():
    word = _by_name(deck._word_templates())
    sent = _by_name(deck._sent_templates())
    for t in (word["ListenMean"], sent["ListenSentMean"]):
        assert "{{Audio}}" in t["qfmt"]
        assert "{{Audio}}" not in t["afmt"]          # no replay on reveal
        assert t["qfmt"].startswith("{{#Audio}}")    # only generated when audio exists
        assert "{{Meaning}}" not in t["qfmt"]        # don't leak the answer
        assert "{{Meaning}}" in t["afmt"]


def test_stroke_back_reveals_animation_not_quiz():
    word = _by_name(deck._word_templates())
    for name in ("CharStroke", "MeanStroke"):
        t = word[name]
        assert "writer.quiz()" in t["qfmt"]          # front quizzes
        assert "{{FrontSide}}" not in t["afmt"]      # back doesn't re-run the quiz
        assert "writer.quiz()" not in t["afmt"]
        assert "animateCharacter" in t["afmt"]       # back shows the answer animated


def test_animations_are_click_to_replay():
    t = _by_name(deck._word_templates())["CharMean"]
    assert "addEventListener('click'" in t["afmt"]


def test_dead_hanzi_data_script_removed():
    for tmpls in _all_template_lists():
        for t in tmpls:
            assert "_hanzi_data.js" not in t["qfmt"]
            assert "_hanzi_data.js" not in t["afmt"]
