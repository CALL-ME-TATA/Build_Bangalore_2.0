""""Diwakar" and "Diwakar Sharma" are both customers: "Diwakar ke 200 aaye" asks which one."""
from __future__ import annotations

from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
CTX = {"customers": [{"id": 5, "name": "diwakar", "tags": [], "aliases": []},
                     {"id": 6, "name": "diwakar sharma", "tags": [], "aliases": []}],
       "limits": {"strict": True, "confirm_new_customer": True}}


def ask():
    r = parse("diwakar ke 200 rs aaye", today=T, ctx=CTX)
    assert (r["status"], r["reason"]) == ("needs_clarification", "same_name"), r
    assert r["question"] == "Aap kaunse Diwakar ki baat kar rahe hain: Diwakar, Diwakar Sharma ya koi aur?"
    return r


@pytest.mark.parametrize("answer,cid", [
    ("Diwakar Sharma", 6), ("Sharma ji", 6), ("doosra", 6), ("Diwakar nahi, Diwakar Sharma", 6),
    ("sirf Diwakar", 5), ("Diwakar", 5), ("pehla", 5), ("Diwakar Sharma nahi, Diwakar", 5),
])
def test_answer_picks_the_right_diwakar(answer, cid):
    r = parse(answer, today=T, ctx=dict(CTX, pending=ask()["pending"]))
    assert r["status"] == "ok" and [(e["customer_id"], e["amount"], e["kind"]) for e in r["events"]] == \
        [(cid, 200, "payment")], r


def test_unclear_answer_asks_again():
    r = parse("pata nahi", today=T, ctx=dict(CTX, pending=ask()["pending"]))
    assert r["status"] == "needs_clarification"


def test_full_name_is_not_asked():
    r = parse("Diwakar Sharma ne 200 diye", today=T, ctx=CTX)
    assert r["status"] == "ok" and r["events"][0]["customer_id"] == 6


def test_single_customer_is_not_asked():
    ctx = dict(CTX, customers=CTX["customers"][:1])
    r = parse("diwakar ke 200 rs aaye", today=T, ctx=ctx)
    assert r["status"] == "ok" and r["events"][0]["customer_id"] == 5


def other(answer="koi aur"):
    r = parse(answer, today=T, ctx=dict(CTX, pending=ask()["pending"]))
    assert (r["status"], r["reason"]) == ("needs_clarification", "new_tag"), r
    assert r["question"] == "Naye Diwakar ki pehchaan boliye, jaise 'chai wale' ya 'gali 3 wale'."
    return r


@pytest.mark.parametrize("answer", ["koi aur", "koi doosra", "naya", "koi aur Diwakar", "new one", "naya wala"])
def test_someone_else_asks_for_a_label_first(answer):
    other(answer)


@pytest.mark.parametrize("label,tag", [("chai wale", "chai wale"), ("gali 3", "gali 3 wale"),
                                       ("Diwakar doodh wala", "doodh wala")])
def test_label_opens_a_new_diwakar_with_it(label, tag):
    r = parse(label, today=T, ctx=dict(CTX, pending=other()["pending"]))
    assert r["status"] == "ok", r
    ev = r["events"][0]
    assert ev.get("new_customer") is True and "customer_id" not in ev and ev["tags"] == [tag] and ev["amount"] == 200


def test_no_label_opens_it_without_one():
    r = parse("bina pehchaan", today=T, ctx=dict(CTX, pending=other()["pending"]))
    assert r["status"] == "ok" and r["events"][0].get("new_customer") and not r["events"][0].get("tags")


def test_a_label_already_in_use_is_asked_again():
    ctx = {**CTX, "customers": CTX["customers"] + [{"id": 7, "name": "diwakar", "tags": ["chai wale"], "aliases": []}]}
    first = parse("diwakar ke 200 rs aaye", today=T, ctx=ctx)
    asked = parse("koi aur", today=T, ctx=dict(ctx, pending=first["pending"]))
    r = parse("chai wale", today=T, ctx=dict(ctx, pending=asked["pending"]))
    assert (r["status"], r["reason"]) == ("needs_clarification", "new_tag"), r


def test_naya_nahi_is_not_someone_else():
    r = parse("naya nahi", today=T, ctx=dict(CTX, pending=ask()["pending"]))
    assert not (r["status"] == "ok" and r["events"][0].get("new_customer")), r
