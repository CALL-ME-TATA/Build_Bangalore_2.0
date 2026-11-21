"""H. Bills, items and part payments (docs/EDGE_CASES.md section H, CONTRACT 1.14 and 2.1)."""
from __future__ import annotations

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_saved


def _confirm(t, kind):
    expect_ask(t, "confirm_entry")
    assert (t.confirm or {}).get("type") == kind, f"expected confirm type {kind}: {t.describe()} {t.confirm}"


def test_H01_bill_minus_payment_is_confirmed_then_saved(shop):
    shop.seed(("ramesh", "credit", 340))
    t = shop.say("Ramesh ka bill 450 hai, 200 diya, baaki udhaar")
    _confirm(t, "computed")
    assert (t.confirm.get("bill"), t.confirm.get("paid")) == (450, 200), t.describe()
    expect_saved(shop.say("haan"), ("credit", "ramesh", 250), shop=shop)
    assert shop.balance("ramesh") == 590


def test_H01_bill_without_a_name_asks_who_first(shop):
    shop.seed(("ramesh", "credit", 340))
    expect_ask(shop.say("Bill 450 hai, 200 diya, baaki udhaar"), "missing_customer")


def test_H02_discount_is_subtracted(shop):
    shop.seed(("ramesh", "credit", 340))
    _confirm(shop.say("Ramesh ka 500 udhaar, 100 discount"), "computed")
    expect_saved(shop.say("haan"), ("credit", "ramesh", 400), shop=shop)


def test_H03_a_quantity_without_a_price_asks_the_price(rs):
    t = rs.say("Ramesh ko 2 kilo chawal udhaar")
    expect_ask(t, "missing_amount")
    assert not any(r["amount"] == 2 for r in t.added)
    expect_saved(rs.say("250 rupaye"), ("credit", "ramesh", 250), shop=rs)


def test_H04_poora_de_diya_confirms_the_whole_balance(shop):
    shop.seed(("sunita", "credit", 770))
    t = shop.say("Sunita ne poora de diya")
    _confirm(t, "settle")
    assert t.confirm.get("balance") == 770, t.describe()
    expect_saved(shop.say("haan"), ("payment", "sunita", 770), shop=shop)
    assert shop.balance("sunita") == 0


def test_H05_aadha_with_an_even_balance_offers_half(shop):
    shop.seed(("sunita", "credit", 770))
    _confirm(shop.say("Sunita ne aadha de diya"), "half")
    expect_saved(shop.say("haan"), ("payment", "sunita", 385), shop=shop)


def test_H05_aadha_with_an_odd_balance_asks_the_amount(shop):
    shop.seed(("sunita", "credit", 775))
    expect_ask(shop.say("Sunita ne aadha de diya"), "missing_amount")


@pytest.mark.parametrize("text", ["Ramesh ka baaki chhod do", "Ramesh ka maaf kar do"])
def test_H06_writeoff_is_confirmed_and_is_not_a_payment(shop, text):
    shop.seed(("ramesh", "credit", 340))
    _confirm(shop.say(text), "writeoff")
    t = shop.say("haan")
    expect_saved(t, ("writeoff", "ramesh", 340), shop=shop)
    assert shop.balance("ramesh") == 0
    assert shop.ledger.payment_total(shop.today) == 0, "a write-off is not counted as a payment received"


@pytest.mark.parametrize("text", ["Ramesh ka hisaab barabar", "Ramesh ka hisaab saaf"])
def test_H07_settling_is_confirmed_first(shop, text):
    shop.seed(("ramesh", "credit", 340))
    t = shop.say(text)
    _confirm(t, "settle")
    assert shop.balance("ramesh") == 340, "nothing may be saved before the yes"


def test_H07_settling_a_zero_balance_is_only_a_query(shop):
    shop.seed(("ramesh", "credit", 100), ("ramesh", "payment", 100))
    t = shop.say("Ramesh ka hisaab barabar")
    expect_nothing_saved(t)
    assert t.status != "needs_clarification", t.describe()


def test_H08_payment_above_the_balance_is_asked(shop):
    shop.seed(("ramesh", "credit", 340))
    t = shop.say("Ramesh ne 1000 diye")
    _confirm(t, "overpayment")
    assert t.confirm.get("balance") == 340, t.describe()
    expect_saved(shop.say("haan"), ("payment", "ramesh", 1000), shop=shop)


def test_H08_payment_equal_to_the_balance_saves(shop):
    shop.seed(("ramesh", "credit", 340))
    expect_saved(shop.say("Ramesh ne 340 diye"), ("payment", "ramesh", 340), shop=shop)


def test_H09_round_off_drops_the_remainder(shop):
    shop.seed(("ramesh", "credit", 347))
    _confirm(shop.say("Ramesh ka round off kar do"), "roundoff")
    expect_saved(shop.say("haan"), ("writeoff", "ramesh", 7), shop=shop)
    assert shop.balance("ramesh") == 340


def test_H09_round_off_of_a_round_balance_asks(shop):
    shop.seed(("ramesh", "credit", 340))
    t = shop.say("Ramesh ka round off kar do")
    expect_ask(t, "missing_amount")


def test_H10_a_stated_balance_is_not_an_entry(rs):
    t = rs.say("Ramesh ka 340 udhaar, total 800 ho gaya")
    expect_saved(t, ("credit", "ramesh", 340), shop=rs)
