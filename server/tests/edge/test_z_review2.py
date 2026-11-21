"""Z. Second review (CONTRACT 1.16 and 3.3). Pipeline tests with the default limits and a seeded roster; Z11 and Z12
run through the live session. Each case asserts what reaches the ledger and what is asked."""
from __future__ import annotations

import time

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_query, expect_reject, expect_saved

BALANCES = {"ramesh": 540, "sunita": 500, "suresh": 1200, "imran": 750, "sharma": 2000, "gupta": 150,
            "lakshmi": 900, "mohan": 60, "pinky": 430, "rajesh kumar": 1000, "anita": 300, "salim": 2500, "geeta": 80}


def roster(shop, **extra):
    shop.seed(*[(n, "credit", b) for n, b in {**BALANCES, **extra}.items()])
    return shop


def names(shop):
    return {c["name"] for c in shop.customers()}


def confirm_type(t):
    return (t.confirm or {}).get("type")


# ---- Z01 ---------------------------------------------------------------------------------------------------------

def test_Z01_one_unknown_name_is_asked_once_and_a_yes_saves_both_entries(shop):
    roster(shop)
    t = shop.say("Ramesh ko 500 udhaar aur Vikram ko 200 udhaar")
    expect_ask(t, "new_customer")
    assert "vikram" in t.reply_text.lower(), f"the question must name Vikram: {t.describe()}"
    expect_saved(shop.say("haan"), ("credit", "ramesh", 500), ("credit", "vikram", 200), shop=shop)


def test_Z01_each_unknown_name_gets_its_own_question_and_no_review_is_needed(shop):
    roster(shop)
    first = shop.say("Vikram ko 500 udhaar aur Sunit ne 200 diye")
    expect_ask(first, "new_customer")
    assert "vikram" in first.reply_text.lower(), first.describe()
    second = shop.say("haan")
    expect_ask(second, "new_customer")
    assert "sunit" in second.reply_text.lower() and "sunita" in second.reply_text.lower(), (
        f"Sunit is asked about separately with Sunita offered: {second.describe()}")
    assert "sunit" not in names(shop), "one yes opened two accounts"
    expect_saved(shop.say("Sunita"), ("credit", "vikram", 500), ("payment", "sunita", 200), shop=shop)


def test_Z01_a_missing_direction_ends_with_a_review_listing_both_entries(shop):
    roster(shop)
    expect_ask(shop.say("Ramesh ne 500 diye Sunita 200"))
    t = shop.say("ne diye")
    assert not any(r["customer"] == "sunita" for r in t.added), f"saved for Sunita without a question: {t.describe()}"
    expect_ask(t, "confirm_entry")
    assert confirm_type(t) == "review", t.describe()
    assert "Ramesh" in t.reply_text and "Sunita" in t.reply_text, f"the review lists every entry: {t.describe()}"
    expect_saved(shop.say("haan"), ("payment", "ramesh", 500), ("payment", "sunita", 200), shop=shop)


# ---- Z02 ---------------------------------------------------------------------------------------------------------

Z02 = [
    ("Ramesh ko 2026 mein 500 udhaar diya", "date", []),
    ("Ramesh ne 200 diye 300 baaki hai", "any", [("payment", "ramesh", 200)]),
    ("Ramesh ko 21 November ko 500 udhaar", "date", []),
    ("Ramesh ko 500 udhaar 21/11 ko", "date", []),
    ("Ramesh ko 10:30 pe 500 udhaar", "any", [("credit", "ramesh", 500)]),
    ("Ramesh ko 1000 udhaar pe 50 byaj", "any", [("credit", "ramesh", 1000)]),
    ("Ramesh ko 340 rupaye 50 paise udhaar", "amount", []),
    ("Ramesh ke saath Sunita ko 200 udhaar", "any", [("credit", "sunita", 200)]),
]


