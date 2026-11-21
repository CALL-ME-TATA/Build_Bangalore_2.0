"""J. Queries and voice insights (docs/EDGE_CASES.md section J, CONTRACT 1.7, 1.14, 2.1 and 5.1)."""
from __future__ import annotations

import time

import pytest

from .kit import expect_query, parse, roster


def book(shop):
    shop.seed(("ramesh", "credit", 340), ("sunita", "credit", 770), ("mohan", "credit", 120),
              ("geeta", "credit", 60), ("sunita", "payment", 70))


def test_J01_balance_is_spoken(shop):
    book(shop)
    t = shop.say("Ramesh ka total?")
    expect_query(t)
    assert "340" in t.reply_text, t.describe()


def test_J02_todays_credit_total(shop):
    book(shop)
    t = shop.say("Aaj kitna udhaar gaya?")
    expect_query(t)
    assert "1290" in t.reply_text.replace(",", ""), t.describe()


def test_J03_daily_summary_is_fast_and_has_both_totals(shop):
    book(shop)
    t0 = time.perf_counter()
    t = shop.say("Aaj ka hisaab batao")
    assert time.perf_counter() - t0 < 2.0
    expect_query(t)
    text = t.reply_text.replace(",", "")
    assert "1290" in text and "70" in text, t.describe()


def test_J04_top_three_are_spoken_and_the_rest_are_left_out(shop):
    book(shop)
    t = shop.say("Kis kis ka baaki hai?")
    expect_query(t)
    low = t.reply_text.lower()
    assert all(n in low for n in ("sunita", "ramesh", "mohan")), t.describe()
    assert "geeta" not in low, f"only the top three are spoken: {t.describe()}"


def test_J05_biggest_due_is_named(shop):
    book(shop)
    t = shop.say("Sabse zyada udhaar kiska hai?")
    expect_query(t)
    assert "sunita" in t.reply_text.lower() and "700" in t.reply_text, t.describe()


def test_J06_this_month_uses_month_boundaries(shop):
    shop.seed(("ramesh", "credit", 1700, 21), ("ramesh", "credit", 200, 20), ("ramesh", "credit", 30, 1))
    t = shop.say("Is mahine ka total")
    expect_query(t)
    assert "230" in t.reply_text and "1700" not in t.reply_text.replace(",", ""), t.describe()
    r = parse("Is mahine ka total", ctx={"customers": roster("ramesh")}, today=shop.today)
    assert r["query"]["type"] == "daily_summary" and r["query"]["period"] == "this_month", r


def test_J06_last_week_runs_monday_to_sunday(shop):
    """Today is Saturday 2026-11-21: last week is Monday 9 to Sunday 15 November."""
    shop.seed(("ramesh", "credit", 333, 13), ("ramesh", "credit", 111, 6), ("ramesh", "credit", 222, 5))
    t = shop.say("pichle hafte kitna udhaar gaya")
    expect_query(t)
    text = t.reply_text.replace(",", "")
    assert "111" in text and "222" not in text and "333" not in text, t.describe()
    r = parse("pichle hafte kitna udhaar gaya", ctx={"customers": roster("ramesh")}, today=shop.today)
    assert r["query"]["type"] == "credit_total" and r["query"]["period"] == "last_week", r


def test_J07_oldest_unpaid_credit_date(shop):
    shop.seed(("ramesh", "credit", 100, 10), ("ramesh", "credit", 50, 3), ("ramesh", "payment", 100, 1))
    t = shop.say("Ramesh ka kab se baaki hai?")
    expect_query(t)
    assert "18" in t.reply_text, f"the oldest credit not fully settled is dated 18 November: {t.describe()}"
    r = parse("Ramesh ka kab se baaki hai?", ctx={"customers": roster("ramesh")}, today=shop.today)
    assert r["query"]["type"] == "due_since", r


def test_J08_two_hundred_entries_answer_in_one_short_sentence(shop):
    for i in range(100):
        shop.ledger.apply({"status": "ok", "action": "append", "events": [
            {"kind": "credit", "customer": "ramesh", "amount": 10, "date": shop.day(0)},
            {"kind": "payment", "customer": "ramesh", "amount": 4, "date": shop.day(0)}]},
            now=shop.clock.t, session_id="seed")
    assert shop.count() == 200
    t = shop.say("Ramesh ka total?")
    expect_query(t)
    assert "600" in t.reply_text and len(t.reply_text.split()) <= 12, t.describe()


def test_J09_total_outstanding_across_customers(shop):
    book(shop)
    t = shop.say("Total udhaar kitna hai")
    expect_query(t)
    assert "1220" in t.reply_text.replace(",", "") and "4" in t.reply_text, t.describe()
    r = parse("Total udhaar kitna hai", ctx={"customers": roster("ramesh")}, today=shop.today)
    assert r["query"]["type"] == "outstanding_total", r


def test_J10_zero_balance_is_settled_not_owes_zero(shop):
    shop.seed(("ramesh", "credit", 100), ("ramesh", "payment", 100))
    t = shop.say("Ramesh ka total?")
    expect_query(t)
    assert "barabar" in t.reply_text.lower() and "₹0" not in t.reply_text, t.describe()


def test_J10_english_zero_balance_says_settled(shop):
    shop.seed(("ramesh", "credit", 100), ("ramesh", "payment", 100))
    t = shop.say("what is Ramesh's balance")
    expect_query(t)
    assert "settled" in t.reply_text.lower(), t.describe()
