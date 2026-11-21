"""CONTRACT 1.16: rules from the third review. Each test name carries the finding id (B1 to B10, S2 to S13).

Reviewer's context: a roster with balances, server limits (strict and confirm_new_customer on), a fresh session."""
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
D0, D1 = "2026-11-21", "2026-11-20"
ROSTER = [{"id": f"c{i}", "name": n, "tags": [], "balance": b} for i, (n, b) in enumerate([
    ("ramesh", 540), ("sunita", 500), ("suresh", 1200), ("imran", 750), ("sharma", 2000), ("gupta", 150),
    ("lakshmi", 900), ("mohan", 60), ("pinky", 430), ("rajesh kumar", 1000), ("anita", 300), ("salim", 2500),
    ("geeta", 80)])]
LIMITS = {"confirm_above": 50000, "max_amount": 9999999, "carry_s": 60, "duplicate_s": 30, "strict": True,
          "confirm_new_customer": True}
LAST = {"kind": "credit", "customer": "ramesh", "customer_id": "c0", "amount": 340, "date": D0, "id": 9}


def ctx(customers=None, **extra):
    c = {"customers": ROSTER if customers is None else customers, "limits": dict(LIMITS)}
    c.update(extra)
    return c


def after(last=None, action="append", age=10, **extra):
    last = last or LAST
    return ctx(last_event=last, last_events=[last], last_turn={"action": action, "age_s": age}, **extra)


def run(utterance, c=None):
    return parse(utterance, today=T, ctx=ctx() if c is None else c)


def answer(first, utterance, c=None):
    cc = dict(ctx() if c is None else c)
    cc["pending"] = first["pending"]
    return parse(utterance, today=T, ctx=cc)


def saved(r):
    return r["status"] == "ok" and r.get("action") in ("append", "amend")


def entries(r):
    return [(e["kind"], e["customer"], e["amount"]) for e in r.get("events") or []]


def chain(utterance, replies, c=None):
    r = run(utterance, c)
    steps = [r]
    for reply in replies:
        r = answer(r, reply, c)
        steps.append(r)
    return steps


# --- B1: one question per unknown name; index; a review after field questions ---------------------------------

def test_B1_two_unknown_names_are_each_asked_then_saved():
    first = run("Vikram ko 500 udhaar aur Sunit ne 200 diye")
    assert first["reason"] == "new_customer" and first["pending"]["index"] == 0
    assert first["pending"]["events"][0]["customer"] == "vikram"
    second = answer(first, "haan")
    assert second["reason"] == "new_customer" and second["pending"]["index"] == 1
    assert [c["name"] for c in second["candidates"]] == ["sunita"]
    done = answer(second, "naya")  # new-customer questions alone: no review (1.16)
    assert saved(done), done
    assert entries(done) == [("credit", "vikram", 500), ("payment", "sunit", 200)]
    assert all(e["new_customer"] for e in done["events"])


def test_B1_picking_the_offered_customer_saves_without_a_review():
    second = answer(run("Vikram ko 500 udhaar aur Sunit ne 200 diye"), "haan")
    done = answer(second, "Sunita")
    assert saved(done), done
    assert entries(done) == [("credit", "vikram", 500), ("payment", "sunita", 200)]
    assert done["events"][1]["customer_id"] == "c1"


def test_B1_a_name_nobody_offered_changes_the_customer_so_the_entries_are_reviewed():
    second = answer(run("Vikram ko 500 udhaar aur Sunit ne 200 diye"), "haan")
    third = answer(second, "Imran")
    assert third["reason"] == "confirm_entry" and third["confirm"]["type"] == "review", third
    assert entries(answer(third, "haan")) == [("credit", "vikram", 500), ("payment", "imran", 200)]


@pytest.mark.parametrize("utterance", ["Mohan ka 340 udhaar, kal 200 diya tha",
                                       "Vikram ka 340 udhaar, kal 200 diya tha"])
