"""CONTRACT 1.14 edge-case rules. Each test name carries the case id from docs/EDGE_CASES.md."""
import time
from datetime import date

import pytest

from nlu.parser import _parse, parse

T = date(2026, 11, 21)
D0, D1 = "2026-11-21", "2026-11-20"
LE = {"last_event": {"kind": "credit", "customer": "ramesh", "amount": 200, "date": D0}}


def run(utterance, ctx=None):
    return parse(utterance, today=T, ctx=ctx)


def answer(first, utterance, ctx=None):
    c = dict(ctx or {})
    c["pending"] = first["pending"]
    return run(utterance, c)


def one(r):
    assert r["status"] == "ok" and len(r["events"]) == 1, r
    e = r["events"][0]
    return e["kind"], e["customer"], e["amount"], e["date"]


def roster(*customers):
    return {"customers": [dict({"tags": []}, **c) for c in customers]}


def recent(kind="credit", customer="ramesh", amount=200, age=5, action="append", **extra):
    return dict({"last_event": {"kind": kind, "customer": customer, "amount": amount, "date": D0},
                 "last_turn": {"action": action, "age_s": age}}, **extra)


# --- A. Numbers -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,amount", [("Ramesh ka 2k udhaar", 2000), ("Ramesh ka 2.5k udhaar", 2500),
                                              ("Ramesh ka ₹2,000 udhaar", 2000), ("Ramesh ka 2,000 udhaar", 2000)])
def test_A13_thousands_and_commas(utterance, amount):
    assert one(run(utterance))[2] == amount


def test_A13_decimal_that_is_not_whole_asks_amount():
    assert run("Ramesh ka 340.5 udhaar")["reason"] == "missing_amount"


def test_A14_large_amount_confirms():
    assert run("Ramesh ka 5,00,000 udhaar")["reason"] == "plausibility"


@pytest.mark.parametrize("utterance", ["Ramesh ka 0 udhaar", "Ramesh ka zero udhaar", "Ramesh ka minus 50 udhaar",
                                       "Ramesh ka -50 udhaar"])
def test_A15_zero_and_negative_are_rejected(utterance):
    r = run(utterance)
    assert r["status"] == "rejected" and r["reason"] == "invalid_number"


@pytest.mark.parametrize("utterance", ["ek customer ka", "ek customer aaya tha", "teen customer aaye the"])
def test_A16_A24_a_count_is_not_an_amount(utterance):
    r = run(utterance)
    assert r["status"] == "rejected" and r["reason"] == "not_ledger"


def test_A16_ek_with_currency_is_one_rupee():
    assert one(run("Ramesh ne ek rupaya diya"))[2] == 1


@pytest.mark.parametrize("utterance,amount", [("Ramesh Ramesh ka 340 340 udhaar", 340),
                                              ("Ramesh ka teen sau teen sau chaalis udhaar", 340)])
def test_A17_repeats_are_said_once(utterance, amount):
    assert one(run(utterance))[1:3] == ("ramesh", amount)


def test_A17_repeated_unit_word_alone_is_not_a_restart():
    assert run("Ramesh ke sau sau chalis udhaar")["reason"] == "missing_amount"


@pytest.mark.parametrize("utterance,amount", [("Ramesh ka four three zero udhaar", 430),
                                              ("Ramesh ka char teen shunya udhaar", 430),
                                              ("Ramesh ka ek do paanch udhaar", 125)])
def test_A18_digits_one_by_one(utterance, amount):
    assert one(run(utterance))[2] == amount


def test_A18_exactly_two_digits_ask():
    assert run("Ramesh ka teen chaar udhaar")["reason"] == "missing_amount"


def test_A11_two_digits_before_sau_ask_which():
    r = run("Ramesh ka teen chaar sau udhaar")
    assert r["reason"] == "confusable_number" and r["candidates"] == [340, 400]
    assert r["question"] == "₹340 ya ₹400?"
    assert one(answer(r, "chaar sau"))[2] == 400


@pytest.mark.parametrize("utterance,cands", [("Ramesh ka 200 ya 300 udhaar", [200, 300]),
                                             ("Ramesh owes 200 or 300", [200, 300])])
def test_A12_two_amounts_joined_by_ya(utterance, cands):
    r = run(utterance)
    assert r["reason"] == "confusable_number" and r["candidates"] == cands


def test_A19_shop_confusables():
    r = run("Ramesh ka 340 udhaar", {"confusables": {"340": [740]}})
    assert r["reason"] == "confusable_number" and r["candidates"] == [340, 740]
    assert one(run("Ramesh ka 340 udhaar", {"confusables": {"500": [50]}}))[2] == 340


def test_A20_devanagari_digits():
    assert one(run("रमेश का १२३ उधार"))[2] == 123


def test_A21_ten_times_usual_confirms():
    ctx = roster({"id": "c1", "name": "ramesh", "usual": 150})
    r = run("Ramesh ka 1500 udhaar", ctx)
    assert r["reason"] == "plausibility" and r["usual"] == 150
    assert run("Ramesh ka 900 udhaar", roster({"id": "c1", "name": "ramesh", "usual": 50}))["status"] == "ok"
    assert run("Ramesh ka 1500 udhaar", roster({"id": "c1", "name": "ramesh"}))["status"] == "ok"


@pytest.mark.parametrize("utterance,reason", [("Ramesh ka 5 crore udhaar", "too_large"),
                                              ("Ramesh ka 999999999999 udhaar", "too_large"),
                                              ("Ramesh ka ek crore udhaar", "too_large")])
