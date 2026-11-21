"""Server findings of the third review (CONTRACT 1.16, 3.3 and 5.1, v1.4)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.pipeline import Pipeline, SessionState, text_fingerprint
from app.replies import Replier

from .conftest import _ev, apply_events, fake_nw

TODAY = date(2026, 11, 21)
R = Replier(fake_nw)
EN = R.with_lang("en")


def count_events(ledger) -> int:
    return ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def st(**kw) -> SessionState:
    return SessionState(session_id=kw.pop("session_id", "sess0001"), disclosed=True, **kw)


def question(reason, events, index=None, **extra):
    pending = {"reason": reason, "action": "append", "events": events}
    if index is not None:
        pending["index"] = index
    pending.update(extra.pop("pending_extra", {}))
    return {"status": "needs_clarification", "reason": reason, "pending": pending, **extra}


# ---- 1. the question is about the event at pending.index ---------------------------------------------------------
def test_new_customer_question_names_the_unknown_customer_not_the_first(pipeline, parser, ledger):
    ledger.create_customer("ramesh")
    events = [_ev("credit", "ramesh", 500, TODAY), _ev("credit", "vikram", 200, TODAY, new_customer=True)]
    parser.canned["q"] = question("new_customer", events, index=1, candidates=[])
    assert pipeline.run_turn(st(), "q").reply_text == "Vikram naya grahak hai. Khata banaun?"
    parser.canned["q"] = question("new_customer", events, candidates=[])  # no index: the marked event
    assert pipeline.run_turn(st(), "q").reply_text == "Vikram naya grahak hai. Khata banaun?"


def test_direction_question_names_the_clause_that_has_no_direction(pipeline, parser):
    events = [_ev("payment", "ramesh", 500, TODAY), {"customer": "sunita", "amount": 200, "date": TODAY.isoformat()}]
    parser.canned["q"] = question("ambiguous_direction", events, index=1)
    assert pipeline.run_turn(st(), "q").reply_text == "Sunita ne diye, ya Sunita ko udhaar?"
    parser.canned["q"] = question("ambiguous_direction", events)  # no index: the event without a kind
    assert pipeline.run_turn(st(), "q").reply_text == "Sunita ne diye, ya Sunita ko udhaar?"


def test_confirm_and_plausibility_questions_use_the_indexed_event(pipeline, parser):
    events = [_ev("credit", "ramesh", 500, TODAY), _ev("credit", "sunita", 60000, TODAY)]
    parser.canned["q"] = question("plausibility", events, index=1)
    assert pipeline.run_turn(st(), "q").reply_text == "Sunita ke ₹60,000, pakka?"  # several pending (1.17)
    c = {"type": "hearsay"}
    parser.canned["q"] = question("confirm_entry", [_ev("credit", "ramesh", 500, TODAY)], index=0, confirm=c,
                                  pending_extra={"confirm": c})
    assert pipeline.run_turn(st(), "q").reply_text == "Ramesh ke ₹500 udhaar likhun?"


def test_name_alone_uses_the_event_without_an_amount():
    events = [{"customer": "ramesh"}]
    assert R.clarification(question("missing_amount", events)).text == "Ramesh ka kya likhun?"


# ---- 2. new confirm types ----------------------------------------------------------------------------------------
def _confirm(ctype, events, index=None, **confirm):
    c = {"type": ctype, **confirm}
    return question("confirm_entry", events, index=index, confirm=c, pending_extra={"confirm": c})


def test_review_lists_every_entry(pipeline, parser, ledger):
    events = [_ev("credit", "ramesh", 500, TODAY), _ev("payment", "sunita", 200, TODAY)]
    parser.canned["q"] = _confirm("review", events)
    assert pipeline.run_turn(st(), "q").reply_text == "2 entry likhun: Ramesh ke ₹500 udhaar, Sunita se ₹200 jama?"
    assert pipeline.run_turn(st(lang="en"), "q").reply_text == \
        "Save 2 entries: ₹500 credit for Ramesh, ₹200 received from Sunita?"
    same = [_ev("credit", "ramesh", 340, TODAY), _ev("payment", "ramesh", 200, TODAY - timedelta(days=1))]
    parser.canned["q"] = _confirm("review", same)
    assert pipeline.run_turn(st(), "q").reply_text == "2 entry likhun: Ramesh ke ₹340 udhaar, kal ke ₹200 jama?"
    t = pipeline.run_turn(st(private=True), "q")
    assert "<340>" in t.speak_text  # a review states no balance: read aloud in private mode too
    assert count_events(ledger) == 0


def test_amend_confirmation_names_the_entry(pipeline, parser):
    parser.canned["q"] = _confirm("amend", [_ev("credit", "ramesh", 430, TODAY)], index=0, old=340, new=430)
    assert pipeline.run_turn(st(), "q").reply_text == "Ramesh ki ₹340 udhaar entry ₹430 kar doon?"
    assert pipeline.run_turn(st(lang="en"), "q").reply_text == "Change Ramesh's ₹340 credit entry to ₹430?"
    t = pipeline.run_turn(st(private=True), "q")
    assert "<340>" in t.speak_text and "<430>" in t.speak_text


def test_writeoff_of_an_explicit_amount(pipeline, parser):
    parser.canned["q"] = _confirm("writeoff", [_ev("writeoff", "ramesh", 200, TODAY)], balance=500)
    assert pipeline.run_turn(st(), "q").reply_text == "Ramesh ke ₹200 maaf karun?"
    assert pipeline.run_turn(st(lang="en"), "q").reply_text == "Write off ₹200 for Ramesh?"
    assert "<200>" in pipeline.run_turn(st(private=True), "q").speak_text  # no balance in it
    parser.canned["q"] = _confirm("writeoff", [_ev("writeoff", "ramesh", 500, TODAY)], balance=500)
    assert pipeline.run_turn(st(), "q").reply_text == "Ramesh ke ₹500 baaki hain. Poore maaf karun?"
    assert pipeline.run_turn(st(private=True), "q").speak_text == "स्क्रीन पर देखिए। हाँ या नहीं बोलिए।"


# ---- 3. a non-answer turn keeps the question open and asks it again ---------------------------------------------
@pytest.fixture
def clock():
    return {"t": datetime(2026, 11, 21, 12, 0).astimezone()}


@pytest.fixture
def timed(ledger, settings, parser, clock):
    return Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw, now=lambda: clock["t"])


def test_non_answer_turns_repeat_the_open_question(timed, parser, clock):
    s = st()
    c = {"type": "hearsay"}
    parser.canned["q"] = _confirm("hearsay", [_ev("credit", "ramesh", 250, TODAY)], index=0)
    first = timed.run_turn(s, "q")
    assert first.reply_text == "Ramesh ke ₹250 udhaar likhun?"
    pending_before = dict(s.pending)
    for make, notice in ((timed.silence, "Kuch sunai nahi diya."), (timed.empty_transcript, "Samajh nahi aaya."),
                         (timed.too_long, "Bahut lamba ho gaya."), (timed.upstream_failure, "Network mein dikkat hai.")):
        clock["t"] += timedelta(seconds=10)
        t = make(s)
        assert t.status == "needs_clarification" and t.reason == "confirm_entry", make.__name__
        assert t.reply_text == f"{notice} Ramesh ke ₹250 udhaar likhun?"
        assert len(t.reply_text.split()) <= 12
        assert t.confirm == c and t.question == first.question and t.message(2)["confirm"] == c
        assert s.pending == pending_before  # not a failed attempt
    # The 60-second clock was not restarted: 40 s have passed, 25 more expire the question.
    clock["t"] += timedelta(seconds=25)
    t = timed.silence(s)
    assert t.status == "rejected" and t.reply_text == "Kuch sunai nahi diya. Dobara boliye." and s.pending is None


def test_repeated_question_keeps_candidates_and_private_speech(timed, parser, ledger):
    c1 = ledger.create_customer("ramesh", tags=["chai wale"])
    c2 = ledger.create_customer("ramesh", tags=["gali wale"])
    cands = [{"id": c1["id"], "name": "ramesh", "tags": ["chai wale"]},
             {"id": c2["id"], "name": "ramesh", "tags": ["gali wale"]}]
    parser.canned["q"] = question("same_name", [{"customer": "ramesh", "kind": "credit", "amount": 200}],
                                  candidates=cands)
    s = st()
    timed.run_turn(s, "q")
    t = timed.silence(s)
    assert t.reply_text == "Kuch sunai nahi diya. Kaunse Ramesh: chai wale ya gali wale?"
    assert [c["id"] for c in t.candidates] == [c1["id"], c2["id"]]
    apply_events(ledger, [_ev("credit", "ramesh", 1, TODAY, customer_id=c1["id"])])
    parser.canned["p"] = _confirm("settle", [_ev("payment", "ramesh", 341, TODAY, customer_id=c1["id"])],
                                  balance=341)
    p = st(session_id="priv", private=True)
    timed.run_turn(p, "p")
    again = timed.upstream_failure(p)
    assert again.speak_text.endswith("स्क्रीन पर देखिए। हाँ या नहीं बोलिए।") and "341" in again.reply_text


def test_without_a_question_the_notice_is_alone(timed):
    t = timed.silence(st())
    assert t.status == "rejected" and t.reply_text == "Kuch sunai nahi diya. Dobara boliye."


async def test_silence_during_a_question_over_the_socket(server, fake_gnani):
    import json

    import websockets

    from .test_session import AUDIO, hello, is_type, of, recv_until

    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "text", "text": "ramesh 340"}))
        await recv_until(ws, is_type("audio_end", turn_id=1))
        fake_gnani.speech = False
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=2))
        r = of(msgs, "result")[0]
        assert r["status"] == "needs_clarification" and r["reason"] == "ambiguous_direction"
        assert r["reply_text"] == "Kuch sunai nahi diya. Ramesh ne diye, ya Ramesh ko udhaar?"
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))  # a press under 0.5 s changes nothing
        await ws.send(bytes(1000))
        await ws.send(json.dumps({"type": "end"}))
        assert (await recv_until(ws, is_type("result")))[-1]["action"] == "none"
        await ws.send(json.dumps({"type": "text", "text": "udhaar"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=4))
        assert of(msgs, "result")[0]["status"] == "ok"


# ---- 4. a replay never shows a question that is no longer open ------------------------------------------------------
def test_replayed_old_question_is_cancelled_and_leaves_the_open_one(pipeline, parser, ledger):
    s = st()
    q1 = pipeline.run_turn(s, "ramesh 340", utt_id="u1")
    assert q1.status == "needs_clarification"
    again = pipeline.run_turn(s, "ramesh 340", utt_id="u1")  # still the open question: replayed
    assert again.duplicate and again.status == "needs_clarification"
    parser.canned["nahi"] = {"status": "rejected", "reason": "cancelled"}
    pipeline.run_turn(s, "nahi", utt_id="u2")
    parser.canned["sunita 200"] = question("ambiguous_direction",
                                           [{"customer": "sunita", "amount": 200, "date": TODAY.isoformat()}])
    pipeline.run_turn(s, "sunita 200", utt_id="u3")
    open_now = dict(s.pending)
    stale = pipeline.run_turn(s, "ramesh 340", utt_id="u1")
    assert stale.status == "rejected" and stale.reason == "cancelled"
    assert stale.reply_text == "Theek hai, entry nahi ki." and stale.question is None
    assert s.pending == open_now and s.asked["utt_id"] == "u3"
    assert count_events(ledger) == 0


# ---- 5. replace wording only for a whole replacement entry ----------------------------------------------------------
def test_unclear_correction_wording_unless_a_whole_new_entry(pipeline, parser, ledger):
    s = st()
    pipeline.run_turn(s, "ramesh ka 340 udhaar")
    rid = ledger.find_customer(key="ramesh")["id"]
    same = question("unclear_correction", [_ev("credit", "ramesh", 340, TODAY, customer_id=rid)],
                    pending_extra={"action": "amend"})
    parser.canned["nahi 340"] = same
    assert pipeline.run_turn(s, "nahi 340").reply_text == "Sahi amount boliye, ya hata do boliye."
    parser.canned["amount galat hai"] = question("unclear_correction", [], pending_extra={"action": "amend"})
    assert pipeline.run_turn(s, "amount galat hai").reply_text == "Sahi amount boliye, ya hata do boliye."
    whole = question("unclear_correction", [_ev("payment", "sunita", 100, TODAY)], pending_extra={"action": "amend"})
    parser.canned["nahi sunita ne 100 diye"] = whole
    assert pipeline.run_turn(s, "nahi sunita ne 100 diye").reply_text == "Pichli entry hata kar yeh likhoon?"


# ---- 6. fingerprint ignores punctuation ------------------------------------------------------------------------------
def test_fingerprint_ignores_punctuation_case_and_spacing(pipeline, ledger):
    assert text_fingerprint("Ramesh ka 340 udhaar.") == text_fingerprint("ramesh  ka 340 udhaar")
    assert text_fingerprint("Nahi, 430!") == text_fingerprint("nahi 430")
    assert text_fingerprint("रमेश का ३४० उधार।") == text_fingerprint("रमेश का ३४० उधार")
    assert text_fingerprint("ramesh ka 340 udhaar") != text_fingerprint("ramesh ka 430 udhaar")
    s = st()
    pipeline.run_turn(s, "ramesh ka 340 udhaar", utt_id="p-1")
    again = pipeline.run_turn(s, "Ramesh ka 340 udhaar.", utt_id="p-1")
    assert again.duplicate and again.error_code is None and count_events(ledger) == 1


# ---- 7. which-entry and same-name questions name what they are about ------------------------------------------------
def test_which_entry_names_customers_when_entries_look_alike():
    cands = [{"id": 1, "kind": "credit", "amount": 200, "customer": "ramesh"},
             {"id": 2, "kind": "credit", "amount": 200, "customer": "sunita"}]
    q = question("unclear_correction", [], candidates=cands, pending_extra={"action": "amend"})
    assert R.clarification(q).text == "Kaunsi entry: Ramesh ₹200 udhaar ya Sunita ₹200 udhaar?"
    assert EN.clarification(q).text == "Which entry: Ramesh ₹200 credit or Sunita ₹200 credit?"
    cands[1].update(amount=150, kind="payment")
    assert R.clarification(q).text == "Kaunsi entry: ₹200 udhaar ya ₹150 jama?"


def test_same_name_in_a_two_clause_sentence_names_the_clause_amount(pipeline, parser, ledger):
    c1 = ledger.create_customer("ramesh", tags=["chai wale"])
    c2 = ledger.create_customer("ramesh", tags=["gali wale"])
    sunita = ledger.create_customer("sunita")
    cands = [{"id": c1["id"], "name": "ramesh", "tags": ["chai wale"]},
             {"id": c2["id"], "name": "ramesh", "tags": ["gali wale"]}]
    events = [_ev("payment", "sunita", 100, TODAY, customer_id=sunita["id"]), _ev("credit", "ramesh", 200, TODAY)]
    parser.canned["q"] = question("same_name", events, index=1, candidates=cands)
    assert pipeline.run_turn(st(), "q").reply_text == "Kaunse Ramesh, ₹200 udhaar wale: chai wale ya gali wale?"
    assert pipeline.run_turn(st(lang="en"), "q").reply_text == \
        "Which Ramesh, for ₹200 credit: chai wale or gali wale?"
    parser.canned["q"] = question("same_name", [_ev("credit", "ramesh", 200, TODAY)], candidates=cands)
    assert pipeline.run_turn(st(), "q").reply_text == "Kaunse Ramesh: chai wale ya gali wale?"


def test_short_notices_in_english(timed, parser):
    parser.canned["q"] = _confirm("hearsay", [_ev("credit", "ramesh", 250, TODAY)], index=0)
    s = st(lang="en")
    timed.run_turn(s, "q")
    assert timed.silence(s).reply_text == "I could not hear anything. Add ₹250 credit for Ramesh?"
    assert timed.upstream_failure(s).reply_text == "Network problem. Add ₹250 credit for Ramesh?"
