""""Tanish se 200 wapis aaye" is a payment, so saying it again after a mishearing is a complete entry and
replaces the open question (CONTRACT: only a complete entry or a query replaces one)."""
from __future__ import annotations

from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
NAMES = ["tanish", "tanish sharma", "tanish dhawan", "ramesh"]
CTX = {"customers": [{"id": i, "name": n, "tags": [], "aliases": []} for i, n in enumerate(NAMES, 1)],
       "limits": {"strict": True, "confirm_new_customer": True}}


def events(r):
    return (r.get("events") or []) + ((r.get("pending") or {}).get("events") or [])


@pytest.mark.parametrize("sentence,name,amount", [
    ("Tanish Dhawan se do sau rupaye wapis aaye.", "tanish dhawan", 200),
    ("Ramesh ke chaar sau rupaye wapis aaye.", "ramesh", 400),
    ("Ramesh se 300 vapis mile", "ramesh", 300),
])
def test_money_coming_back_is_a_payment(sentence, name, amount):
    r = parse(sentence, today=T, ctx=CTX)
    assert r["status"] == "ok", r
    assert [(e["customer"], e["kind"], e["amount"]) for e in r["events"]] == [(name, "payment", amount)]


def test_shop_paying_back_still_asks():
    r = parse("Ramesh ko 200 wapas diye", today=T, ctx=CTX)
    assert (r["status"], r["reason"]) == ("needs_clarification", "ambiguous_direction")


def test_saying_the_complete_sentence_again_replaces_the_question():
    misheard = parse("tane se do sau rupaye wapis aaye.", today=T, ctx=CTX)
    assert misheard["status"] == "needs_clarification" and events(misheard)[0]["customer"] == "tane"
    again = parse("Tanish se do sau rupaye wapis aaye.", today=T, ctx=dict(CTX, pending=misheard["pending"]))
    assert "tane" not in str(again).lower(), again
    assert again["reason"] == "same_name" and [e["kind"] for e in events(again)] == ["payment"]


def test_a_plain_answer_still_answers():
    q = parse("Ramesh ke 200", today=T, ctx=CTX)
    assert q["reason"] == "ambiguous_direction"
    a = parse("jama", today=T, ctx=dict(CTX, pending=q["pending"]))
    assert a["status"] == "ok" and [(e["customer"], e["kind"]) for e in a["events"]] == [("ramesh", "payment")]


def test_an_amount_answer_for_the_same_customer_still_answers():
    q = parse("Ramesh ka udhaar likho", today=T, ctx=CTX)
    a = parse("Ramesh ka 250", today=T, ctx=dict(CTX, pending=q["pending"]))
    assert a["status"] == "ok" and [(e["customer"], e["amount"]) for e in a["events"]] == [("ramesh", 250)], a