def test_A22_above_max_amount_is_rejected(utterance, reason):
    r = run(utterance)
    assert r["status"] == "rejected" and r["reason"] == reason


def test_A22_max_amount_from_limits():
    assert run("Ramesh ka 20000 udhaar", {"limits": {"max_amount": 10000}})["reason"] == "too_large"


def test_confirm_below_without_currency():
    lim = {"limits": {"confirm_below": 10}}
    assert run("Ramesh ka teen udhaar", lim)["reason"] == "plausibility"
    assert one(run("Ramesh ka teen rupaye udhaar", lim))[2] == 3
    assert one(run("Ramesh ka teen udhaar"))[2] == 3  # no limits: as before


@pytest.mark.parametrize("utterance", ["Ramesh ka 340 paise udhaar", "Ramesh ka 340 rupay udhaar",
                                       "Ramesh ka rs. 340 udhaar", "Ramesh ka 340 rupaiye udhaar"])
def test_A23_currency_words_are_never_names(utterance):
    assert one(run(utterance))[1:3] == ("ramesh", 340)


@pytest.mark.parametrize("utterance", ["Ramesh ko 2 kilo chawal udhaar", "Ramesh ko 3 packet doodh udhaar"])
def test_H03_quantity_with_customer_asks_price(utterance):
    r = run(utterance)
    assert r["reason"] == "missing_amount" and r["question"] == "Kitne ka?"
    assert one(answer(r, "80 rupaye"))[1:3] == ("ramesh", 80)


def test_H03_quantity_and_amount_is_confirmed_since_1_15():
    r = run("Ramesh ko 2 kilo chawal 120 rupaye ka udhaar")  # a count beside an amount (1.15 B7)
    assert r["confirm"]["type"] == "unsure" and r["pending"]["events"][0]["amount"] == 120


# --- B. Direction -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["gave Sunita 500 on credit", "gave 500 to Sunita on credit"])
def test_B06_gave_on_credit(utterance):
    assert one(run(utterance)) == ("credit", "sunita", 500, D0)


@pytest.mark.parametrize("utterance", ["Ramesh ne 30 udhaar chuka diya", "Ramesh ka udhaar wapas aaya 30",
                                       "Ramesh ne 30 udhaar lautaya"])
def test_B11_udhaar_repaid_is_a_payment(utterance):
    assert one(run(utterance)) == ("payment", "ramesh", 30, D0)


@pytest.mark.parametrize("utterance", ["Ramesh ne Ramesh ko 100 diya", "Sunita ko ne 500 diya",
                                       "Sunita ne ko 500 diya"])
def test_B12_one_name_with_ne_and_ko_asks(utterance):
    assert run(utterance)["reason"] == "ambiguous_direction"


def test_B12_date_ko_is_not_a_particle_for_the_name():
    assert run("Ramesh ne somvar ko 200 diye")["reason"] == "unclear_date"


def test_B14_one_customer_paying_another():
    r = run("Ramesh ne Sunita ko 100 diya")
    assert r["status"] == "rejected" and r["reason"] == "out_of_scope"


@pytest.mark.parametrize("utterance,ctx", [("Ramesh ne advance 500 diya", None), ("Ramesh ka 500 advance", None),
                                           ("Ramesh ka advance 500 diya", None)])
def test_B15_advance_is_a_payment_and_never_a_name(utterance, ctx):
    assert one(run(utterance, ctx))[:3] == ("payment", "ramesh", 500)


def test_B15_advance_skips_the_overpayment_question():
    ctx = roster({"id": "c1", "name": "ramesh", "balance": 0})
    assert run("Ramesh ne advance 500 diya", ctx)["status"] == "ok"


def test_B15_advance_after_an_entry_asks_the_customer_since_1_15():
    assert run("advance 500 diya", LE)["reason"] == "missing_customer"


def test_B15_advance_without_customer_asks():
    assert run("advance 500 diya")["reason"] == "missing_customer"


def test_B16_wapas_kiya_without_ne():
    assert run("wapas kiya 100", recent())["reason"] == "missing_customer"
    assert run("Ramesh ko 100 wapas kiya")["reason"] == "ambiguous_direction"
    assert one(run("Ramesh ne 100 wapas kiya"))[0] == "payment"


@pytest.mark.parametrize("utterance", ["Ramesh 100 note kar lo", "Ramesh ka 100 likh lo", "Ramesh ka 100 daal do",
                                       "Ramesh ke 100 chadha do", "Ramesh 100 add karo"])
def test_L04_action_words_with_a_name_are_credit(utterance):
    assert one(run(utterance))[:3] == ("credit", "ramesh", 100)


# --- Carry-over and context expiry --------------------------------------------------------------------------------

def test_L01_recent_entry_carries_customer_and_kind():
    assert one(run("200 add kar do", recent())) == ("credit", "ramesh", 200, D0)


def test_L02_after_carry_s_asks_customer():
    assert run("200 add kar do", recent(age=61))["reason"] == "missing_customer"
    assert run("200 add kar do", recent(age=61, limits={"carry_s": 120}))["status"] == "ok"


def test_L02_without_last_turn_the_event_age_decides():
    old = {"last_event": {"kind": "credit", "customer": "ramesh", "amount": 200, "date": D0, "age_s": 61}}
    assert run("aur 200", old)["reason"] == "missing_customer"
    fresh = {"last_event": {"kind": "credit", "customer": "ramesh", "amount": 200, "date": D0, "age_s": 59}}
    assert one(run("aur 200", fresh))[1] == "ramesh"


def test_L03_no_recent_customer_asks():
    assert run("200 add kar do")["reason"] == "missing_customer"