def test_B1_flagship_sentence_with_an_unknown_name_asks_once_then_saves_both(utterance):
    # "naya" answers the plain and the either-or form of the new-customer question (1.18)
    name = utterance.split()[0].lower()
    c = ctx([c for c in ROSTER if c["name"] != name])
    first = run(utterance, c)
    assert first["reason"] == "new_customer" and first["pending"]["index"] == 0
    done = answer(first, "naya", c)
    assert saved(done) and done["action"] == "append", done
    assert entries(done) == [("credit", name, 340), ("payment", name, 200)]
    assert [e["date"] for e in done["events"]] == [D0, D1]
    assert done["events"][0]["new_customer"] is True


@pytest.mark.parametrize("utterance,key", [("Vikram ka 340 udhaar, kal Vikrum ne 200 diye", "vikram"),
                                           ("Mohan ka 340 udhaar, kal मोहन ने 200 दिए", "mohan"),
                                           ("Mohan ka 340 udhaar, kal Mohun ne 200 diye", "mohan")])
def test_B1_one_unknown_name_in_two_spellings_is_asked_once_under_one_key(utterance, key):
    c = ctx([c for c in ROSTER if c["name"] != "mohan"])
    first = run(utterance, c)
    assert first["reason"] == "new_customer"
    done = answer(first, "naya", c)
    assert saved(done), done
    assert entries(done) == [("credit", key, 340), ("payment", key, 200)]


def test_B1_the_same_unknown_name_in_three_events_is_asked_once():
    c = ctx([c for c in ROSTER if c["name"] != "mohan"])
    done = answer(run("Mohan ka 100 udhaar, Mohan ne 50 diye, Mohan ka 20 udhaar", c), "naya", c)
    assert entries(done) == [("credit", "mohan", 100), ("payment", "mohan", 50), ("credit", "mohan", 20)]


def test_B1_two_different_unknown_names_get_a_question_each():
    first = run("Mohan ka 100 udhaar aur Sohan ne 50 diye", ctx([c for c in ROSTER if c["name"] != "mohan"]))
    c = ctx([c for c in ROSTER if c["name"] != "mohan"])
    assert first["question"].startswith("Mohan")
    second = answer(first, "naya", c)
    assert second["reason"] == "new_customer" and second["pending"]["index"] == 1
    assert second["question"].startswith("Sohan")
    done = answer(second, "naya", c)
    assert entries(done) == [("credit", "mohan", 100), ("payment", "sohan", 50)]


def test_B1_unknown_name_and_a_missing_direction_end_with_the_review():
    first = run("Vikram ka 500 udhaar, Sunita 200")
    assert first["reason"] == "ambiguous_direction" and first["pending"]["index"] == 1
    second = answer(first, "Sunita ne diye")
    assert second["reason"] == "new_customer" and second["pending"]["index"] == 0
    third = answer(second, "haan")
    assert third["reason"] == "confirm_entry" and third["confirm"]["type"] == "review"
    assert entries(answer(third, "haan")) == [("credit", "vikram", 500), ("payment", "sunita", 200)]


@pytest.mark.parametrize("utterance,index", [("Ramesh ko 500 udhaar aur Vikram ko 200 udhaar", 1),
                                             ("Vikram ko 500 udhaar aur Ramesh ko 200 udhaar", 0),
                                             ("Ramesh ko 500 udhaar aur Rames ko 200 udhaar", 1)])
def test_B1_the_question_carries_the_index_of_its_event(utterance, index):
    r = run(utterance)
    assert r["reason"] == "new_customer" and r["pending"]["index"] == index
    done = answer(r, "naya")  # 1.18: a question that offers a close customer takes "naya", not a bare yes
    assert saved(done) and len(done["events"]) == 2, done


def test_B1_direction_question_in_a_two_entry_sentence_then_review():
    r = run("Ramesh ne 500 diye Sunita 200")
    assert r["reason"] == "ambiguous_direction" and r["pending"]["index"] == 1
    rev = answer(r, "ne diye")
    assert rev["reason"] == "confirm_entry" and rev["confirm"]["type"] == "review"
    assert entries(answer(rev, "haan")) == [("payment", "ramesh", 500), ("payment", "sunita", 200)]


def test_B1_a_single_entry_after_a_question_has_no_review():
    r = run("Vikram ko 500 udhaar")
    assert entries(answer(r, "haan")) == [("credit", "vikram", 500)]


