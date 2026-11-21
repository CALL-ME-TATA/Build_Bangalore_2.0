"""CONTRACT 1.12: rules added after the first review. One section per numbered review item, beyond the golden set,
including the answer flows for the three new questions (which entry, undo confirmation, replace or append)."""
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
D0, D1 = "2026-11-21", "2026-11-20"
LAST = {"last_event": {"kind": "credit", "customer": "ramesh", "amount": 340, "date": D0}}
TWO = {"last_event": {"id": 2, "kind": "payment", "customer": "sunita", "amount": 200, "date": D1},
       "last_events": [{"id": 1, "kind": "credit", "customer": "ramesh", "amount": 340, "date": D0},
                       {"id": 2, "kind": "payment", "customer": "sunita", "amount": 200, "date": D1}]}


def run(utterance, ctx=None):
    return parse(utterance, today=T, ctx=ctx)


def answer(first, utterance, ctx=None):
    """Answer the question asked by `first` (a needs_clarification result)."""
    c = dict(ctx or {})
    c["pending"] = first["pending"]
    return run(utterance, c)


def one(result):
    assert result["status"] == "ok", result
    assert len(result["events"]) == 1, result
    e = result["events"][0]
    return e["kind"], e["customer"], e["amount"], e["date"]


# 1. The word before a particle is the name; a particle without a name never carries over --------------------------

@pytest.mark.parametrize("utterance,customer,kind", [
    ("Bhabhi ne 200 diye", "bhabhi", "payment"),  # kinship word
    ("Sir ko 100 udhaar", "sir", "credit"),  # honorific
    ("Mili ko 100 udhaar", "mili", "credit"),  # keyword "mila"
    ("Ok ne 50 diye", "ok", "payment"),  # filler-like word
    ("Seth ji ko 100 udhaar", "seth", "credit"),  # honorific run alone: ji dropped
])
def test_word_before_particle_is_the_name(utterance, customer, kind):
    k, c, _a, _d = one(run(utterance, LAST))
    assert (k, c) == (kind, customer)


def test_honorific_is_still_dropped_next_to_a_name():
    assert one(run("Sharma ji ko 100 udhaar"))[1] == "sharma"


@pytest.mark.parametrize("utterance", ["ko 200 udhaar", "ne 200 diye", "se 200 mile"])
def test_particle_without_name_does_not_carry_over(utterance):
    r = run(utterance, LAST)
    assert r["reason"] == "missing_customer"


def test_particle_without_name_does_not_take_previous_clause_customer():
    r = run("Ramesh ka 100 udhaar aur ko 50 udhaar")
    assert r["status"] == "needs_clarification" and r["reason"] == "missing_customer"


def test_time_words_with_dates_keep_their_meaning():
    q = run("Aaj ka hisaab batao")
    assert q["query"]["type"] == "daily_summary"


# 2. Pronouns ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,kind", [
    ("Usne 200 diye", "payment"), ("Usko 100 udhaar diya", "credit"), ("Inka 50 udhaar likh do", "credit"),
    ("उसने 200 दिए", "payment"),
])
def test_pronoun_means_last_customer(utterance, kind):
    k, c, _a, _d = one(run(utterance, LAST))
    assert (k, c) == (kind, "ramesh")


def test_pronoun_without_last_event_asks():
    assert run("Usne 200 diye")["reason"] == "missing_customer"


def test_pronoun_respects_carry_over_age():
    stale = {"last_event": dict(LAST["last_event"], age_s=500)}
    assert run("Usne 200 diye", stale)["reason"] == "missing_customer"


def test_pronoun_never_becomes_a_customer():
    r = run("Wo 200 de gaya")
    assert r["reason"] == "missing_customer"
    assert "customer" not in r["pending"]["events"][0]


def test_pronoun_balance_query():
    assert run("Uska total", LAST)["query"] == {"type": "balance", "customer": "ramesh"}
    first = run("Uska total")
    assert first["reason"] == "missing_customer" and first["pending"]["action"] == "query"
    assert answer(first, "Sunita")["query"] == {"type": "balance", "customer": "sunita"}