def test_L06_D07_after_a_query_the_customer_carries_but_not_the_kind():
    ctx = recent(action="query")
    ctx["last_turn"]["customer"] = "sunita"
    r = run("aur 200", ctx)
    assert r["reason"] == "ambiguous_direction"
    assert r["pending"]["events"][0]["customer"] == "sunita"


def test_D06_carry_form_takes_the_last_kind():
    assert one(run("50 add kar do", recent(kind="payment")))[0] == "payment"
    assert one(run("aur 50", recent(kind="payment")))[0] == "payment"


def test_carry_after_other_turns_asks():
    for action in ("undo", "question", "none"):
        assert run("aur 200", recent(action=action))["reason"] == "missing_customer"


# --- D. Corrections, undo, stopping -------------------------------------------------------------------------------

def test_D04_correct_the_customer_not_the_amount():
    r = run("nahi, Ramesh ka nahi, Sunita ka 200", LE)
    assert r["action"] == "amend" and one(r) == ("credit", "sunita", 200, D0)
    assert one(run("Ramesh ka nahi Sunita ka", LE))[1:3] == ("sunita", 200)


def test_D11_correction_after_undo_is_blocked():
    ctx = dict(LE, last_turn={"action": "undo", "age_s": 3})
    r = run("nahi, 430", ctx)
    assert r["status"] == "rejected" and r["reason"] == "no_last_event"


@pytest.mark.parametrize("utterance", ["Ramesh ka 340 udhaar ruko", "340 nahi 430 ruko", "Ramesh ka 100 udhaar wait",
                                       "Ramesh ko 50 diya ruk jao", "Sunita ka 20 udhaar rehne do",
                                       "Ramesh ka 100 udhaar ek minute", "Ramesh ka 50 udhaar cancel"])
def test_D12_stop_word_at_the_end_saves_nothing(utterance):
    r = run(utterance, LE)
    assert r["status"] == "rejected" and r["reason"] == "cancelled"


@pytest.mark.parametrize("word", ["cancel", "chhodo", "rehne do", "ruko"])
def test_D13_stop_word_alone_clears_a_question(word):
    first = run("Ramesh ka 60000 udhaar")
    r = answer(first, word)
    assert r == {"status": "rejected", "reason": "cancelled", **({"lang": "hi"} if word != "cancel" else {})} \
        or (r["status"] == "rejected" and r["reason"] == "cancelled")


def test_D13_alone_with_nothing_pending():
    assert run("cancel", LE)["action"] == "undo"
    assert run("cancel karo", LE)["action"] == "undo"
    assert run("chhodo", LE)["reason"] == "cancelled"
    assert run("pichli entry cancel", LE)["action"] == "undo"


def test_D13_cancel_carries_no_lang():
    assert "lang" not in run("cancel", LE)
    assert "lang" not in run("ok")


@pytest.mark.parametrize("utterance", ["uh Ramesh ka matlab 340 udhaar", "umm Ramesh ka 340 udhaar yaar",
                                       "Ramesh ka like 340 udhaar", "wo na Ramesh ka 340 udhaar"])
def test_D15_fillers_are_never_names(utterance):
    assert one(run(utterance))[1:3] == ("ramesh", 340)


def test_D16_self_correction_in_one_sentence():
    assert one(run("Ramesh ka 340, nahi 430 udhaar"))[2] == 430


# --- E. Customers ------------------------------------------------------------------------------------------------

def test_E03_th_and_t_are_the_same_letter():
    r = run("Sunitha ka 50 udhaar", roster({"id": "c1", "name": "sunita"}))
    assert r["events"][0]["customer_id"] == "c1"


def test_E07_stored_name_that_is_a_number_word():
    ctx = roster({"id": "c1", "name": "das"})
    assert one(run("Das ka 100 udhaar", ctx))[1:3] == ("das", 100)
    assert one(run("Ramesh ko das rupaye udhaar", ctx))[1:3] == ("ramesh", 10)


def test_E07_stored_name_that_is_a_filler():
    ctx = roster({"id": "c1", "name": "bas"})
    assert one(run("Bas ne 100 diye", ctx))[1] == "bas"


CONFIRM_NEW = {"confirm_new_customer": True}


def test_E09_unknown_name_asks_when_the_server_wants_it():
    ctx = dict(roster({"id": "c1", "name": "rakesh"}), limits=CONFIRM_NEW)
    r = run("Rakes ka 50 udhaar", ctx)
    assert r["reason"] == "new_customer" and [c["id"] for c in r["candidates"]] == ["c1"]
    assert r["question"] == "Rakes naya customer hai, ya Rakesh?"
    assert run("Rakes ka 50 udhaar", roster({"id": "c1", "name": "rakesh"}))["events"][0]["new_customer"] is True


@pytest.mark.parametrize("reply,expect", [
    ("haan", {"customer": "rakes", "new_customer": True}),
    ("naya", {"customer": "rakes", "new_customer": True}),
    ("bana do", {"customer": "rakes", "new_customer": True}),
    ("Rakesh", {"customer": "rakesh", "customer_id": "c1"}),
    ("wahi", {"customer": "rakesh", "customer_id": "c1"}),
    ("purana", {"customer": "rakesh", "customer_id": "c1"}),
    ("pehla", {"customer": "rakesh", "customer_id": "c1"}),
])
def test_E09_new_customer_answers(reply, expect):
    ctx = dict(roster({"id": "c1", "name": "rakesh"}), limits=CONFIRM_NEW)
    first = run("Rakes ka 50 udhaar", ctx)
    r = answer(first, reply, ctx)
    assert r["status"] == "ok", r
    assert {k: r["events"][0].get(k) for k in expect} == expect