@pytest.mark.parametrize("text,kind,allowed", Z02)
def test_Z02_stray_numbers_are_never_amounts_or_names(shop, text, kind, allowed):
    roster(shop)
    before = names(shop)
    t = shop.say(text)
    got = [(r["kind"], r["customer"], r["amount"]) for r in t.saved]
    assert not any(r["amount"] in (2026, 21, 50, 60, 300) for r in t.added), f"a stray number became an entry: {t.describe()}"
    assert set(got) <= set(allowed) and len(got) <= len(allowed), f"wrong entry saved: {t.describe()}"
    assert names(shop) == before, f"a customer was created: {names(shop) - before}"
    if kind == "date":
        expect_ask(t, "unclear_date")
    if kind == "amount":
        expect_ask(t, "missing_amount")


# ---- Z03 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("answer,kind", [("usko diye", "credit"), ("unko diye", "credit"), ("inko diye", "credit"),
                                          ("usne diye", "payment")])
def test_Z03_pronoun_answers_to_the_direction_question(shop, answer, kind):
    roster(shop)
    expect_ask(shop.say("Ramesh ka 500"), "ambiguous_direction")
    expect_saved(shop.say(answer), (kind, "ramesh", 500), shop=shop)


# ---- Z04 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("stored,text,amount", [("mohan das", "Ramesh ne teen sau das diye", 310),
                                                 ("sattar", "Ramesh ne do sau sattar diye", 270)])
def test_Z04_a_number_word_that_is_also_a_name_stays_in_the_number(shop, stored, text, amount):
    roster(shop, **{stored: 1000})
    t = shop.say(text)
    got = [(r["kind"], r["customer"], r["amount"]) for r in t.saved]
    assert got in ([], [("payment", "ramesh", amount)]), f"wrong amount or customer: {t.describe()}"
    assert not any(r["customer"] == stored for r in t.added), t.describe()


# ---- Z05 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["usko 430 kar do", "uska 430 karo", "wo galat tha, 430 likho", "arre 430 likhna tha",
                                  "sorry 430 likho", "change karke 430 kar do"])
def test_Z05_make_it_n_is_an_amend_confirmation_never_a_second_entry(shop, text):
    roster(shop)
    expect_saved(shop.say("Ramesh ko 340 udhaar"), ("credit", "ramesh", 340), shop=shop)
    t = shop.say(text)
    expect_ask(t, "confirm_entry")
    assert confirm_type(t) == "amend" and (t.confirm.get("old"), t.confirm.get("new")) == (340, 430), t.describe()
    assert "karke" not in names(shop)
    done = shop.say("haan")
    assert done.status == "ok" and [(r["kind"], r["amount"]) for r in done.saved] == [("credit", 430)], done.describe()
    assert shop.balance("ramesh") == 540 + 430


# ---- Z06 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,amount", [
    ("Ramesh ka 200 write off kar do", 200), ("Ramesh ka 200 udhaar maaf kar diya", 200),
    ("Ramesh ko 50 ka discount diya", 50), ("Ramesh ko 50 chhoot di", 50)])
def test_Z06_a_reduction_asks_the_writeoff_confirmation_and_is_never_a_credit(shop, text, amount):
    roster(shop)
    t = shop.say(text)
    expect_ask(t, "confirm_entry")
    assert confirm_type(t) == "writeoff", t.describe()
    expect_saved(shop.say("haan"), ("writeoff", "ramesh", amount), shop=shop)


# ---- Z07 ---------------------------------------------------------------------------------------------------------

def test_Z07_purchase_minus_payment_is_confirmed_as_the_difference(shop):
    roster(shop)
    t = shop.say("Ramesh ne 340 ka saaman liya, 300 diye, 40 udhaar likh do")
    expect_ask(t, "confirm_entry")
    assert confirm_type(t) == "computed", t.describe()
    done = shop.say("haan")
    assert [(r["kind"], r["amount"]) for r in done.saved] == [("credit", 40)], done.describe()
    assert shop.balance("ramesh") <= 540 + 40