# --- B2: dates, times and balances are never amounts ------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ko 2026 mein 500 udhaar diya", "Ramesh ko 21 November ko 500 udhaar",
                                       "Ramesh ko 500 udhaar 21/11 ko", "Ramesh ko 500 udhaar 21-11-2026 ko",
                                       "Sunita ne 3 March ko 200 diye", "Ramesh ko 500 udhaar December mein"])
def test_B2_dates_ask_which_day(utterance):
    r = run(utterance)
    assert r["reason"] == "unclear_date", r
    events = r["pending"]["events"]
    assert [e.get("amount") for e in events] == [500 if "Sunita" not in utterance else 200]


@pytest.mark.parametrize("utterance,amount", [("Ramesh ko 10:30 pe 500 udhaar", 500),
                                              ("Ramesh ko 10 baje 500 udhaar", 500),
                                              ("Sunita ne shaam 6 baje 200 diye", 200)])
def test_B2_times_are_ignored(utterance, amount):
    r = run(utterance)
    assert saved(r) and [e["amount"] for e in r["events"]] == [amount], r


@pytest.mark.parametrize("utterance,expect", [("Ramesh ne 200 diye 300 baaki hai", [("payment", "ramesh", 200)]),
                                              ("Ramesh ne 200 diye baaki 300", [("payment", "ramesh", 200)]),
                                              ("Sunita ne 100 diye, ab 400 baaki hain", [("payment", "sunita", 100)])])
def test_B2_a_stated_balance_is_never_an_entry(utterance, expect):
    assert entries(run(utterance)) == expect


@pytest.mark.parametrize("utterance,expect", [
    ("Sharma ji ke do hazaar mein se paanch sau aa gaye", [("payment", "sharma", 500)]),
    ("Ramesh ke 540 mein se 200 diye", [("payment", "ramesh", 200)]),
])
def test_B2_n_mein_se_m(utterance, expect):
    assert entries(run(utterance)) == expect


@pytest.mark.parametrize("utterance", ["Ramesh ko 340 rupaye 50 paise udhaar", "Ramesh ne 20 rupay 75 paise diye"])
def test_B2_rupees_and_paise_ask_the_amount(utterance):
    assert run(utterance)["reason"] == "missing_amount"


def test_B2_byaj_and_saath_are_never_names():
    r = run("Ramesh ko 1000 udhaar pe 50 byaj")
    assert not saved(r) and "byaj" not in str((r.get("pending") or {}).get("events"))
    r2 = run("Ramesh ke saath Sunita ko 200 udhaar")
    assert 60 not in [e.get("amount") for e in (r2.get("pending") or {}).get("events") or r2.get("events") or []]


# --- B3: pronoun answers ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("reply,kind", [("usko diye", "credit"), ("unko diye", "credit"), ("inko diye", "credit"),
                                        ("usko diya tha", "credit"), ("usne diye", "payment"),
                                        ("unhone diye", "payment"), ("inhone diye", "payment")])
def test_B3_pronoun_answers_to_the_direction_question(reply, kind):
    first = run("Ramesh 200")
    assert first["reason"] == "ambiguous_direction"
    assert entries(answer(first, reply)) == [(kind, "ramesh", 200)]


# --- B4: a number word that is a stored name ----------------------------------------------------------------------

DAS = ROSTER + [{"id": "x1", "name": "mohan das", "tags": [], "balance": 0}, {"id": "x2", "name": "sattar", "tags": []}]


@pytest.mark.parametrize("utterance,expect", [("Ramesh ne teen sau das diye", ("payment", "ramesh", 310)),
                                              ("Sunita ko ek sau das udhaar", ("credit", "sunita", 110)),
                                              ("Imran ko paanch sau das udhaar likh do", ("credit", "imran", 510)),
                                              ("Ramesh ne do sau sattar diye", ("payment", "ramesh", 270))])
def test_B4_a_number_phrase_keeps_its_words(utterance, expect):
    r = run(utterance, ctx(DAS))
    assert entries(r) == [expect], r


