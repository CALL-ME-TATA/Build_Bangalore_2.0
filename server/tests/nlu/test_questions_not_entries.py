"""CONTRACT 1.19: a question is never an entry.

Rule 1: a sentence with a question word or a trailing "?" and no complete entry is a query when it matches one,
otherwise rejected `not_ledger`; it never starts an entry or a question about an entry.
Rule 2: a number directly before a time unit is never an amount.
Rule 3: a question about an entry raised by a sentence that held a question word is answered and then read back
(`confirm_entry`) before anything is saved.

Today is 2026-11-22. Roster: Ramesh, Mohan, Sunita and two Sureshes (chai wale, doodh wale)."""
import json
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 22)
D0 = "2026-11-22"
ROSTER = [
    {"id": "c1", "name": "ramesh", "tags": [], "balance": 1000},
    {"id": "c2", "name": "mohan", "tags": [], "balance": 1000},
    {"id": "c3", "name": "suresh", "tags": ["chai wale"], "balance": 500},
    {"id": "c4", "name": "suresh", "tags": ["doodh wale"], "balance": 700},
    {"id": "c5", "name": "sunita", "tags": [], "balance": 900},
]


def ctx(roster=True, **extra):
    c = {"customers": json.loads(json.dumps(ROSTER))} if roster else {}
    c.update(extra)
    return c


def run(utterance, c=None):
    return parse(utterance, today=T, ctx=ctx() if c is None else c)


def answer(prev, reply, c=None):
    cc = dict(ctx() if c is None else c)
    cc["pending"] = prev["pending"]
    return parse(reply, today=T, ctx=cc)


def amounts(r):
    events = list(r.get("events") or []) + list((r.get("pending") or {}).get("events") or [])
    return [e.get("amount") for e in events if "amount" in e]


def saved(r):
    return r.get("status") == "ok" and r.get("action") in ("append", "amend")


# --- Rule 1: a question with no complete entry ---------------------------------------------------------------

@pytest.mark.parametrize("roster", [True, False])
def test_Q6_last_payment_question_is_not_a_payment(roster):
    r = run("Pichli baar Mohan ne kitna diya tha aur kab?", ctx(roster))
    assert r["status"] == "rejected" and r["reason"] == "not_ledger", r
    assert "pending" not in r


@pytest.mark.parametrize("roster", [True, False])
def test_Q6_answer_300_after_the_question_saves_nothing(roster):
    c = ctx(roster)
    first = run("Pichli baar Mohan ne kitna diya tha aur kab?", c)
    assert "pending" not in first  # no question is asked, so "300" is not an answer
    r = run("300", c)
    assert not saved(r), r


@pytest.mark.parametrize("roster", [True, False])
def test_total_and_ageing_question_is_the_outstanding_total(roster):
    r = run("Meri kul udhaari kitni hai, aur usme se kitna 30 din se purana hai?", ctx(roster))
    assert r["status"] == "ok" and r["action"] == "query", r
    assert r["query"]["type"] == "outstanding_total"
    assert 30 not in amounts(r)


def test_total_and_ageing_question_then_a_name_and_yes_saves_nothing():
    c = ctx()
    first = run("Meri kul udhaari kitni hai, aur usme se kitna 30 din se purana hai?", c)
    assert "pending" not in first
    assert not saved(run("Ramesh", c))
    assert not saved(run("haan", c))


@pytest.mark.parametrize("roster", [True, False])
def test_list_request_with_a_negation_is_not_ledger(roster):
    r = run("Jinhone pichle do hafte me kuch nahi diya unki list batao", ctx(roster))
    assert r["status"] == "rejected" and r["reason"] == "not_ledger", r


@pytest.mark.parametrize("utterance", ["Ramesh ne kitna diya?", "Mohan ne kab diya?", "Ramesh 200?",
                                       "When did Ramesh pay 200", "who paid 200", "how much did Ramesh pay"])
def test_other_questions_without_a_complete_entry_are_not_entries(utterance):
    r = run(utterance)
    assert r["status"] == "rejected" and r["reason"] == "not_ledger", r


def test_balance_question_still_a_query():
    r = run("Suresh ka kitna baaki hai?", ctx(roster=False))
    assert r["status"] == "ok" and r["query"] == {"type": "balance", "customer": "suresh"}, r


def test_balance_question_with_two_sureshes_asks_which_then_answers_the_query():
    r = run("Suresh ka kitna baaki hai?")
    assert r["reason"] == "same_name" and r["pending"]["action"] == "query", r
    done = answer(r, "chai wale")
    assert done["status"] == "ok" and done["action"] == "query"
    assert done["query"]["type"] == "balance" and done["query"]["customer_id"] == "c3"


@pytest.mark.parametrize("utterance,query", [
    ("Ramesh ka total?", {"type": "balance", "customer": "ramesh"}),
    ("Aaj kitna udhaar gaya?", {"type": "credit_total", "period": "today"}),
    ("Meri kul udhaari kitni hai", {"type": "outstanding_total"}),
    ("Sabse zyada udhaar kiska hai?", {"type": "top_dues"}),
])
def test_queries_are_unchanged(utterance, query):
    r = run(utterance, ctx(roster=False))
    assert r["status"] == "ok" and r["action"] == "query" and r["query"] == query, r


