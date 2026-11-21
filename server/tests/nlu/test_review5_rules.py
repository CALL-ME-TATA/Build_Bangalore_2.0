"""CONTRACT 1.18: rules from the fourth review, and the parser rule of 3.5 (noise). Each test name carries the
finding id (B1 to B10, S1 to S9) or NOISE.

Roster balances in rupees: Ramesh 1,030; Mohan 140; Geeta 1,005; Sunita 0. Strict mode and confirm_new_customer on
unless a test says otherwise. Today is 2026-11-21."""
import json
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
D0, D1, D2 = "2026-11-21", "2026-11-20", "2026-11-19"
ROSTER = [
    {"id": "c1", "name": "ramesh", "tags": [], "balance": 1030},
    {"id": "c2", "name": "mohan", "tags": [], "balance": 140},
    {"id": "c3", "name": "sunita", "tags": [], "balance": 0},
    {"id": "c4", "name": "geeta", "tags": [], "balance": 1005},
]
LIMITS = {"strict": True, "confirm_new_customer": True, "duplicate_s": 30, "carry_s": 60}


def ctx(customers=None, pending=None, **extra):
    c = {"customers": json.loads(json.dumps(ROSTER if customers is None else customers)), "limits": dict(LIMITS)}
    limits = extra.pop("limits", None)
    if limits:
        c["limits"].update(limits)
    c.update(extra)
    if pending is not None:
        c["pending"] = pending
    return c


def last(kind="credit", amount=340, customer="ramesh", cid="c1", age=5, eid=7):
    return {"id": eid, "kind": kind, "customer": customer, "customer_id": cid, "amount": amount, "date": D0,
            "age_s": age}


def after(*events, action="append", age=5, **extra):
    events = list(events) or [last()]
    return ctx(last_event=events[-1], last_events=events, last_turn={"action": action, "age_s": age}, **extra)


def run(utterance, c=None):
    return parse(utterance, today=T, ctx=ctx() if c is None else c)


def answer(prev, reply, c=None):
    cc = dict(ctx() if c is None else c)
    cc["pending"] = prev["pending"]
    return parse(reply, today=T, ctx=cc)


def chain(utterance, replies, c=None):
    steps = [run(utterance, c)]
    for reply in replies:
        steps.append(answer(steps[-1], reply, c))
    return steps


def saved(r):
    return r["status"] == "ok" and r.get("action") in ("append", "amend")


def entries(r):
    evs = r.get("events") or (r.get("pending") or {}).get("events") or []
    return [(e.get("customer"), e.get("kind"), e.get("amount")) for e in evs]


def ctype(r):
    return (r.get("confirm") or {}).get("type")


def index(r):
    return (r.get("pending") or {}).get("index")


# --- B1: a cash purchase is refused; a past credit that came back asks -------------------------------------------

@pytest.mark.parametrize("utterance", [
    "Ramesh ne 200 ka saaman liya paise de diye", "Ramesh ne 200 ka saaman liya aur paise de diye",
    "Ramesh ne 200 ka saaman liya, paise de diye", "Ramesh ne 200 ka saaman liya paise de gaya",
    "Ramesh ne 200 ka saaman liya usne de diye", "Ramesh ne 200 ka saaman liya payment ho gaya",
    "Ramesh ne 200 ka saaman liya payment de diya", "Ramesh ne 200 ka saaman liya poora payment kar diya",
    "Ramesh ne 200 ka saaman liya cash de diya", "Ramesh ne 200 ka saaman liya UPI kar diya",
    "Ramesh ne 200 ka saaman liya Paytm kar diya", "Ramesh ne 200 ka saaman liya online de diya",
    "Ramesh ne 200 ka saaman cash mein liya", "Ramesh ne 200 ka saaman nakad liya",
    "Ramesh 200 ka saaman le gaya nakad", "Ramesh 200 ka saaman le gaya aur de gaya",
    "Ramesh 200 ka saaman le gaya aur paise bhi de gaya", "Ramesh ko 200 ka saaman diya aur paise le liye",
    "Ramesh ko 200 ka saaman diya usne paise de diye", "Ramesh ne 200 ka saaman liya, hisaab barabar",
    "Ramesh ne 500 ka saaman liya aur payment kar diya", "Ramesh ne 200 ka maal liya, PhonePe kar diya",
    "Ramesh bought goods for 200 in cash", "Ramesh bought goods for 200 and paid",
    "रमेश ने 200 का सामान लिया पैसे दे दिए", "रमेश ने 200 का सामान नकद लिया",
])
def test_B1_a_cash_purchase_is_out_of_scope(utterance):
    r = run(utterance)
    assert r["status"] == "rejected" and r["reason"] == "out_of_scope", r


@pytest.mark.parametrize("utterance,expect", [
    ("Ramesh ne 200 ka saaman liya", ("ramesh", "credit", 200)),
    ("Ramesh 200 ka saaman le gaya", ("ramesh", "credit", 200)),
    ("Ramesh ko 200 ka saaman diya", ("ramesh", "credit", 200)),
    ("Ramesh bought goods worth 200 on credit", ("ramesh", "credit", 200)),
    ("Ramesh ne 200 ka saaman udhaar liya", ("ramesh", "credit", 200)),
])
def test_B1_a_purchase_without_money_handed_over_stays_a_credit(utterance, expect):
    r = run(utterance)
    assert saved(r) and entries(r) == [expect], r


@pytest.mark.parametrize("utterance", ["Ramesh ko 200 udhaar diye the, aaj de gaya",
                                       "Ramesh ko 200 udhaar diya tha wo aa gaya",
                                       "Ramesh ko 200 udhaar diye the, usne de diye",
                                       "रमेश को 200 उधार दिए थे, आज दे गया"])