@pytest.mark.parametrize("name,utterance,amount", [("paanch", "Ramesh ko paanch sau udhaar", 500),
                                                   ("sau", "Ramesh ko paanch sau udhaar", 500),
                                                   ("do", "Ramesh ko 200 likh do", 200)])
def test_B4_customers_named_like_number_words(name, utterance, amount):
    roster = ROSTER + [{"id": "n1", "name": name, "tags": []}]
    r = run(utterance, ctx(roster))
    assert entries(r) == [("credit", "ramesh", amount)], r


def test_B4_the_stored_name_still_wins_at_the_start():
    assert entries(run("Sattar ko 50 udhaar", ctx(DAS)))[0][1] == "sattar"


# --- B5, B9, S7: corrections phrased as instructions ------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["usko 430 kar do", "uska 430 karo", "isko 430 karo", "wo galat tha, 430 likho",
                                       "arre 430 likhna tha", "sorry 430 likho", "change karke 430 kar do",
                                       "theek karo 430", "sorry 430 tha"])
def test_B5_hindi_make_it_n_is_an_amend_confirmation(utterance):
    r = run(utterance, after())
    assert not saved(r), r
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "amend", "old": 340, "new": 430}, r
    assert r["question"] == "Ramesh ki ₹340 udhaar entry ₹430 kar doon?"
    done = answer(r, "haan", after())
    assert done["action"] == "amend" and done["events"][0]["amount"] == 430


def test_B5_payment_entry_is_amended_not_added():
    last = dict(LAST, kind="payment", amount=200)
    r = run("usko 300 kar do", after(last))
    assert r["confirm"] == {"type": "amend", "old": 200, "new": 300}
    done = answer(r, "haan", after(last))
    assert done["action"] == "amend" and entries(done) == [("payment", "ramesh", 300)]


@pytest.mark.parametrize("action", ["question", "query", "none", "rejected"])
def test_S7_correction_after_another_turn_asks_the_amend_confirmation(action):
    r = run("nahi, 430", after(action=action, age=90))
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "amend", "old": 340, "new": 430}, r


def test_S7_correction_after_an_undo_is_still_rejected():
    r = run("nahi, 430", after(action="undo"))
    assert r["status"] == "rejected" and r["reason"] == "no_last_event"


@pytest.mark.parametrize("utterance", ["nahi 340", "amount galat hai"])
def test_S7_correction_that_changes_nothing_uses_the_unclear_wording(utterance):
    r = run(utterance, after())
    assert r["reason"] == "unclear_correction" and r["question"] == "Sahi amount boliye, ya hata do boliye."


def test_B9_karke_is_never_a_customer():
    r = run("change karke 430 kar do", after())
    assert "karke" not in str(r)


# --- B6: reducing words ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,customer,amount", [
    ("Ramesh ka 200 write off kar do", "ramesh", 200), ("Ramesh ka 200 udhaar maaf kar diya", "ramesh", 200),
    ("Ramesh ko 50 ka discount diya", "ramesh", 50), ("Ramesh ko 50 chhoot di", "ramesh", 50),
    ("Sunita ke 100 chhod do", "sunita", 100), ("Imran ka 70 kam kar do", "imran", 70),
])
def test_B6_a_reduction_with_one_amount_is_a_writeoff_confirmation(utterance, customer, amount):
    r = run(utterance)
    assert not saved(r), r
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "writeoff", r
    e = r["pending"]["events"][0]
    assert (e["kind"], e["customer"], e["amount"]) == ("writeoff", customer, amount)
    assert answer(r, "haan")["events"][0]["kind"] == "writeoff"


def test_B6_pronoun_writeoff():
    r = run("uska 200 maaf kar do", after())
    assert r["confirm"]["type"] == "writeoff" and r["pending"]["events"][0]["customer"] == "ramesh"


@pytest.mark.parametrize("utterance,c", [("aur 200 de do", "after"), ("Ramesh ko 200 advance diya", None),
                                         ("Ramesh ko 200 de do", None), ("Ramesh ko 200 de dena", None)])
def test_B6_S13_instructions_to_give_ask_the_direction(utterance, c):
    r = run(utterance, after() if c else None)
    assert r["reason"] == "ambiguous_direction", r