# 3. last_events and the amend target ---------------------------------------------------------------------------

def test_single_event_keeps_target_last():
    r = run("nahi, 430", LAST)
    assert r["target"] == "last"


def test_bare_correction_with_two_events_asks_which():
    r = run("nahi 430", TWO)
    assert r["reason"] == "unclear_correction"
    assert r["question"] == "Kaunsi entry: ₹340 udhaar ya ₹200 jama?"
    assert [c["id"] for c in r["candidates"]] == [1, 2]


@pytest.mark.parametrize("reply,event_id,kind,customer", [
    ("340", 1, "credit", "ramesh"), ("udhaar", 1, "credit", "ramesh"), ("pehli", 1, "credit", "ramesh"),
    ("200", 2, "payment", "sunita"), ("jama", 2, "payment", "sunita"), ("doosri", 2, "payment", "sunita"),
])
def test_which_entry_answers(reply, event_id, kind, customer):
    first = run("nahi 430", TWO)
    r = answer(first, reply, TWO)
    assert r["status"] == "ok" and r["action"] == "amend"
    assert r["target"] == {"event_id": event_id}
    assert r["events"][0]["kind"] == kind and r["events"][0]["customer"] == customer
    assert r["events"][0]["amount"] == 430


def test_which_entry_unclear_answer_reasks_then_cancels():
    first = run("nahi 430", TWO)
    second = answer(first, "999", TWO)
    assert second["reason"] == "unclear_correction" and second["pending"]["attempts"] == 1
    assert answer(second, "kuch nahi pata", TWO) == {"status": "rejected", "reason": "cancelled", "lang": "hi"}


def test_named_customer_picks_the_event():
    r = run("Sunita nahi Geeta", TWO)
    assert r["target"] == {"event_id": 2} and r["events"][0]["customer"] == "geeta"


def test_named_amount_not_among_events_asks():
    assert run("999 nahi 430", TWO)["reason"] == "unclear_correction"


# 4. N din pehle -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,amount,day", [
    ("Ramesh ne paanch sau das din pehle diye", 500, "2026-11-11"),
    ("Ramesh ne 300 ek din pehle diye", 300, D1),
    ("Ramesh ne 200 60 din pehle diye", 200, "2026-09-22"),
])
def test_only_the_number_before_din_counts_days(utterance, amount, day):
    _k, _c, a, d = one(run(utterance))
    assert (a, d) == (amount, day)


@pytest.mark.parametrize("utterance", ["Ramesh ne 61 din pehle 200 diye", "Ramesh ne 200 sau din pehle diye"])
def test_too_many_days_asks(utterance):
    assert run(utterance)["reason"] == "unclear_date"


# 5. Not entries, dena, "likh do sau", a second name without an amount -----------------------------------------

@pytest.mark.parametrize("utterance,reason", [
    ("Ramesh ne 500 nahi diye", "negated"),
    ("Sunita ka koi udhaar nahi hai", "negated"),
    ("Ramesh ko kuch nahi dena", "negated"),
    ("Kya Sunita ne 200 diye?", "not_ledger"),
    ("Kya Ramesh ka 300 udhaar hai", "not_ledger"),
    ("Ramesh ki entry cancel ho gayi", "not_ledger"),
])
def test_rejected(utterance, reason):
    r = run(utterance, LAST)
    assert r["status"] == "rejected" and r["reason"] == reason


def test_kya_query_still_answers():
    assert run("Kya Ramesh ka total hai")["query"]["type"] == "balance"


@pytest.mark.parametrize("utterance", ["Sunita ka 50 dena", "Ramesh ko 200 udhaar dena"])
def test_dena_asks_direction(utterance):
    assert run(utterance)["reason"] == "ambiguous_direction"


@pytest.mark.parametrize("utterance", ["Ramesh ko 200 dena hai", "Ramesh ko 200 dene hain"])
def test_dena_hai_is_future_since_1_14(utterance):
    assert run(utterance)["reason"] == "future"