@pytest.mark.parametrize("utterance", ["Ramesh ko 200 diye kya?", "Ramesh ka 300 udhaar kab?"])
def test_complete_entry_with_a_question_word_stays_an_entry_and_is_confirmed(utterance):
    r = run(utterance, ctx(roster=False))
    assert r["reason"] == "confirm_entry" and amounts(r) in ([200], [300]), r


# --- Rule 2: a number before a time unit -------------------------------------------------------------------------

def test_entries_keep_their_amounts_and_dates():
    r = run("Ramesh ka 340 udhaar", ctx(roster=False))
    assert r["status"] == "ok" and r["events"] == [{"kind": "credit", "customer": "ramesh", "amount": 340, "date": D0}]
    r = run("Ramesh ne 3 din pehle 200 diye", ctx(roster=False))
    assert r["status"] == "ok" and r["events"][0]["amount"] == 200 and r["events"][0]["date"] == "2026-11-19"


@pytest.mark.parametrize("utterance,iso", [("Ramesh ne do din pehle 200 diye", "2026-11-20"),
                                           ("Ramesh ne parso 200 diye", "2026-11-20"),
                                           ("Ramesh ne kal 200 diye", "2026-11-21")])
def test_relative_dates_still_work(utterance, iso):
    r = run(utterance, ctx(roster=False))
    assert r["status"] == "ok" and r["events"][0]["amount"] == 200 and r["events"][0]["date"] == iso, r


@pytest.mark.parametrize("utterance", ["5 baje Ramesh ko 200 udhaar", "Ramesh ko 200 udhaar 5 baje",
                                       "Ramesh ka 200 udhaar 30 din se", "Ramesh ko 2 ghante pehle 200 udhaar diya"])
def test_time_counts_are_never_amounts(utterance):
    r = run(utterance, ctx(roster=False))
    assert r["status"] == "ok" and r["events"][0]["amount"] == 200 and r["events"][0]["kind"] == "credit", r


@pytest.mark.parametrize("utterance", ["do hafte pehle Sunita ne 500 diye", "2 hafte pehle Sunita ne 500 diye"])
def test_weeks_ago_asks_the_date_and_never_takes_the_week_count(utterance):
    r = run(utterance, ctx(roster=False))
    assert r["reason"] == "unclear_date", r
    assert amounts(r) == [500]
    assert r["pending"]["events"][0]["kind"] == "payment" and r["pending"]["events"][0]["customer"] == "sunita"


# --- Rule 3: the answer to a question raised by a question sentence is read back ----------------------------

def _read_back(steps_result, kind, customer, amount):
    assert steps_result["reason"] == "confirm_entry", steps_result
    events = steps_result["pending"]["events"]
    assert any(e.get("kind") == kind and e.get("customer") == customer and e.get("amount") == amount for e in events)


def test_rule3_missing_customer_answer_is_read_back():
    first = run("Ramesh aur Sunita ko 500 udhaar kab")
    assert first["reason"] == "missing_customer", first
    second = answer(first, "Ramesh")
    _read_back(second, "credit", "ramesh", 500)
    done = answer(second, "haan")
    assert saved(done) and done["events"][0]["amount"] == 500


def test_rule3_missing_amount_answer_is_read_back():
    first = run("kab Ramesh ne 200 diye aur Mohan ne bhi diye")
    assert first["reason"] == "missing_amount", first
    _read_back(answer(first, "100"), "payment", "mohan", 100)


def test_rule3_same_name_answer_is_read_back():
    first = run("Suresh ko 200 udhaar likh do, kaise")
    assert first["reason"] == "same_name", first
    second = answer(first, "pehla")
    _read_back(second, "credit", "suresh", 200)
    assert answer(second, "nahi")["reason"] == "cancelled"


def test_rule3_ambiguous_direction_answer_is_read_back():
    first = run("Ramesh ka 200 udhaar aur Mohan 100 kab")
    assert first["reason"] == "ambiguous_direction", first
    _read_back(answer(first, "udhaar"), "credit", "mohan", 100)


def test_rule3_unclear_date_answer_is_read_back():
    first = run("Ramesh ne kab 200 diye pichle hafte")
    assert first["reason"] == "unclear_date", first
    second = answer(first, "kal")
    _read_back(second, "payment", "ramesh", 200)
    assert second["pending"]["events"][0]["date"] == "2026-11-21"


def test_rule3_answers_without_a_question_word_still_save_directly():
    first = run("Ramesh ko udhaar")
    assert first["reason"] == "missing_amount"
    assert saved(answer(first, "340"))
    first = run("Suresh ko 200 udhaar")
    assert first["reason"] == "same_name"
    assert saved(answer(first, "pehla"))


def test_two_amount_choice_with_a_question_mark_is_read_back():
    # "?" on a bare choice of two amounts asks which amount (A12); the entry is read back before it is saved.
    le = {"kind": "credit", "customer": "ramesh", "customer_id": "c1", "amount": 100, "date": D0, "age_s": 5}
    c = ctx(last_event=le)
    r = run("teen sau chaalis ya saat sau chaalis?", c)
    assert r["reason"] == "confusable_number" and r["candidates"] == [340, 740]
    assert r["pending"]["confirm"] == {"type": "hearsay"}