# --- B7: purchase and payment in one sentence -------------------------------------------------------------------

@pytest.mark.parametrize("utterance,amounts", [
    ("Ramesh ne 340 ka saaman liya, 300 diye, 40 udhaar likh do", (340, 300, 40)),
    ("Ramesh took goods worth 500, paid 300, 200 on credit", (500, 300, 200)),
])
def test_B7_bill_paid_rest_is_one_credit(utterance, amounts):
    r = run(utterance)
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "computed", r
    assert [e["amount"] for e in r["pending"]["events"]] == [amounts[2]]


# "Ramesh ne 500 ka saaman liya aur payment kar diya" is a cash sale since 1.18 (test_review5_rules B1).
@pytest.mark.parametrize("utterance", ["Ramesh ko 500 udhaar diya tha wo aa gaya",
                                       "Ramesh ko 500 udhaar diya, cash diya",
                                       "Ramesh took 500 on credit and paid", "Ramesh ko 500 udhaar diya, usne de diye"])
def test_B7_credit_with_an_amount_less_payment_cue_asks(utterance):
    r = run(utterance)
    assert r["reason"] == "ambiguous_direction", r


@pytest.mark.parametrize("utterance,amount", [("Ramesh ko sawa do sau rupaye aur udhaar diye", 225),
                                              ("Ramesh ko 200 udhaar de do", 200),
                                              ("Ramesh ko 300 ka saaman aur udhaar diya", 300)])
def test_B6_B7_a_credit_word_keeps_give_and_aur_a_credit(utterance, amount):
    r = run(utterance)
    assert saved(r) and entries(r) == [("credit", "ramesh", amount)], r


@pytest.mark.parametrize("utterance", ["galat, 430", "Wrong, 430", "nahi 430"])
def test_B5_a_plain_correction_right_after_the_entry_stays_direct(utterance):
    r = run(utterance, after(action="append", age=5))
    assert r["status"] == "ok" and r["action"] == "amend" and r["events"][0]["amount"] == 430, r


# --- B8, B10: conflicting directions and the duplicate question ----------------------------------------------------

@pytest.mark.parametrize("reply", ["nahi 300 jama", "nahi 300 diye", "300 to jama tha"])
def test_B8_a_direction_word_through_nahi_or_to_conflicts(reply):
    first = run("Ramesh bol raha tha 340 udhaar")
    assert first["reason"] == "confirm_entry"
    r = answer(first, reply)
    assert not saved(r), r


def test_B8_plausibility_and_overpayment_conflicts():
    p = run("Ramesh ka 75000 udhaar")
    assert not saved(answer(p, "nahi 7500 jama"))
    o = run("Ramesh ne 5000 diye")
    assert o["confirm"]["type"] == "overpayment"
    assert not saved(answer(o, "nahi 300 udhaar"))


def test_B8_same_name_answer_with_a_conflicting_direction():
    roster = ROSTER + [{"id": "k1", "name": "ramesh", "tags": ["kirana wale"]}]
    r = run("Ramesh ka 200 udhaar", ctx(roster))
    assert r["reason"] == "same_name"
    assert not saved(answer(r, "kirana wale ne diye", ctx(roster)))


def test_B10_duplicate_question_takes_only_yes_or_no():
    c = after(age=5)
    r = run("Ramesh ka 340 udhaar", c)
    assert r["confirm"]["type"] == "duplicate"
    assert not saved(answer(r, "nahi 430", c))
    assert not saved(answer(r, "430", c))


# --- S2: payments without a needless question ----------------------------------------------------------------------

@pytest.mark.parametrize("utterance,expect", [
    ("Pinky se 430 mil gaye", ("payment", "pinky", 430)), ("Sunita ke 200 rupaye aa gaye", ("payment", "sunita", 200)),
    ("Gupta ji ne 150 Google Pay kiya", ("payment", "gupta", 150)), ("Sunita ne 250 online bheje", ("payment",
    "sunita", 250)),
    ("Imran ne 300 PhonePe kiya", ("payment", "imran", 300)), ("Anita ne 100 transfer kiya", ("payment", "anita", 100)),
    ("Salim ne 500 bhej diye", ("payment", "salim", 500)), ("Suresh ne 500 ka ration liya", ("credit", "suresh", 500)),
])
def test_S2_everyday_payment_and_purchase_words(utterance, expect):
    r = run(utterance)
    assert entries(r) == [expect], r