def test_B1_a_past_credit_that_came_back_asks_the_direction(utterance):
    r = run(utterance)
    assert r["reason"] == "ambiguous_direction", r


# --- B2: udhaar with a customer-gives verb and no ko asks -------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "Ramesh udhaar ke 200 de gaya", "Ramesh aaj udhaar ke 200 de gaya", "Ramesh udhaar ka 200 de gaya",
    "Ramesh pichle udhaar ke 200 de gaya", "Ramesh udhaar ke 200 rupaye de gaya", "Ramesh 200 udhaar de gaya",
    "Ramesh 200 ka udhaar de gaya", "Ramesh udhaar 200 de gaya", "Ramesh udhaar de gaya 200",
    "udhaar ke 200 Ramesh de gaya", "रमेश उधार के 200 दे गया",
])
def test_B2_udhaar_with_de_gaya_and_no_ko_asks(utterance):
    r = run(utterance)
    assert r["reason"] == "ambiguous_direction", r
    assert r["pending"]["events"][0]["amount"] == 200


def test_B2_a_name_after_the_amount_is_taken_only_as_the_subject_of_de_gaya():
    assert run("udhaar ke 200 Ramesh de gaya")["pending"]["events"][0]["customer"] == "ramesh"
    assert run("200 udhaar Vikram rakha")["reason"] != "new_customer"


@pytest.mark.parametrize("utterance,kind", [("Ramesh ko 200 udhaar de diya", "credit"),
                                            ("Ramesh 200 de gaya", "payment")])
def test_B2_the_plain_forms_are_unchanged(utterance, kind):
    assert entries(run(utterance)) == [("ramesh", kind, 200)]


# --- B3: ke naam / khate mein name the account; a payment word wins ----------------------------------------------

@pytest.mark.parametrize("utterance", [
    "Ramesh ke naam se 200 jama karo", "Ramesh ke naam 200 jama karo", "Ramesh ke naam pe 200 jama kar do",
    "Ramesh ke naam 200 jama", "Ramesh ke naam ka 200 jama hua", "Ramesh ke naam 200 aaye",
    "Ramesh ke naam se 200 aaye hain", "Ramesh ke naam 200 mile", "Ramesh ke naam ka 200 payment aaya",
    "Ramesh ke naam pe 200 ka payment likh do", "Ramesh ke naam 200 kaat do",
    "Ramesh ke khate mein 200 payment likh do", "Ramesh ke khate mein payment 200 likh do",
    "Ramesh ke khate mein 200 ka payment daal do", "Ramesh ke khate mein 200 ka payment add karo",
    "रमेश के नाम 200 जमा करो",
])
def test_B3_a_payment_word_wins_over_the_account_words(utterance):
    r = run(utterance)
    assert saved(r) and entries(r) == [("ramesh", "payment", 200)], r


@pytest.mark.parametrize("utterance", ["Ramesh ke naam 200 likh do", "Ramesh ke khate mein 200 likh do",
                                       "Ramesh ke naam 200 udhaar likh do"])
def test_B3_account_words_alone_are_a_credit(utterance):
    assert entries(run(utterance)) == [("ramesh", "credit", 200)]


def test_B3_a_credit_word_and_a_payment_word_ask():
    assert run("Ramesh ke naam 200 udhaar aur jama")["reason"] == "ambiguous_direction"


# --- B4: yes with an address word is yes; no new name out of "haan bhai" -----------------------------------------

@pytest.mark.parametrize("reply", ["haan bhai", "ha bhai", "haan bhaiya", "theek hai bhai", "haan sir", "haan madam",
                                   "haan beta", "hau", "yeah open it", "go ahead", "create", "khol do",
                                   "haan khata khol do", "yes please", "haan ji bana do"])
def test_B4_yes_with_an_address_word_opens_the_account(reply):
    done = answer(run("Vikram ko 500 udhaar"), reply)
    assert saved(done), done
    assert entries(done) == [("vikram", "credit", 500)] and done["events"][0]["new_customer"] is True


@pytest.mark.parametrize("reply", ["Bhai", "Open", "sir"])
def test_B4_an_address_word_alone_never_becomes_the_customer(reply):
    r = answer(run("Vikram ko 500 udhaar"), reply)
    assert not saved(r) or entries(r) == [("vikram", "credit", 500)], r
    assert "bhai" not in json.dumps(r).lower() and "open" not in str(entries(r))


def test_B4_a_stored_name_or_a_name_before_a_particle_still_renames():
    r = answer(run("Vikram ko 500 udhaar"), "Mohan")
    assert entries(r) == [("mohan", "credit", 500)] and r["events"][0]["customer_id"] == "c2"
    r = answer(run("Vikram ko 500 udhaar"), "Vikas")  # not stored, not before a particle: asked again
    assert r["reason"] == "new_customer" and r["pending"]["events"][0]["customer"] == "vikram"


def test_B4_yes_with_an_address_word_answers_other_questions_too():
    first = run("Ramesh ka 99000 udhaar")
    assert first["reason"] == "plausibility"
    assert saved(answer(first, "haan bhai"))


# --- B5: purchase, paid amount and the rest: one computed credit -------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "Ramesh ne 500 ka saaman liya 200 diye baaki udhaar", "Ramesh ne 500 ka saaman liya 200 diye baaki udhaar likh do",
    "Ramesh 500 ka saaman le gaya 200 de gaya baaki udhaar", "Ramesh ne 500 ka saaman liya, 200 diye, baaki likh do",
    "Ramesh ka bill 500 hua 200 diye baaki udhaar", "रमेश ने 500 का सामान लिया 200 दिए बाकी उधार",
])
def test_B5_bill_paid_rest_is_one_computed_credit(utterance):
    r = run(utterance)
    assert r["reason"] == "confirm_entry" and ctype(r) == "computed", r
    assert r["confirm"]["bill"] == 500 and r["confirm"]["paid"] == 200
    assert entries(r) == [("ramesh", "credit", 300)]
    assert entries(answer(r, "haan")) == [("ramesh", "credit", 300)]