def test_E09_new_customer_no_cancels_and_another_name_resolves_again():
    ctx = dict(roster({"id": "c1", "name": "rakesh"}, {"id": "c2", "name": "mohan"}), limits=CONFIRM_NEW)
    first = run("Rakes ka 50 udhaar", ctx)
    assert answer(first, "nahi", ctx)["reason"] == "cancelled"
    assert answer(first, "Mohan", ctx)["events"][0]["customer_id"] == "c2"


@pytest.mark.parametrize("spoken,stored,close", [("rakes", "rakesh", True), ("ramesh", "rakesh", True),
                                                 ("esh", "ramesh", True), ("mohan", "rakesh", False),
                                                 ("sunita", "sunita", False)])
def test_E05_close_names(spoken, stored, close):
    from nlu.names import close_name
    assert close_name(spoken, stored) is close


def test_E12_known_name_alone_asks_what_to_write():
    ctx = roster({"id": "c1", "name": "ramesh"})
    r = run("Ramesh", ctx)
    assert r["reason"] == "missing_amount" and r["question"] == "Ramesh ka kya likhun?"
    assert r["pending"]["events"] == [{"customer": "ramesh", "customer_id": "c1", "date": D0}]
    assert one(answer(r, "340 udhaar", ctx))[:3] == ("credit", "ramesh", 340)
    q = answer(r, "hisaab", ctx)
    assert q["action"] == "query" and q["query"] == {"type": "balance", "customer": "ramesh", "customer_id": "c1"}


def test_E12_unknown_word_alone_is_not_an_entry():
    assert run("Ramesh")["reason"] == "not_ledger"
    assert run("Kamal", roster({"id": "c1", "name": "ramesh"}))["reason"] == "not_ledger"


def test_E01_gali_tag_shown_whole():
    ctx = roster({"id": "c1", "name": "ramesh", "tags": ["chai wale"]},
                 {"id": "c2", "name": "ramesh", "tags": ["gali number 3"]})
    assert run("Ramesh ka 100 udhaar", ctx)["question"] == "Kaunse Ramesh: chai wale ya gali number 3?"


def test_E15_large_roster_stays_fast():
    customers = [{"id": f"c{i}", "name": f"customer{i} kumar", "tags": [], "balance": i} for i in range(1000)]
    customers.append({"id": "r1", "name": "ramesh", "tags": []})
    ctx = {"customers": customers}
    for u in ("Ramesh ka 340 udhaar", "Rameysh ne 200 diye", "Naya naam ka 50 udhaar"):
        _parse(u, T, ctx)
    start = time.perf_counter()
    for _ in range(5):
        for u in ("Ramesh ka 340 udhaar", "Rameysh ne 200 diye", "Naya naam ka 50 udhaar"):
            _parse(u, T, ctx)
    per_call_ms = (time.perf_counter() - start) * 1000 / 15
    assert per_call_ms < 10, per_call_ms


# --- F. Glued tokens ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,expect", [
    ("sunita kofivehundred diya", ("credit", "sunita", 500, D0)),  # cut: "sunita" is carried below
    ("sunita ko500 diya", ("credit", "sunita", 500, D0)),
    ("Ramesh nefivehundred diya", ("payment", "ramesh", 500, D0)),
    ("Ramesh ko paanchsau udhaar", ("credit", "ramesh", 500, D0)),
    ("Ramesh ka rs500 udhaar", ("credit", "ramesh", 500, D0)),
    ("Ramesh ka 500rs udhaar", ("credit", "ramesh", 500, D0)),
])
def test_F01_F02_glued_tokens_are_cut(utterance, expect):
    # 1.15: a cut into particle and number needs a stored or carried customer in the sentence
    carried = {"last_event": {"kind": "credit", "customer": expect[1], "amount": 1, "date": D0}}
    assert one(run(utterance, carried)) == expect


def test_F01_glued_name_and_particle_with_a_stored_name():
    r = run("sunitako 500 diya", roster({"id": "c1", "name": "sunita"}))
    assert one(r)[:3] == ("credit", "sunita", 500)


def test_F03_token_that_cannot_be_cut_stays_whole():
    r = run("Kotwal ka 100 udhaar")
    assert one(r)[1] == "kotwal"


def test_F04_stored_name_is_never_split():
    r = run("Konda ka 100 udhaar", roster({"id": "c1", "name": "konda"}))
    assert r["events"][0]["customer_id"] == "c1"


def test_F08_comma_between_digits_is_dropped():
    assert one(run("Sunita ka 3,40 udhaar"))[2] == 340
    r = run("Ramesh, ka 340.")
    assert r["reason"] == "ambiguous_direction"
    assert r["pending"]["events"][0]["customer"] == "ramesh" and r["pending"]["events"][0]["amount"] == 340


# --- G. Not commands ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ko 500 dena hai", "Ramesh ko 500 dene hain", "Ramesh ko 500 dena padega",
                                       "Ramesh 500 de dega", "Agar Sunita 200 de to likh dena",
                                       "if Ramesh pays 200", "Sunita 200 de to theek"])
def test_G01_G02_promises_and_conditionals(utterance):
    r = run(utterance)
    assert r["status"] == "rejected" and r["reason"] == "future"


@pytest.mark.parametrize("utterance,kind", [("Ramesh bol raha tha 340 udhaar", "credit"),
                                            ("Kal Ramesh ne 300 diya tha na?", "payment"),
                                            ("Ramesh said he paid 200", "payment")])
