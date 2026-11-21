"""B. Direction: credit or payment (docs/EDGE_CASES.md section B, CONTRACT 1.4 and 1.14)."""
from __future__ import annotations

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_reject, expect_saved


def test_B01_ko_diya_is_credit(rs):
    expect_saved(rs.say("Sunita ko 500 diya"), ("credit", "sunita", 500), shop=rs)


def test_B02_ne_diya_is_payment(rs):
    expect_saved(rs.say("Sunita ne 500 diya"), ("payment", "sunita", 500), shop=rs)


def test_B03_ka_udhaar_is_credit(rs):
    expect_saved(rs.say("Ramesh ka 340 udhaar"), ("credit", "ramesh", 340), shop=rs)


def test_B04_payment_diya(rs):
    expect_saved(rs.say("Ramesh ne 200 payment diya"), ("payment", "ramesh", 200), shop=rs)


def test_B04_bare_mila_is_never_a_credit(rs):
    """`200 mila` has no name: it is asked, or carried over as a payment. It is never a credit."""
    expect_saved(rs.say("Ramesh ne 100 diye"), ("payment", "ramesh", 100), shop=rs)
    t = rs.say("200 mila")
    if t.status == "ok":
        expect_saved(t, ("payment", "ramesh", 200), shop=rs)
    else:
        expect_ask(t, "missing_customer")


@pytest.mark.parametrize("text", ["Sunita paid 500", "received 500 from Sunita"])
def test_B05_english_payment(rs, text):
    expect_saved(rs.say(text), ("payment", "sunita", 500), shop=rs)


@pytest.mark.parametrize("text", ["gave Sunita 500 on credit", "Sunita owes 500"])
def test_B06_english_credit(rs, text):
    expect_saved(rs.say(text), ("credit", "sunita", 500), shop=rs)


def test_B07_no_name_asks_who(rs):
    expect_ask(rs.say("500 diya"), "missing_customer")


def test_B08_no_direction_asks(rs):
    expect_ask(rs.say("Sunita ka 500"), "ambiguous_direction")


def test_B09_negation_blocks_an_entry(rs):
    expect_reject(rs.say("Sunita ne nahi diya"), "negated")


def test_B10_nahi_dena_hai_saves_nothing(rs):
    t = rs.say("Sunita ko 500 nahi dena hai")
    assert t.status == "rejected", t.describe()
    expect_nothing_saved(t)


@pytest.mark.parametrize("text,amount", [
    ("Ramesh ne 30 udhaar chuka diya", 30), ("Ramesh ka udhaar wapas aaya 20", 20),
    ("Ramesh ne 50 udhaar wapas kiya", 50),
])
def test_B11_udhaar_wapas_is_payment(rs, text, amount):
    expect_saved(rs.say(text), ("payment", "ramesh", amount), shop=rs)


def test_B11_udhaar_chuka_diya_without_amount_settles_after_yes(rs):
    t = rs.say("Ramesh ne udhaar chuka diya")
    expect_ask(t, "confirm_entry")
    expect_saved(rs.say("haan"), ("payment", "ramesh", 1000), shop=rs)


@pytest.mark.parametrize("text", ["Sunita 500 diya", "Sunita ko ne 500 diya"])
def test_B12_particle_dropped_or_swapped_asks(rs, text):
    expect_ask(rs.say(text))


def test_B12_ne_and_ko_for_one_name_asks_direction(rs):
    expect_ask(rs.say("Sunita ko ne 500 diya"), "ambiguous_direction")


def test_B13_amount_first_is_credit_with_ko(rs):
    expect_saved(rs.say("500 Sunita ko diya"), ("credit", "sunita", 500), shop=rs)


def test_B14_two_customers_in_one_clause_is_rejected(rs):
    expect_reject(rs.say("Ramesh ne Sunita ko 100 diya"), "out_of_scope")


@pytest.mark.parametrize("text", ["Ramesh ne advance 500 diya", "Ramesh ka 500 advance"])
def test_B15_advance_is_a_payment_without_overpayment_question(rs, text):
    expect_saved(rs.say(text), ("payment", "ramesh", 500), shop=rs)
    assert rs.balance("ramesh") == 500


def test_B15_advance_without_a_name_asks_who_then_saves(rs):
    expect_ask(rs.say("advance 500 diya"), "missing_customer")
    expect_saved(rs.say("Ramesh"), ("payment", "ramesh", 500), shop=rs)


def test_B16_wapas_kiya_without_name_asks(rs):
    expect_ask(rs.say("wapas kiya 100"), ("missing_customer", "ambiguous_direction"))


def test_B16_wapas_kiya_with_ko_asks_direction(rs):
    expect_ask(rs.say("Ramesh ko 100 wapas kiya"), "ambiguous_direction")


def test_B16_ne_wapas_kiya_is_payment(rs):
    expect_saved(rs.say("Ramesh ne 100 wapas kiya"), ("payment", "ramesh", 100), shop=rs)