@pytest.mark.parametrize("text", ["Ramesh ne 500 ka saaman liya aur payment kar diya",
                                  "Ramesh ko 500 udhaar diya tha wo aa gaya"])
def test_Z07_a_credit_followed_by_a_payment_cue_is_never_saved_as_the_credit(shop, text):
    roster(shop)
    t = shop.say(text)
    expect_ask(t, "ambiguous_direction")


# ---- Z08 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("setup,answer", [
    ("Ramesh bol raha tha 340 udhaar", "nahi 300 jama"), ("Ramesh bol raha tha 340 udhaar", "nahi 300 diye"),
    ("Ramesh ne 5000 diye", "nahi 300 udhaar")])
def test_Z08_an_answer_that_conflicts_with_the_pending_kind_saves_nothing(shop, setup, answer):
    roster(shop)
    expect_ask(shop.say(setup), "confirm_entry")
    t = shop.say(answer)
    assert not t.added, f"the pending entry was saved after a conflicting answer: {t.describe()}"


# ---- Z09 ---------------------------------------------------------------------------------------------------------

def test_Z09_change_karke_is_not_a_customer_and_a_yes_never_replaces_the_entry(shop):
    roster(shop)
    shop.say("Ramesh ko 340 udhaar")
    t = shop.say("change karke 430 kar do")
    assert "karke" not in names(shop) and not t.added, t.describe()
    if t.reason == "new_customer":
        yes = shop.say("haan")
        assert not yes.reversals and "karke" not in names(shop), f"a bare yes replaced the entry: {yes.describe()}"


# ---- Z10 ---------------------------------------------------------------------------------------------------------

def test_Z10_a_number_to_the_duplicate_question_saves_nothing(shop):
    roster(shop)
    shop.say("Ramesh ne 100 diye")
    expect_ask(shop.say("Ramesh ne 100 diye"), "confirm_entry")
    t = shop.say("nahi 430")
    assert not t.added, t.describe()


# ---- Z13 ---------------------------------------------------------------------------------------------------------

