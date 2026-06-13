"""Unit tests for pipeline.text_utils.normalize_description."""

from pipeline.text_utils import normalize_description


def test_basic_normalization():
    assert normalize_description("Surfer, BLUE wetsuit!") == "surfer blue wetsuit"


def test_empty_and_none_safe():
    assert normalize_description("") == ""
    assert normalize_description(None) == ""


def test_collapses_whitespace_and_strips_punctuation():
    assert normalize_description("  Athlete  #7   (red)  ") == "athlete 7 red"


def test_different_suffixes_do_not_collide():
    # Regression for the old 40-char-prefix key: these share a long prefix but
    # are different athletes — they must produce DIFFERENT keys.
    a = normalize_description("surfer in black wetsuit on a white board")
    b = normalize_description("surfer in black wetsuit on a yellow board")
    assert a != b


def test_same_description_same_key():
    assert normalize_description("Goofy-foot surfer, RED rashguard") == \
           normalize_description("goofy foot surfer red rashguard")
