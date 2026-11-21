"""Fourth review, server side (CONTRACT 1.18 and the 5.1 rows of v1.6)."""
from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx
import pytest
import websockets

from app.pipeline import SessionState
from app.replies import Replier, fixed_replies

from .conftest import _ev, apply_events, fake_nw
from .test_session import AUDIO, hello, is_type, of, recv_until

TODAY = date(2026, 11, 21)
R = Replier(fake_nw)
EN = R.with_lang("en")
REAL = Replier()
PRIVATE_SPEECH = "स्क्रीन पर देखिए। हाँ या नहीं बोलिए।"


def st(**kw) -> SessionState:
    return SessionState(session_id=kw.pop("session_id", "sess0001"), disclosed=True, **kw)


def ask(reason, events, index=None, confirm=None, action="append", **extra):
    pending = {"reason": reason, "action": action, "events": events}
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


# ---- missing amount of a write-off ----------------------------------------------------------------------------
def test_missing_amount_of_a_writeoff_one_or_several_events():
    one = [{"kind": "writeoff", "customer": "mohan", "date": TODAY.isoformat()}]
    several = [_ev("credit", "ramesh", 200, TODAY)] + one
    for events, index in ((one, None), (several, 1), (several, None)):
        q = ask("missing_amount", events, index=index)
        assert R.clarification(q).text == "Mohan ke kitne rupaye maaf karun?"
        assert EN.clarification(q).text == "How many rupees to write off for Mohan?"
    assert REAL.clarification(ask("missing_amount", one)).speak == "Mohan के कितने रुपये माफ़ करूँ?"
    assert R.clarification(ask("missing_amount", [{"kind": "writeoff"}])).text == "Kitne rupaye?"  # no customer


# ---- replace check names the new entry ------------------------------------------------------------------------
def test_replace_check_names_the_new_entry(pipeline, parser, ledger):
    s = st()
    pipeline.run_turn(s, "sunita ne 150 diye")  # the review's case: a payment, then a credit for someone else
    parser.canned["nahi geeta ko 500 udhaar"] = ask("unclear_correction", [_ev("credit", "geeta", 500, TODAY)],
                                                    action="amend")
    t = pipeline.run_turn(s, "nahi geeta ko 500 udhaar")
    assert t.reply_text == "Pichli entry hata kar Geeta ke ₹500 udhaar likhoon?"
    assert pipeline.run_turn(st(lang="en", session_id="sess0001"), "nahi geeta ko 500 udhaar").reply_text == \
        "Replace the last entry with ₹500 credit for Geeta?"
    assert "<500>" in pipeline.run_turn(st(private=True), "nahi geeta ko 500 udhaar").speak_text  # no balance
    speak = REAL.replace_check({"customer": "Geeta", "amount": 500, "kind": "payment"}).speak
    assert speak.startswith("पिछली एंट्री हटा कर Geeta के ") and speak.endswith("रुपये जमा लिखूँ?")
    assert R.replace_check({"customer": "Geeta", "amount": 500}).text == "Pichli entry hata kar yeh likhoon?"
    assert R.replace_check().speak in {x.speak for x in fixed_replies(R)}  # the cached generic phrase stays


def test_S7_no_to_the_replace_check_writes_nothing_and_reask_uses_the_new_wording(pipeline, parser, ledger):
    s = st()
    pipeline.run_turn(s, "sunita ne 150 diye")
    before = count_events(ledger)
    parser.canned["nahi geeta ko 500 udhaar"] = ask("unclear_correction", [_ev("credit", "geeta", 500, TODAY)],
                                                    action="amend")
    pipeline.run_turn(s, "nahi geeta ko 500 udhaar")
    again = pipeline.silence(s)
    assert again.reply_text == "Kuch sunai nahi diya. Pichli entry hata kar Geeta ke ₹500 udhaar likhoon?"
    parser.canned["nahi"] = {"status": "rejected", "reason": "cancelled", "action": "amend"}
    t = pipeline.run_turn(s, "nahi")
    assert t.status == "rejected" and t.reply_text == "Theek hai, entry nahi ki." and s.pending is None
    assert count_events(ledger) == before and ledger.find_customer(key="geeta") is None
    assert ledger.balance(ledger.find_customer(key="sunita")["id"]) == -150  # the old entry stays