Z13 = [
    ("Pinky se 430 mil gaye", "payment", "pinky", 430), ("Sunita ke 200 rupaye aa gaye", "payment", "sunita", 200),
    ("Gupta ji ne 150 Google Pay kiya", "payment", "gupta", 150),
    ("Sharma ji ke do hazaar mein se paanch sau aa gaye", "payment", "sharma", 500),
    ("Sunita ne 250 online bheje", "payment", "sunita", 250), ("Suresh ne 500 ka ration liya", "credit", "suresh", 500),
    ("पिंकी को ३४० उधार", "credit", "pinky", 340), ("Ramesh ka 340 udhaar", "credit", "ramesh", 340),
    ("Ramesh ne 200 diye", "payment", "ramesh", 200), ("Imran ko 450 udhaar", "credit", "imran", 450),
    ("Imran ne 300 diye", "payment", "imran", 300), ("Lakshmi ka dedh sau udhaar", "credit", "lakshmi", 150),
    ("Laxmi ne dhai sau diye", "payment", "lakshmi", 250), ("Salim ko sawa sau udhaar", "credit", "salim", 125),
    ("Salim ne saade teen sau diye", "payment", "salim", 350), ("Anita ka paune do sau udhaar", "credit", "anita", 175),
    ("Anita ne 100 rupaye diye", "payment", "anita", 100), ("Mohan ka 40 udhaar", "credit", "mohan", 40),
    ("Mohan ne 50 diye", "payment", "mohan", 50), ("Geeta ko 120 udhaar", "credit", "geeta", 120),
    ("Geeta ne 80 diye", "payment", "geeta", 80), ("Rajesh Kumar ko 700 udhaar", "credit", "rajesh kumar", 700),
    ("Rajesh Kumar ne 400 diye", "payment", "rajesh kumar", 400), ("Sharma ji ka 1200 udhaar", "credit", "sharma", 1200),
    ("Sharma ji ne 500 payment diya", "payment", "sharma", 500), ("Gupta ji ko 60 udhaar", "credit", "gupta", 60),
    ("Suresh ne teen sau paanch diye", "payment", "suresh", 305), ("Suresh ka do hazaar udhaar", "credit", "suresh", 2000),
    ("Ramesh ne kal 100 diye", "payment", "ramesh", 100, 1), ("Sunita ko parso 150 udhaar", "credit", "sunita", 150, 2),
    ("received 200 from Pinky", "payment", "pinky", 200), ("Sunita paid 100", "payment", "sunita", 100),
    ("Imran took 300 on credit", "credit", "imran", 300), ("gave Salim 500 on credit", "credit", "salim", 500),
    ("Anita owes 150", "credit", "anita", 150), ("Ramesh ka 340 udhaar likh do", "credit", "ramesh", 340),
    ("Suresh ke khate mein 250 likh do", "credit", "suresh", 250),
    ("Lakshmi ne 450 udhaar chuka diya", "payment", "lakshmi", 450), ("Sunita se 100 liye", "payment", "sunita", 100),
    ("Imran ka teen sau chalis udhaar", "credit", "imran", 340), ("Salim ne 1000 UPI kiya", "payment", "salim", 1000),
    ("Geeta ka paanch sau udhaar", "credit", "geeta", 500), ("Ramesh ne paanch sau rupaye diye", "payment", "ramesh", 500),
    ("Pinky ne 200 PhonePe kiya", "payment", "pinky", 200), ("Anita ne 100 Paytm kiya", "payment", "anita", 100),
    ("Sunita ne 300 transfer kiya", "payment", "sunita", 300),
]


@pytest.mark.parametrize("case", Z13, ids=[c[0] for c in Z13])
def test_Z13_everyday_sentences_are_saved_directly(shop, case):
    text, kind, name, amount, *days = case
    roster(shop)
    expect_saved(shop.say(text), (kind, name, amount, *days), shop=shop)


# ---- Z14 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("answer", ["haan udhaar", "le gayi"])
def test_Z14_natural_direction_answers_give_credit(shop, answer):
    roster(shop)
    expect_ask(shop.say("Ramesh ka 500"), "ambiguous_direction")
    expect_saved(shop.say(answer), ("credit", "ramesh", 500), shop=shop)


def test_Z14_liye_answers_the_direction_question(shop):
    roster(shop)
    expect_ask(shop.say("Ramesh ka 500"), "ambiguous_direction")
    t = shop.say("liye")
    assert t.status == "ok" and [(r["customer"], r["amount"]) for r in t.saved] == [("ramesh", 500)], t.describe()


def test_Z14_likh_do_is_yes_to_a_likhun_question(shop):
    roster(shop)
    expect_ask(shop.say("Ramesh bol raha tha 340 udhaar"), "confirm_entry")
    expect_saved(shop.say("likh do"), ("credit", "ramesh", 340), shop=shop)


def test_Z14_kal_ka_answers_the_date_question(shop):
    roster(shop)
    expect_ask(shop.say("Ramesh ne pichle hafte 200 diye"), "unclear_date")
    expect_saved(shop.say("kal ka"), ("payment", "ramesh", 200, 1), shop=shop)


@pytest.mark.parametrize("answer", ["mat banao", "nahi banana"])
def test_Z14_no_to_a_new_customer_saves_nothing_and_creates_nobody(shop, answer):
    roster(shop)
    expect_ask(shop.say("Zubair ka 340 udhaar"), "new_customer")
    t = shop.say(answer)
    assert not t.added and not ({"zubair", "banana", "banao"} & names(shop)), t.describe()


# ---- Z15 ---------------------------------------------------------------------------------------------------------

