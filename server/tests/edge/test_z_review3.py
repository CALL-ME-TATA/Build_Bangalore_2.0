"""Z18 to Z28: questions in sentences with several entries (CONTRACT 1.17), over /ws/session with the mock speech
service and a seeded ledger with known balances."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from nlu.speak import number_to_words

from .test_z_review2 import DEMO
from .wskit import IST


def lv(stack, **balances):
    """Seed customers with balances through the live ledger (a balance of 0 creates the customer only)."""
    for name, bal in balances.items():
        stack.seed_customer(name.replace("_", " "), credit=bal)


def moved(stack):
    """Rows written by sessions (not the seed), as (kind, customer, amount); write-offs read as `writeoff`."""
    out = []
    for r in stack.rows():
        if r["session_id"] == "seed" or r["kind"] == "reversal":
            continue
        kind = "writeoff" if r.get("adjustment") == "writeoff" else r["kind"]
        out.append((kind, r["customer"], r["amount"]))
    return out


def digits(text):
    return text.replace(",", "")


class Result(dict):
    """A result message that prints as one line: status, reason, confirm type and the reply."""

    def __repr__(self):
        confirm = (self.get("confirm") or {}).get("type")
        return f"{self.get('status')}/{self.get('reason')}/{confirm} {self.get('reply_text')!r}"


def say(client, text, **kw):
    return Result(client.text(text, **kw).result)


def test_Z18_the_second_customers_overpayment_question_names_that_customer(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    q = say(c, "Ramesh ne 500 diye aur Mohan ne 200 diye")
    assert q["status"] == "needs_clarification" and q["reason"] == "confirm_entry", q
    assert q["confirm"]["type"] == "overpayment" and q["confirm"].get("balance") == 140, q
    assert "Mohan" in q["reply_text"] and "Ramesh" not in q["reply_text"], f"wrong name in the question: {q['reply_text']}"
    assert "140" in digits(q["reply_text"]) and "200" in q["reply_text"], q["reply_text"]
    assert moved(live_stack) == []
    say(c, "haan")
    assert moved(live_stack) == [("payment", "ramesh", 500), ("payment", "mohan", 200)]


def test_Z18_no_to_the_overpayment_saves_nothing(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    say(c, "Ramesh ne 500 diye aur Mohan ne 200 diye")
    r = say(c, "nahi")
    assert r["status"] == "rejected" and moved(live_stack) == [], r


def test_Z18_a_second_customer_who_owes_nothing_gets_the_advance_wording(live_stack):
    lv(live_stack, ramesh=1000, mohan=0)
    c = live_stack.session()
    q = say(c, "Ramesh ne 500 diye aur Mohan ne 200 diye")
    assert q["confirm"]["type"] == "overpayment", q
    assert "Mohan" in q["reply_text"] and "advance" in q["reply_text"].lower() and "Ramesh" not in q["reply_text"], q
    say(c, "haan")
    assert moved(live_stack) == [("payment", "ramesh", 500), ("payment", "mohan", 200)]


def test_Z18_a_credit_as_the_first_entry(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    q = say(c, "Ramesh ka 500 udhaar aur Mohan ne 200 diye")
    assert q["confirm"]["type"] == "overpayment" and "Mohan" in q["reply_text"] and "Ramesh" not in q["reply_text"], q
    say(c, "haan")
    assert moved(live_stack) == [("credit", "ramesh", 500), ("payment", "mohan", 200)]


def test_Z19_two_implausible_amounts_are_asked_one_after_the_other(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    q1 = say(c, "Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar")
    assert q1["reason"] == "plausibility" and "99" in digits(q1["reply_text"]) and "Ramesh" in q1["reply_text"], q1
    assert moved(live_stack) == []
    q2 = say(c, "haan")
    assert q2["reason"] == "plausibility" and "88" in digits(q2["reply_text"]) and "Mohan" in q2["reply_text"], q2
    assert "99000" not in digits(q2["reply_text"]) and moved(live_stack) == [], "a yes answers only the question asked"
    say(c, "haan")
    assert moved(live_stack) == [("credit", "ramesh", 99000), ("credit", "mohan", 88000)]


def test_Z19_yes_then_no_saves_nothing(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    say(c, "Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar")
    say(c, "haan")
    r = say(c, "nahi")
    assert r["status"] == "rejected" and moved(live_stack) == [], r


def test_Z19_a_new_amount_for_the_second_replaces_only_the_second_then_a_review(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    say(c, "Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar")
    say(c, "haan")
    review = say(c, "nahi 7500")
    assert review["reason"] == "confirm_entry" and review["confirm"]["type"] == "review", review
    text = digits(review["reply_text"])
    assert "99000" in text and "7500" in text and "88000" not in text, review["reply_text"]
    assert moved(live_stack) == []
    say(c, "haan")
    assert moved(live_stack) == [("credit", "ramesh", 99000), ("credit", "mohan", 7500)]


def test_Z20_both_customers_over_their_balance_get_two_questions(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    q1 = say(c, "Ramesh ne 2000 diye aur Mohan ne 200 diye")
    assert q1["confirm"]["type"] == "overpayment" and q1["confirm"]["balance"] == 1000, q1
    assert "Ramesh" in q1["reply_text"] and "Mohan" not in q1["reply_text"], q1["reply_text"]
    q2 = say(c, "haan")
    assert q2["confirm"]["type"] == "overpayment" and q2["confirm"]["balance"] == 140, q2
    assert "Mohan" in q2["reply_text"] and "Ramesh" not in q2["reply_text"], q2["reply_text"]
    assert moved(live_stack) == []
    say(c, "haan")
    assert moved(live_stack) == [("payment", "ramesh", 2000), ("payment", "mohan", 200)]


Z21 = [
    ("Ramesh ka 200 udhaar aur Mohan ka baaki maaf kar do", "50", ("writeoff", "mohan", 50)),
    ("Ramesh ka 200 udhaar aur Mohan ne poora de diya", "100", ("payment", "mohan", 100)),
    ("Ramesh ka 200 udhaar aur Mohan ne aadha de diya", "100", ("payment", "mohan", 100)),
    ("Ramesh ka 200 udhaar aur Mohan ka round off kar do", "7", ("writeoff", "mohan", 7)),
]


@pytest.mark.parametrize("text,answer,second", Z21)
def test_Z21_a_balance_instruction_stays_in_its_clause_and_asks_its_own_amount(live_stack, text, answer, second):
    lv(live_stack, ramesh=1000, mohan=147)
    c = live_stack.session()
    q = say(c, text)
    assert q["status"] == "needs_clarification" and q["reason"] == "missing_amount", q
    assert "Mohan" in q["reply_text"] and "kitne rupaye" in q["reply_text"].lower() and "Ramesh" not in q["reply_text"], q
    assert moved(live_stack) == [], "nothing may be saved before the amount is known"
    review = say(c, answer)
    assert review["reason"] == "confirm_entry" and review["confirm"]["type"] == "review", review
    assert "Ramesh" in review["reply_text"] and "Mohan" in review["reply_text"], review["reply_text"]
    say(c, "haan")
    assert moved(live_stack) == [("credit", "ramesh", 200), second], moved(live_stack)


def test_Z22_a_reduction_with_its_own_amount_in_its_own_clause(live_stack):
    lv(live_stack, ramesh=1000, mohan=147)
    c = live_stack.session()
    q = say(c, "Ramesh ka 200 udhaar aur Mohan ke 50 maaf kar do")
    assert q["reason"] == "confirm_entry" and q["confirm"]["type"] == "writeoff", q
    assert "Mohan" in q["reply_text"] and "50" in q["reply_text"] and "Ramesh" not in q["reply_text"], q["reply_text"]
    assert moved(live_stack) == []
    done = say(c, "haan")
    assert moved(live_stack) == [("credit", "ramesh", 200), ("writeoff", "mohan", 50)]
    text = digits(done["reply_text"])
    assert all(w in text for w in ("Ramesh", "Mohan", "200", "50")), f"the saved reply must list both: {text}"


Z23 = [
    ("Ramesh ka khata, Sunita ko pandrah sau udhaar", "Sunita", ("credit", "sunita", 1500)),
    ("Ramesh aur Sunita ko 500 udhaar", "Ramesh", ("credit", "ramesh", 500)),
]


@pytest.mark.parametrize("text,answer,saved", Z23)
def test_Z23_one_amount_and_two_names_asks_whose_account(live_stack, text, answer, saved):
    lv(live_stack, ramesh=1000, sunita=500)
    c = live_stack.session()
    q = say(c, text)
    assert q["status"] == "needs_clarification" and q["reason"] == "missing_customer", q
    assert moved(live_stack) == [], "nothing may be saved before the answer"
    say(c, answer)
    assert moved(live_stack) == [saved], moved(live_stack)


def test_Z24_the_real_transcript_with_a_stray_word_as_a_name(live_stack):
    lv(live_stack, ramesh=1000)
    c = live_stack.session()
    q = say(c, "Maya khata Shivakumar, Shivakumar ke khate mein pandrah sau rupaye udhaar likh diya.")
    assert q["reason"] == "missing_customer", q
    nq = say(c, "Shivakumar")
    assert nq["reason"] == "new_customer" and "Shivakumar" in nq["reply_text"], nq
    assert moved(live_stack) == []
    say(c, "haan")
    assert moved(live_stack) == [("credit", "shivakumar", 1500)]
    assert sorted(x["name"] for x in live_stack.ledger.customers_for_parser()) == ["ramesh", "shivakumar"]


def _chain_at_second_question(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    say(c, "Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar")
    q2 = say(c, "haan")
    assert "Mohan" in q2["reply_text"], q2
    return c


@pytest.mark.parametrize("turn", ["silence", "empty", "long"])
def test_Z25_a_silent_empty_or_long_turn_repeats_the_current_question(live_stack, turn):
    c = _chain_at_second_question(live_stack)
    if turn == "silence":
        r = Result(c.speak({"silence": True}, audio_ms=1200).result)
    elif turn == "empty":
        r = Result(c.speak("", audio_ms=1200).result)
    else:
        r = Result(c.speak("Ramesh ka 340 udhaar", audio_ms=31_000, realtime=False).result)
    assert r["status"] == "needs_clarification" and r["reason"] == "plausibility", r
    assert "Mohan" in r["reply_text"] and "Ramesh" not in r["reply_text"], f"the first question came back: {r['reply_text']}"
    assert moved(live_stack) == []
    say(c, "haan")
    assert moved(live_stack) == [("credit", "ramesh", 99000), ("credit", "mohan", 88000)]


@pytest.mark.parametrize("gap,answered", [(30, True), (65, False)])
def test_Z25_the_sixty_second_expiry_counts_from_the_current_question(live_stack, gap, answered):
    t0 = datetime(2026, 11, 21, 11, 0, tzinfo=IST)
    live_stack.clock.set(t0)
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    say(c, "Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar")
    live_stack.clock.set(t0 + timedelta(seconds=50))
    say(c, "haan")  # the second question is asked 50 s after the first
    live_stack.clock.set(t0 + timedelta(seconds=50 + gap))
    say(c, "haan")
    assert bool(moved(live_stack)) is answered, moved(live_stack)


def test_Z26_balances_in_a_chain_are_not_spoken_in_private_mode(live_stack):
    lv(live_stack, ramesh=1370, mohan=140)
    c = live_stack.session(private=True)
    q1 = say(c, "Ramesh ne 2000 diye aur Mohan ne 200 diye")
    q2 = say(c, "haan")
    assert "1370" in digits(q1["reply_text"]) and "140" in digits(q2["reply_text"]), (q1, q2)
    spoken = " ".join(str(r.get("text")) for r in live_stack.mock_log()["tts_requests"])
    for balance in (1370, 140):
        assert str(balance) not in spoken and number_to_words(balance, "deva") not in spoken, (
            f"balance {balance} was sent to speech: {spoken!r}")


def test_Z27_several_entries_pending_carry_the_name_in_the_question(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session()
    assert say(c, "Ramesh ka 200 udhaar aur Mohan ka baaki maaf kar do")["reply_text"] == "Mohan ke kitne rupaye?"
    c2 = live_stack.session()
    assert say(c2, "Ramesh ka 99000 udhaar aur Mohan ka 200 udhaar")["reply_text"] == "Ramesh ke ₹99,000, pakka?"


def test_Z27_one_entry_pending_keeps_the_unchanged_wording(live_stack):
    lv(live_stack, ramesh=1000)
    c = live_stack.session()
    assert say(c, "Ramesh ne paise diye")["reply_text"] == "Kitne rupaye?"
    c2 = live_stack.session()
    assert say(c2, "Ramesh ka 99000 udhaar")["reply_text"] == "₹99,000, pakka?"


def test_Z27_english_forms(live_stack):
    lv(live_stack, ramesh=1000, mohan=140)
    c = live_stack.session(lang="en")
    assert say(c, "Ramesh took 99000 on credit and Mohan took 200 on credit")["reply_text"] == (
        "₹99,000 for Ramesh, are you sure?")
    c2 = live_stack.session(lang="en")
    assert say(c2, "Ramesh took 200 on credit and Mohan paid")["reply_text"] == "How many rupees for Mohan?"
    c3 = live_stack.session(lang="en")
    assert say(c3, "Ramesh took 99000 on credit")["reply_text"] == "₹99,000, are you sure?"


def test_Z28_the_flagship_sentence_on_a_fresh_ledger(live_stack):
    c = live_stack.session()
    q = say(c, "Mohan ka 340 udhaar, kal 200 diya tha")
    assert q["reason"] == "new_customer" and "Mohan" in q["reply_text"], q
    say(c, "haan")
    assert moved(live_stack) == [("credit", "mohan", 340), ("payment", "mohan", 200)]
    assert live_stack.balance("mohan") == 140


def test_Z28_two_entries_with_one_unknown_name_need_one_yes(live_stack):
    lv(live_stack, ramesh=1000)
    c = live_stack.session()
    q = say(c, "Ramesh ko 500 udhaar aur Vikram ko 200 udhaar")
    assert q["reason"] == "new_customer" and "Vikram" in q["reply_text"], q
    say(c, "haan")
    assert moved(live_stack) == [("credit", "ramesh", 500), ("credit", "vikram", 200)]


def test_Z28_the_demo_script_over_the_session(live_stack):
    c = live_stack.session()
    for said, reply, ramesh in DEMO:
        r = say(c, said)
        assert r["reply_text"] == reply, f"demo step {said!r}: expected {reply!r}, got {r['reply_text']!r}"
        assert live_stack.balance("ramesh") == ramesh, f"demo step {said!r}: balance {live_stack.balance('ramesh')}"
    assert live_stack.balance("mohan") == 140
