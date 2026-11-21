"""CONTRACT v1.2, group 1: parser context, replies per reason, result fields, write-offs, idempotency, expiry."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.config import Settings
from app.pipeline import Pipeline, SessionState
from app.replies import Replier

from .conftest import _ev, apply_events, fake_nw

TODAY = date(2026, 11, 21)
R = Replier(fake_nw)
EN = R.with_lang("en")


def count_events(ledger) -> int:
    return ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def count_utterances(ledger) -> int:
    return ledger.conn.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]


class Clock:
    def __init__(self, start: datetime):
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def disclosed(state):
    state.disclosed = True
    return state


@pytest.fixture
def clock():
    return Clock(datetime(2026, 11, 21, 12, 0).astimezone())


@pytest.fixture
def timed(ledger, settings, parser, clock):
    return Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw, now=clock)


# ---- 1. parser context ------------------------------------------------------------------------------------------
def test_ctx_carries_v12_fields(pipeline, disclosed, parser, ledger):
    pipeline.run_turn(disclosed, "ramesh ka 340 udhaar")
    apply_events(ledger, [_ev("credit", "ramesh", 200, TODAY), _ev("credit", "ramesh", 300, TODAY)])
    pipeline.run_turn(disclosed, "ramesh ka total")
    ctx = parser.calls[-1]["ctx"]
    ramesh = [c for c in ctx["customers"] if c["name"] == "ramesh"][0]
    assert ramesh["balance"] == 840 and ramesh["usual"] == 300  # median of 340, 200, 300
    assert ctx["limits"] == {"confirm_above": 50000, "confirm_below": 10, "max_amount": 9999999, "carry_s": 60,
                             "duplicate_s": 30, "confirm_new_customer": True, "strict": True}
    assert ctx["confusables"] == {}
    assert ctx["last_turn"]["action"] == "append" and ctx["last_turn"]["customer"] == "ramesh"
    assert ctx["last_turn"]["customer_id"] == ramesh["id"] and ctx["last_turn"]["age_s"] >= 0


def test_usual_needs_three_credits(pipeline, disclosed, parser, ledger):
    apply_events(ledger, [_ev("credit", "sunita", 100, TODAY), _ev("credit", "sunita", 900, TODAY)])
    pipeline.run_turn(disclosed, "aaj ka hisaab")
    sunita = [c for c in parser.calls[-1]["ctx"]["customers"] if c["name"] == "sunita"][0]
    assert sunita["balance"] == 1000 and "usual" not in sunita


def test_limits_from_env():
    s = Settings.from_env({"MAX_AMOUNT": "500000", "CONFIRM_NEW_CUSTOMER": "0"})
    assert s.max_amount == 500000 and s.confirm_new_customer is False
    d = Settings.from_env({})
    assert d.max_amount == 9999999 and d.confirm_new_customer is True and d.tts_prewarm is True
    assert d.strict_save is True and Settings.from_env({"STRICT_SAVE": "0"}).strict_save is False


def test_last_turn_follows_each_kind_of_turn(timed, state, parser, clock, ledger):
    state.disclosed = True
    timed.run_turn(state, "ramesh ka 340 udhaar")
    clock.advance(5)
    timed.run_turn(state, "ramesh ka total")
    assert parser.calls[-1]["ctx"]["last_turn"] == {"action": "append", "customer": "ramesh",
                                                   "customer_id": ledger.find_customer(key="ramesh")["id"],
                                                   "age_s": 5}
    timed.run_turn(state, "ramesh 340")
    lt = parser.calls[-1]["ctx"]["last_turn"]
    assert lt["action"] == "query" and lt["customer"] == "ramesh"
    timed.run_turn(state, "aaj ka hisaab")
    assert parser.calls[-1]["ctx"]["last_turn"]["action"] == "question"
    timed.run_turn(state, "undo karo")
    assert parser.calls[-1]["ctx"]["last_turn"] == {"action": "query", "age_s": 0}  # summary: no single customer
    timed.run_turn(state, "kuch bhi")
    assert parser.calls[-1]["ctx"]["last_turn"]["action"] == "undo"
    timed.run_turn(state, "aaj ka hisaab")
    assert parser.calls[-1]["ctx"]["last_turn"]["action"] == "none"


# ---- 2. replies -------------------------------------------------------------------------------------------------
def test_A22_amount_past_number_words_is_too_large_and_saves_nothing(ledger, settings, parser, state):
    real = Pipeline(ledger, settings, parse=parser)  # the real nlu.speak.number_to_words
    t = real.run_turn(state, "Ramesh ka 999999999999 udhaar")
    assert t.status == "rejected" and t.reason == "too_large"
    assert t.reply_text.endswith("Itni badi rakam nahi likh sakta.")
    assert count_events(ledger) == 0 and ledger.find_customer(key="ramesh") is None


def test_A22_amount_above_max_amount_env_is_too_large(ledger, parser, state, tmp_path):
    s = Settings(ledger_db=str(tmp_path / "k.db"), max_amount=1000)
    pipe = Pipeline(ledger, s, parse=parser, number_to_words=fake_nw)
    state.disclosed = True
    parser.canned["big"] = {"status": "ok", "action": "append", "events": [_ev("credit", "ramesh", 1001, TODAY)]}
    assert pipe.run_turn(state, "big").reason == "too_large" and count_events(ledger) == 0


def test_unexpected_parser_exception_is_rejected_reply(pipeline, disclosed, parser, ledger):
    def boom(today, ctx):
        raise RuntimeError("parser bug with Ramesh 340")

    parser.canned["boom"] = boom
    t = pipeline.run_turn(disclosed, "boom")
    assert t.status == "rejected" and t.reply_text == "Maaf kijiye, samajh nahi aaya. Dobara boliye."
    assert count_events(ledger) == 0


def test_reply_failure_rolls_back_the_entry(pipeline, disclosed, ledger, monkeypatch):
    def broken(*a, **k):
        raise ValueError("cannot voice")

    monkeypatch.setattr(Replier, "saved", broken)
    t = pipeline.run_turn(disclosed, "ramesh ka 340 udhaar")
    assert t.status == "rejected" and "samajh nahi aaya" in t.reply_text
    assert count_events(ledger) == 0 and ledger.find_customer(key="ramesh") is None


def test_bad_event_from_parser_is_rejected_with_nothing_saved(pipeline, disclosed, parser, ledger):
    parser.canned["bad"] = {"status": "ok", "action": "append",
                            "events": [_ev("credit", "ramesh", 100, TODAY), _ev("payment", "ramesh", 0, TODAY)]}
    assert pipeline.run_turn(disclosed, "bad").status == "rejected" and count_events(ledger) == 0


@pytest.mark.parametrize("utterance,hi,en", [
    ("ramesh kal dega", "Yeh baad ki baat hai, abhi kuch nahi likha.", "That has not happened yet, so nothing was saved."),
    ("ramesh ne nahi diya", "Theek hai, kuch nahi likha.", "Okay, nothing was saved."),
    ("kiraya 500 diya", "Yeh udhaar entry nahi hai, isliye nahi likha.",
     "That is not a credit entry, so nothing was saved."),
    ("ek crore crore", "Itni badi rakam nahi likh sakta.", "That amount is too large to save."),
    ("haan", "Kis baare mein?", "About what?"),
    ("minus 50", "Maaf kijiye, samajh nahi aaya. Dobara boliye.", "Sorry, I did not understand. Please say it again."),
    ("kuch bhi", "Maaf kijiye, samajh nahi aaya. Dobara boliye.", "Sorry, I did not understand. Please say it again."),
])
def test_G01_B09_I01_A22_G06_rejection_reply_per_reason(pipeline, parser, utterance, hi, en):
    st = SessionState(session_id="s1", disclosed=True)
    assert pipeline.run_turn(st, utterance).reply_text == hi
    result = parser(utterance, today=TODAY, ctx={})
    result.pop("lang", None)
    parser.canned[utterance] = result
    st = SessionState(session_id="s2", disclosed=True, lang="en")
    assert pipeline.run_turn(st, utterance).reply_text == en


def test_D03_D09_D11_nothing_to_amend_undo_and_after_undo(pipeline, disclosed, ledger):
    assert pipeline.run_turn(disclosed, "nahi 430").reply_text == "Pehle koi entry nahi hai."
    assert pipeline.run_turn(disclosed, "undo karo").reply_text == "Undo karne ke liye kuch nahi hai."
    pipeline.run_turn(disclosed, "ramesh ka 340 udhaar")
    assert pipeline.run_turn(disclosed, "undo karo").reply_text.startswith("Pichli entry hata di")
    t = pipeline.run_turn(disclosed, "nahi 430")
    assert t.reply_text == "Woh entry hat chuki hai. Poori entry dobara boliye." and t.status == "rejected"
    disclosed.lang = "en"
    pipeline.run_turn(disclosed, "ramesh ka 340 udhaar")  # result lang "hi" switches back
    disclosed.lang = "en"
    pipeline.run_turn(disclosed, "undo karo")
    assert pipeline.run_turn(disclosed, "nahi 430").reply_text == \
        "That entry was removed. Please say the full entry again."
    assert count_events(ledger) == 4  # two credits and two reversals, nothing amended after an undo


def test_D11_ledger_nothing_after_undo_uses_removed_wording(pipeline, disclosed, parser, ledger):
    """A parser that still returns an amend after an undo finds nothing active and gets the D11 wording."""
    pipeline.run_turn(disclosed, "ramesh ka 340 udhaar")
    pipeline.run_turn(disclosed, "undo karo")
    parser.canned["nahi 999"] = {"status": "ok", "action": "amend", "target": "last",
                                 "events": [_ev("credit", "ramesh", 999, TODAY)]}
    assert pipeline.run_turn(disclosed, "nahi 999").reply_text.startswith("Woh entry hat chuki hai.")


def test_E14_J10_balance_no_entries_and_settled(pipeline, disclosed, ledger):
    pipeline.run_turn(disclosed, "ramesh ka 340 udhaar")
    pipeline.run_turn(disclosed, "undo karo")
    assert pipeline.run_turn(disclosed, "ramesh ka total").reply_text == "Ramesh ka koi hisaab nahi hai."
    apply_events(ledger, [_ev("credit", "ramesh", 100, TODAY), _ev("payment", "ramesh", 100, TODAY)])
    assert pipeline.run_turn(disclosed, "ramesh ka total").reply_text == "Ramesh ka hisaab barabar hai."
    disclosed.lang = "en"
    assert pipeline.run_turn(disclosed, "ramesh ka total").reply_text == "Ramesh's account is settled."


def test_unknown_customer_in_balance_query(pipeline, disclosed, parser):
    parser.canned["x"] = {"status": "ok", "action": "query", "query": {"type": "balance", "customer": "zubin"}}
    assert pipeline.run_turn(disclosed, "x").reply_text == "Zubin ka khata nahi mila."


def test_E09_new_customer_question_is_built_from_the_result(pipeline, disclosed, ledger):
    t = pipeline.run_turn(disclosed, "mohan ko 200 udhaar")
    assert t.status == "needs_clarification" and t.reason == "new_customer"
    assert t.reply_text == "Mohan naya grahak hai. Khata banaun?" and t.question == t.reply_text
    assert "Mohan नया ग्राहक है" in t.speak_text and count_events(ledger) == 0
    t = pipeline.run_turn(disclosed, "haan")
    assert t.status == "ok" and t.reply_text.startswith("Naya khata Mohan.")
    assert ledger.balance(ledger.find_customer(key="mohan")["id"]) == 200


def test_E09_new_customer_with_close_names_and_candidates(pipeline, disclosed, parser, ledger):
    c = ledger.create_customer("rakesh", tags=["doodh wale"])
    ev = _ev("credit", "rakes", 100, TODAY, new_customer=True)
    parser.canned["rakes ko 100 udhaar"] = {
        "status": "needs_clarification", "reason": "new_customer", "question": "roman",
        "candidates": [{"id": c["id"], "name": "rakesh", "tags": ["doodh wale"]}],
        "pending": {"reason": "new_customer", "action": "append", "events": [ev],
                    "candidates": [{"id": c["id"], "name": "rakesh", "tags": ["doodh wale"]}]}}
    t = pipeline.run_turn(disclosed, "rakes ko 100 udhaar")
    assert t.reply_text == "Rakes naya grahak hai, ya Rakesh?"
    assert t.message(1)["candidates"] == [{"id": c["id"], "display": "Rakesh", "tags": ["doodh wale"]}]
    disclosed.lang = "en"
    assert pipeline.run_turn(disclosed, "rakes ko 100 udhaar").reply_text == "Is Rakes a new customer, or Rakesh?"


def test_E12_name_alone_and_H03_quantity(pipeline, disclosed, ledger):
    apply_events(ledger, [_ev("credit", "ramesh", 10, TODAY)])
    assert pipeline.run_turn(disclosed, "ramesh").reply_text == "Ramesh ka kya likhun?"
    assert pipeline.run_turn(disclosed, "ramesh ko 2 kilo chawal udhaar").reply_text == "Kitne ka?"
    disclosed.lang = "en"
    assert pipeline.run_turn(disclosed, "ramesh").reply_text == "What should I note for Ramesh?"
    assert pipeline.run_turn(disclosed, "ramesh ko 2 kilo chawal udhaar").reply_text == "For how many rupees?"


def _confirm(ctype, events, **confirm):
    c = {"type": ctype, **confirm}
    return {"status": "needs_clarification", "reason": "confirm_entry", "confirm": c, "question": "roman fallback",
            "pending": {"reason": "confirm_entry", "action": "append", "events": events, "confirm": c}}


@pytest.mark.parametrize("ctype,events,confirm,hi,en", [
    ("computed", [_ev("credit", "ramesh", 300, TODAY)], {"bill": 500, "paid": 200},
     "Ramesh ke ₹300 udhaar likhun?", "Add ₹300 credit for Ramesh?"),
    ("hearsay", [_ev("payment", "ramesh", 500, TODAY - timedelta(days=1))], {},
     "Ramesh se kal ke ₹500 jama likhun?", "Record ₹500 received from Ramesh, dated yesterday?"),
    ("settle", [_ev("payment", "ramesh", 340, TODAY)], {"balance": 340},
     "Ramesh ke ₹340 baaki hain. Poore jama likhun?", "Ramesh owes ₹340. Record all of it as received?"),
    ("half", [_ev("payment", "ramesh", 170, TODAY)], {"balance": 340},
     "Aadha yaani ₹170. Ramesh se jama likhun?", "Half is ₹170. Record it as received from Ramesh?"),
    ("writeoff", [_ev("writeoff", "ramesh", 340, TODAY)], {"balance": 340},
     "Ramesh ke ₹340 baaki hain. Poore maaf karun?", "Ramesh owes ₹340. Write all of it off?"),
    ("roundoff", [_ev("writeoff", "ramesh", 5, TODAY)], {"balance": 345},
     "Ramesh ke ₹345 baaki hain. ₹5 chhod doon?", "Ramesh owes ₹345. Drop ₹5?"),
    ("overpayment", [_ev("payment", "ramesh", 500, TODAY)], {"balance": 340},
     "Ramesh ke sirf ₹340 baaki hain. ₹500 hi likhun?", "Ramesh owes only ₹340. Record ₹500 anyway?"),
    ("overpayment", [_ev("payment", "ramesh", 500, TODAY)], {"balance": 0},
     "Ramesh ka kuch baaki nahi. ₹500 advance likhun?", "Ramesh owes nothing. Record ₹500 as an advance?"),
    ("duplicate", [_ev("credit", "ramesh", 340, TODAY)], {},
     "Yeh entry abhi likhi hai. Ek aur likhun?", "I just saved this entry. Save another one?"),
    ("someday", [_ev("credit", "ramesh", 340, TODAY)], {}, "roman fallback", "roman fallback"),
])
def test_H01_H09_K01_confirm_entry_questions(pipeline, parser, ledger, ctype, events, confirm, hi, en):
    parser.canned["c"] = _confirm(ctype, events, **confirm)
    for lang, want in (("hi", hi), ("en", en)):
        st = SessionState(session_id="s" + lang, disclosed=True, lang=lang)
        t = pipeline.run_turn(st, "c")
        assert t.reply_text == want and t.status == "needs_clarification"
        assert t.confirm["type"] == ctype and t.message(1)["confirm"]["type"] == ctype
        assert st.pending["reason"] == "confirm_entry"
    assert count_events(ledger) == 0


def test_unknown_reason_falls_back_to_parser_question(pipeline, disclosed, parser):
    parser.canned["q"] = {"status": "needs_clarification", "reason": "brand_new", "question": "Kya matlab?",
                          "pending": {"reason": "brand_new", "events": []}}
    assert pipeline.run_turn(disclosed, "q").reply_text == "Kya matlab?"


def test_new_customer_question_ignores_roman_question_string(pipeline, disclosed):
    t = pipeline.run_turn(disclosed, "mohan ko 200 udhaar")
    assert "(roman)" not in t.reply_text


# ---- 3. result message additions --------------------------------------------------------------------------------
def test_result_carries_query_and_balances(pipeline, disclosed, ledger, parser):
    t = pipeline.run_turn(disclosed, "ramesh ka 340 udhaar")
    rid = ledger.find_customer(key="ramesh")["id"]
    assert t.message(1)["balances"] == [{"customer_id": rid, "display": "Ramesh", "balance": 340}]
    t = pipeline.run_turn(disclosed, "ramesh ka total")
    msg = t.message(2)
    assert msg["query"] == {"type": "balance", "customer_id": rid} and "balances" not in msg
    parser.canned["w"] = {"status": "ok", "action": "query", "query": {"type": "daily_summary", "period": "this_week"}}
    assert pipeline.run_turn(disclosed, "w").message(3)["query"] == {"type": "daily_summary", "period": "this_week"}
    t = pipeline.run_turn(disclosed, "nahi 430")
    assert t.message(4)["balances"] == [{"customer_id": rid, "display": "Ramesh", "balance": 430}]


def test_result_candidates_for_numbers(pipeline, disclosed, parser):
    parser.canned["c"] = {"status": "needs_clarification", "reason": "confusable_number", "candidates": [340, 400],
                          "pending": {"reason": "confusable_number", "action": "append", "events": [],
                                      "candidates": [340, 400]}}
    t = pipeline.run_turn(disclosed, "c")
    assert t.message(1)["candidates"] == [340, 400] and t.reply_text == "₹340 ya ₹400?"


# ---- 4. write-offs ----------------------------------------------------------------------------------------------
def test_H06_writeoff_saved_stored_as_payment_and_left_out_of_totals(pipeline, disclosed, ledger):
    apply_events(ledger, [_ev("credit", "ramesh", 340, TODAY)])
    pipeline.run_turn(disclosed, "sunita ne 150 diye")
    q = pipeline.run_turn(disclosed, "ramesh ka baaki chhod do")
    assert q.reply_text == "Ramesh ke ₹340 baaki hain. Poore maaf karun?" and count_events(ledger) == 2
    t = pipeline.run_turn(disclosed, "haan")
    assert t.status == "ok" and t.reply_text == "Ramesh ke ₹340 maaf kiye."
    assert t.entries[0]["kind"] == "writeoff"
    row = ledger.conn.execute("SELECT kind, adjustment FROM events ORDER BY id DESC LIMIT 1").fetchone()
    assert (row["kind"], row["adjustment"]) == ("payment", "writeoff")
    rid = ledger.find_customer(key="ramesh")["id"]
    assert ledger.balance(rid) == 0
    today = pipeline.now().date()
    assert ledger.payment_total(today) == 150  # the write-off is not a payment
    assert ledger.recent_entries()[0]["kind"] == "writeoff"
    disclosed.lang = "en"
    assert EN.saved([dict(t.entries[0], customer="Ramesh")], today).text == "Wrote off ₹340 for Ramesh."


def test_writeoff_can_be_amended_and_undone(pipeline, disclosed, parser, ledger):
    parser.canned["w"] = {"status": "ok", "action": "append", "events": [_ev("writeoff", "ramesh", 50, TODAY)]}
    apply_events(ledger, [_ev("credit", "ramesh", 340, TODAY)])
    pipeline.run_turn(disclosed, "w")
    t = pipeline.run_turn(disclosed, "nahi 430")
    assert parser.calls[-1]["ctx"]["last_event"]["kind"] == "writeoff"
    assert t.reply_text == "Theek kar diya: Ramesh, ₹430 maaf."
    assert [e["kind"] for e in t.entries] == ["writeoff", "writeoff"] and t.entries[0]["reversed"]
    rid = ledger.find_customer(key="ramesh")["id"]
    assert ledger.balance(rid) == 340 - 430
    u = pipeline.run_turn(disclosed, "undo karo")
    assert u.reply_text == "Pichli entry hata di: Ramesh, ₹430 maaf." and ledger.balance(rid) == 340


# ---- 5. idempotency ---------------------------------------------------------------------------------------------
def test_K01_O02_repeated_utt_id_saves_once_and_replays_result(pipeline, disclosed, ledger):
    first = pipeline.run_turn(disclosed, "ramesh ka 340 udhaar", utt_id="client-1", device_ts="2026-11-21T09:00:00")
    again = pipeline.run_turn(disclosed, "ramesh ka 340 udhaar", utt_id="client-1")
    assert count_events(ledger) == 1 and again.duplicate and not first.duplicate
    assert again.message(2)["duplicate"] is True and again.reply_text == first.reply_text
    assert again.entries == first.entries and again.status == "ok"
    rec = ledger.find_utterance("client-1")
    assert rec["device_ts"] == "2026-11-21T09:00:00" and rec["status"] == "ok"
    ev = ledger.conn.execute("SELECT utterance_id FROM events").fetchone()
    assert ev["utterance_id"] == "client-1"


def test_O05_utterance_row_is_in_the_same_transaction(pipeline, disclosed, ledger, monkeypatch):
    monkeypatch.setattr(ledger, "_insert_utterance", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    t = pipeline.run_turn(disclosed, "ramesh ka 340 udhaar", utt_id="u-x")
    assert t.status == "rejected" and count_events(ledger) == 0


def test_repeated_utt_id_for_a_question_replays(pipeline, disclosed, ledger):
    a = pipeline.run_turn(disclosed, "ramesh 340", utt_id="q-1")
    b = pipeline.run_turn(disclosed, "ramesh 340", utt_id="q-1")
    assert b.duplicate and b.status == "needs_clarification" and b.question == a.question
    assert count_utterances(ledger) == 1


def test_bad_utt_id_is_ignored(pipeline, disclosed, ledger):
    pipeline.run_turn(disclosed, "ramesh ka 340 udhaar", utt_id="x" * 65)
    pipeline.run_turn(disclosed, "ramesh ka 340 udhaar", utt_id="x" * 65)
    assert count_events(ledger) == 2


# ---- 6. pending expiry ------------------------------------------------------------------------------------------
def test_E02_open_question_expires_after_60_seconds(timed, state, parser, clock, ledger):
    state.disclosed = True
    timed.run_turn(state, "ramesh 340")
    clock.advance(59)
    timed.run_turn(state, "udhaar")
    assert parser.calls[-1]["ctx"]["pending"]["reason"] == "ambiguous_direction"
    assert ledger.balance(ledger.find_customer(key="ramesh")["id"]) == 340
    timed.run_turn(state, "ramesh 340")
    clock.advance(61)
    t = timed.run_turn(state, "udhaar")
    assert "pending" not in parser.calls[-1]["ctx"] and t.status == "rejected"
    assert state.pending is None


# ---- word counts and spoken form (N03, N01) ---------------------------------------------------------------------
def _all_replies(r):
    ev = {"kind": "credit", "customer": "Ramesh", "amount": 1250, "date": TODAY.isoformat()}
    return [
        r.saved([ev], TODAY), r.saved([dict(ev, kind="writeoff")], TODAY), r.amend(ev), r.undo(ev),
        r.nothing_to_amend(), r.nothing_to_undo(), r.entry_removed(), r.future(), r.negated(), r.out_of_scope(),
        r.too_large(), r.no_question(), r.new_customer("Ramesh"), r.new_customer("Rakes", ["Rakesh"]),
        r.name_alone("Ramesh"), r.quantity(), r.confirm_entry("Ramesh", "credit", 300, "2026-11-20", TODAY),
        r.confirm_entry("Ramesh", "payment", 300), r.confirm_settle("Ramesh", 340), r.confirm_half("Ramesh", 170),
        r.confirm_writeoff("Ramesh", 340), r.confirm_roundoff("Ramesh", 345, 5),
        r.confirm_overpayment("Ramesh", 340, 500), r.confirm_overpayment("Ramesh", 0, 500), r.confirm_duplicate(),
        r.silence(), r.too_long(), r.private(), r.no_entries("Ramesh"), r.balance("Ramesh", 0),
        r.daily_summary({"count": 2, "credit": 500000, "payment": 125000}, "last_month"),
        r.outstanding_total(125000, 12), r.due_since("Ramesh", date(2026, 11, 5)), r.reminder_ready("Ramesh"),
        r.reminder_no_consent("Ramesh"), r.reminder_nothing_due("Ramesh"), r.reminder_confirm("Ramesh", 340, 850),
        r.reminder_quiet(), r.credit_total(500, "this_week"), r.payment_total(0, "last_week"),
        r.saved([ev, dict(ev, kind="payment", amount=200, date="2026-11-20")], TODAY),
        r.confirm_entries([ev, dict(ev, kind="payment", amount=200, date="2026-11-20")], TODAY),
    ]


def test_N03_every_reply_is_about_twelve_words():
    for r in (R, EN):
        for reply in _all_replies(r):
            assert len(reply.text.split()) <= 12, reply.text


def test_N01_hinglish_speech_is_devanagari_with_amounts_in_words():
    real = Replier()
    for reply in _all_replies(real):
        assert any("ऀ" <= ch <= "ॿ" for ch in reply.speak), reply.speak
        assert "₹" not in reply.speak and not any(ch.isdigit() for ch in reply.speak), reply.speak
    for reply in _all_replies(real.with_lang("en")):
        assert "₹" not in reply.speak and not any(ch.isdigit() for ch in reply.speak), reply.speak


def test_section_51_templates_hinglish_and_english():
    assert R.daily_summary({"count": 1, "credit": 500, "payment": 200}, "this_week").text == \
        "Is hafte ₹500 udhaar gaya, ₹200 jama hue."
    assert R.daily_summary({"count": 1, "credit": 500, "payment": 200}, "last_month").text == \
        "Pichle mahine ₹500 udhaar gaya, ₹200 jama hue."
    assert EN.daily_summary({"count": 1, "credit": 500, "payment": 200}, "this_week").text == \
        "This week: ₹500 credit, ₹200 received."
    assert R.outstanding_total(4500, 7).text == "Kul baaki ₹4,500 hai, 7 grahakon par."
    assert EN.outstanding_total(4500, 7).text == "Total outstanding is ₹4,500, from 7 customers."
    assert R.due_since("Ramesh", date(2026, 11, 5)).text == "Ramesh ka 5 navambar se baaki hai."
    assert EN.due_since("Ramesh", date(2026, 11, 5)).text == "Ramesh has owed since 5 November."
    assert R.private().text == "Jawab screen par hai." and EN.private().text == "The answer is on the screen."
    assert R.silence().text == "Kuch sunai nahi diya. Dobara boliye."
    assert R.too_long().text == "Bahut lamba ho gaya. Chhote vaakya mein boliye."
    assert R.reminder_ready("Ramesh").text == "Ramesh ka reminder taiyaar hai, screen par dekhiye."
    assert R.reminder_no_consent("Ramesh").text == "Ramesh ne reminder ke liye haan nahi kaha hai."
    assert R.reminder_nothing_due("Ramesh").text == "Ramesh ka kuch baaki nahi, reminder nahi banaya."
    assert R.reminder_confirm("Ramesh", 340, 850).text == \
        "Ramesh ke ₹340 baaki hain, ₹850 nahi. ₹340 ka reminder banaun?"
    assert R.reminder_quiet().text == "Reminder subah 9 se raat 8 baje ke beech hi bante hain."


def test_unclear_correction_candidates_are_entries_with_display_names(pipeline, disclosed, parser, ledger):
    out = apply_events(ledger, [_ev("credit", "ramesh", 340, TODAY), _ev("payment", "ramesh", 200, TODAY)])
    a, b = out.saved
    parser.canned["nahi"] = {
        "status": "needs_clarification", "reason": "unclear_correction",
        "candidates": [{"id": a["id"], "kind": "credit", "customer": "ramesh", "customer_id": a["customer_id"],
                        "amount": 340, "date": TODAY.isoformat()},
                       {"id": b["id"], "kind": "payment", "customer": "ramesh", "amount": 200}],
        "pending": {"reason": "unclear_correction", "action": "amend", "events": []}}
    t = pipeline.run_turn(disclosed, "nahi")
    assert t.reply_text == "Kaunsi entry: ₹340 udhaar ya ₹200 jama?"
    assert t.message(1)["candidates"] == [
        {"id": a["id"], "kind": "credit", "amount": 340, "customer": "Ramesh"},
        {"id": b["id"], "kind": "payment", "amount": 200, "customer": "Ramesh"}]


def test_same_name_candidates_have_display_and_tags(pipeline, disclosed, parser, ledger):
    c1 = ledger.create_customer("ramesh", tags=["chai wale"])
    c2 = ledger.create_customer("ramesh", tags=["gali 3"])
    cands = [{"id": c1["id"], "name": "ramesh", "tags": ["chai wale"]}, {"id": c2["id"], "name": "ramesh",
                                                                        "tags": ["gali 3"]}]
    parser.canned["ramesh ka total?"] = {"status": "needs_clarification", "reason": "same_name", "candidates": cands,
                                         "pending": {"reason": "same_name", "action": "query",
                                                     "query": {"type": "balance"}, "candidates": cands}}
    msg = pipeline.run_turn(disclosed, "ramesh ka total?").message(1)
    assert msg["candidates"] == [{"id": c1["id"], "display": "Ramesh chai wale", "tags": ["chai wale"]},
                                 {"id": c2["id"], "display": "Ramesh gali 3", "tags": ["gali 3"]}]


def test_strict_mode_unsure_question_never_shows_the_unknown_words(pipeline, parser, ledger):
    one = [_ev("credit", "ramesh", 340, TODAY)]
    two = [_ev("credit", "ramesh", 340, TODAY), _ev("payment", "ramesh", 200, TODAY - timedelta(days=1))]
    for events, hi, en in (
            (one, "Ramesh ke ₹340 udhaar likhun?", "Add ₹340 credit for Ramesh?"),
            (two, "2 entry likhun: Ramesh ke ₹340 udhaar, kal ke ₹200 jama?",
             "Save 2 entries: ₹340 credit for Ramesh, and ₹200 received yesterday?")):
        parser.canned["u"] = _confirm("unsure", events, words=["blorf"])
        for lang, want in (("hi", hi), ("en", en)):
            st = SessionState(session_id="s" + lang, disclosed=True, lang=lang)
            t = pipeline.run_turn(st, "u")
            assert t.reply_text == want, t.reply_text
            msg = t.message(1)
            assert msg["confirm"] == {"type": "unsure"} and "blorf" not in str(msg) and "blorf" not in t.speak_text
            assert st.pending["confirm"]["words"] == ["blorf"]  # the parser still gets them back
    assert count_events(ledger) == 0