@pytest.mark.parametrize("utterance", ["Ramesh ne 500 ka saaman liya 300 baaki hai",
                                       "Ramesh 500 ka saaman le gaya, 300 baaki hai"])
def test_B5_purchase_and_the_rest_stated_is_a_computed_credit_of_the_rest(utterance):
    r = run(utterance)
    assert ctype(r) == "computed" and entries(r) == [("ramesh", "credit", 300)], r


# --- B6 / B7: a stray word is not a customer -------------------------------------------------------------------

@pytest.mark.parametrize("utterance,expect", [
    ("Ramesh also paid 200", ("ramesh", "payment", 200)), ("Ramesh finally paid 200", ("ramesh", "payment", 200)),
    ("Ramesh has given 200", ("ramesh", "payment", 200)), ("Ramesh purchased 250", ("ramesh", "credit", 250)),
    ("Ramesh cleared 200", ("ramesh", "payment", 200)), ("Ramesh already paid 200", ("ramesh", "payment", 200)),
    ("Ramesh just paid 200", ("ramesh", "payment", 200)), ("Ramesh had taken 200", ("ramesh", "credit", 200)),
])
def test_B6_english_adverbs_and_auxiliaries_are_fillers(utterance, expect):
    r = run(utterance)
    assert saved(r) and entries(r) == [expect], r


@pytest.mark.parametrize("utterance,words", [
    ("Ramesh ne 500 ka saaman liya, 600 udhaar rakha", ["rakha"]),  # 200 is the computed form (B5 below)
])
def test_B6_a_stray_word_gets_the_unsure_confirmation_and_is_never_a_customer(utterance, words):
    r = run(utterance)
    assert ctype(r) == "unsure" and r["confirm"]["words"] == words, r
    assert all(e[0] == "ramesh" for e in entries(r))


@pytest.mark.parametrize("utterance,c", [
    ("100 kam karo", "after"), ("he took another 100", "after"), ("Ramesh paid 200 out of 500", None),
    ("Ramesh paid 200 in cash and 300 by UPI", None), ("Ramesh ne 500 diye 300 chutte wapas diye", None),
    ("sabko 50 udhaar", None), ("kisi ne 50 diye", None), ("koi 50 de gaya", None),
    ("Ramesh ne 200 diye lekin 100 kam the", None), ("ise 430 kar do", "after"), ("jo kal aaya tha 200 udhaar", None),
])
def test_B6_no_new_customer_out_of_a_stray_word(utterance, c):
    r = run(utterance, after() if c else None)
    names = {e[0] for e in entries(r) if e[0]}
    assert names <= {"ramesh", "mohan", "geeta", "sunita"}, r
    assert r.get("reason") != "new_customer", r


@pytest.mark.parametrize("utterance,key", [("Ramesh Chopra ko 200 udhaar", "ramesh chopra"),
                                           ("Ramesh wants 200 on credit", "ramesh wants")])
def test_B6_a_stored_first_name_plus_an_unknown_word_offers_the_stored_customer(utterance, key):
    r = run(utterance)
    assert r["reason"] == "new_customer" and r["pending"]["events"][0]["customer"] == key
    assert [c["name"] for c in r["candidates"]][:1] == ["ramesh"]
    assert r["question"].endswith("ya Ramesh?")


def test_B6_a_relation_is_not_a_stored_first_name():
    r = run("Ramesh ki biwi ko 200 udhaar")
    assert r["reason"] == "new_customer" and r["candidates"] == []


@pytest.mark.parametrize("utterance", ["Rames ko 500 udhaar", "Ramesh Chopra ko 200 udhaar"])
def test_B7_close_and_stored_first_names_ask_with_the_switch_off(utterance):
    r = run(utterance, ctx(limits={"confirm_new_customer": False}))
    assert r["reason"] == "new_customer" and r["candidates"], r


def test_B7_with_the_switch_off_only_a_name_before_a_particle_is_accepted_silently():
    off = ctx(limits={"confirm_new_customer": False})
    r = run("Vikram ko 500 udhaar", off)
    assert saved(r) and r["events"][0]["new_customer"] is True
    r = run("Vikram 500 le gaya", off)
    assert r["reason"] == "new_customer", r
    r = run("Vikram ko 500 udhaar", ctx(limits={"confirm_new_customer": False, "strict": False}))
    assert saved(r)


@pytest.mark.parametrize("utterance", ["sabko 50 udhaar", "kisi ne 50 diye", "Ramesh paid 200 in cash and 300 by UPI"])
def test_B7_with_the_switch_off_strays_still_never_save_to_a_new_customer(utterance):
    r = run(utterance, ctx(limits={"confirm_new_customer": False}))
    assert not any(e.get("new_customer") for e in (r.get("events") or [])), r


# --- B8: restated corrections right after an entry are the amend confirmation ------------------------------------

@pytest.mark.parametrize("utterance,new", [
    ("Ramesh ka 430 likhna tha", 430), ("Ramesh ka 430 udhaar tha", 430), ("430 kar do", 430), ("430 karo", 430),
    ("430 kar dijiye", 430), ("amount 430 karo", 430), ("sorry 430", 430), ("actually 350", 350),
    ("it was 350", 350), ("I meant 350", 350), ("रमेश का 430 लिखना था", 430),
])
def test_B8_a_restatement_right_after_an_entry_is_the_amend_confirmation(utterance, new):
    r = run(utterance, after())
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "amend", "old": 340, "new": new}, r
    done = answer(r, "haan", after())
    assert done["action"] == "amend" and entries(done) == [("ramesh", "credit", new)]