# --- S3: natural answers ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("reply,kind", [("haan udhaar", "credit"), ("le gayi", "credit"), ("liye", "credit"),
                                        ("udhaar 200", "credit"), ("jama 200", "payment"), ("jama nahi udhaar",
                                        "credit"),
                                        ("udhaar nahi jama", "payment")])
def test_S3_direction_answers(reply, kind):
    first = run("Sunita 200")
    assert entries(answer(first, reply)) == [(kind, "sunita", 200)]


def test_S3_likh_do_is_yes_to_likhun():
    first = run("Ramesh bol raha tha 340 udhaar")
    assert entries(answer(first, "likh do")) == [("credit", "ramesh", 340)]


@pytest.mark.parametrize("reply,day", [("kal ka", D1), ("aaj hi", D0)])
def test_S3_date_answers(reply, day):
    first = run("Ramesh ne somvar ko 200 diye")
    r = answer(first, reply)
    assert r["status"] == "ok" and r["events"][0]["date"] == day, r


@pytest.mark.parametrize("reply", ["mat banao", "nahi banana", "nahi banao"])
def test_S3_no_to_the_new_customer_question(reply):
    first = run("Vikram ko 500 udhaar")
    r = answer(first, reply)
    assert r["status"] == "rejected" and r["reason"] == "cancelled", r


# --- S4: words that are never customer names --------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Karo 430", "badal 430 udhaar", "Edit 430", "Amount 430 udhaar",
                                       "Correction 430",
                                       "hi 430 udhaar", "Sirf 430 udhaar", "Lekin 430 udhaar", "jisme 430 udhaar",
                                       "Ramesh still 430 udhaar", "Ramesh needs 430 udhaar", "wo wala 430 hai"])
def test_S4_vocabulary_words_are_never_new_customers(utterance):
    r = run(utterance)
    events = ((r.get("pending") or {}).get("events") or []) + (r.get("events") or [])
    names = " ".join(str(e.get("customer", "")) for e in events).lower().split()
    for word in ("karo", "badal", "edit", "amount", "correction", "hi", "sirf", "lekin", "jisme", "still", "needs",
                 "wo", "wala"):
        assert word not in names, r
    assert all(e.get("customer", "x") != "" for e in events)


# --- S6: over-payment on an amend --------------------------------------------------------------------------------

def test_S6_overpayment_check_on_amend_leaves_out_the_replaced_entry():
    last = dict(LAST, kind="payment", amount=540)
    roster = [dict(ROSTER[0], balance=0)] + ROSTER[1:]
    r = run("nahi 500", after(last, customers=roster))
    assert r["action"] == "amend" and r["events"][0]["amount"] == 500, r


# --- S8: a date word in a customer answer ---------------------------------------------------------------------------

def test_S8_date_kept_in_a_customer_answer():
    first = run("500 udhaar")
    r = answer(first, "Ramesh ka kal ka")
    assert entries(r) == [("credit", "ramesh", 500)] and r["events"][0]["date"] == D1


# --- S9: same-name question in a two-clause sentence names its clause ------------------------------------------------

def test_S9_same_name_question_carries_the_index():
    roster = ROSTER + [{"id": "r2", "name": "ramesh", "tags": ["gali 3"]}]
    r = run("Ramesh ko 200 udhaar aur Ramesh ne 100 diye", ctx(roster))
    assert r["reason"] == "same_name" and r["pending"]["index"] == 0
    second = answer(r, "pehla", ctx(roster))
    assert second["reason"] == "same_name" and second["pending"]["index"] == 1


# --- S10: punctuation inside a number phrase ---------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ko teen sau, chalis udhaar", "Ramesh ko teen sau. Chalis udhaar",
                                       "Ramesh ko three. Forty udhaar"])
