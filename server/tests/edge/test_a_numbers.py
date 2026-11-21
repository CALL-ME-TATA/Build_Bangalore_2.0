"""A. Number parsing (docs/EDGE_CASES.md section A, CONTRACT 1.3 and 1.14)."""
from __future__ import annotations

import pytest

from nlu.numbers import parse_number

from .kit import expect_ask, expect_nothing_saved, expect_reject, expect_saved, parse, roster


def _says_credit(rs, phrase: str, amount: int, name: str = "ramesh"):
    t = rs.say(f"{name.title()} ka {phrase} udhaar")
    expect_saved(t, ("credit", name, amount), shop=rs)


def _phrase_case(rs, phrase: str, value: int) -> None:
    assert parse_number(phrase) == value, f"parse_number({phrase!r}) -> {parse_number(phrase)!r}, expected {value}"
    _says_credit(rs, phrase, value)


def test_A01_teen_sau_chaalis(rs):
    _phrase_case(rs, "teen sau chaalis", 340)


@pytest.mark.parametrize("phrase", ["three hundred forty", "three forty"])
def test_A02_english_340(rs, phrase):
    _phrase_case(rs, phrase, 340)


def test_A03_dedh_sau(rs):
    _phrase_case(rs, "dedh sau", 150)


def test_A04_dhai_sau(rs):
    _phrase_case(rs, "dhai sau", 250)


def test_A05_sawa_sau(rs):
    _phrase_case(rs, "sawa sau", 125)


def test_A06_saade_teen_sau(rs):
    _phrase_case(rs, "saade teen sau", 350)


def test_A07_paanch_sau_paanch(rs):
    _phrase_case(rs, "paanch sau paanch", 505)


def test_A08_do_hazaar_paanch_sau(rs):
    _phrase_case(rs, "do hazaar paanch sau", 2500)


@pytest.mark.parametrize("phrase,value", [("unchaas", 49), ("unsath", 59), ("unnasi", 79), ("nawasi", 89)])
def test_A09_unnasi_is_79(rs, phrase, value):
    assert parse_number(phrase) == value
    _says_credit(rs, phrase, value)


@pytest.mark.parametrize("phrase,value", [("pachaas", 50), ("saath", 60), ("pachhattar", 75)])
def test_A10_tens(rs, phrase, value):
    assert parse_number(phrase) == value
    # CONTRACT 1.15: a bare `saath` in the amount position is asked about; with a currency word it is 60.
    _says_credit(rs, f"{phrase} rupaye" if phrase == "saath" else phrase, value)


def test_A11_teen_chaar_sau_asks_340_or_400(rs):
    t = rs.say("Ramesh ka teen chaar sau udhaar")
    expect_ask(t, "confusable_number")
    assert t.candidates == [340, 400], t.describe()
    t2 = rs.say("pehla")
    expect_saved(t2, ("credit", "ramesh", 340), shop=rs)


def test_A12_two_amounts_with_ya_asks_both(rs):
    t = rs.say("Ramesh ka 200 ya 300 udhaar")
    expect_ask(t, "confusable_number")
    assert t.candidates == [200, 300], t.describe()


@pytest.mark.parametrize("phrase,value", [("₹2,000", 2000), ("2,000", 2000), ("2k", 2000), ("2.5k", 2500)])
def test_A13_k_suffix_and_separators(rs, phrase, value):
    if "k" not in phrase:
        assert parse_number(phrase) == value
    _says_credit(rs, phrase, value)


def test_A14_500000_is_confirmed_before_saving(rs):
    t = rs.say("Ramesh ka 5,00,000 udhaar")
    expect_ask(t, "plausibility")
    t2 = rs.say("haan")
    expect_saved(t2, ("credit", "ramesh", 500000), shop=rs)


@pytest.mark.parametrize("phrase", ["zero", "0", "minus 50"])
def test_A15_zero_and_negative_are_rejected(rs, phrase):
    t = rs.say(f"Ramesh ka {phrase} udhaar")
    expect_reject(t, "invalid_number")


@pytest.mark.parametrize("text", ["ek customer ka", "ek customer aaya tha", "Ramesh ek baar aaya tha"])
def test_A16_stray_ek_is_not_amount_one(rs, text):
    t = rs.say(text)
    assert t.status != "ok" or t.action != "append", t.describe()
    expect_nothing_saved(t)
    assert not any(r["amount"] == 1 for r in t.added)


@pytest.mark.parametrize("text", ["Ramesh Ramesh ka 340 340 udhaar", "Ramesh ka teen sau teen sau chaalis udhaar"])
def test_A17_repeated_words_are_said_once(rs, text):
    t = rs.say(text)
    expect_saved(t, ("credit", "ramesh", 340), shop=rs)


@pytest.mark.parametrize("phrase", ["four three zero", "char teen shunya"])
def test_A18_digits_one_by_one(rs, phrase):
    _says_credit(rs, phrase, 430)


