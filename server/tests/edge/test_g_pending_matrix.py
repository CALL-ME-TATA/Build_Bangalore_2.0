"""G08 across every kind of open question: a complete new sentence replaces the question (CONTRACT 1.9, 1.13).

Each case raises one pending question, then says one of four things. The fresh sentence is parsed on its own, and
no amount, kind or customer of the dropped question may reach the ledger.
"""
from __future__ import annotations

import pytest

from .kit import expect_nothing_saved, expect_query, expect_saved

BASE = [("ramesh", "credit", 1000), ("sunita", "credit", 1000), ("mohan", "credit", 1007)]
TAGGED = [("ramesh", "credit", 1000, 0, "chai wale"), ("ramesh", "credit", 1000, 0, "gali wale"),
          ("sunita", "credit", 1000), ("mohan", "credit", 1007)]


def case(say, reason, c="ramesh", o="sunita", forbid=(), confirm=None, known=True, seeds=BASE, fresh=None):
    return dict(say=say, reason=reason, c=c, o=o, forbid=set(forbid), confirm=confirm, known=known, seeds=seeds,
                fresh=fresh)


SETUPS = {
    "new_customer": case(["Geeta ne 150 diye"], "new_customer", c="geeta", o="ramesh", forbid=[150], known=False),
    "computed": case(["Ramesh ka bill 450 hai, 200 diya, baaki udhaar"], "confirm_entry", forbid=[250],
                     confirm="computed"),
    "settle": case(["Ramesh ne poora de diya"], "confirm_entry", forbid=[1000], confirm="settle"),
    "half": case(["Sunita ne aadha de diya"], "confirm_entry", c="sunita", o="ramesh", forbid=[500], confirm="half"),
    "writeoff": case(["Ramesh ka baaki chhod do"], "confirm_entry", forbid=[1000], confirm="writeoff"),
    "roundoff": case(["Mohan ka round off kar do"], "confirm_entry", c="mohan", o="ramesh", forbid=[7],
                     confirm="roundoff"),
    "overpayment": case(["Ramesh ne 5000 diye"], "confirm_entry", forbid=[5000], confirm="overpayment"),
    "duplicate": case(["Ramesh ne 100 diye", "Ramesh ne 100 diye"], "confirm_entry", forbid=[100],
                      confirm="duplicate"),
    "hearsay": case(["Ramesh bol raha tha 340 udhaar"], "confirm_entry", forbid=[340], confirm="hearsay"),
    "unsure": case(["Ramesh ka blorp 340 udhaar"], "confirm_entry", forbid=[340], confirm="unsure"),
    "missing_amount": case(["Ramesh ne paise diye"], "missing_amount"),
    "missing_customer": case(["500 diya"], "missing_customer", forbid=[500]),
    "ambiguous_direction": case(["Ramesh ka 500"], "ambiguous_direction", forbid=[500]),
    "same_name": case(["Ramesh ka 50 udhaar"], "same_name", forbid=[50], seeds=TAGGED,
                      fresh="Ramesh chai wale ka 61 udhaar"),
    "confusable_number": case(["Ramesh ka teen chaar sau udhaar"], "confusable_number", forbid=[340, 400]),
    "plausibility": case(["Ramesh ka 51000 udhaar"], "plausibility", forbid=[51000]),
    "unclear_correction": case(["Ramesh ka 100 udhaar", "nahi"], "unclear_correction"),
    "unclear_correction_two_entries": case(["Ramesh ka 340 udhaar, kal 200 diya tha", "nahi, 430"],
                                           "unclear_correction", forbid=[430]),
    "unclear_date": case(["Ramesh ne pichle hafte 200 diye"], "unclear_date", forbid=[200]),
    "name_alone": case(["Ramesh"], "missing_amount"),
}

FRESH_SAME = {"ramesh": "Ramesh ka 61 udhaar", "mohan": "Mohan ka 61 udhaar", "sunita": "Sunita ka 61 udhaar",
              "geeta": "Geeta ka 61 udhaar"}


def raise_question(shop, setup):
    shop.seed(*setup["seeds"])
    last = None
    for sentence in setup["say"]:
        last = shop.say(sentence)
    assert last.status == "needs_clarification" and last.reason == setup["reason"], (
        f"setup did not raise {setup['reason']}: {last.describe()}")
    if setup["confirm"]:
        assert (last.confirm or {}).get("type") == setup["confirm"], f"confirm type: {last.describe()}"
    return shop.count()


def no_pending_amount_reached(shop, setup, since):
    rows = [r for r in shop.rows() if r["id"] > since and r["kind"] != "reversal"]
    leaked = [r for r in rows if r["amount"] in setup["forbid"]]
    assert not leaked, f"an amount of the dropped question reached the ledger: {leaked}"


def after_fresh_nothing_pending_is_left(shop):
    n = shop.count()
    t = shop.say("haan")
    expect_nothing_saved(t, "the dropped question was answered later")
    assert shop.count() == n


@pytest.mark.parametrize("name", SETUPS)
def test_G08_complete_entry_for_the_same_customer_is_parsed_fresh(shop, name):
    setup = SETUPS[name]
    since = raise_question(shop, setup)
    t = shop.say(setup["fresh"] or FRESH_SAME[setup["c"]])
    if setup["known"]:
        expect_saved(t, ("credit", setup["c"], 61), shop=shop)
    else:
        assert t.status == "needs_clarification" and t.reason == "new_customer", t.describe()
        expect_nothing_saved(t)
    no_pending_amount_reached(shop, setup, since)
    if setup["known"]:
        after_fresh_nothing_pending_is_left(shop)


@pytest.mark.parametrize("name", SETUPS)
def test_G08_complete_entry_for_another_customer_is_parsed_fresh(shop, name):
    setup = SETUPS[name]
    since = raise_question(shop, setup)
    t = shop.say(f"{setup['o'].title()} ne 77 diye")
    expect_saved(t, ("payment", setup["o"], 77), shop=shop)
    no_pending_amount_reached(shop, setup, since)
    after_fresh_nothing_pending_is_left(shop)


@pytest.mark.parametrize("name", SETUPS)
def test_G08_a_balance_query_drops_the_question(shop, name):
    setup = SETUPS[name]
    since = raise_question(shop, setup)
    t = shop.say(f"{setup['o'].title()} ka total?")
    expect_query(t)
    assert shop.count() == since
    after_fresh_nothing_pending_is_left(shop)


@pytest.mark.parametrize("name", SETUPS)
def test_G08_an_unrelated_half_sentence_saves_nothing(shop, name):
    setup = SETUPS[name]
    since = raise_question(shop, setup)
    t = shop.say("mausam achha hai")
    expect_nothing_saved(t)
    assert shop.count() == since
    no_pending_amount_reached(shop, setup, since)