def test_Z15_a_correction_after_theek_hai_asks_the_amend_confirmation(shop):
    roster(shop)
    shop.say("Ramesh ko 340 udhaar")
    shop.say("theek hai")
    t = shop.say("nahi, 430")
    expect_ask(t, "confirm_entry")
    assert confirm_type(t) == "amend", t.describe()
    assert not t.added


def test_Z15_a_correction_after_an_undo_is_still_refused(shop):
    roster(shop)
    shop.say("Ramesh ko 340 udhaar")
    u = shop.say("undo karo")
    if u.status == "needs_clarification":
        shop.say("haan")
    expect_reject(shop.say("nahi, 430"), "no_last_event")


def test_Z15_a_correction_after_a_silent_turn_asks_the_amend_confirmation(live_stack):
    live_stack.seed_customer("ramesh", credit=540)
    c = live_stack.session()
    c.text("Ramesh ko 340 udhaar")
    c.speak({"silence": True}, audio_ms=1200)
    n = live_stack.count()
    turn = c.text("nahi, 430")
    assert live_stack.count() == n, "nothing may change before the yes"
    r = turn.result
    assert r["status"] == "needs_clarification" and (r.get("confirm") or {}).get("type") == "amend", r


# ---- Z16 ---------------------------------------------------------------------------------------------------------

def test_Z16_an_entry_plus_a_query_never_drops_the_entry(shop):
    roster(shop)
    t = shop.say("Ramesh ne 200 diye ab kitna baaki hai")
    expect_ask(t, "confirm_entry")
    assert confirm_type(t) == "hearsay", t.describe()
    events = (shop.state.pending or {}).get("events") or []
    assert [(e.get("kind"), e.get("amount")) for e in events] == [("payment", 200)], shop.state.pending


def test_Z16_kitna_dena_hai_is_a_balance_query(shop):
    roster(shop)
    t = shop.say("Lakshmi ko kitna dena hai")
    expect_query(t)
    assert "900" in t.reply_text, t.describe()


# ---- Z11, Z12 (session) --------------------------------------------------------------------------------------

def _seed_live(stack):
    stack.seed_customer("ramesh", credit=540)
    stack.seed_customer("sunita", credit=500)


def test_Z11_a_replayed_utterance_never_puts_an_old_question_back(live_stack):
    _seed_live(live_stack)
    c = live_stack.session()
    first = c.text("Ramesh ka 51000 udhaar", utt_id="u-z11-1")
    assert first.result["status"] == "needs_clarification", first.result
    assert c.text("nahi", utt_id="u-z11-2").result["status"] == "rejected"
    third = c.text("Sunita ka 52000 udhaar", utt_id="u-z11-3")
    assert third.result["status"] == "needs_clarification", third.result
    n = live_stack.count()
    replay = c.text("Ramesh ka 51000 udhaar", utt_id="u-z11-1")
    assert replay.result["status"] != "needs_clarification", f"the old question came back: {replay.result}"
    assert replay.result.get("reason") == "cancelled" and live_stack.count() == n, replay.result
    c.text("haan")
    saved = [(r["customer"], r["amount"]) for r in live_stack.rows() if r["session_id"] != "seed"]
    assert saved in ([], [("sunita", 52000)]), f"a bare yes saved the wrong entry: {saved}"


def test_Z12_a_question_survives_a_silent_turn_and_a_short_press(live_stack):
    _seed_live(live_stack)
    c = live_stack.session()
    asked = c.text("Ramesh ka 51000 udhaar")
    assert asked.result["status"] == "needs_clarification", asked.result
    n = live_stack.count()
    short = c.speak("Sunita ne 100 diye", audio_ms=300)
    assert short.result["action"] == "none" and live_stack.count() == n, short.result
    time.sleep(0.6)  # let the mock hear the short press's frames before the next press; otherwise the mock may
    # report speech for the old press after the new `start`, which is a race in the mock and not in the server
    silent = c.speak({"silence": True}, audio_ms=1200)
    r = silent.result
    assert r["status"] == "needs_clarification" and r.get("reason") == "plausibility", f"the question was lost: {r}"
    assert "Kuch sunai nahi diya" in r["reply_text"] and "51" in r["reply_text"].replace(",", ""), r
    assert live_stack.count() == n
    c.text("haan")
    saved = [(r["customer"], r["kind"], r["amount"]) for r in live_stack.rows() if r["session_id"] != "seed"]
    assert saved == [("ramesh", "credit", 51000)], saved