def test_B8_a_payment_restated_as_jama_tha():
    r = run("Ramesh ka 430 jama tha", after(last(kind="payment", amount=340)))
    assert r["confirm"] == {"type": "amend", "old": 340, "new": 430}


@pytest.mark.parametrize("utterance", ["Ramesh ka 430 udhaar tha", "Mohan ka 430 likhna tha"])
def test_B8_another_kind_or_customer_is_not_a_restatement(utterance):
    r = run(utterance, after(last(kind="payment", amount=340)))
    assert ctype(r) != "amend", r


def test_B8_not_after_another_turn():
    r = run("430 kar do", after(action="query"))
    assert r.get("reason") != "confirm_entry" or ctype(r) == "amend"
    assert r.get("question") != "Kiska khata?" or r["reason"] == "missing_customer"


# --- B9: sentences whose words are all known but which are not that entry ----------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ka udhaar 200 ho gaya", "Ramesh ka 200 udhaar batao",
                                       "रमेश का उधार 200 हो गया"])
def test_B9_a_stated_or_asked_balance_is_the_balance_query(utterance):
    r = run(utterance)
    assert r["status"] == "ok" and r["action"] == "query" and r["query"]["type"] == "balance", r


@pytest.mark.parametrize("utterance", ["Ramesh se 200 vasool karne hain", "Ramesh se 200 lene hain",
                                       "Ramesh ke 200 lena hai"])
def test_B9_still_to_collect_is_future(utterance):
    assert run(utterance)["reason"] == "future"


@pytest.mark.parametrize("utterance", ["Ramesh ka 200 udhaar likhna mat", "Ramesh ka 200 udhaar mat likhna",
                                       "Ramesh ka 200 udhaar na likhna"])
def test_B9_a_negation_after_the_verb_is_negated(utterance):
    assert run(utterance)["reason"] == "negated"


@pytest.mark.parametrize("utterance", ["Ramesh ne 200 diye the kya aur Mohan ko 100 udhaar",
                                       "Ramesh ne 200 diye the kya, Mohan ko 100 udhaar",
                                       "Ramesh ka 200 udhaar likha tha"])
def test_B9_a_question_or_stative_clause_confirms_the_whole_utterance(utterance):
    r = run(utterance)
    assert r["reason"] == "confirm_entry" and ctype(r) == "hearsay", r


def test_B9_given_and_taken_back_asks():
    assert run("Ramesh ne 200 diye the wo wapas le gaya")["reason"] == "ambiguous_direction"


@pytest.mark.parametrize("utterance", ["Ramesh ka 200 udhaar likh dena kal", "Ramesh ka 200 udhaar kal likh dena"])
def test_B9_kal_with_an_instruction_for_later_asks_the_date(utterance):
    assert run(utterance)["reason"] == "unclear_date"


def test_B9_the_flagship_and_stated_total_are_unchanged():
    assert entries(run("Ramesh ka 340 udhaar, kal 200 diya tha")) == [("ramesh", "credit", 340),
                                                                      ("ramesh", "payment", 200)]
    assert entries(run("Ramesh ka 340 udhaar, total 800 ho gaya")) == [("ramesh", "credit", 340)]


# --- B10: dates -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,day", [
    ("Ramesh paid 200 last night", D1), ("Ramesh ne kal raat 200 diye", D1), ("Ramesh paid 200 yesterday evening", D1),
    ("Ramesh paid 200 this morning", D0), ("Ramesh ne aaj subah 200 diye", D0),
])
def test_B10_parts_of_the_day(utterance, day):
    r = run(utterance)
    assert saved(r) and r["events"][0]["date"] == day, r


@pytest.mark.parametrize("utterance", ["Ramesh paid 200 last week", "Ramesh paid 200 last monday"])
def test_B10_other_last_phrases_ask(utterance):
    assert run(utterance)["reason"] == "unclear_date"


@pytest.mark.parametrize("utterance,dates", [
    ("kal Ramesh ne 200 diye the aur Mohan ne bhi 100 diye the", [D1, D1]),
    ("kal Ramesh ne 200 diye, Mohan ne 100 diye", [D1, D1]),
    ("yesterday Ramesh paid 200 and Mohan paid 100", [D1, D1]),
    ("kal Ramesh ne 200 diye aur Mohan ne aaj 100 diye", [D1, D0]),
    ("parso Ramesh ne 200 diye, Mohan ne 50 diye aur Geeta ne 100 diye", [D2, D2, D2]),
    ("Ramesh ne 200 diye aur kal Mohan ne 100 diye", [D0, D1]),
])
def test_B10_a_leading_date_word_covers_every_clause_without_its_own(utterance, dates):
    r = run(utterance)
    assert saved(r) and [e["date"] for e in r["events"]] == dates, r


# --- S1: over-payment adds up; a reduction above the balance -----------------------------------------------------

@pytest.mark.parametrize("utterance", ["Mohan ne 100 diye aur 100 diye", "Mohan ne 100 diye, kal 100 diye the"])
def test_S1_over_payment_adds_up_one_customers_payments(utterance):
    r = run(utterance)
    assert ctype(r) == "overpayment" and index(r) == 1 and r["confirm"]["balance"] == 140, r


def test_S1_payments_within_the_balance_save():
    assert saved(run("Mohan ne 50 diye aur 50 diye"))