def test_G03_G04_hearsay_and_tag_questions_confirm(utterance, kind):
    r = run(utterance)
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "hearsay"}
    assert r["pending"]["events"][0]["kind"] == kind
    assert answer(r, "haan")["status"] == "ok"
    assert answer(r, "nahi")["reason"] == "cancelled"


def test_G03_plain_yes_no_question_stays_not_ledger():
    assert run("Kya Ramesh ne 500 diye the?")["reason"] == "not_ledger"


@pytest.mark.parametrize("utterance", ["haan", "nahi", "yes", "no"])
def test_G06_yes_or_no_with_nothing_asked(utterance):
    assert run(utterance)["reason"] == "no_question"


def test_G06_nahi_after_an_entry_is_still_a_correction_question():
    assert run("nahi", LE)["reason"] == "unclear_correction"


@pytest.mark.parametrize("utterance", ["Ramesh ka 340 kitna hua?", "Ramesh ke 340 kab se baaki hain"])
def test_G09_question_word_wins_over_the_amount(utterance):
    r = run(utterance)
    assert r["action"] == "query" and r["query"]["customer"] == "ramesh"


# --- H. Bills and settlements ------------------------------------------------------------------------------------

BAL = roster({"id": "c1", "name": "ramesh", "balance": 340}, {"id": "c2", "name": "sunita", "balance": 341})


def test_H01_bill_minus_paid_confirms():
    r = run("Ramesh ka bill 450 hai, 200 diya, baaki udhaar")
    assert r["reason"] == "confirm_entry"
    assert r["confirm"] == {"type": "computed", "bill": 450, "paid": 200}
    assert r["pending"]["events"][0]["amount"] == 250
    ok = answer(r, "haan")
    assert one(ok) == ("credit", "ramesh", 250, D0)
    assert one(answer(r, "300"))[2] == 300


def test_H01_paid_more_than_bill_is_out_of_scope():
    assert run("Ramesh ka bill 450 hai, 500 diya")["reason"] == "out_of_scope"


def test_H01_customer_is_asked_first():
    r = run("Bill 450 hai, 200 diya, baaki udhaar")
    assert r["reason"] == "missing_customer"
    r2 = answer(r, "Ramesh")
    assert r2["reason"] == "confirm_entry" and r2["confirm"]["type"] == "computed"


def test_H02_discount():
    r = run("Ramesh ka 500 udhaar, 100 discount")
    assert r["reason"] == "confirm_entry" and r["pending"]["events"][0]["amount"] == 400


def test_H04_H07_settle_the_whole_balance():
    for u in ("Ramesh ne poora de diya", "Ramesh ka hisaab barabar", "Ramesh ka hisaab saaf",
              "Ramesh ne udhaar chuka diya"):
        r = run(u, BAL)
        assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "settle", "balance": 340}, u
        assert one(answer(r, "haan", BAL))[:3] == ("payment", "ramesh", 340)


def test_H04_no_balance_gives_the_balance_query():
    q = run("Ramesh ka hisaab barabar", roster({"id": "c1", "name": "ramesh", "balance": 0}))
    assert q["action"] == "query" and q["query"]["type"] == "balance"
    assert run("Ramesh ne poora de diya")["action"] == "query"


def test_H05_half():
    r = run("Ramesh ne aadha de diya", BAL)
    assert r["confirm"] == {"type": "half", "balance": 340} and r["pending"]["events"][0]["amount"] == 170
    odd = run("Sunita ne aadha de diya", BAL)
    assert odd["reason"] == "missing_amount" and odd["pending"]["events"][0]["kind"] == "payment"


@pytest.mark.parametrize("utterance", ["Ramesh ka baaki chhod do", "Ramesh ka maaf kar do", "Ramesh ka write off karo"])
def test_H06_writeoff(utterance):
    r = run(utterance, BAL)
    assert r["confirm"] == {"type": "writeoff", "balance": 340}
    ok = answer(r, "haan", BAL)
    assert ok["events"][0]["kind"] == "writeoff" and ok["events"][0]["amount"] == 340


def test_H06_writeoff_without_balance_is_the_query():
    assert run("Ramesh ka baaki chhod do")["action"] == "query"


def test_H08_overpayment():
    r = run("Ramesh ne 1000 diya", BAL)
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "overpayment", "balance": 340}
    assert r["question"] == "Sirf ₹340 baaki hain, ₹1,000 hi?"
    assert one(answer(r, "340", BAL))[2] == 340
    assert one(answer(r, "haan", BAL))[2] == 1000


def test_H08_not_asked_with_credits_in_the_same_sentence_or_without_balance():
    assert run("Ramesh ka 700 udhaar aur 1000 diye", BAL)["status"] == "ok"
    assert run("Ramesh ne 1000 diya")["status"] == "ok"
    assert run("Suresh ne 1000 diya", BAL)["status"] == "ok"  # a new customer


def test_H09_round_off():
    ctx = dict(roster({"id": "c1", "name": "ramesh", "balance": 343}), **recent())
    r = run("round off kar do", ctx)
    assert r["confirm"] == {"type": "roundoff", "balance": 343} and r["pending"]["events"][0]["amount"] == 3
    even = dict(roster({"id": "c1", "name": "ramesh", "balance": 340}), **recent())
    r2 = run("round off kar do", even)
    assert r2["reason"] == "missing_amount" and r2["pending"]["events"][0]["kind"] == "writeoff"


@pytest.mark.parametrize("utterance", ["Ramesh ka 340 udhaar, total 800 ho gaya", "Ramesh ka 340 udhaar, ab 800 baaki",
                                       "Ramesh ka 340 udhaar kul 800"])
