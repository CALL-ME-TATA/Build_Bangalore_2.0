"""nlu.speak.number_to_words: standard spellings for the speech synthesiser, and a lossless round trip."""
import unicodedata

import pytest
from hypothesis import given, settings, strategies as st

from nlu.numbers import parse_number
from nlu.speak import MAX_SPOKEN, number_to_words


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


@settings(max_examples=1500, deadline=None)
@given(st.integers(min_value=1, max_value=MAX_SPOKEN), st.sampled_from(["deva", "roman"]))
def test_words_parse_back(n, script):
    assert parse_number(number_to_words(n, script)) == n


@pytest.mark.parametrize("n", list(range(1, 1000)) + [1000, 1001, 99_999, 100_000, 100_001, 999_999, 1_000_000,
                                                      MAX_SPOKEN])
@pytest.mark.parametrize("script", ["deva", "roman"])
def test_words_parse_back_low_range(n, script):
    assert parse_number(number_to_words(n, script)) == n


@pytest.mark.parametrize("n,text", [
    (340, "तीन सौ चालीस"),
    (1500, "एक हज़ार पाँच सौ"),
    (125000, "एक लाख पच्चीस हज़ार"),
    (100, "एक सौ"),
    (6, "छह"),
    (15, "पंद्रह"),
    (44, "चवालीस"),
    (79, "उन्यासी"),
    (99, "निन्यानवे"),
    (250, "दो सौ पचास"),
    (9_999_999, "निन्यानवे लाख निन्यानवे हज़ार नौ सौ निन्यानवे"),
])
def test_devanagari_spot_checks(n, text):
    assert number_to_words(n, "deva") == nfc(text)


@pytest.mark.parametrize("n,text", [
    (340, "teen sau chaalis"),
    (1500, "ek hazaar paanch sau"),
    (125000, "ek lakh pachchees hazaar"),
    (430, "chaar sau tees"),
])
def test_roman_spot_checks(n, text):
    assert number_to_words(n, "roman") == text


def test_default_script_is_devanagari():
    assert number_to_words(200) == "दो सौ"


def test_zero():
    assert number_to_words(0, "deva") == "शून्य"
    assert number_to_words(0, "roman") == "shunya"


def test_devanagari_output_has_no_latin_letters():
    for n in (1, 17, 340, 1500, 99_999, 125_000, 9_999_999):
        text = number_to_words(n, "deva")
        assert all("ऀ" <= ch <= "ॿ" or ch == " " for ch in text), text


@pytest.mark.parametrize("bad", [-1, MAX_SPOKEN + 1, 1.5, "340", True])
def test_out_of_range_raises(bad):
    with pytest.raises(ValueError):
        number_to_words(bad)


def test_unknown_script_raises():
    with pytest.raises(ValueError):
        number_to_words(5, "kannada")
