"""CONTRACT 1.17: questions in sentences with several entries. Test names carry the item they cover:
Q1 (one question, one entry: pending.index and the question built from that event), Q2 (each doubtful event asked in
turn), Q3 (balance instructions and reductions stay in their clause), Q4 (what was said is kept).

Roster balances in rupees: Ramesh 1,030; Mohan 140; Sunita 0; Geeta 1,005. Strict mode and confirm_new_customer on."""
import json
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
D0 = "2026-11-21"
ROSTER = [
    {"id": "c1", "name": "ramesh", "tags": [], "balance": 1030},
    {"id": "c2", "name": "mohan", "tags": [], "balance": 140},
    {"id": "c3", "name": "sunita", "tags": [], "balance": 0},
    {"id": "c4", "name": "geeta", "tags": [], "balance": 1005},
]
LIMITS = {"strict": True, "confirm_new_customer": True}


def ctx(pending=None, **limits):
    c = {"customers": json.loads(json.dumps(ROSTER)), "limits": dict(LIMITS, **limits)}
    if pending is not None:
        c["pending"] = pending
    return c


def run(utterance):
    return parse(utterance, today=T, ctx=ctx())


def answer(prev, reply):
    return parse(reply, today=T, ctx=ctx(prev["pending"]))


def chain(utterance, replies):
    steps = [run(utterance)]
    for reply in replies:
        steps.append(answer(steps[-1], reply))
    return steps


def saved(r):
    return r["status"] == "ok" and r.get("action") == "append"


def entries(r):
    evs = r.get("events") or (r.get("pending") or {}).get("events") or []
    return [(e.get("customer"), e.get("kind"), e.get("amount")) for e in evs]


def index(r):
    return (r.get("pending") or {}).get("index")


def ctype(r):
    return (r.get("confirm") or {}).get("type")


# --- Q1: a confirmation about one entry of several carries its index and is built from that entry ---------------

@pytest.mark.parametrize("utterance,i,balance,question", [
    ("Ramesh ne 500 diye aur Mohan ne 200 diye", 1, 140, "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?"),
    ("Ramesh ka 200 udhaar aur Mohan ne 200 diye", 1, 140, "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?"),
    ("Ramesh ne 500 diye aur Sunita ne 200 diye", 1, 0, "Sunita ka kuch baaki nahi. ₹200 advance likhun?"),
    ("Mohan ne 200 diye aur Ramesh ne 500 diye", 0, 140, "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?"),
    ("रमेश ने 500 दिए और मोहन ने 200 दिए", 1, 140, "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?"),
    ("Ramesh paid 500 and Mohan paid 200", 1, 140, "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?"),
])
def test_Q1_overpayment_on_one_entry_carries_its_index(utterance, i, balance, question):
    r = run(utterance)
    assert r["reason"] == "confirm_entry" and ctype(r) == "overpayment", r
    assert index(r) == i and r["confirm"]["balance"] == balance
    assert r["question"] == question
    done = answer(r, "haan")
    assert saved(done) and len(done["events"]) == 2, done


def test_Q1_overpayment_after_a_plausibility_yes_names_the_paying_customer():
    first = run("Ramesh ka 99000 udhaar aur Mohan ne 200 diye")
    assert first["reason"] == "plausibility" and index(first) == 0
    second = answer(first, "haan")
    assert ctype(second) == "overpayment" and index(second) == 1 and second["confirm"]["balance"] == 140
    assert second["question"] == "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?"
    assert saved(answer(second, "haan"))


def test_Q1_plausibility_on_the_second_entry_carries_its_index():
    r = run("Ramesh ka 200 udhaar aur Mohan ka 99000 udhaar")
    assert r["reason"] == "plausibility" and index(r) == 1 and r["question"] == "₹99,000, pakka?"


def test_Q1_a_reask_keeps_the_indexed_question():
    r = run("Ramesh ne 500 diye aur Mohan ne 200 diye")
    again = answer(r, "kya?")
    assert again["reason"] == "confirm_entry" and index(again) == 1
    assert again["question"] == "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?"