# ---- write-off above the balance -------------------------------------------------------------------------------
def test_writeoff_above_the_balance(pipeline, parser):
    c = {"type": "writeoff", "balance": 140}
    parser.canned["q"] = ask("confirm_entry", [_ev("writeoff", "mohan", 400, TODAY)], index=0, confirm=c)
    assert pipeline.run_turn(st(), "q").reply_text == "Mohan ke sirf ₹140 baaki hain. ₹400 maaf karun?"
    assert pipeline.run_turn(st(lang="en"), "q").reply_text == "Mohan owes only ₹140. Write off ₹400?"
    assert pipeline.run_turn(st(private=True), "q").speak_text == PRIVATE_SPEECH  # it states the balance
    speak = REAL.confirm_writeoff_above("Mohan", 140, 400).speak
    assert "सिर्फ़" in speak and "माफ़ करूँ?" in speak and not any(ch.isdigit() for ch in speak)
    zero = {"type": "writeoff", "balance": 0}
    parser.canned["z"] = ask("confirm_entry", [_ev("writeoff", "sunita", 50, TODAY)], index=0, confirm=zero)
    assert pipeline.run_turn(st(), "z").reply_text == "Sunita ke sirf ₹0 baaki hain. ₹50 maaf karun?"
    below = {"type": "writeoff", "balance": 500}
    parser.canned["b"] = ask("confirm_entry", [_ev("writeoff", "mohan", 200, TODAY)], index=0, confirm=below)
    assert pipeline.run_turn(st(), "b").reply_text == "Mohan ke ₹200 maaf karun?"
    assert "<200>" in pipeline.run_turn(st(private=True), "b").speak_text


# ---- same name with three customers -----------------------------------------------------------------------------
def cands(*tags):
    return [{"id": f"c{i}", "name": "suresh", "tags": [t] if t else []} for i, t in enumerate(tags)]


def same_name(*tags):
    return {**ask("same_name", [_ev("credit", "suresh", 200, TODAY)]), "candidates": cands(*tags)}


def test_S3_same_name_three_customers_in_order_with_the_untagged_one_in_place():
    assert R.clarification(same_name("chai wale", "gali 4", "")).text == \
        "Kaunse Suresh: chai wale, gali 4 ya bina tag wale?"
    assert EN.clarification(same_name("chai wale", "gali 4", "")).text == \
        "Which Suresh: chai wale, gali 4 or the one with no tag?"
    assert R.clarification(same_name("chai wale", "")).text == "Kaunse Suresh: chai wale ya bina tag wale?"
    assert R.clarification(same_name("", "chai wale")).text == "Kaunse Suresh: bina tag wale ya chai wale?"
    assert R.clarification(same_name("a", "b", "c", "d")).text == "Kaunse Suresh: a, b ya c?"  # the first three
    speak = REAL.clarification(same_name("chai wale", "", "gali 4")).speak
    assert speak == "कौन से Suresh: chai wale, बिना टैग वाले या gali 4?"
    for r in (R, EN):
        assert "pehle wale" not in r.clarification(same_name("chai wale", "", "gali 4")).text
        assert len(r.clarification(same_name("chai wale", "gali 4", "")).text.split()) <= 12


def test_same_name_candidates_in_the_result_keep_the_spoken_order(pipeline, parser, ledger):
    a = ledger.create_customer("suresh", tags=["chai wale"])
    b = ledger.create_customer("suresh")
    c = ledger.create_customer("suresh", tags=["gali 4"])
    order = [{"id": x["id"], "name": "suresh", "tags": x["tags"]} for x in (a, b, c)]
    parser.canned["q"] = {**ask("same_name", [_ev("credit", "suresh", 200, TODAY)]), "candidates": order}
    t = pipeline.run_turn(st(), "q")
    assert t.reply_text == "Kaunse Suresh: chai wale, bina tag wale ya gali 4?"
    assert [x["id"] for x in t.message(1)["candidates"]] == [a["id"], b["id"], c["id"]]


def test_new_rows_keep_to_twelve_words():
    for r in (R, EN):
        for reply in (r.writeoff_amount_for("Ramesh Chopra"),
                      r.replace_check({"customer": "Ramesh Chopra", "amount": 125000, "kind": "credit"}),
                      r.confirm_writeoff_above("Ramesh Chopra", 140, 125000)):
            assert len(reply.text.split()) <= 12, reply.text


# ---- 3. a late speech_start of an earlier press never counts for the next one -----------------------------------
async def test_late_speech_start_of_an_earlier_press_is_ignored(server, fake_gnani):
    """Press 1: Gnani reports speech only after the server has given up (no speech). Press 2 is silent. The late
    speech_start and transcript of press 1 arrive during press 2 and must not make it "heard" or give it words."""
    fake_gnani.speech_start_delay = 1.6
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        first = of(await recv_until(ws, is_type("audio_end", turn_id=1), timeout=8), "result")[0]
        assert first["reason"] == "silence"
        fake_gnani.speech = False
        fake_gnani.speech_start_delay = 0.0
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        second = of(await recv_until(ws, is_type("audio_end", turn_id=2), timeout=8), "result")[0]
        assert second["reason"] == "silence" and second["reply_text"] == "Kuch sunai nahi diya. Dobara boliye."
        await asyncio.sleep(0.5)
    async with httpx.AsyncClient() as c:
        assert (await c.get(server.http + "/api/ledger")).json()["entries"] == []


async def test_a_heard_turn_keeps_its_socket(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        for i in (1, 2):
            await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
            await ws.send(bytes(AUDIO))
            await ws.send(json.dumps({"type": "end"}))
            await recv_until(ws, is_type("audio_end", turn_id=i))
    assert len(fake_gnani.stt_sessions) == 1  # a turn that ended normally does not cost a new handshake