def test_H10_stated_balance_is_not_an_entry(utterance):
    assert one(run(utterance)) == ("credit", "ramesh", 340, D0)


# --- I. Out of scope ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Wholesaler ko 5000 diya", "Supplier ko 5000 diye", "Dukaan ka kiraya 8000",
                                       "Cash mein 300 becha", "maal ka paisa 3000 diya", "bijli ka bill bhara 900",
                                       "thok wale ko 2000 diye", "salary di 8000"])
def test_I01_I03_out_of_scope(utterance):
    r = run(utterance, LE)
    assert r["status"] == "rejected" and r["reason"] == "out_of_scope"


def test_I01_unless_the_word_is_a_stored_customer():
    assert one(run("Dealer ko 500 udhaar", roster({"id": "c1", "name": "dealer"})))[1] == "dealer"


# --- J. Queries and reminders -------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,query", [
    ("Is mahine ka total", {"type": "daily_summary", "period": "this_month"}),
    ("pichle hafte kitna udhaar gaya", {"type": "credit_total", "period": "last_week"}),
    ("is hafte kitna aaya", {"type": "payment_total", "period": "this_week"}),
    ("last month total credit", {"type": "credit_total", "period": "last_month"}),
    ("Total udhaar kitna hai", {"type": "outstanding_total"}),
    ("kul baaki", {"type": "outstanding_total"}),
    ("sab ka total", {"type": "outstanding_total"}),
    ("total outstanding", {"type": "outstanding_total"}),
    ("Ramesh ka kab se baaki hai", {"type": "due_since", "customer": "ramesh"}),
])
def test_J06_J07_J09_queries(utterance, query):
    r = run(utterance)
    assert r["action"] == "query" and r["query"] == query, r


def test_J06_unknown_period_asks_the_day():
    r = run("pichle saal kitna udhaar gaya")
    assert r["reason"] == "unclear_date" and r["pending"]["action"] == "query"
    assert answer(r, "kal")["query"] == {"type": "credit_total", "period": "yesterday"}


@pytest.mark.parametrize("utterance,expect", [
    ("Ramesh ko reminder bhejo", {"customer": "ramesh"}),
    ("Send Ramesh a reminder for 850", {"customer": "ramesh", "amount": 850}),
    ("remind Sunita", {"customer": "sunita"}),
])
def test_Q08_reminder(utterance, expect):
    r = run(utterance)
    assert r["status"] == "ok" and r["action"] == "reminder"
    assert {k: r.get(k) for k in expect} == expect


def test_Q08_reminder_resolves_the_customer():
    r = run("Ramesh ko reminder bhej do", roster({"id": "c1", "name": "ramesh"}))
    assert r["customer_id"] == "c1"
    asked = run("reminder bhejo")
    assert asked["reason"] == "missing_customer"
    assert answer(asked, "Ramesh")["action"] == "reminder"


# --- K. Duplicates -----------------------------------------------------------------------------------------------

def test_K01_same_entry_within_duplicate_s_confirms():
    ctx = recent(amount=200, age=10)
    ctx["last_events"] = [ctx["last_event"]]
    r = run("Ramesh ka 200 udhaar", ctx)
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "duplicate"}
    assert one(answer(r, "haan", ctx))[2] == 200
    assert run("Ramesh ka 200 udhaar", dict(ctx, last_turn={"action": "append", "age_s": 31}))["status"] == "ok"
    assert run("aur 200", ctx)["status"] == "ok"  # carry-over forms are never asked


# --- Fallbacks and safety ----------------------------------------------------------------------------------------

def test_absent_new_fields_keep_todays_behaviour():
    assert one(run("Ramesh ne 1000 diya"))[2] == 1000
    assert run("Ramesh ka 1500 udhaar")["status"] == "ok"
    assert run("Rakes ka 50 udhaar", roster({"id": "c1", "name": "rakesh"}))["status"] == "ok"


@pytest.mark.parametrize("utterance", ["999999999999999999999", "2k" * 50, "-" * 30 + "5", "ko" * 40, "1,,,2",
                                       "₹₹₹", "k k k 2k2k2k", "zminus zposs zparso"])
def test_no_input_raises(utterance):
    _parse(utterance, T, {"customers": [{"id": "c1", "name": "sunita", "tags": [], "balance": 5}],
                          "limits": {"confirm_below": 10, "confirm_new_customer": True}})


# --- S. Language support -----------------------------------------------------------------------------------------

def test_S01_vocabulary_tables_are_data_files():
    from nlu.lexicon import load
    numbers, keywords, parser_vocab, names = (load(n) for n in ("numbers", "keywords", "parser", "names"))
    assert numbers["roman_1_99"]["79"].split()[0] == "unyaasi"  # 79, not 89 (A09)
    assert {"measure", "filler", "udhaar", "give", "stop"} <= set(keywords)
    assert {"relations", "out_of_scope_words", "english_words"} <= set(parser_vocab)
    assert "ji" in names["honorifics"]


def test_S01_keyword_spellings_never_fold_onto_number_words():
    from nlu.lexicon import load
    from nlu.numbers import WORD_LOOKUP
    from nlu.translit import fold, is_devanagari, romanise_word
    clashes = []
    for canon, text in load("keywords").items():
        for w in text.split():
            f = fold(romanise_word(w) if is_devanagari(w) else w)
            if f in WORD_LOOKUP and canon not in ("measure",):
                clashes.append((canon, w))
    assert clashes == [], clashes