def test_S10_punctuation_inside_a_number(utterance):
    assert entries(run(utterance)) == [("credit", "ramesh", 340)]


# --- S11: name folds ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,cid", [("पिंकी ने 50 दिए", "c8"), ("Laxmi ko 100 udhaar", "c6"),
                                           ("Pinki ka 20 udhaar", "c8"), ("Lakshmy ne 30 diye", "c6")])
def test_S11_final_y_and_x_for_ksh(utterance, cid):
    r = run(utterance)
    assert r["status"] == "ok" and r["events"][0]["customer_id"] == cid, r


# --- S12, S13: entry with a query; balance queries with dena / lena; two-name shapes ---------------------------

def test_S12_entry_and_query_in_one_sentence_confirms_the_entry():
    r = run("Ramesh ne 200 diye ab kitna baaki hai")
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "hearsay"
    assert entries(answer(r, "haan")) == [("payment", "ramesh", 200)]


@pytest.mark.parametrize("utterance,customer", [("Lakshmi ko kitna dena hai", "lakshmi"),
                                                ("Ramesh se kitna lena hai", "ramesh")])
def test_S13_kitna_dena_lena_is_a_balance_query(utterance, customer):
    r = run(utterance)
    assert r["action"] == "query" and r["query"]["type"] == "balance" and r["query"]["customer"] == customer


def test_S13_relation_with_a_tag():
    r = run("Ramesh chai wale ke bete ko 200 udhaar")
    events = r.get("events") or (r.get("pending") or {}).get("events")
    assert events[0]["amount"] == 200 and "beta" in events[0]["customer"]


def test_S13_one_customer_paying_for_another_is_out_of_scope():
    r = run("Sunita ne Ramesh ke 200 diye")
    assert r["status"] == "rejected" and r["reason"] == "out_of_scope"


@pytest.mark.parametrize("utterance", ["total", "payment", "cancel", "ok"])
def test_shared_words_alone_carry_no_lang(utterance):
    assert "lang" not in run(utterance)


# --- Regression guard: everyday sentences stay as they were ---------------------------------------------------------