# ---- Z17 ---------------------------------------------------------------------------------------------------------

def test_Z17_the_problem_statement_sentence_on_a_fresh_ledger(shop):
    t = shop.say("Mohan ka 340 udhaar, kal 200 diya tha")
    expect_ask(t, "new_customer")
    assert "mohan" in t.reply_text.lower(), t.describe()
    done = shop.say("haan")
    expect_saved(done, ("credit", "mohan", 340), ("payment", "mohan", 200, 1), shop=shop)
    assert [c["name"] for c in shop.customers()] == ["mohan"], "exactly one new customer"
    assert shop.balance("mohan") == 140


DEMO = [
    ("Ramesh ka 340 udhaar", "Ramesh naya grahak hai. Khata banaun?", 0),
    ("haan", "Naya khata Ramesh. Ramesh ke khate mein ₹340 udhaar likh diya.", 340),
    ("Nahi, 430", "Theek kar diya: Ramesh, ₹430 udhaar.", 430),
    ("Aur 200 payment mila", "Ramesh se ₹200 mile, jama kar diya.", 230),
    ("Ramesh ka total?", "Ramesh ke ₹230 baaki hain.", 230),
    ("Ramesh ka teen chaar sau udhaar", "₹340 ya ₹400?", 230),
    ("pehla", "Ramesh ke khate mein ₹340 udhaar likh diya.", 570),
    ("undo karo", "Pichli entry hata di: Ramesh, ₹340 udhaar.", 230),
    ("Wholesaler ko paanch hazaar diye", "Yeh udhaar entry nahi hai, isliye nahi likha.", 230),
    ("Ramesh ka bill 450 hai, 200 diya, baaki udhaar", "Ramesh ke ₹250 udhaar likhun?", 230),
    ("haan", "Ramesh ke khate mein ₹250 udhaar likh diya.", 480),
    ("Ramesh ka total?", "Ramesh ke ₹480 baaki hain.", 480),
    ("Aaj ka hisaab batao", "Aaj ₹680 udhaar gaya, ₹200 jama hue. Sabse zyada baaki: Ramesh, ₹480.", 480),
    ("Mohan ka 340 udhaar, kal 200 diya tha", "Mohan naya grahak hai. Khata banaun?", 480),
    ("haan", "Naya khata Mohan. 2 entry likhi: Mohan ke ₹340 udhaar, kal ke ₹200 jama.", 480),
    ("Ramesh ka paanch lakh udhaar", "₹5,00,000, pakka?", 480),
    ("nahi", "Theek hai, entry nahi ki.", 480),
]


def test_Z17_the_demo_script_variant_a_gives_the_stated_replies_and_balances(make_shop):
    s = make_shop(disclosed=False)
    greeting = s.pipeline.greeting(s.state)
    assert greeting.reply_text == "Namaste! Main KhataVaani hoon, ek AI sahayak."
    s.pipeline.mark_spoken(s.state, greeting)
    for say, reply, ramesh in DEMO:
        t = s.say(say)
        assert t.reply_text == reply, f"demo step {say!r}: expected {reply!r}, got {t.reply_text!r}"
        assert s.balance("ramesh") == ramesh, f"demo step {say!r}: Ramesh's balance is {s.balance('ramesh')}"
    assert s.balance("mohan") == 140