def test_likh_dena_is_still_an_instruction():
    assert one(run("Ramesh ka 200 udhaar likh dena"))[0] == "credit"


@pytest.mark.parametrize("reply,amount", [("do sau", 200), ("sau", 100), ("pehla", 200), ("doosra", 100)])
def test_likh_do_sau_asks_and_resolves(reply, amount):
    first = run("Ramesh ke naam likh do sau rupaye")
    assert first["reason"] == "confusable_number" and first["candidates"] == [200, 100]
    assert one(answer(first, reply))[2] == amount


def test_do_sau_after_a_non_verb_is_200():
    assert one(run("Ramesh ko do sau udhaar"))[2] == 200


def test_second_name_without_amount_asks_amount():
    r = run("Ramesh ne 500 diye Sunita bhi")
    assert r["reason"] == "missing_amount"
    assert r["pending"]["events"][1]["customer"] == "sunita"
    assert "amount" not in r["pending"]["events"][1]


# 6. Undo and "nahi" followed by a sentence ---------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Sunita ki entry hata do", "pehli entry hata do", "dono entry hata do",
                                       "kal wali entry hata do"])
def test_non_generic_undo_asks(utterance):
    r = run(utterance, LAST)
    assert r["reason"] == "unclear_correction"
    assert r["question"] == "Sirf pichli entry hata sakta hoon: Ramesh, ₹340 udhaar. Hata doon?"


@pytest.mark.parametrize("reply,expect", [
    ("haan", {"status": "ok", "action": "undo", "target": "last"}),
    ("haan hata do", {"status": "ok", "action": "undo", "target": "last"}),
    ("nahi", {"status": "rejected", "reason": "cancelled"}),
])
def test_undo_confirmation_answers(reply, expect):
    first = run("Sunita ki entry hata do", LAST)
    r = answer(first, reply, LAST)
    assert {k: r[k] for k in expect} == expect


def test_undo_naming_last_customer_with_fuzzy_spelling():
    assert run("Rameysh ki entry hata do", LAST)["action"] == "undo"


def test_nahi_then_query_runs_query():
    r = run("nahi, aaj ka hisaab batao", LAST)
    assert r["action"] == "query" and r["query"]["type"] == "daily_summary"


def test_nahi_then_full_new_entry_asks_replace():
    r = run("Nahi Sunita ne 500 diye", LAST)
    assert r["reason"] == "unclear_correction" and r["question"] == "Pichli entry hata kar yeh likhoon?"
    yes = answer(r, "haan", LAST)
    assert yes["action"] == "amend" and yes["target"] == "last"
    assert one(yes) == ("payment", "sunita", 500, D0)
    no = answer(r, "nahi", LAST)
    assert no["action"] == "append" and one(no) == ("payment", "sunita", 500, D0)


def test_nahi_with_partial_change_amends_directly():
    r = run("nahi, Suresh ka 500 udhaar", LAST)
    assert r["action"] == "amend" and one(r) == ("credit", "suresh", 500, D0)


# 7. Fuzzy matching ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("spoken,stored,same", [
    ("Rameysh", "ramesh", True), ("Suneeta", "sunita", True),
    ("Sunit", "sunita", False), ("Rajan", "ranjan", False), ("Kamal", "kamala", False),
])
def test_fuzzy_rule_in_resolution(spoken, stored, same):
    r = run(f"{spoken} ko 100 udhaar", {"customers": [{"id": "c1", "name": stored, "tags": []}]})
    e = r["events"][0]
    assert (e.get("customer_id") == "c1") is same


# 8. Two-word names, first-person words, English auxiliaries ----------------------------------------------------

@pytest.mark.parametrize("utterance,customer", [
    ("Ramesh Kumar Gupta ne 100 diye", "ramesh kumar gupta"), ("Mohan Lal ko 50 udhaar", "mohan lal"),
])
def test_name_words_in_a_row_are_one_name(utterance, customer):
    assert one(run(utterance))[1] == customer


def test_comma_keeps_two_names_apart():
    assert run("Ramesh, Suresh ko 200 diya")["reason"] == "missing_amount"