def test_S1_a_reduction_above_the_balance_states_it():
    r = run("Mohan ka 400 maaf kar do")
    assert ctype(r) == "writeoff" and r["confirm"] == {"type": "writeoff", "amount": 400, "balance": 140}
    assert r["question"] == "Mohan ke sirf ₹140 baaki hain. ₹400 maaf karun?"
    assert saved(answer(r, "haan"))


def test_S1_a_reduction_within_the_balance_is_unchanged():
    r = run("Mohan ka 40 maaf kar do")
    assert r["confirm"] == {"type": "writeoff", "amount": 40}


def test_S1_a_reduction_for_a_customer_who_owes_nothing_is_the_balance_query():
    r = run("Sunita ka 50 maaf kar do")
    assert r["status"] == "ok" and r["action"] == "query" and r["query"]["customer"] == "sunita"


# --- S2: the duplicate question on every repeat ----------------------------------------------------------------

def test_S2_every_repeat_asks_also_the_third_time():
    first = last(amount=200, age=4)
    r = run("Ramesh ka 200 udhaar", after(first))
    assert ctype(r) == "duplicate"
    third = run("Ramesh ka 200 udhaar", after(first, action="question"))
    assert ctype(third) == "duplicate", third


def test_S2_a_repeated_event_inside_a_longer_utterance_asks():
    r = run("Ramesh ka 200 udhaar aur Mohan ka 50 udhaar", after(last(amount=200, age=4)))
    assert ctype(r) == "duplicate" and index(r) == 0, r
    r = run("Mohan ka 50 udhaar aur Ramesh ka 200 udhaar", after(last(amount=200, age=4)))
    assert ctype(r) == "duplicate" and index(r) == 1, r
    done = answer(r, "haan", after(last(amount=200, age=4)))
    assert saved(done) and len(done["events"]) == 2


def test_S2_outside_the_window_or_after_an_undo_no_question():
    assert saved(run("Ramesh ka 200 udhaar", after(last(amount=200, age=90), age=90)))
    assert saved(run("Ramesh ka 200 udhaar", after(last(amount=200, age=4), action="undo")))


# --- S3 / S4: same-name answers ----------------------------------------------------------------------------------

THREE = [{"id": "s1", "name": "suresh", "tags": ["chai wale"], "balance": 500},
         {"id": "s2", "name": "suresh", "tags": ["gali 4"], "balance": 100},
         {"id": "s3", "name": "suresh", "tags": [], "balance": 0}]


def test_S3_three_customers_are_all_offered_and_teesra_picks_the_third():
    c = ctx(THREE)
    r = run("Suresh ka 200 udhaar", c)
    assert r["reason"] == "same_name" and [x["id"] for x in r["candidates"]] == ["s1", "s2", "s3"]
    assert answer(r, "teesra", c)["events"][0]["customer_id"] == "s3"
    assert answer(r, "third", c)["events"][0]["customer_id"] == "s3"
    assert answer(r, "pehla", c)["events"][0]["customer_id"] == "s1"
    assert answer(r, "pehle wale", c)["events"][0]["customer_id"] == "s1"
    assert answer(r, "bina tag wale", c)["events"][0]["customer_id"] == "s3"


def test_S3_an_answer_that_fits_none_is_a_failed_attempt():
    c = ctx(THREE)
    r = answer(run("Suresh ka 200 udhaar", c), "station wale", c)
    assert r["reason"] == "same_name" and r["pending"]["attempts"] == 1


@pytest.mark.parametrize("roster", [[THREE[0], THREE[2]], [THREE[2], THREE[0]]])
def test_ORD_two_customers_ordinals_follow_the_candidates_and_bina_tag_wale_is_the_untagged(roster):
    c = ctx(roster)
    r = run("Suresh ka 200 udhaar", c)
    first = r["candidates"][0]["id"]
    for reply in ("pehle wale", "pehla", "pehla wala"):
        assert answer(r, reply, c)["events"][0]["customer_id"] == first, reply
    assert answer(r, "doosra", c)["events"][0]["customer_id"] == r["candidates"][1]["id"]
    assert answer(r, "bina tag wale", c)["events"][0]["customer_id"] == "s3"
    assert "bina tag wale" in r["question"] and "pehle wale" not in r["question"]


@pytest.mark.parametrize("utterance,ctype_,amount", [("Suresh ne poora de diya", "settle", 500),
                                                     ("Suresh ka baaki maaf kar do", "writeoff", 500)])
def test_S4_the_instruction_goes_on_after_the_same_name_answer(utterance, ctype_, amount):
    c = ctx(THREE[:2])
    r = run(utterance, c)
    assert r["reason"] == "same_name"
    nxt = answer(r, "chai wale", c)
    assert nxt["reason"] == "confirm_entry" and ctype(nxt) == ctype_, nxt
    assert entries(nxt) == [("suresh", "payment" if ctype_ == "settle" else "writeoff", amount)]


# --- S5: computed needs its words; day of the month; sath sau ----------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ne 500 ka note diya, 200 kaate, 300 wapas kiye",
                                       "Ramesh ka 300 udhaar, 100 chawal ka aur 200 aate ka"])
def test_S5_three_amounts_without_the_words_are_not_computed(utterance):
    r = run(utterance)
    assert ctype(r) != "computed" and not saved(r), r


@pytest.mark.parametrize("utterance", ["Ramesh ne 340 ka saaman liya, 300 diye, 40 udhaar likh do",
                                       "Ramesh took goods worth 500, paid 300, 200 on credit"])
def test_S5_three_amounts_with_the_words_are_computed(utterance):
    assert ctype(run(utterance)) == "computed"