@pytest.mark.parametrize("word,value", [("unchaas", 49), ("unsath", 59), ("unnasi", 79), ("nawasi", 89)])
def test_A09_unnasi_is_79(word, value):
    from nlu.numbers import parse_number
    assert parse_number(word) == value


TWO_CLOSE = dict(roster({"id": "c1", "name": "rakesh", "tags": ["chai wale"]},
                        {"id": "c2", "name": "rakesh", "tags": ["gali number 3"]}), limits=CONFIRM_NEW)


def test_E09_page_buttons_always_work():
    first = run("Rakes ka 50 udhaar", TWO_CLOSE)
    assert first["reason"] == "new_customer" and len(first["candidates"]) == 2
    assert answer(first, "pehla", TWO_CLOSE)["events"][0]["customer_id"] == "c1"
    assert answer(first, "doosra", TWO_CLOSE)["events"][0]["customer_id"] == "c2"
    assert answer(first, "first", TWO_CLOSE)["events"][0]["customer_id"] == "c1"
    assert answer(first, "second", TWO_CLOSE)["events"][0]["customer_id"] == "c2"
    made = answer(first, "naya", TWO_CLOSE)
    assert made["events"][0]["new_customer"] is True and made["events"][0]["customer"] == "rakes"
    assert answer(first, "naya customer", TWO_CLOSE)["events"][0]["new_customer"] is True


@pytest.mark.parametrize("reply", ["wahi", "purana", "Rakesh"])
def test_E09_with_two_same_name_candidates_only_position_or_tag_picks(reply):
    first = run("Rakes ka 50 udhaar", TWO_CLOSE)
    r = answer(first, reply, TWO_CLOSE)
    assert r["status"] == "needs_clarification" and r["reason"] == "new_customer"


def test_E09_tag_picks_among_same_name_candidates():
    first = run("Rakes ka 50 udhaar", TWO_CLOSE)
    assert answer(first, "chai wale", TWO_CLOSE)["events"][0]["customer_id"] == "c1"


def test_D03_D09_no_last_event_says_which_action():
    assert run("undo karo") == {"status": "rejected", "reason": "no_last_event", "action": "undo", "lang": "hi"}
    assert run("nahi, 430")["action"] == "amend"


# --- Strict mode: words the parser does not know ------------------------------------------------------------------

STRICT = {"limits": {"strict": True}}


def _golden_cases():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / "eval"
    for name in ("golden.seed.jsonl", "golden.jsonl"):
        path = root / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    yield json.loads(line)


def test_strict_mode_keeps_every_golden_save():
    """Every golden sentence that is saved today is still saved with strict on: normal speech is not slowed."""
    turned = []
    for case in _golden_cases():
        ctx = case.get("ctx") or {}
        if _parse(case["utterance"], T, ctx).get("status") != "ok":
            continue
        strict = dict(ctx, limits=dict(ctx.get("limits") or {}, strict=True))
        r = _parse(case["utterance"], T, strict)
        if r.get("status") != "ok":
            turned.append((case["id"], case["utterance"], r.get("reason"), r.get("confirm")))
    assert turned == []


@pytest.mark.parametrize("utterance,words", [("Ramesh ko 2 dabbe udhaar", ["dabbe"]),
                                             ("Ramesh ne 500 phenk diye", ["phenk"]),
                                             ("Ramesh ne 500 xyzzy diye", ["xyzzy"]),
                                             ("रमेश ने 500 फेंक दिए", ["phenk"])])
def test_strict_gate_asks_about_unknown_words(utterance, words):
    r = run(utterance, STRICT)
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "unsure", "words": words}
    assert r["question"].startswith(f"'{' '.join(words)}' samajh nahi aaya.")
    assert run(utterance)["status"] == "ok"  # strict off: saved as before


def test_strict_gate_yes_saves_and_no_cancels():
    first = run("Ramesh ne 500 phenk diye", STRICT)
    assert one(answer(first, "haan", STRICT)) == ("payment", "ramesh", 500, D0)
    assert answer(first, "nahi", STRICT)["reason"] == "cancelled"


def test_strict_gate_other_rules_decide_first():
    strict = run("Ramesh ka 340 udhaar zzzgarbage", STRICT)  # an unlisted trailing word: unsure, amount kept
    assert strict["confirm"] == {"type": "unsure", "words": ["zzzgarbage"]}
    assert run("Ramesh ka 340 udhaar zzzgarbage")["reason"] == "missing_amount"  # strict off: a second name (1.12)
    assert run("Ramesh ko 2 kilo zzzchawal udhaar", STRICT)["question"] == "Kitne ka?"
    assert run("Wholesaler ko 5000 zzz diya", STRICT)["reason"] == "out_of_scope"
    ctx = dict(roster({"id": "c1", "name": "rakesh"}), limits={"strict": True, "confirm_new_customer": True})
    first = run("Rakes ka 50 udhaar", ctx)
    assert first["reason"] == "new_customer"
    assert answer(first, "naya", ctx)["status"] == "ok"  # the asked name counts as explained


def test_strict_gate_skips_queries_undo_and_answers():
    assert run("Ramesh ka total zzz batao", STRICT)["action"] == "query"
    assert run("pichli entry zzz hata do", dict(LE, **STRICT))["status"] in ("ok", "needs_clarification")
    plaus = {"reason": "plausibility", "action": "append", "events": [{"kind": "credit", "customer": "ramesh",
                                                                       "amount": 60000, "date": D0}]}
    assert one(run("haan", dict(STRICT, pending=plaus)))[2] == 60000