def test_A18_two_single_digits_ask_for_the_amount(rs):
    t = rs.say("Ramesh ka teen chaar udhaar")
    expect_ask(t, "missing_amount")


@pytest.mark.parametrize("heard,alt,pair", [
    ("Ramesh ka fifteen udhaar", "Ramesh ka fifty udhaar", [15, 50]),
    ("Ramesh ka twelve udhaar", "Ramesh ka twenty udhaar", [12, 20]),
])
def test_A19_second_transcript_disagrees_asks(heard, alt, pair):
    r = parse(heard, ctx={"customers": roster("ramesh"), "stt_alternatives": [alt]})
    assert r["status"] == "needs_clarification" and r.get("reason") == "confusable_number", r
    assert r["candidates"] == pair, r


def test_A19_confusables_table_asks_at_parser_level():
    r = parse("Ramesh ka 340 udhaar", ctx={"customers": roster("ramesh"), "confusables": {"340": [740]}})
    assert r["status"] == "needs_clarification" and r.get("reason") == "confusable_number", r
    assert r["candidates"] == [340, 740], r


def test_A19_shop_correction_history_reaches_the_parser(rs):
    for _ in range(2):
        rs.say("Ramesh ka 340 udhaar")
        rs.say("nahi 740")
    n = rs.count()
    t = rs.say("Ramesh ka 340 udhaar")
    expect_ask(t, "confusable_number")
    assert rs.count() == n


@pytest.mark.parametrize("phrase,value", [("१२३", 123), ("३४०", 340), ("١٢٣", 123)])
def test_A20_other_digit_scripts(rs, phrase, value):
    _says_credit(rs, phrase, value)


@pytest.mark.parametrize("amount", [1000, 9000])
def test_A21_ten_times_the_usual_is_confirmed(shop, amount):
    shop.seed(("ramesh", "credit", 100), ("ramesh", "credit", 120), ("ramesh", "credit", 90))
    t = shop.say(f"Ramesh ka {amount} udhaar")
    expect_ask(t, ("plausibility", "confirm_entry"))


def test_A21_five_times_the_usual_saves(shop):
    shop.seed(("ramesh", "credit", 100), ("ramesh", "credit", 120), ("ramesh", "credit", 90))
    expect_saved(shop.say("Ramesh ka 500 udhaar"), ("credit", "ramesh", 500), shop=shop)


def test_A21_usual_needs_three_entries(shop):
    shop.seed(("ramesh", "credit", 100), ("ramesh", "credit", 120))
    expect_saved(shop.say("Ramesh ka 9000 udhaar"), ("credit", "ramesh", 9000), shop=shop)


@pytest.mark.parametrize("phrase", ["51000", "99 lakh"])
def test_A22_large_amount_is_confirmed(rs, phrase):
    t = rs.say(f"Ramesh ka {phrase} udhaar")
    expect_ask(t, "plausibility")


def test_A22_exactly_the_limit_saves(rs):
    expect_saved(rs.say("Ramesh ka 50000 udhaar"), ("credit", "ramesh", 50000), shop=rs)


@pytest.mark.parametrize("phrase", ["5 crore", "999999999999", "1,00,00,000"])
def test_A22_above_the_maximum_is_rejected(rs, phrase):
    t = rs.say(f"Ramesh ka {phrase} udhaar")
    expect_reject(t, "too_large")


@pytest.mark.parametrize("text,kind,amount", [
    ("Ramesh ka rs 500 udhaar", "credit", 500), ("Ramesh ka rs. 500 udhaar", "credit", 500),
    ("Ramesh ka 500 rupaye udhaar", "credit", 500), ("Ramesh ka 500 rupay udhaar", "credit", 500),
    ("Ramesh ka 500 rupaiye udhaar", "credit", 500), ("Ramesh ka 500 rupees udhaar", "credit", 500),
    ("Ramesh ka 500 paise udhaar", "credit", 500), ("Ramesh ka ₹500 udhaar", "credit", 500),
    ("Ramesh ne paanch sau paisa diye", "payment", 500), ("Ramesh ka 500 paisa udhaar", "credit", 500),
])
def test_A23_currency_words(rs, text, kind, amount):
    expect_saved(rs.say(text), (kind, "ramesh", amount), shop=rs)


def test_A23_currency_word_is_never_a_name(rs):
    t = rs.say("Ramesh ne paise diye")
    expect_ask(t, "missing_amount")


def test_A24_teen_as_a_count_is_not_an_entry(rs):
    t = rs.say("teen customer aaye the")
    expect_reject(t, "not_ledger")


def test_A24_bare_teen_amount_is_confirmed(rs):
    t = rs.say("Ramesh ka teen udhaar")
    expect_ask(t, "plausibility")


def test_A24_teen_rupaye_is_an_amount(rs):
    expect_saved(rs.say("Ramesh ka teen rupaye udhaar"), ("credit", "ramesh", 3), shop=rs)