@pytest.mark.parametrize("utterance", ["Ramesh ne 15 ko 200 diye", "Ramesh ko 3 ko 500 udhaar diya"])
def test_S5_a_day_of_the_month_before_ko_asks_the_date(utterance):
    r = run(utterance)
    assert r["reason"] == "unclear_date" and [e[2] for e in entries(r)] in ([200], [500]), r


def test_S5_a_tag_number_before_ko_is_not_a_date():
    c = ctx([{"id": "r1", "name": "ramesh", "tags": ["chai wale"]}, {"id": "r2", "name": "ramesh",
                                                                       "tags": ["gali number 3"]}])
    assert run("Ramesh gali 3 ko 100 diya", c)["events"][0]["customer_id"] == "r2"


@pytest.mark.parametrize("utterance", ["Ramesh ko sath sau udhaar", "Ramesh ko saath sau udhaar"])
def test_S5_sath_sau_asks_700_or_6000(utterance):
    r = run(utterance)
    assert r["reason"] == "confusable_number" and r["candidates"] == [700, 6000], r
    assert entries(answer(r, "700")) == [("ramesh", "credit", 700)]


def test_S5_saat_sau_is_unchanged():
    assert entries(run("Ramesh ko saat sau udhaar")) == [("ramesh", "credit", 700)]


# --- S6: payment and "drop the rest" -----------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,events", [
    ("Geeta ne 1000 diye baaki chhod do", [("geeta", "payment", 1000), ("geeta", "writeoff", 5)]),
    ("Mohan ne 100 diye aur baaki maaf kar do", [("mohan", "payment", 100), ("mohan", "writeoff", 40)]),
    ("Mohan ne 100 diye baaki 40 chhod do", [("mohan", "payment", 100), ("mohan", "writeoff", 40)]),
    ("Mohan ne 100 diye baaki 30 chhod do", [("mohan", "payment", 100), ("mohan", "writeoff", 30)]),
])
def test_S6_payment_and_the_rest_written_off_behind_the_review(utterance, events):
    r = run(utterance)
    assert ctype(r) == "review" and entries(r) == events, r
    done = answer(r, "haan")
    assert saved(done) and entries(done) == events


@pytest.mark.parametrize("utterance,customers", [
    ("Sunita ne 100 diye baaki chhod do", None),
    ("Mohan ne 200 diye baaki chhod do", None),
    ("Vikram ne 100 diye baaki chhod do", "nobalance"),
])
def test_S6_without_a_balance_above_the_payment_the_writeoff_amount_is_asked(utterance, customers):
    c = ctx([dict(x, balance=None) for x in ROSTER] + [{"id": "c9", "name": "vikram", "tags": []}]) \
        if customers else None
    r = run(utterance, c)
    evs = (r.get("pending") or {}).get("events") or []
    pay = [e for e in evs if e.get("kind") == "payment"]
    off = [e for e in evs if e.get("kind") == "writeoff"]
    assert pay and off and "amount" not in off[0], r
    assert r["reason"] in ("missing_amount", "new_customer")


def test_S6_the_paid_amount_is_never_the_writeoff_amount():
    for u in ("Geeta ne 1000 diye baaki chhod do", "Mohan ne 100 diye baaki 40 chhod do",
              "Mohan ne 100 diye aur baaki maaf kar do", "Sunita ne 100 diye baaki chhod do"):
        r = run(u)
        assert ("geeta", "writeoff", 1000) not in entries(r) and ("mohan", "writeoff", 100) not in entries(r)
        assert ("sunita", "writeoff", 100) not in entries(r)


# --- S7: a no to the replace check cancels ---------------------------------------------------------------------

def test_S7_no_to_the_replace_check_cancels_and_the_question_names_the_new_entry():
    c = after(last(kind="payment", amount=100))
    r = run("nahi Geeta ko 500 udhaar", c)
    assert r["question"] == "Pichli entry hata kar Geeta ke ₹500 udhaar likhoon?"
    assert entries(r) == [("geeta", "credit", 500)]
    assert answer(r, "nahi", c)["reason"] == "cancelled"
    assert answer(r, "haan", c)["action"] == "amend"


# --- S8: answers ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("reply,kind,day", [("kal udhaar", "credit", D1), ("udhaar kal ka", "credit", D1),
                                            ("parso jama", "payment", D2), ("kal diye", "payment", D1)])
def test_S8_a_date_word_beside_a_direction_answer_is_kept(reply, kind, day):
    done = answer(run("Ramesh 200"), reply)
    assert saved(done) and done["events"][0]["kind"] == kind and done["events"][0]["date"] == day, done


def test_S8_a_complete_query_still_replaces_the_question():
    r = answer(run("Ramesh 200"), "kal kitna udhaar gaya")
    assert r["action"] == "query"


def test_S8_rames_haan_is_asked_again_and_naya_opens():
    first = run("Rames ko 500 udhaar")
    assert first["question"] == "Rames naya customer hai, ya Ramesh?"
    again = answer(first, "haan")
    assert again["reason"] == "new_customer"
    assert answer(again, "naya")["events"][0]["new_customer"] is True
    assert answer(first, "Ramesh")["events"][0]["customer_id"] == "c1"
    assert answer(first, "purana")["events"][0]["customer_id"] == "c1"
    assert answer(first, "pehla")["events"][0]["customer_id"] == "c1"


@pytest.mark.parametrize("reply", ["Mohan", "Mohan wali", "Mohan ki"])
def test_S8_the_customers_name_picks_the_entry(reply):
    two = [dict(last(amount=100), id=1), dict(last(amount=100, customer="mohan", cid="c2"), id=2)]
    c = after(*two)
    r = run("100 nahi 150", c)
    assert r["question"].startswith("Kaunsi entry")
    done = answer(r, reply, c)
    assert done["action"] == "amend" and entries(done) == [("mohan", "credit", 150)], done
    assert done["target"] == {"event_id": 2}


