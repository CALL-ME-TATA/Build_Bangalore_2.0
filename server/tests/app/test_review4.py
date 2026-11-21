"""Questions in sentences with several entries (CONTRACT 1.17 and the 5.1 rows of v1.5)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.pipeline import Pipeline, SessionState
from app.replies import Replier

from .conftest import _ev, fake_nw

TODAY = date(2026, 11, 21)
R = Replier(fake_nw)
EN = R.with_lang("en")
REAL = Replier()  # the real number_to_words, for spoken-form checks


def st(**kw) -> SessionState:
    return SessionState(session_id=kw.pop("session_id", "sess0001"), disclosed=True, **kw)


def ask(reason, events, index=None, confirm=None, **extra):
    pending = {"reason": reason, "action": "append", "events": events}
    if index is not None:
        pending["index"] = index
    if confirm is not None:
        pending["confirm"] = confirm
    out = {"status": "needs_clarification", "reason": reason, "pending": pending, **extra}
    if confirm is not None:
        out["confirm"] = confirm
    return out


def count_events(ledger) -> int:
    return ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


# ---- 1. named missing-amount and plausibility questions ---------------------------------------------------------
def test_missing_amount_names_the_customer_when_several_entries_are_pending():
    events = [_ev("credit", "ramesh", 200, TODAY), {"kind": "payment", "customer": "mohan", "date": TODAY.isoformat()}]
    q = ask("missing_amount", events, index=1)
    assert R.clarification(q).text == "Mohan ke kitne rupaye?"
    assert EN.clarification(q).text == "How many rupees for Mohan?"
    assert R.clarification(ask("missing_amount", events)).text == "Mohan ke kitne rupaye?"  # the event lacking it
    assert REAL.clarification(q).speak == "Mohan के कितने रुपये?"


def test_missing_amount_wording_unchanged_for_one_event_or_no_customer():
    assert R.clarification(ask("missing_amount", [{"kind": "credit", "customer": "ramesh"}])).text == "Kitne rupaye?"
    two_unnamed = [_ev("credit", "ramesh", 200, TODAY), {"kind": "credit", "date": TODAY.isoformat()}]
    assert R.clarification(ask("missing_amount", two_unnamed, index=1)).text == "Kitne rupaye?"
    assert EN.clarification(ask("missing_amount", [{"kind": "credit"}])).text == "How many rupees?"


def test_plausibility_names_the_customer_of_the_indexed_event():
    events = [_ev("credit", "ramesh", 99000, TODAY), _ev("credit", "mohan", 88000, TODAY)]
    assert R.clarification(ask("plausibility", events, index=0)).text == "Ramesh ke ₹99,000, pakka?"
    assert R.clarification(ask("plausibility", events, index=1)).text == "Mohan ke ₹88,000, pakka?"
    assert EN.clarification(ask("plausibility", events, index=1)).text == "₹88,000 for Mohan, are you sure?"
    speak = REAL.clarification(ask("plausibility", events, index=1)).speak
    assert speak.startswith("Mohan के ") and speak.endswith("रुपये, पक्का?") and not any(c.isdigit() for c in speak)
    # Without an index the largest amount is the one in doubt.
    assert R.clarification(ask("plausibility", events)).text == "Ramesh ke ₹99,000, pakka?"
    assert R.clarification(ask("plausibility", [_ev("credit", "ramesh", 99000, TODAY)])).text == "₹99,000, pakka?"


def test_named_questions_stay_within_twelve_words_and_are_not_cached():
    for r in (R, EN):
        for reply in (r.missing_amount_for("Ramesh Chopra"), r.plausibility_for("Ramesh Chopra", 1250000)):
            assert len(reply.text.split()) <= 12, reply.text
    from app.replies import fixed_replies

    fixed = {x.speak for x in fixed_replies(R)}
    assert R.missing_amount().speak in fixed and R.missing_amount_for("Ramesh").speak not in fixed


# ---- 2. balance confirmations use pending.index ------------------------------------------------------------------
TWO_PAYMENTS = [_ev("payment", "ramesh", 500, TODAY), _ev("payment", "mohan", 200, TODAY)]


@pytest.mark.parametrize("ctype,events,confirm,hi,en", [
    ("overpayment", TWO_PAYMENTS, {"balance": 140},
     "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?", "Mohan owes only ₹140. Record ₹200 anyway?"),
    ("overpayment", TWO_PAYMENTS, {"balance": 0},
     "Mohan ka kuch baaki nahi. ₹200 advance likhun?", "Mohan owes nothing. Record ₹200 as an advance?"),
    ("settle", [_ev("credit", "ramesh", 500, TODAY), _ev("payment", "mohan", 340, TODAY)], {"balance": 340},
     "Mohan ke ₹340 baaki hain. Poore jama likhun?", "Mohan owes ₹340. Record all of it as received?"),
    ("half", [_ev("credit", "ramesh", 500, TODAY), _ev("payment", "mohan", 170, TODAY)], {"balance": 340},
     "Aadha yaani ₹170. Mohan se jama likhun?", "Half is ₹170. Record it as received from Mohan?"),
    ("writeoff", [_ev("credit", "ramesh", 200, TODAY), _ev("writeoff", "mohan", 340, TODAY)], {"balance": 340},
     "Mohan ke ₹340 baaki hain. Poore maaf karun?", "Mohan owes ₹340. Write all of it off?"),
    ("writeoff", [_ev("credit", "ramesh", 200, TODAY), _ev("writeoff", "mohan", 50, TODAY)], {"balance": 340},
     "Mohan ke ₹50 maaf karun?", "Write off ₹50 for Mohan?"),
    ("roundoff", [_ev("credit", "ramesh", 500, TODAY), _ev("writeoff", "mohan", 5, TODAY)], {"balance": 345},
     "Mohan ke ₹345 baaki hain. ₹5 chhod doon?", "Mohan owes ₹345. Drop ₹5?"),
])
def test_balance_confirmations_are_built_from_the_indexed_event(pipeline, parser, ctype, events, confirm, hi, en):
    parser.canned["q"] = ask("confirm_entry", events, index=1, confirm={"type": ctype, **confirm})
    assert pipeline.run_turn(st(), "q").reply_text == hi
    assert pipeline.run_turn(st(lang="en"), "q").reply_text == en


# ---- 3. a chain of questions in one utterance --------------------------------------------------------------------
class Chain:
    """A stub parser for `Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar` (1.17): one question per doubtful event,
    asked in turn, saved after the last yes. Counts failed attempts per question in `pending.attempts`."""

    EVENTS = [_ev("credit", "ramesh", 99000, TODAY), _ev("credit", "mohan", 88000, TODAY)]

    def __init__(self):
        self.calls = []

    def __call__(self, utterance, *, today, ctx=None):
        self.calls.append({"utterance": utterance, "ctx": ctx})
        pending = (ctx or {}).get("pending")
        if utterance == "sentence":
            return ask("plausibility", self.EVENTS, index=0)
        if pending is None:
            return {"status": "rejected", "reason": "not_ledger"}
        if utterance == "haan" and pending.get("index") == 0:
            return ask("plausibility", self.EVENTS, index=1)
        if utterance == "haan" and pending.get("index") == 1:
            return {"status": "ok", "action": "append", "events": self.EVENTS}
        if utterance == "nahi":
            return {"status": "rejected", "reason": "cancelled"}
        failed = dict(pending, attempts=pending.get("attempts", 0) + 1)
        return {"status": "needs_clarification", "reason": "plausibility", "pending": failed}


@pytest.fixture
def chain_pipe(ledger, settings):
    clock = {"t": datetime(2026, 11, 21, 12, 0).astimezone()}
    parser = Chain()
    pipe = Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw, now=lambda: clock["t"])
    return pipe, parser, clock


def test_a_chain_of_questions_saves_only_after_the_last_yes(chain_pipe, ledger):
    pipe, parser, clock = chain_pipe
    s = st()
    first = pipe.run_turn(s, "sentence")
    assert first.reply_text == "Ramesh ke ₹99,000, pakka?" and count_events(ledger) == 0
    clock["t"] += timedelta(seconds=50)
    second = pipe.run_turn(s, "haan")
    assert second.status == "needs_clarification" and second.reply_text == "Mohan ke ₹88,000, pakka?"
    assert parser.calls[-1]["ctx"]["pending"]["index"] == 0  # the yes answered the first question
    assert s.pending["index"] == 1 and count_events(ledger) == 0
    # The 60-second expiry restarts with the new question: 50 s after it the question is still open.
    clock["t"] += timedelta(seconds=50)
    t = pipe.silence(s)
    assert t.reply_text == "Kuch sunai nahi diya. Mohan ke ₹88,000, pakka?"  # the current question, not the first
    attempt = pipe.run_turn(s, "kuch aur")
    assert attempt.status == "needs_clarification" and s.pending["attempts"] == 1
    saved = pipe.run_turn(s, "haan")
    assert saved.status == "ok" and parser.calls[-1]["ctx"]["pending"]["index"] == 1
    assert count_events(ledger) == 2 and s.pending is None


def test_attempts_are_counted_per_question(chain_pipe):
    pipe, parser, _ = chain_pipe
    s = st()
    pipe.run_turn(s, "sentence")
    pipe.run_turn(s, "kuch aur")
    assert s.pending["attempts"] == 1 and s.pending["index"] == 0
    pipe.run_turn(s, "haan")  # answers question 1 (the stub's yes ignores the attempt count)
    assert "attempts" not in s.pending and s.pending["index"] == 1  # the next question starts again


def test_a_chain_expires_sixty_seconds_after_the_latest_question(chain_pipe, ledger):
    pipe, parser, clock = chain_pipe
    s = st()
    pipe.run_turn(s, "sentence")
    pipe.run_turn(s, "haan")
    clock["t"] += timedelta(seconds=61)
    t = pipe.run_turn(s, "haan")
    assert "pending" not in parser.calls[-1]["ctx"] and t.status == "rejected" and count_events(ledger) == 0


def test_no_in_the_middle_of_a_chain_saves_nothing(chain_pipe, ledger):
    pipe, _, _ = chain_pipe
    s = st()
    pipe.run_turn(s, "sentence")
    pipe.run_turn(s, "haan")
    assert pipe.run_turn(s, "nahi").reply_text == "Theek hai, entry nahi ki."
    assert count_events(ledger) == 0 and s.pending is None


def test_private_mode_hides_the_balance_question_inside_a_chain(pipeline, parser, ledger):
    events = [_ev("credit", "ramesh", 99000, TODAY), _ev("payment", "mohan", 200, TODAY)]
    parser.canned["sentence"] = ask("plausibility", events, index=0)
    parser.canned["haan"] = ask("confirm_entry", events, index=1, confirm={"type": "overpayment", "balance": 140})
    s = st(private=True)
    first = pipeline.run_turn(s, "sentence")
    assert "<99000>" in first.speak_text  # an amount check states no balance
    second = pipeline.run_turn(s, "haan")
    assert second.reply_text == "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?"
    assert second.speak_text == "स्क्रीन पर देखिए। हाँ या नहीं बोलिए।"
    again = pipeline.silence(s)
    assert again.speak_text == "कुछ सुनाई नहीं दिया। स्क्रीन पर देखिए। हाँ या नहीं बोलिए।"
    assert "₹140" in again.reply_text and count_events(ledger) == 0


# ---- 4. a write-off among several entries -----------------------------------------------------------------------
MIXED = [{"kind": "credit", "customer": "Ramesh", "amount": 200, "date": TODAY.isoformat()},
         {"kind": "writeoff", "customer": "Mohan", "amount": 50, "date": TODAY.isoformat()}]


def test_several_entries_with_a_writeoff_saved_and_reviewed():
    assert R.saved(MIXED, TODAY).text == "2 entry likhi: Ramesh ke ₹200 udhaar, Mohan ke ₹50 maaf."
    assert EN.saved(MIXED, TODAY).text == "2 entries: ₹200 credit for Ramesh, and ₹50 written off for Mohan."
    assert R.confirm_entries(MIXED, TODAY).text == "2 entry likhun: Ramesh ke ₹200 udhaar, Mohan ke ₹50 maaf?"
    assert EN.confirm_entries(MIXED, TODAY).text == "Save 2 entries: ₹200 credit for Ramesh, ₹50 written off for Mohan?"
    speak = REAL.saved(MIXED, TODAY).speak
    assert "Mohan के" in speak and "माफ़" in speak and not any(c.isdigit() for c in speak)


def test_review_question_with_a_writeoff_through_the_pipeline(pipeline, parser):
    events = [_ev("credit", "ramesh", 200, TODAY), _ev("writeoff", "mohan", 50, TODAY)]
    parser.canned["q"] = ask("confirm_entry", events, confirm={"type": "review"})
    assert pipeline.run_turn(st(), "q").reply_text == "2 entry likhun: Ramesh ke ₹200 udhaar, Mohan ke ₹50 maaf?"
