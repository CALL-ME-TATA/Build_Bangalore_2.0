"""Server findings of the second review: private questions, utt_id reuse, device_ts, log safety, Origin check,
write-offs as last events, and `last_turn` after questions and rejections (CONTRACT 1.15)."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

import httpx
import pytest
import websockets

from app.gnani import stt as stt_module
from app.logsafe import StripQuery, describe
from app.main import create_app, origin_allowed
from app.pipeline import Pipeline, SessionState, clean_device_ts

from .conftest import _ev, apply_events, fake_nw
from .test_review_fixes import running
from .test_session import AUDIO, hello, is_type, of, recv_until

TODAY = date(2026, 11, 21)
NOON = datetime(2026, 11, 21, 12, 0).astimezone()


def count_events(ledger) -> int:
    return ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def _confirm(ctype, events, **confirm):
    c = {"type": ctype, **confirm}
    return {"status": "needs_clarification", "reason": "confirm_entry", "confirm": c,
            "pending": {"reason": "confirm_entry", "action": "append", "events": events, "confirm": c}}


# ---- 1. private mode never speaks a balance in a question --------------------------------------------------------
@pytest.mark.parametrize("ctype,events,confirm", [
    ("settle", [_ev("payment", "ramesh", 340, TODAY)], {"balance": 340}),
    ("writeoff", [_ev("writeoff", "ramesh", 340, TODAY)], {"balance": 340}),
    ("overpayment", [_ev("payment", "ramesh", 500, TODAY)], {"balance": 340}),
    ("roundoff", [_ev("writeoff", "ramesh", 5, TODAY)], {"balance": 345}),
    ("half", [_ev("payment", "ramesh", 170, TODAY)], {"balance": 340}),
])
def test_N08_private_mode_keeps_balances_of_questions_off_the_voice(pipeline, parser, ctype, events, confirm):
    parser.canned["q"] = _confirm(ctype, events, **confirm)
    for lang, spoken in (("hi", "स्क्रीन पर देखिए। हाँ या नहीं बोलिए।"),
                         ("en", "Please check the screen, then say yes or no.")):
        t = pipeline.run_turn(SessionState(session_id="p" + lang, disclosed=True, lang=lang, private=True), "q")
        public = pipeline.run_turn(SessionState(session_id="o" + lang, disclosed=True, lang=lang), "q")
        assert t.speak_text == spoken and t.reply_text == public.reply_text  # the full question is on screen
        assert public.speak_text != spoken  # outside private mode the question is spoken


def test_N08_private_mode_reminder_mismatch_question(ledger, settings, parser):
    pipe = Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw, now=lambda: NOON)
    apply_events(ledger, [_ev("credit", "ramesh", 340, TODAY)])
    rid = ledger.find_customer(key="ramesh")["id"]
    ledger.set_reminder_opt_in(rid, True, "9876543210", now=NOON)
    parser.canned["r"] = {"status": "ok", "action": "reminder", "customer": "ramesh", "amount": 850}
    t = pipe.run_turn(SessionState(session_id="s", disclosed=True, private=True), "r")
    assert t.reason == "confirm_entry" and "₹340" in t.reply_text
    assert t.speak_text == "स्क्रीन पर देखिए। हाँ या नहीं बोलिए।"


def test_private_mode_still_reads_back_a_plain_confirmation(pipeline, parser):
    parser.canned["q"] = _confirm("computed", [_ev("credit", "ramesh", 300, TODAY)], bill=500, paid=200)
    t = pipeline.run_turn(SessionState(session_id="s", disclosed=True, private=True), "q")
    assert "<300>" in t.speak_text  # what is being entered is read back; only balances stay on screen


# ---- 2. a reused utt_id ------------------------------------------------------------------------------------------
def test_utt_id_with_another_sentence_is_refused_and_a_retry_from_a_new_session_replays(pipeline, ledger):
    a = SessionState(session_id="sessA", disclosed=True)
    pipeline.run_turn(a, "ramesh ka 340 udhaar", utt_id="u-1")
    same = pipeline.run_turn(a, "Ramesh  ka 340 UDHAAR", utt_id="u-1")  # spacing and case do not matter
    assert same.duplicate and same.error_code is None
    other_text = pipeline.run_turn(a, "sunita ne 150 diye", utt_id="u-1")
    assert other_text.error_code == "utt_id_reused" and not other_text.duplicate
    # O02: the offline queue resends after a page reload, in a new session; the same sentence is a retry.
    other_session = pipeline.run_turn(SessionState(session_id="sessB", disclosed=True), "ramesh ka 340 udhaar",
                                      utt_id="u-1")
    assert other_session.duplicate and other_session.error_code is None
    assert pipeline.run_turn(SessionState(session_id="sessC", disclosed=True), "sunita ne 150 diye",
                             utt_id="u-1").error_code == "utt_id_reused"
    assert count_events(ledger) == 1 and ledger.find_customer(key="sunita") is None


async def test_reused_utt_id_gets_an_error_message_and_no_result(server):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar", "utt_id": "w-1"}))
        await recv_until(ws, is_type("audio_end", turn_id=1))
        await ws.send(json.dumps({"type": "text", "text": "sunita ne 150 diye", "utt_id": "w-1"}))
        msgs = await recv_until(ws, is_type("state", turn_id=2, state="idle"))
        assert of(msgs, "error")[0]["code"] == "utt_id_reused" and not of(msgs, "result")
        assert not [m for m in msgs if isinstance(m, tuple)]
    async with httpx.AsyncClient() as c:
        assert [e["amount"] for e in (await c.get(server.http + "/api/ledger")).json()["entries"]] == [340]


# ---- 3. device_ts ------------------------------------------------------------------------------------------------
def test_C09_device_ts_accepts_only_iso_8601():
    assert clean_device_ts("2026-11-21T10:00:00+05:30") == "2026-11-21T10:00:00+05:30"
    assert clean_device_ts("2026-11-21T04:30:00Z") == "2026-11-21T04:30:00+00:00"
    assert clean_device_ts("2026-11-21 10:00") == "2026-11-21T10:00:00"
    for bad in ("yesterday", "1732170000", 1732170000, "<script>", "2026-13-45T10:00", "x" * 64, None, True):
        assert clean_device_ts(bad) is None, bad


def test_C09_invalid_device_ts_is_not_stored(pipeline, ledger):
    st = SessionState(session_id="s", disclosed=True)
    pipeline.run_turn(st, "ramesh ka 340 udhaar", utt_id="d-1", device_ts="not a time")
    pipeline.run_turn(st, "sunita ne 150 diye", utt_id="d-2", device_ts="2026-11-21T04:30:00Z")
    assert ledger.find_utterance("d-1")["device_ts"] is None
    assert ledger.find_utterance("d-2")["device_ts"] == "2026-11-21T04:30:00+00:00"


# ---- 4. tracebacks -----------------------------------------------------------------------------------------------
def test_describe_has_type_and_place_but_no_message():
    try:
        raise ValueError("Ramesh 340 secret")
    except ValueError as exc:
        text = describe(exc)
    assert text.startswith("ValueError at test_review2.py:") and "Ramesh" not in text and "340" not in text


async def test_stt_callback_and_reader_failures_log_no_message(settings, caplog):
    caplog.set_level(logging.DEBUG)
    client = stt_module.SttClient(settings)

    async def boom(kind, text=None):
        raise RuntimeError("zorbax 7341")

    client._on_event = boom
    await client._emit("partial", "zorbax 7341")
    text = "\n".join(f"{r.getMessage()} {r.exc_text or ''}" for r in caplog.records)
    assert "stt event callback failed: RuntimeError at" in text and "zorbax" not in text and "7341" not in text


async def test_speaking_failure_logs_no_message(server, fake_gnani, caplog, monkeypatch):
    from app.gnani.tts import TtsClient

    async def broken(self, text, persist=False, lang="hi"):
        raise RuntimeError(f"cannot say {text}")
        yield b""  # pragma: no cover

    caplog.set_level(logging.DEBUG)
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        monkeypatch.setattr(TtsClient, "synth", broken)
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar"}))
        msgs = await recv_until(ws, is_type("state", turn_id=1, state="idle"))
        assert of(msgs, "error")[0]["code"] == "tts_upstream"
    text = "\n".join(f"{r.getMessage()} {r.exc_text or ''}" for r in caplog.records)
    assert "speaking failed: RuntimeError at" in text and "cannot say" not in text and "Ramesh" not in text


# ---- 5. access code never reaches the access log -----------------------------------------------------------------
def test_access_log_records_lose_the_query_string(settings, parser):
    create_app(settings, parse=parser, number_to_words=fake_nw)
    assert any(isinstance(f, StripQuery) for f in logging.getLogger("uvicorn.access").filters)
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "GET", "/api/ledger?code=sesame&limit=5", "1.1", 200), None)
    for f in logging.getLogger("uvicorn.access").filters:
        f.filter(record)
    assert "sesame" not in record.getMessage() and "/api/ledger" in record.getMessage()


async def test_access_code_query_still_works_and_is_not_logged(settings, parser, fake_gnani, caplog):
    settings.access_code = "sesame"
    app = create_app(settings, parse=parser, number_to_words=fake_nw)
    import uvicorn

    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="info", access_log=True))
    import asyncio

    keep = Keep()
    logging.getLogger("uvicorn.access").addHandler(keep)  # uvicorn's config stops it propagating to caplog
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.01)
    http = f"http://127.0.0.1:{srv.servers[0].sockets[0].getsockname()[1]}"
    try:
        async with httpx.AsyncClient() as c:
            assert (await c.get(http + "/api/customers", params={"code": "sesame"})).status_code == 200
            assert (await c.get(http + "/api/customers", headers={"X-Access-Code": "sesame"})).status_code == 200
    finally:
        srv.should_exit = True
        await task
        logging.getLogger("uvicorn.access").removeHandler(keep)
    assert len(lines) >= 2 and all("sesame" not in line for line in lines), lines
    assert any("/api/customers" in line for line in lines)


# ---- 6. a write-off as the last event ----------------------------------------------------------------------------
def test_writeoff_is_reported_as_last_event_and_reversals_keep_the_adjustment(pipeline, parser, ledger):
    st = SessionState(session_id="sess0001", disclosed=True)
    apply_events(ledger, [_ev("credit", "ramesh", 340, TODAY)])
    parser.canned["w"] = {"status": "ok", "action": "append", "events": [_ev("writeoff", "ramesh", 40, TODAY)]}
    pipeline.run_turn(st, "w")
    assert ledger.last_active_event("sess0001")["kind"] == "writeoff"
    assert [e["kind"] for e in ledger.last_events("sess0001")] == ["writeoff"]
    pipeline.run_turn(st, "nahi 430")
    rows = ledger.conn.execute("SELECT kind, adjustment FROM events ORDER BY id").fetchall()
    assert [(r["kind"], r["adjustment"]) for r in rows][-3:] == [
        ("payment", "writeoff"), ("reversal", "writeoff"), ("payment", "writeoff")]
    pipeline.run_turn(st, "undo karo")
    last = ledger.conn.execute("SELECT kind, adjustment FROM events ORDER BY id DESC LIMIT 1").fetchone()
    assert (last["kind"], last["adjustment"]) == ("reversal", "writeoff")
    assert ledger.balance(ledger.find_customer(key="ramesh")["id"]) == 340
    assert ledger.payment_total(pipeline.now().date()) == 0


# ---- 7. Origin allow-list ----------------------------------------------------------------------------------------
def test_origin_allow_list():
    assert origin_allowed(None, "shop.example:8000")
    assert origin_allowed("https://abc.trycloudflare.com", "abc.trycloudflare.com")
    assert origin_allowed("http://localhost:5173", "127.0.0.1:8000")
    assert origin_allowed("http://127.0.0.1:5173", "127.0.0.1:8000")
    assert origin_allowed("https://kiosk.example", "x:1", "https://kiosk.example, https://other.example/")
    assert not origin_allowed("https://evil.example", "abc.trycloudflare.com")
    assert not origin_allowed("null", "abc.trycloudflare.com")
    assert not origin_allowed("https://abc.trycloudflare.com.evil.example", "abc.trycloudflare.com")


async def test_ws_from_a_foreign_origin_is_refused(server):
    with pytest.raises(websockets.InvalidStatus):
        async with websockets.connect(server.url, origin="https://evil.example"):
            pass
    host = server.url.split("//", 1)[1].split("/", 1)[0]
    async with websockets.connect(server.url, origin=f"http://{host}") as ws:
        assert of(await hello(ws), "ready")


async def test_allowed_origins_env(settings, parser, fake_gnani):
    from app.config import Settings

    assert Settings.from_env({"ALLOWED_ORIGINS": "https://a.example"}).allowed_origins == "https://a.example"
    settings.allowed_origins = "https://kiosk.example"
    settings.gnani_base_url = fake_gnani.base_url
    async with running(create_app(settings, parse=parser, number_to_words=fake_nw)) as (_, url):
        async with websockets.connect(url, origin="https://kiosk.example") as ws:
            await ws.send(json.dumps({"type": "ping", "t": 1}))
            assert (await recv_until(ws, is_type("pong")))[-1]["t"] == 1


# ---- CONTRACT 1.15: last_turn after questions and rejections -------------------------------------------------------
def test_last_turn_is_question_after_a_question_even_when_it_expires(ledger, settings, parser):
    clock = {"t": NOON}
    pipe = Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw, now=lambda: clock["t"])
    st = SessionState(session_id="s", disclosed=True)
    pipe.run_turn(st, "ramesh ka 340 udhaar")
    pipe.run_turn(st, "ramesh 340")
    clock["t"] += timedelta(seconds=90)  # the question expires
    pipe.run_turn(st, "nahi 430")
    ctx = parser.calls[-1]["ctx"]
    assert ctx["last_turn"]["action"] == "question" and "pending" not in ctx


def test_last_turn_is_none_after_a_rejection_even_with_a_question_open(pipeline, parser):
    st = SessionState(session_id="s", disclosed=True)
    pipeline.run_turn(st, "ramesh 340")
    pipeline.run_turn(st, "kuch bhi")  # not_ledger keeps the question open
    pipeline.run_turn(st, "udhaar")
    ctx = parser.calls[-1]["ctx"]
    assert ctx["last_turn"]["action"] == "none" and ctx["pending"]["reason"] == "ambiguous_direction"


def test_last_turn_is_none_after_a_spoken_silence_or_failure(pipeline, parser):
    st = SessionState(session_id="s", disclosed=True)
    pipeline.run_turn(st, "ramesh ka 340 udhaar")
    for spoken in (pipeline.silence, pipeline.too_long, pipeline.empty_transcript, pipeline.upstream_failure):
        pipeline.run_turn(st, "ramesh ka 340 udhaar")
        spoken(st)
        pipeline.run_turn(st, "nahi 430")
        assert parser.calls[-1]["ctx"]["last_turn"]["action"] == "none", spoken.__name__