def test_S8_aur_with_an_amount_after_an_entry_is_a_new_entry():
    r = run("uska 5 rupaye aur likh do", after(last(amount=10)))
    assert saved(r) and r["action"] == "append" and entries(r) == [("ramesh", "credit", 5)]


@pytest.mark.parametrize("utterance", ["Ramesh ne jaldi se 200 diye aur Mohan ko 100 udhaar",
                                       "Ramesh ne yaad se 200 diye aur Mohan ko 100 udhaar",
                                       "Ramesh ne galti se 200 diye aur Mohan ko 100 udhaar"])
def test_S8_adverb_se_is_a_filler(utterance):
    r = run(utterance)
    assert saved(r) and entries(r) == [("ramesh", "payment", 200), ("mohan", "credit", 100)], r


# --- S9: English -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh bought items worth 250 on credit", "Ramesh paid 200 this morning",
                                       "Ramesh purchased 250", "Ramesh paid 200 last night"])
def test_S9_english_sentences_carry_lang_en(utterance):
    assert run(utterance)["lang"] == "en"


@pytest.mark.parametrize("utterance", ["he paid 200", "she paid 200", "they paid 200"])
def test_S9_english_pronouns_carry_over(utterance):
    r = run(utterance, after())
    assert saved(r) and entries(r)[0][0] == "ramesh", r


def test_S9_he_took_another_carries_over_and_another_is_confirmed_in_strict_mode():
    r = run("he took another 100", after())
    assert ctype(r) == "unsure" and r["confirm"]["words"] == ["another"] and entries(r) == [("ramesh", "credit", 100)]
    r = run("he took another 100", after(limits={"strict": False}))
    assert saved(r) and entries(r) == [("ramesh", "credit", 100)]


@pytest.mark.parametrize("utterance", ["Ramesh paid in full", "Ramesh paid everything", "Ramesh paid the full amount",
                                       "Ramesh cleared everything"])
def test_S9_paid_in_full_is_settle(utterance):
    r = run(utterance)
    assert ctype(r) == "settle" and entries(r) == [("ramesh", "payment", 1030)], r


def test_S9_write_off_xs_balance():
    r = run("write off Ramesh's balance")
    assert ctype(r) == "writeoff" and entries(r) == [("ramesh", "writeoff", 1030)]


@pytest.mark.parametrize("utterance,expect", [("Ramesh paid 200 not 300", ("ramesh", "payment", 200)),
                                              ("Ramesh took 200 not 300", ("ramesh", "credit", 200))])
def test_S9_n_not_m_with_no_earlier_entry_is_hearsay_for_n(utterance, expect):
    r = run(utterance)
    assert ctype(r) == "hearsay" and entries(r) == [expect], r


def test_S9_n_not_m_after_an_entry_is_still_a_correction():
    r = run("200 not 340", after())
    assert r.get("action") == "amend" or ctype(r) == "amend", r


# --- NOISE: limits.noisy confirms a save first (3.5) -------------------------------------------------------------

NOISY = {"noisy": True}


def test_NOISE_a_plain_entry_is_confirmed_and_yes_saves():
    c = ctx(limits=NOISY)
    r = run("Ramesh ka 340 udhaar", c)
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "unsure", "words": [], "noise": True}
    assert r["question"] == "Ramesh ke ₹340 udhaar likhun?" and entries(r) == [("ramesh", "credit", 340)]
    assert entries(answer(r, "haan", c)) == [("ramesh", "credit", 340)]


def test_NOISE_two_entries_are_read_back_together():
    r = run("Ramesh ka 340 udhaar aur Mohan ka 50 udhaar", ctx(limits=NOISY))
    assert r["confirm"]["noise"] is True and r["question"].startswith("2 entry likhun:")


def test_NOISE_an_amend_is_confirmed():
    r = run("nahi, 430", after(limits=NOISY))
    assert r["confirm"]["noise"] is True and r["pending"]["action"] == "amend"
    done = answer(r, "haan", after(limits=NOISY))
    assert done["action"] == "amend" and entries(done) == [("ramesh", "credit", 430)]


def test_NOISE_queries_undo_and_answers_are_not_gated():
    assert run("Ramesh ka total", ctx(limits=NOISY))["action"] == "query"
    assert run("undo karo", after(limits=NOISY))["action"] == "undo"
    first = run("Vikram ko 500 udhaar", ctx(limits=NOISY))
    assert first["reason"] == "new_customer"  # another question comes first, as today
    assert saved(answer(first, "haan", ctx(limits=NOISY)))


def test_NOISE_strict_words_are_kept():
    r = run("Ramesh ne 500 blorp diye", ctx(limits=NOISY))
    assert r["confirm"] == {"type": "unsure", "words": ["blorp"], "noise": True}


def test_NOISE_absent_or_false_changes_nothing():
    for limits in ({}, {"noisy": False}):
        assert saved(run("Ramesh ka 340 udhaar", ctx(limits=limits)))


# --- Follow-up (1.18 reworded): CLOSE, ORD (above), GOODS, REL, B5 kept credit -----------------------------------

@pytest.mark.parametrize("spoken,stored,close", [
    ("jamesh", "ramesh", True), ("rakes", "rakesh", True), ("ravesh", "ramesh", True), ("ramek", "ramesh", True),
    ("tanishke", "tanishk", True), ("kamala", "kamal", True), ("sunit", "sunita", True), ("ramesh", "rakesh", True),
    ("esh", "ramesh", True), ("rakesh sharma", "ramesh sharma", True),
    ("mohan", "imran", False), ("mohin", "mohan", False), ("vikram", "ramesh", False), ("mohan", "rakesh", False),
    ("sunita", "sunita", False), ("raman", "ramesh", False),
])
def test_CLOSE_one_consonant_and_nothing_else(spoken, stored, close):
    from nlu.names import close_name
    assert close_name(spoken, stored) is close


