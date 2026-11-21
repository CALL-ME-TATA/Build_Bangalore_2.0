"""Property tests for nlu.numbers.parse_number: canonical words, spelling variants and plain digits round-trip."""
from hypothesis import given, settings, strategies as st

from nlu.numbers import parse_number
from tests.oracle.hindi_numbers import MAX_N, render, variants

amounts = st.integers(min_value=1, max_value=MAX_N)


@settings(max_examples=2000, deadline=None)
@given(amounts)
def test_canonical_words_roundtrip(n):
    assert parse_number(render(n)) == n


@settings(max_examples=1000, deadline=None)
@given(amounts)
def test_spelling_variants_roundtrip(n):
    for v in variants(render(n)):
        assert parse_number(v) == n, v


@settings(max_examples=500, deadline=None)
@given(amounts)
def test_plain_digits(n):
    assert parse_number(str(n)) == n


def test_non_numbers_return_none():
    for text in ["namaste", "udhaar", "Ramesh", ""]:
        assert parse_number(text) is None


def test_bare_sau_is_100():
    assert parse_number("sau") == 100
