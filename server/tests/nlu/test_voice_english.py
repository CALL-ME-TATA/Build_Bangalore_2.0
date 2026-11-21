"""CONTRACT 1.13: reply language, English sentences, first person, relations, full stops (from the first voice test)."""
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
D0 = "2026-11-21"
LAST = {"last_event": {"kind": "credit", "customer": "ramesh", "amount": 340, "date": D0}}


def run(utterance, ctx=None):
    return parse(utterance, today=T, ctx=ctx)


def one(result):
    assert result["status"] == "ok" and len(result["events"]) == 1, result
    e = result["events"][0]
    return e["kind"], e["customer"], e["amount"], e["date"]


# 1. lang ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,lang", [
    ("Ramesh paid 500", "en"), ("Received 300 from Sunita", "en"), ("Undo that", "en"), ("Who owes the most?", "en"),
    ("No, 430", "en"), ("Ramesh paid 200 day before yesterday", "en"), ("mausam kaisa hai", "hi"),
    ("Ramesh ka 340 udhaar", "hi"), ("रमेश का 340 उधार", "hi"), ("Ramesh ko three forty credit de do", "hi"),
    ("undo karo", "hi"), ("haan", "hi"), ("Ramesh ne paid kiya 500", "hi"), ("teen sau chaalis", None),
    ("500", None), ("₹1,500", None), ("Ramesh", None), ("", None),
])
def test_lang(utterance, lang):
    r = run(utterance, LAST)
    assert r.get("lang") == lang, r


def test_lang_on_rejected_and_pending_results():
    assert run("thank you")["lang"] == "en"
    first = run("Ramesh ka 60000 udhaar")
    assert run("yes", {"pending": first["pending"]})["lang"] == "en"


# 2. English sentences ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,kind,customer,amount", [
    ("Ramesh has paid 500.", "payment", "ramesh", 500),
    ("Ramesh returned 100", "payment", "ramesh", 100),
    ("Ramesh deposited 250", "payment", "ramesh", 250),
    ("Got 200 from Mohan", "payment", "mohan", 200),
    ("Collected 150 from Sunita", "payment", "sunita", 150),
    ("Payment of 400 from Ramesh", "payment", "ramesh", 400),
    ("Ramesh took goods worth 300", "credit", "ramesh", 300),
    ("Ramesh bought for 120 on credit", "credit", "ramesh", 120),
    ("Ramesh borrowed 400", "credit", "ramesh", 400),
    ("500 credit to Mohan", "credit", "mohan", 500),
    ("Lent 300 to Ramesh", "credit", "ramesh", 300),
    ("Put 80 on Sunita's account", "credit", "sunita", 80),
    ("Give two hundred credit to Geeta", "credit", "geeta", 200),
])
def test_english_entries(utterance, kind, customer, amount):
    assert one(run(utterance)) == (kind, customer, amount, D0)


@pytest.mark.parametrize("utterance", ["Paid 200 to Ramesh", "Pay 300 to Sunita", "Ramesh 200 debit", "Ramesh 500"])
def test_english_asks_direction(utterance):
    r = run(utterance)
    assert r["reason"] == "ambiguous_direction"
    assert r["pending"]["events"][0]["customer"] in ("ramesh", "sunita")


@pytest.mark.parametrize("utterance", ["Pay five hundred rupees to Ramesh.", "Give 100 to Ramesh",
                                       "Add 250 to Mohan's account."])
def test_imperative_verb_is_never_a_name(utterance):
    r = run(utterance)
    e = r["events"][0] if r["status"] == "ok" else r["pending"]["events"][0]
    assert e["customer"] in ("ramesh", "mohan")


@pytest.mark.parametrize("utterance,amount", [("Not 340, 430", 430), ("Wrong, 430", 430), ("Change it to 450", 450),
                                              ("Make it five hundred", 500)])
def test_english_amend(utterance, amount):
    r = run(utterance, LAST)
    assert r["action"] == "amend" and r["events"][0]["amount"] == amount


@pytest.mark.parametrize("utterance", ["Undo", "Cancel that", "Delete the last entry", "Remove the last one"])
def test_english_undo(utterance):
    assert run(utterance, LAST)["action"] == "undo"


@pytest.mark.parametrize("utterance,query", [
    ("Ramesh's balance", {"type": "balance", "customer": "ramesh"}),
    ("Ramesh's total?", {"type": "balance", "customer": "ramesh"}),
    ("How much is due from Ramesh?", {"type": "balance", "customer": "ramesh"}),
    ("Today's credit", {"type": "credit_total", "period": "today"}),
    ("How much did I receive today?", {"type": "payment_total", "period": "today"}),
    ("Today's collection", {"type": "payment_total", "period": "today"}),
    ("Today's total", {"type": "daily_summary", "period": "today"}),
    ("Today's account", {"type": "daily_summary", "period": "today"}),
    ("Top dues", {"type": "top_dues"}),
])
def test_english_queries(utterance, query):
    r = run(utterance)
    assert r["action"] == "query" and r["query"] == query