@pytest.mark.parametrize("utterance", ["Mujhe Ramesh ne 100 diye", "Humne Ramesh ko 100 diye",
                                       "Ramesh had paid 100", "Ramesh has already paid 100"])
def test_first_person_and_auxiliaries_are_not_names(utterance):
    assert one(run(utterance))[1] == "ramesh"


# 9. Answers with extra words, non-names, attempts --------------------------------------------------------------

DIRECTION = {"pending": {"reason": "ambiguous_direction", "action": "append", "events": [
    {"customer": "ramesh", "amount": 500, "date": D0}]}}


@pytest.mark.parametrize("reply,kind", [("Ramesh ne diye", "payment"), ("Ramesh ji ko udhaar", "credit"),
                                        ("Ramesh Sharma ne diye", "payment"), ("haan udhaar", None)])
def test_direction_answers_with_name(reply, kind):
    r = run(reply, DIRECTION)
    if kind is None:
        assert r["status"] == "needs_clarification"
    else:
        assert one(r)[0] == kind


def test_direction_answer_naming_someone_else_is_not_accepted():
    r = run("Suresh ne diye", DIRECTION)
    assert r["status"] == "needs_clarification" and r["reason"] == "ambiguous_direction"


def test_amount_answer_with_extra_words():
    first = run("Ramesh ko udhaar")
    assert one(answer(first, "Ramesh ko 300 rupaye udhaar")) == ("credit", "ramesh", 300, D0)


def test_amount_answer_fills_a_missing_kind():
    first = run("Ramesh ka saade do sau")
    assert first["reason"] == "missing_amount"
    assert one(answer(first, "250 udhaar"))[:3] == ("credit", "ramesh", 250)


@pytest.mark.parametrize("reply,amount", [("haan likh do", 60000), ("nahi 7500", 7500), ("nahi, saat hazaar", 7000)])
def test_plausibility_answers_with_extra_words(reply, amount):
    first = run("Ramesh ka 60000 udhaar")
    assert one(answer(first, reply))[2] == amount


@pytest.mark.parametrize("reply,customer", [("Chacha", "chacha"), ("Didi", "didi"), ("Lala ji", "lala")])
def test_customer_answer_kinship_word(reply, customer):
    first = run("300 udhaar")
    assert one(answer(first, reply))[1] == customer


@pytest.mark.parametrize("reply", ["dobara boliye", "samajh nahi aaya", "hello"])
def test_non_names_never_become_customers(reply):
    first = run("300 udhaar")
    r = answer(first, reply)
    assert r["status"] == "needs_clarification" and r["reason"] == "missing_customer"


def test_two_unresolved_answers_cancel():
    first = run("Ramesh 200")
    second = answer(first, "pata nahi")
    assert second["reason"] == "ambiguous_direction" and second["pending"]["attempts"] == 1
    third = answer(second, "dobara boliye")
    assert third["status"] == "rejected" and third["reason"] == "cancelled"


def test_resolved_answer_starts_a_new_count():
    first = run("Ramesh ka 60000 udhaar", {"customers": [{"id": "c1", "name": "ramesh", "tags": ["a wale"]},
                                                         {"id": "c2", "name": "ramesh", "tags": ["b wale"]}]})
    second = answer(first, "pehla", {"customers": []})
    assert second["reason"] == "plausibility" and "attempts" not in second["pending"]


# 10. Periods and unknown customers -----------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,qtype", [("Kal ka hisaab", "daily_summary"), ("Kal kitna aaya", "payment_total"),
                                             ("Kal kitna jama hua", "payment_total")])
def test_yesterday_period(utterance, qtype):
    assert run(utterance)["query"] == {"type": qtype, "period": "yesterday"}


def test_unknown_customer_only_with_a_roster():
    assert "unknown_customer" not in run("Suresh ka total")["query"]
    known = run("Ramesh ka total", {"customers": [{"id": "c1", "name": "ramesh", "tags": []}]})
    assert known["query"] == {"type": "balance", "customer": "ramesh", "customer_id": "c1"}