def test_CLOSE_flagship_with_imran_in_the_roster_asks_the_plain_question_and_yes_saves():
    roster = [c for c in ROSTER if c["name"] != "mohan"] + [{"id": "c8", "name": "imran", "tags": [], "balance": 50}]
    c = ctx(roster)
    first = run("Mohan ka 340 udhaar, kal 200 diya tha", c)
    assert first["reason"] == "new_customer" and first["candidates"] == [], first
    assert first["question"] == "Mohan naya customer hai?"
    done = answer(first, "haan", c)
    assert saved(done) and entries(done) == [("mohan", "credit", 340), ("mohan", "payment", 200)]


@pytest.mark.parametrize("utterance", ["Ramesh ka 300 udhaar, 100 chawal ka aur 200 aate ka",
                                       "रमेश का 300 उधार, 100 चावल का और 200 आटे का",
                                       "Ramesh ka 300 udhaar, 100 doodh ka aur 200 cheeni ka"])
def test_GOODS_a_goods_word_is_never_a_customer(utterance):
    r = run(utterance)
    assert r["status"] == "needs_clarification" and r["reason"] != "new_customer", r
    assert {e[0] for e in entries(r)} <= {"ramesh", None}
    for word in ("chawal", "aate", "doodh", "cheeni", "Chawal", "Aate"):
        assert word not in (r.get("question") or "")


def test_GOODS_chawal_ko_is_not_a_name_either():
    r = run("chawal ko 100 udhaar")
    assert r["reason"] != "new_customer" and not saved(r), r


@pytest.mark.parametrize("utterance,key", [("his wife paid 200", "ramesh ki biwi"),
                                           ("uski biwi ne 200 diye", "ramesh ki biwi"),
                                           ("her son took 100", "ramesh ka beta"),
                                           ("uska beta 200 le gaya", "ramesh ka beta")])
def test_REL_a_possessive_and_a_relation_is_the_carried_customers_relation(utterance, key):
    r = run(utterance, after())
    assert r["reason"] == "new_customer" and r["pending"]["events"][0]["customer"] == key, r


@pytest.mark.parametrize("utterance", ["his wife paid 200", "uski biwi ne 200 diye"])
def test_REL_without_a_carried_customer_asks_whose_account(utterance):
    r = run(utterance)
    assert r["reason"] == "missing_customer" and r["pending"]["events"][0]["amount"] == 200, r


@pytest.mark.parametrize("utterance", ["Ramesh ne 500 ka saaman liya, 200 udhaar rakha",
                                       "Ramesh ne 500 ka saaman liya, 200 udhaar likh do",
                                       "Ramesh ne 500 ka saaman liya, 200 khate mein likh do"])
def test_B5_a_purchase_and_a_smaller_kept_credit_is_one_computed_credit(utterance):
    r = run(utterance)
    assert ctype(r) == "computed" and r["confirm"]["bill"] == 500 and r["confirm"]["paid"] == 300, r
    assert entries(r) == [("ramesh", "credit", 200)]
    assert entries(answer(r, "haan")) == [("ramesh", "credit", 200)]


@pytest.mark.parametrize("utterance", ["Ramesh ne 500 ka saaman liya, 600 udhaar rakha",
                                       "Ramesh ne 500 ka saaman liya aur Mohan ka 200 udhaar likh do",
                                       "Ramesh ne 500 ka saaman liya, 200 diye"])
def test_B5_other_two_amount_forms_are_unchanged(utterance):
    assert ctype(run(utterance)) != "computed"


# --- Follow-up 2: the particle decision survives the questions about a missing field ------------------------------

OFF = {"confirm_new_customer": False}


@pytest.mark.parametrize("first_text,reply,expect", [
    ("anil ko udhaar", "do sau", ("anil", "credit", 200)),
    ("ganesh ka 500", "ganesh ne diye", ("ganesh", "payment", 500)),
    ("अनिल को उधार", "200", ("anil", "credit", 200)),
])
def test_B7_switch_off_a_name_before_a_particle_saves_after_the_missing_field(first_text, reply, expect):
    c = ctx(limits=OFF)
    first = run(first_text, c)
    assert first["reason"] in ("missing_amount", "ambiguous_direction"), first
    done = answer(first, reply, c)
    assert saved(done) and entries(done) == [expect], done
    assert done["events"][0]["new_customer"] is True


@pytest.mark.parametrize("first_text,reply", [("anil ko udhaar", "do sau"), ("ganesh ka 500", "ganesh ne diye")])
def test_B7_switch_on_the_new_customer_question_comes_after_the_missing_field(first_text, reply):
    done = answer(run(first_text), reply)
    assert done["reason"] == "new_customer", done


def test_B7_switch_off_a_close_name_still_asks_after_the_amount():
    c = ctx(limits=OFF)
    r = answer(run("Rames ko udhaar", c), "200", c)
    assert r["reason"] == "new_customer" and [x["id"] for x in r["candidates"]] == ["c1"], r


def test_B7_switch_off_a_name_not_before_a_particle_still_asks_after_the_amount():
    c = ctx(limits=OFF)
    first = run("Vikram 500 le gaya aur Anil", c)
    r = run("Vikram udhaar", c)
    assert r["reason"] in ("missing_amount", "new_customer"), r
    if r["reason"] == "missing_amount":
        assert answer(r, "500", c)["reason"] == "new_customer"
    assert first["status"] == "needs_clarification"