def test_strict_gate_on_amend():
    r = run("nahi, 430 phenk", dict(LE, **STRICT))
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "unsure" and r["pending"]["action"] == "amend"
    ok = answer(r, "haan", dict(LE, **STRICT))
    assert ok["action"] == "amend" and ok["events"][0]["amount"] == 430


def test_strict_gate_accepts_stored_names_tags_and_goods():
    ctx = dict(roster({"id": "c1", "name": "ramesh", "tags": ["chai wale"]}), **STRICT)
    assert run("Ramesh chai wale ka 100 udhaar", ctx)["status"] == "ok"
    assert run("Ramesh ne 200 ka doodh liya", STRICT)["status"] == "ok"
    assert run("Rameysh ne 200 diye", dict(roster({"id": "c1", "name": "ramesh"}), **STRICT))["status"] == "ok"


# --- Interface additions (1.14 "Result additions") ----------------------------------------------------------------

def test_H03_quantity_question_carries_quantity_flag():
    r = run("Ramesh ko 2 kilo chawal udhaar")
    assert r["quantity"] is True and r["pending"]["quantity"] is True and r["question"] == "Kitne ka?"
    again = answer(r, "pata nahi")
    assert again.get("quantity") is True and again["question"] == "Kitne ka?"


REMINDER_PENDING = {"reason": "confirm_entry", "action": "reminder", "confirm": {"type": "reminder", "balance": 340},
                    "events": [{"customer": "ramesh", "customer_id": "c1"}]}


@pytest.mark.parametrize("reply", ["haan", "haan bhejo", "yes"])
def test_Q08_yes_to_a_reminder_question(reply):
    r = run(reply, {"pending": REMINDER_PENDING})
    assert {k: v for k, v in r.items() if k != "lang"} == {"status": "ok", "action": "reminder", "customer": "ramesh",
                                                           "customer_id": "c1"}


def test_Q08_no_to_a_reminder_question():
    assert run("nahi", {"pending": REMINDER_PENDING})["reason"] == "cancelled"


def test_warm_up_runs_and_makes_the_first_parse_fast():
    from nlu.parser import warm
    warm()
    start = time.perf_counter()
    run("Ramesh ka teen sau chaalis udhaar")
    assert (time.perf_counter() - start) * 1000 < 20


@pytest.mark.parametrize("utterance,words", [
    ("Ramesh ka 340 udhaar bahut", ["bahut"]),            # at the end
    ("Ramesh ka 340 udhaar kyunki", ["kyunki"]),
    ("Ramesh ka 340 udhaar qwxz", ["qwxz"]),
    ("Ramesh ka 340 bahut udhaar", ["bahut"]),            # in the middle
    ("Ramesh ne 340 qwxz diye", ["qwxz"]),
])
def test_strict_unknown_word_anywhere_asks_unsure_with_the_amount_kept(utterance, words):
    r = run(utterance, STRICT)
    assert r["reason"] == "confirm_entry" and r["confirm"] == {"type": "unsure", "words": words}, r
    assert r["pending"]["events"][0]["amount"] == 340


def test_strict_unknown_word_at_the_start_joins_the_name_and_asks_about_it():
    ctx = dict(roster({"id": "c1", "name": "ramesh"}), limits={"strict": True, "confirm_new_customer": True})
    r = run("bahut Ramesh ka 340 udhaar", ctx)
    assert r["status"] == "needs_clarification" and r["reason"] == "new_customer"


def test_strict_trailing_stored_name_is_still_a_second_customer():
    ctx = dict(roster({"id": "c1", "name": "ramesh"}, {"id": "c2", "name": "sunita"}), limits={"strict": True})
    assert run("Ramesh ne 500 diye Sunita bhi", ctx)["reason"] == "missing_amount"


def test_trailing_unknown_word_without_strict_is_unchanged():
    assert run("Ramesh ka 340 udhaar bahut")["reason"] == "missing_amount"  # 1.12: a second name with no amount


# --- A12: two amounts are asked first, then the next missing field -------------------------------------------------

@pytest.mark.parametrize("utterance", ["340 ya 740", "teen sau chaalis ya saat sau chaalis?"])
def test_A12_bare_two_amounts_with_a_carried_customer_ask_the_amount_first(utterance):
    ctx = recent(amount=100)
    r = run(utterance, ctx)
    assert r["reason"] == "confusable_number" and r["candidates"] == [340, 740]
    second = answer(r, "doosra", ctx)
    # 1.15: a new turn without a name or continuation word asks whose account; "wahi" picks the last customer
    assert second["reason"] == "missing_customer" and second["pending"]["events"][0]["amount"] == 740
    third = answer(second, "wahi", ctx)
    assert third["reason"] == "ambiguous_direction"
    done = answer(third, "udhaar", ctx)
    if done.get("reason") == "confirm_entry":  # the "?" form is a question: confirmed before saving (1.15)
        done = answer(done, "haan", ctx)
    assert one(done) == ("credit", "ramesh", 740, D0)


def test_A12_bare_two_amounts_without_a_customer():
    r = run("340 ya 740")
    assert r["reason"] == "confusable_number" and r["candidates"] == [340, 740]
    second = answer(r, "pehla")
    assert second["reason"] == "missing_customer" and second["pending"]["events"][0]["amount"] == 340


def test_pehla_is_not_an_answer_to_a_direction_question():
    first = run("Ramesh 500")
    assert first["reason"] == "ambiguous_direction"
    r = answer(first, "pehla")
    assert r["status"] == "needs_clarification" and r["reason"] == "ambiguous_direction"
    assert r["pending"]["attempts"] == 1
    assert answer(r, "doosra")["reason"] == "cancelled"  # a second failed attempt drops it; nothing saved