def test_Q1_single_entry_overpayment_is_unchanged():
    r = run("Mohan ne 200 diye")
    assert ctype(r) == "overpayment" and index(r) is None and r["question"] == "Sirf ₹140 baaki hain, ₹200 hi?"
    assert saved(answer(r, "haan"))


# --- Q2: each doubtful event is asked in turn; a no cancels the whole utterance ---------------------------------

def test_Q2_two_implausible_amounts_are_asked_one_after_the_other():
    first, second, done = chain("Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar", ["haan", "haan"])
    assert first["reason"] == "plausibility" and index(first) == 0 and first["question"] == "₹99,000, pakka?"
    assert second["reason"] == "plausibility" and index(second) == 1 and second["question"] == "₹88,000, pakka?"
    assert saved(done) and entries(done) == [("ramesh", "credit", 99000), ("mohan", "credit", 88000)]


@pytest.mark.parametrize("utterance", ["Ramesh ne 2000 diye aur Mohan ne 200 diye",
                                       "रमेश ने 2000 दिए और मोहन ने 200 दिए", "Ramesh paid 2000 and Mohan paid 200"])
def test_Q2_two_overpayments_are_asked_one_after_the_other(utterance):
    first = run(utterance)
    assert ctype(first) == "overpayment" and index(first) == 0 and first["confirm"]["balance"] == 1030
    second = answer(first, "haan")
    assert ctype(second) == "overpayment" and index(second) == 1 and second["confirm"]["balance"] == 140
    done = answer(second, "haan")
    assert saved(done) and entries(done) == [("ramesh", "payment", 2000), ("mohan", "payment", 200)]


def test_Q2_three_entries_doubtful_first_and_last():
    steps = chain("Ramesh ka 99000 udhaar, Mohan ka 300 udhaar aur Geeta ka 77000 udhaar", ["haan", "haan"])
    assert [index(s) for s in steps[:2]] == [0, 2]
    assert saved(steps[2]) and [e[2] for e in entries(steps[2])] == [99000, 300, 77000]


def test_Q2_three_entries_doubtful_last_only():
    r = run("Ramesh ka 200 udhaar, Mohan ka 300 udhaar aur Geeta ka 77000 udhaar")
    assert r["reason"] == "plausibility" and index(r) == 2
    assert saved(answer(r, "haan"))


def test_Q2_three_entries_all_doubtful():
    steps = chain("Ramesh ka 99000 udhaar, Mohan ka 88000 udhaar aur Geeta ka 77000 udhaar", ["haan"] * 3)
    assert [index(s) for s in steps[:3]] == [0, 1, 2]
    assert saved(steps[3])


@pytest.mark.parametrize("utterance,replies", [
    ("Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar", ["haan", "nahi"]),
    ("Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar", ["nahi"]),
    ("Ramesh ne 2000 diye aur Mohan ne 200 diye", ["haan", "nahi"]),
    ("Ramesh ka 99000 udhaar aur Mohan ne 200 diye", ["haan", "nahi"]),
    ("Ramesh ka 99000 udhaar, Mohan ka 88000 udhaar aur Geeta ka 77000 udhaar", ["haan", "nahi"]),
])
def test_Q2_a_no_in_the_chain_cancels_the_whole_utterance(utterance, replies):
    last = chain(utterance, replies)[-1]
    assert last["status"] == "rejected" and last["reason"] == "cancelled", last


def test_Q2_an_amount_answer_in_the_chain_replaces_that_entry_only_and_is_not_asked_again():
    first, second, review, done = chain("Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar",
                                        ["nahi 9000", "haan", "haan"])
    assert second["reason"] == "plausibility" and index(second) == 1
    assert entries(second) == [("ramesh", "credit", 9000), ("mohan", "credit", 88000)]
    assert ctype(review) == "review"  # an answer changed a field (1.16)
    assert saved(done) and entries(done) == [("ramesh", "credit", 9000), ("mohan", "credit", 88000)]