EVERYDAY_OK = [
    ("Ramesh ka 340 udhaar", ("credit", "ramesh", 340)), ("Ramesh ko 500 udhaar diya", ("credit", "ramesh", 500)),
    ("Sunita ne 500 diye", ("payment", "sunita", 500)), ("Sunita ne paanch sau diye", ("payment", "sunita", 500)),
    ("Ramesh ka teen sau chalis udhar", ("credit", "ramesh", 340)), ("Imran ne 200 jama kiye", ("payment",
    "imran", 200)),
    ("Sharma ji ka 150 udhaar likh do", ("credit", "sharma", 150)), ("Gupta ji ne 100 diye", ("payment", "gupta", 100)),
    ("Lakshmi ko 250 ka saaman diya", ("credit", "lakshmi", 250)), ("Mohan ne 50 rupaye diye", ("payment",
    "mohan", 50)),
    ("Pinky ka 120 udhaar", ("credit", "pinky", 120)), ("Rajesh Kumar ne 300 diye", ("payment", "rajesh kumar", 300)),
    ("Anita ko 80 udhaar", ("credit", "anita", 80)), ("Salim ne 1000 diye", ("payment", "salim", 1000)),
    ("Geeta ka 40 udhaar", ("credit", "geeta", 40)), ("Ramesh ne kal 200 diye", ("payment", "ramesh", 200)),
    ("Sunita ka parso 150 udhaar", ("credit", "sunita", 150)), ("Imran ka dedh sau udhaar", ("credit", "imran", 150)),
    ("Suresh ne dhai sau diye", ("payment", "suresh", 250)), ("Ramesh ko sawa sau udhaar", ("credit", "ramesh", 125)),
    ("Lakshmi ne saade teen sau diye", ("payment", "lakshmi", 350)), ("Mohan ka 60 udhaar", ("credit", "mohan", 60)),
    ("Ramesh paid 500", ("payment", "ramesh", 500)), ("Sunita took 200 on credit", ("credit", "sunita", 200)),
    ("received 300 from Imran", ("payment", "imran", 300)), ("Ramesh owes 100", ("credit", "ramesh", 100)),
    ("Sharma ne 500 UPI kiya", ("payment", "sharma", 500)), ("Gupta ne 100 online diye", ("payment", "gupta", 100)),
    ("Pinky ke khate mein 200 likh do", ("credit", "pinky", 200)), ("Anita ke naam 100 likh do", ("credit",
    "anita", 100)),
    ("Salim ke jama 500 likh do", ("payment", "salim", 500)), ("Ramesh se 200 mile", ("payment", "ramesh", 200)),
    ("Sunita 200 de gayi", ("payment", "sunita", 200)), ("Imran 300 le gaya", ("credit", "imran", 300)),
    ("रमेश का 340 उधार", ("credit", "ramesh", 340)), ("सुनीता ने 500 दिए", ("payment", "sunita", 500)),
    ("Ramesh ko 2000 udhaar", ("credit", "ramesh", 2000)), ("Imran ka 75 udhaar", ("credit", "imran", 75)),
    ("Ramesh ne 20 rupaye diye", ("payment", "ramesh", 20)), ("Lakshmi ka 1200 udhaar", ("credit", "lakshmi", 1200)),
    ("haan Ramesh ka 100 udhaar", ("credit", "ramesh", 100)), ("accha Sunita ne 50 diye", ("payment", "sunita", 50)),
    ("Ramesh bhai ka 30 udhaar", ("credit", "ramesh", 30)), ("Sunita didi ne 40 diye", ("payment", "sunita", 40)),
    ("Ramesh ka do sau udhaar", ("credit", "ramesh", 200)), ("Ramesh ne 450 diye", ("payment", "ramesh", 450)),
    ("Mohan ko 10 udhaar", ("credit", "mohan", 10)), ("Ramesh ka 2k udhaar", ("credit", "ramesh", 2000)),
    ("Ramesh ka 1,500 udhaar", ("credit", "ramesh", 1500)), ("Ramesh ne Rs. 200 diye", ("payment", "ramesh", 200)),
    ("Ramesh ne ₹300 diye", ("payment", "ramesh", 300)), ("Gupta ji ka 70 udhaar", ("credit", "gupta", 70)),
    ("Sharma ne 150 cash diye", ("payment", "sharma", 150)), ("Pinky ne 430 diye", ("payment", "pinky", 430)),
    ("Rajesh Kumar ko 100 udhaar", ("credit", "rajesh kumar", 100)), ("Anita ne 300 chuka diye", ("payment",
    "anita", 300)),
    ("Ramesh ne 100 wapas kiye", ("payment", "ramesh", 100)), ("Ramesh ka 340 udhaar likh do.", ("credit",
    "ramesh", 340)),
    ("Sunita ne deedh sau rupaye diye.", ("payment", "sunita", 150)),
    ("Ramesh ka three forty udhaar likh do.", ("credit", "ramesh", 340)),
    ("Imran ne five hundred diye", ("payment", "imran", 500)), ("Ramesh ko teen sau udhaar", ("credit", "ramesh", 300)),
    ("Suresh ka 100 udhaar", ("credit", "suresh", 100)), ("Ramesh ko 500 ka saaman diya", ("credit", "ramesh", 500)),
    ("Ramesh ne paanch sau ka saaman liya", ("credit", "ramesh", 500)), ("Sunita ne 200 Paytm kiya", ("payment",
    "sunita", 200)),
]


@pytest.mark.parametrize("utterance,expect", EVERYDAY_OK, ids=[u for u, _ in EVERYDAY_OK])
def test_everyday_sentences_still_save(utterance, expect):
    r = run(utterance)
    assert r["status"] == "ok" and entries(r) == [expect], r


@pytest.mark.parametrize("utterance,expect", [
    ("Ramesh ka 340 udhaar, kal 200 diya tha", [("credit", "ramesh", 340), ("payment", "ramesh", 200)]),
    ("Ramesh ka 100 udhaar aur Sunita ne 50 diye", [("credit", "ramesh", 100), ("payment", "sunita", 50)]),
])
def test_everyday_two_entry_sentences_still_save(utterance, expect):
    assert entries(run(utterance)) == expect
