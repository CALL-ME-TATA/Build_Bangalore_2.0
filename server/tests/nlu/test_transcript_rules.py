"""CONTRACT 1.13, "More rules from the transcripts of the first voice test", beyond the golden v-cases."""
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
D0 = "2026-11-21"
LAST = {"last_event": {"kind": "credit", "customer": "ramesh", "amount": 340, "date": D0}}
DIRECTION = {"pending": {"reason": "ambiguous_direction", "action": "append", "events": [
    {"customer": "ramesh", "amount": 500, "date": D0}]}}


def run(utterance, ctx=None):
    return parse(utterance, today=T, ctx=ctx)


def one(result):
    assert result["status"] == "ok" and len(result["events"]) == 1, result
    e = result["events"][0]
    return e["kind"], e["customer"], e["amount"], e["date"]


# 1. A pending question is replaced only by a complete entry or a query --------------------------------------------

@pytest.mark.parametrize("utterance", ["ami Hazar", "Suresh ko 200", "Suresh 300", "Mohan", "thik hai",
                                       "Suresh ka 400"])
def test_incomplete_utterance_is_an_answer_attempt(utterance):
    r = run(utterance, DIRECTION)
    assert r["status"] == "needs_clarification" and r["reason"] == "ambiguous_direction"
    assert r["pending"]["events"] == DIRECTION["pending"]["events"]  # no new customer anywhere


def test_live_sequence_never_saves_to_a_misheard_customer():
    first = run("ami Hazar.", DIRECTION)
    second = run("Udhaar.", dict(DIRECTION, pending=first["pending"]))
    assert one(second) == ("credit", "ramesh", 500, D0)


@pytest.mark.parametrize("utterance,expect", [
    ("Suresh ne 200 diye", ("payment", "suresh", 200, D0)),
    ("Suresh ko 300 udhaar", ("credit", "suresh", 300, D0)),
])
def test_complete_entry_replaces_the_question(utterance, expect):
    assert one(run(utterance, DIRECTION)) == expect


def test_query_replaces_the_question():
    assert run("Sunita ka total", DIRECTION)["query"] == {"type": "balance", "customer": "sunita"}


def test_two_failed_attempts_cancel():
    first = run("ami Hazar", DIRECTION)
    assert run("thik hai", dict(DIRECTION, pending=first["pending"]))["reason"] == "cancelled"


# 2. A non-number before a unit word is a misheard number --------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ka saadh sau udhaar", "Ramesh ne bhaat hazaar diye",
                                       "Ramesh ko blah lakh udhaar"])
def test_misheard_number_asks_amount(utterance):
    r = run(utterance)
    assert r["reason"] == "missing_amount"
    assert r["pending"]["events"][0]["customer"] == "ramesh"


def test_word_before_unit_is_never_a_name():
    r = run("Ramesh sau udhaar")
    assert r["reason"] == "missing_amount"
    assert "customer" not in r["pending"]["events"][0]


def test_misheard_correction_asks_amount_and_the_answer_amends():
    first = run("nahi nahi, saadh sau rupaye.", LAST)
    assert first["reason"] == "missing_amount" and first["pending"]["action"] == "amend"
    r = run("saat sau", dict(LAST, pending=first["pending"]))
    assert r["action"] == "amend" and one(r) == ("credit", "ramesh", 700, D0)


@pytest.mark.parametrize("utterance,amount", [("Ramesh ko sau udhaar", 100), ("Ramesh ko saatt sau udhaar", 700),
                                              ("Ramesh ko teen sau udhaar", 300)])
def test_real_numbers_before_units_still_parse(utterance, amount):
    assert one(run(utterance))[2] == amount


# 3. An amount-only correction changes only the amount ------------------------------------------------------------

def test_amount_only_correction():
    stored = {"last_event": {"kind": "payment", "customer": "sunita", "amount": 200, "date": "2026-11-19",
                             "customer_id": "c5"}}
    r = run("nahi nahi, 700 rupaye", stored)
    assert r["events"] == [{"kind": "payment", "customer": "sunita", "amount": 700, "date": "2026-11-19",
                            "customer_id": "c5"}]


# 4. First-person phrases are never names --------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["sau rupaye aaye mere paas", "mere ko 200 mile", "mereko 200 mile",
                                       "mujhko 200 mile", "hamare paas 200 aaye"])
def test_first_person_phrases_are_payments_by_the_carried_customer(utterance):
    assert one(run(utterance, LAST))[:2] == ("payment", "ramesh")


@pytest.mark.parametrize("utterance", ["mera 200 udhaar", "meri 200 entry"])
def test_first_person_words_never_become_customers(utterance):
    r = run(utterance)
    events = r.get("events") or r.get("pending", {}).get("events") or [{}]
    assert all(e.get("customer") not in ("mera", "meri") for e in events)


def test_first_person_without_carry_asks_customer():
    assert run("sau rupaye aaye mere paas")["reason"] == "missing_customer"


# 5. Spellings seen live -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,expect", [
    ("Ramesh ne 100 wapis kiye", ("payment", "ramesh", 100, D0)),
    ("Ramesh ne 100 vapas kiye", ("payment", "ramesh", 100, D0)),
    ("Ramesh ke khata mein 200 likh do", ("credit", "ramesh", 200, D0)),
    ("Ramesh ki bewi ko 50 udhaar", ("credit", "ramesh ki biwi", 50, D0)),
    ("Ramesh ko teen sa rupaye udhaar", ("credit", "ramesh", 300, D0)),
    ("Ramesh ko do hazaar paanch sa udhaar", ("credit", "ramesh", 2500, D0)),
])
def test_live_spellings(utterance, expect):
    assert one(run(utterance)) == expect


def test_sa_alone_is_not_a_number():
    assert run("Ramesh sa udhaar")["reason"] == "missing_amount"


# 6. English seen live ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Five hundred in Ramesh's account.", "Paid five hundred rupees to Ramesh.",
                                       "Pay Ramesh five hundred."])
def test_english_asks_direction_with_customer_and_amount(utterance):
    r = run(utterance)
    assert r["reason"] == "ambiguous_direction"
    assert r["pending"]["events"] == [{"customer": "ramesh", "amount": 500, "date": D0}]


@pytest.mark.parametrize("utterance", ["Give Ramesh five hundred rupees worth of product.",
                                       "Give Ramesh 500 worth of goods", "Give five hundred to Ramesh"])
def test_english_give_is_credit(utterance):
    assert one(run(utterance)) == ("credit", "ramesh", 500, D0)


def test_tag_after_comma_belongs_to_the_name():
    r = run("Ramesh, doodh wale ke paanch sa rupaye udhaar.")
    assert one(r) == ("credit", "ramesh", 500, D0)
    assert r["events"][0]["tags"] == ["doodh wale"]