def test_Q2_an_amount_answer_to_an_overpayment_question_replaces_that_entry():
    first, second = chain("Ramesh ne 2000 diye aur Mohan ne 200 diye", ["1000"])
    assert ctype(second) == "overpayment" and index(second) == 1
    assert entries(second) == [("ramesh", "payment", 1000), ("mohan", "payment", 200)]


def test_Q2_plain_yes_answers_do_not_add_a_review():
    *_, done = chain("Ramesh ne 2000 diye aur Mohan ne 200 diye", ["haan", "haan"])
    assert saved(done)


def test_Q2_words_still_to_confirm_are_asked_after_the_entry_questions():
    steps = chain("Ramesh ne 2000 blorp diye aur Mohan ne 200 diye", ["haan", "haan", "haan"])
    assert [ctype(s) for s in steps[:3]] == ["overpayment", "overpayment", "unsure"]
    assert saved(steps[3])


# --- Q3: balance instructions and reductions stay in their clause -------------------------------------------------

@pytest.mark.parametrize("utterance,i,kind,customer,others", [
    ("Ramesh ka 200 udhaar aur Mohan ka baaki maaf kar do", 1, "writeoff", "mohan", [("ramesh", "credit", 200)]),
    ("Ramesh ka 200 udhaar aur Geeta ka round off kar do", 1, "writeoff", "geeta", [("ramesh", "credit", 200)]),
    ("Ramesh ka 200 udhaar aur Mohan ne poora de diya", 1, "payment", "mohan", [("ramesh", "credit", 200)]),
    ("Ramesh ka 200 udhaar aur Mohan ne aadha de diya", 1, "payment", "mohan", [("ramesh", "credit", 200)]),
    ("Mohan ka baaki maaf kar do aur Ramesh ka 200 udhaar", 0, "writeoff", "mohan", [("ramesh", "credit", 200)]),
    ("रमेश का 200 उधार और मोहन का बाकी माफ कर दो", 1, "writeoff", "mohan", [("ramesh", "credit", 200)]),
    ("Ramesh took 200 on credit and write off Mohan's balance", 1, "writeoff", "mohan", [("ramesh", "credit", 200)]),
    ("Ramesh ka 200 udhaar aur uska baaki maaf kar do", 1, "writeoff", "ramesh", [("ramesh", "credit", 200)]),
])
def test_Q3_a_balance_instruction_beside_another_entry_asks_its_amount(utterance, i, kind, customer, others):
    r = run(utterance)
    assert r["reason"] == "missing_amount" and index(r) == i, r
    evs = r["pending"]["events"]
    assert len(evs) == 2
    assert evs[i]["kind"] == kind and evs[i]["customer"] == customer and "amount" not in evs[i]
    assert [(e["customer"], e["kind"], e["amount"]) for j, e in enumerate(evs) if j != i] == others
    assert "confirm" not in r  # nothing is worked out from the balance here


def test_Q3_never_a_writeoff_of_the_other_clause_amount():
    r = run("Ramesh ka 200 udhaar aur Mohan ka baaki maaf kar do")
    assert ("ramesh", "writeoff", 200) not in entries(r)
    done = answer(answer(r, "140"), "haan")
    assert saved(done) and entries(done) == [("ramesh", "credit", 200), ("mohan", "writeoff", 140)]


def test_Q3_three_clauses_with_a_round_off_in_the_middle():
    steps = chain("Ramesh ka 200 udhaar, Geeta ka round off kar do aur Sunita ne 100 diye", ["5", "haan", "haan"])
    assert steps[0]["reason"] == "missing_amount" and index(steps[0]) == 1
    assert ctype(steps[1]) == "overpayment" and index(steps[1]) == 2  # Sunita owes nothing
    assert ctype(steps[2]) == "review"
    assert entries(steps[3]) == [("ramesh", "credit", 200), ("geeta", "writeoff", 5), ("sunita", "payment", 100)]


@pytest.mark.parametrize("utterance", ["Ramesh ka 200 udhaar aur Mohan ke 50 maaf kar do",
                                       "Ramesh ka 200 udhaar aur Mohan ka 50 chhod do"])
