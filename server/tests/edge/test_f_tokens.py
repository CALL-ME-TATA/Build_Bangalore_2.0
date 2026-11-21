"""F. Glued tokens and normalisation (docs/EDGE_CASES.md section F, CONTRACT 1.14)."""
from __future__ import annotations

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_saved


def test_F01_glued_particle_and_number(shop):
    shop.seed(("sunita", "credit", 1000))
    expect_saved(shop.say("sunita kofivehundred diya"), ("credit", "sunita", 500), shop=shop)


@pytest.mark.parametrize("text,kind", [("sunita ko500 diya", "credit"), ("sunita nefivehundred diya", "payment")])
def test_F02_letters_and_digits_split(shop, text, kind):
    shop.seed(("sunita", "credit", 1000))
    expect_saved(shop.say(text), (kind, "sunita", 500), shop=shop)


def test_F03_a_token_that_cannot_be_cut_stays_whole(shop):
    shop.seed(("sunita", "credit", 1000))
    t = shop.say("sunita ko qwertyfive diya")
    expect_nothing_saved(t, "an uncuttable token must not become an amount")


def test_F04_stored_name_konda_is_not_split(shop):
    shop.seed(("konda", "credit", 100))
    t = shop.say("Konda ko 50 udhaar")
    expect_saved(t, ("credit", "konda", 50), shop=shop)
    assert [c["name"] for c in shop.customers()] == ["konda"]


def test_F05_two_cuts_with_different_meanings_ask(shop):
    """`ramsedo` is ram + se + do, or ramse + do: two stored customers, two readings."""
    shop.seed(("ram", "credit", 100), ("ramse", "credit", 100))
    t = shop.say("ramsedo udhaar")
    expect_nothing_saved(t, "an ambiguous cut must not save")
    assert t.status == "needs_clarification" and t.reason == "missing_amount", t.describe()


@pytest.mark.parametrize("text", ["SUNITA KO 500 DIYA", "sUnItA kO 500 DiYa", "Sunita Ko 500 Diya"])
def test_F06_casing_is_ignored(shop, text):
    shop.seed(("sunita", "credit", 1000))
    expect_saved(shop.say(text), ("credit", "sunita", 500), shop=shop)


@pytest.mark.parametrize("text", ["रमेश का 340 उधार", "Ramesh ka 340 udhar", "Ramesh ka 340 udhaar",
                                   "रमेश का ३४० उधार"])
def test_F07_devanagari_or_roman_for_the_same_word(shop, text):
    shop.seed(("ramesh", "credit", 100))
    expect_saved(shop.say(text), ("credit", "ramesh", 340), shop=shop)


@pytest.mark.parametrize("text", ["Ramesh, ka 340. udhaar", "Ramesh ka 3,40 udhaar", "Ramesh ka 340 udhaar."])
def test_F08_punctuation_is_cleaned(shop, text):
    shop.seed(("ramesh", "credit", 100))
    expect_saved(shop.say(text), ("credit", "ramesh", 340), shop=shop)