@pytest.mark.parametrize("utterance,day", [("Ramesh paid 100 today", D0), ("Ramesh paid 100 yesterday", "2026-11-20"),
                                           ("Ramesh paid 100 day before yesterday", "2026-11-19"),
                                           ("Ramesh paid 100 three days ago", "2026-11-18")])
def test_english_dates(utterance, day):
    assert one(run(utterance))[3] == day


PLAUS = {"pending": {"reason": "plausibility", "action": "append", "events": [
    {"kind": "credit", "customer": "ramesh", "amount": 60000, "date": D0}]}}
DIRECTION = {"pending": {"reason": "ambiguous_direction", "action": "append", "events": [
    {"customer": "ramesh", "amount": 500, "date": D0}]}}


@pytest.mark.parametrize("reply", ["yeah", "correct", "right", "sure"])
def test_english_yes(reply):
    assert one(run(reply, PLAUS))[2] == 60000


def test_english_no():
    assert run("no", PLAUS) == {"status": "rejected", "reason": "cancelled", "lang": "en"}


def test_cancel_carries_no_lang():
    assert run("cancel", PLAUS) == {"status": "rejected", "reason": "cancelled"}


@pytest.mark.parametrize("reply,kind", [("paid", "payment"), ("he paid", "payment"), ("credit", "credit"),
                                        ("took credit", "credit")])
def test_english_direction_answers(reply, kind):
    assert one(run(reply, DIRECTION))[0] == kind


# 3. First person -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,ctx,expect", [
    ("Maine Ramesh ko 200 diye", LAST, ("credit", "ramesh", 200, D0)),
    ("Humne Sunita ko 300 diye", None, ("credit", "sunita", 300, D0)),
    ("Maine Ramesh se 200 liye", None, ("payment", "ramesh", 200, D0)),
    ("Mujhe Ramesh ne 300 diye", None, ("payment", "ramesh", 300, D0)),
    ("Mujhe Ramesh se 150 mile", LAST, ("payment", "ramesh", 150, D0)),
    ("I gave 500 to Ramesh", None, ("credit", "ramesh", 500, D0)),
    ("मैंने रमेश को 200 दिए", None, ("credit", "ramesh", 200, D0)),
])
def test_first_person(utterance, ctx, expect):
    assert one(run(utterance, ctx)) == expect


@pytest.mark.parametrize("utterance", ["Maine 200 diye", "Mujhe 200 mile"])
def test_first_person_without_customer_asks(utterance):
    r = run(utterance)
    assert r["reason"] == "missing_customer"


# 4. Relations --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,customer", [
    ("Ramesh ki patni ko 100 udhaar", "ramesh ki biwi"),
    ("Ramesh ka ladka 50 de gaya", "ramesh ka beta"),
    ("Ramesh ki beti ne 20 diye", "ramesh ki beti"),
    ("Ramesh ke papa ne 100 diye", "ramesh ke papa"),
    ("Ramesh ka baap ko 100 udhaar", "ramesh ke papa"),
    ("Ramesh ki mummy ko 100 udhaar", "ramesh ki maa"),
    ("Ramesh ka bhai ne 60 diye", "ramesh ka bhai"),
    ("Ramesh's daughter took 70 on credit", "ramesh ki beti"),
    ("Ramesh's brother paid 90", "ramesh ka bhai"),
    ("रमेश की बीवी को 100 उधार", "ramesh ki biwi"),
])
def test_relations_name_another_person(utterance, customer):
    assert one(run(utterance))[1] == customer


def test_relation_query_is_not_for_x_himself():
    roster = {"customers": [{"id": "c1", "name": "ramesh", "tags": []}]}
    q = run("Ramesh ki biwi ka khata?", roster)["query"]
    assert q["customer"] == "ramesh ki biwi" and q.get("unknown_customer") is True and "customer_id" not in q


def test_relation_word_alone_is_still_an_honorific():
    assert one(run("Ramesh bhai ka 100 udhaar"))[1] == "ramesh"


# 5. Full stops -------------------------------------------------------------------------------------------------

def test_full_stop_before_particle_is_not_a_boundary():
    assert one(run("Ramesh. Ko 200 udhaar."))[1] == "ramesh"


def test_full_stop_between_two_entries_still_splits():
    r = run("Ramesh ka 100 udhaar. Sunita ne 50 diye.")
    assert [e["customer"] for e in r["events"]] == ["ramesh", "sunita"]