def test_Q3_a_reduction_with_its_own_amount_is_a_writeoff_of_that_amount(utterance):
    r = run(utterance)
    assert r["reason"] == "confirm_entry" and ctype(r) == "writeoff" and index(r) == 1, r
    assert r["confirm"]["amount"] == 50 and r["question"] == "Mohan ke ₹50 maaf karun?"
    assert entries(r) == [("ramesh", "credit", 200), ("mohan", "writeoff", 50)]
    done = answer(r, "haan")
    assert saved(done) and entries(done) == [("ramesh", "credit", 200), ("mohan", "writeoff", 50)]
    assert answer(r, "nahi")["reason"] == "cancelled"


def test_Q3_a_reduction_yes_still_checks_the_other_entries():
    first = run("Ramesh ne 2000 diye aur Mohan ke 50 maaf kar do")
    assert ctype(first) == "writeoff" and index(first) == 1
    second = answer(first, "haan")
    assert ctype(second) == "overpayment" and index(second) == 0


@pytest.mark.parametrize("utterance,expect", [
    ("Ramesh ka baaki maaf kar do", ("writeoff", "ramesh", 1030)),
    ("Ramesh ka 200 maaf kar do", ("writeoff", "ramesh", 200)),
    ("Ramesh ne poora de diya", ("settle", "ramesh", 1030)),
])
def test_Q3_single_clause_instructions_are_unchanged(utterance, expect):
    r = run(utterance)
    assert r["reason"] == "confirm_entry" and ctype(r) == expect[0]
    assert entries(r)[0][0] == expect[1] and entries(r)[0][2] == expect[2]


def test_Q3_bill_and_discount_stays_one_computed_credit():
    r = run("Ramesh ka 500 udhaar, 100 discount")
    assert ctype(r) == "computed" and entries(r) == [("ramesh", "credit", 400)]


# --- Q4: what was said is kept ---------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,kind,amount", [
    ("Ramesh ka khata, Sunita ko pandrah sau udhaar", "credit", 1500),
    ("Maya, Shivakumar ko pandrah sau udhaar", "credit", 1500),
    ("Maya khata Shivakumar, Shivakumar ke khate mein pandrah sau rupaye udhaar likh diya.", "credit", 1500),
    ("Ramesh aur Sunita ko 500 udhaar", "credit", 500),
    ("Ramesh and Sunita paid 500", "payment", 500),
    ("रमेश का खाता, सुनीता को पंद्रह सौ उधार", "credit", 1500),
])
def test_Q4_two_names_and_one_amount_ask_the_customer_and_keep_the_rest(utterance, kind, amount):
    r = run(utterance)
    assert r["reason"] == "missing_customer", r
    assert r["pending"]["events"] == [{"kind": kind, "amount": amount, "date": D0}]


def test_Q4_a_stored_name_answer_completes_the_entry():
    done = answer(run("Ramesh ka khata, Sunita ko pandrah sau udhaar"), "Sunita")
    assert saved(done) and entries(done) == [("sunita", "credit", 1500)]


def test_Q4_a_new_name_answer_goes_through_the_new_customer_question():
    first, second, done = chain("Maya khata Shivakumar, Shivakumar ke khate mein pandrah sau rupaye udhaar likh diya.",
                                ["Shivakumar", "haan"])
    assert second["reason"] == "new_customer" and second["pending"]["events"][0]["amount"] == 1500
    assert saved(done) and entries(done) == [("shivakumar", "credit", 1500)]
    assert done["events"][0]["new_customer"] is True


def test_Q4_two_direction_words_and_one_amount_still_ask_the_amount():
    r = run("Ramesh ka 100 udhaar aur Sunita ko udhaar")
    assert r["reason"] == "missing_amount" and index(r) == 1
    assert entries(r) == [("ramesh", "credit", 100), ("sunita", "credit", None)]


def test_Q4_bhi_still_asks_the_amount():
    r = run("Ramesh ne 500 diye Sunita bhi")
    assert r["reason"] == "missing_amount" and index(r) == 1
