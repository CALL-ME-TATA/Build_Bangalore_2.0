"""Spoken fractions common in shop talk. sawa = +1/4, saade = +1/2, paune = -1/4, dedh = 1.5, dhai = 2.5."""
import pytest

from nlu.numbers import parse_number

CASES = {
    "sawa sau": 125,
    "dedh sau": 150,
    "dhai sau": 250,
    "paune sau": 75,
    "sawa do sau": 225,
    "sawa teen sau": 325,
    "sawa paanch sau": 525,
    "saade teen sau": 350,
    "saade paanch sau": 550,
    "paune do sau": 175,
    "paune teen sau": 275,
    "paune paanch sau": 475,
    "dedh hazaar": 1500,
    "dhai hazaar": 2500,
    "sawa hazaar": 1250,
}


@pytest.mark.parametrize("text,expected", list(CASES.items()))
def test_fraction_phrases(text, expected):
    assert parse_number(text) == expected
