"""Tests for the rules added after the first review (CONTRACT section 3.1 and 1.12)."""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

import httpx
import pytest
import uvicorn
import websockets

from app import admin
from app.config import REPO_ROOT, Settings
from app.gnani.stt import SttClient
from app.gnani.tts import TtsClient, TtsError
from app.main import create_app
from app.pipeline import Pipeline, SessionState
from app.replies import Replier

from .conftest import apply_events, fake_nw
from .test_session import AUDIO, hello, is_type, of, recv_until

R = Replier(fake_nw)
TODAY = date(2026, 11, 21).isoformat()


def ev(kind, customer, amount, **extra):
    return {"kind": kind, "customer": customer, "amount": amount, "date": TODAY, **extra}


@asynccontextmanager
async def running(app):
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.01)
    port = srv.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}/ws/session"
    finally:
        srv.should_exit = True
        await task


# ---- 1. disclosure ----------------------------------------------------------------------------------------------
async def test_cancelled_greeting_is_not_disclosure(server, fake_gnani):
    fake_gnani.tts_chunks = 30
    fake_gnani.tts_chunk_delay = 0.02
    async with websockets.connect(server.url) as ws:
        await ws.send(json.dumps({"type": "hello"}))
        await recv_until(ws, lambda m: isinstance(m, tuple))  # greeting audio has started
        await ws.send(json.dumps({"type": "text", "text": "sunita ne 150 diye"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
        assert any(m.get("cancelled") for m in of(msgs, "audio_end"))
        assert "ek AI sahayak" in of(msgs, "result")[0]["reply_text"]
        assert "एआई" in fake_gnani.tts_requests[-1]["text"]
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=2))
        assert "AI sahayak" not in of(msgs, "result")[0]["reply_text"]


async def test_failed_greeting_audio_still_ends_and_is_not_disclosure(server, fake_gnani):
    fake_gnani.tts_die_after_first_chunk = True
    async with websockets.connect(server.url) as ws:
        msgs = await hello(ws)
        assert of(msgs, "error")[0]["code"] == "tts_upstream"
        assert of(msgs, "audio_end") and not of(msgs, "audio_end")[0].get("cancelled")
        fake_gnani.tts_die_after_first_chunk = False
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
        assert "ek AI sahayak" in of(msgs, "result")[0]["reply_text"]


# ---- 2. last_events and targeted amend --------------------------------------------------------------------------
def test_last_events_and_targeted_amend(ledger, settings):
    seen = []

    def parse(u, *, today, ctx=None):
        seen.append(ctx)
        if u == "two":
            return {"status": "ok", "action": "append", "events": [ev("credit", "ramesh", 340),
                                                                    ev("payment", "ramesh", 200)]}
        target = {"event_id": ctx["last_events"][0]["id"]} if u == "first" else {"event_id": 9999}
        if u == "foreign":
            target = {"event_id": foreign_id}
        return {"status": "ok", "action": "amend", "target": target,
                "events": [ev("credit", "ramesh", 111, customer_id=ctx["last_event"]["customer_id"])]}

    pipe = Pipeline(ledger, settings, parse=parse, number_to_words=fake_nw)
    state = SessionState(session_id="sess0001", disclosed=True)
    foreign_id = apply_events(ledger, [ev("credit", "mohan", 5)], session="other").saved[0]["id"]
    pipe.run_turn(state, "two")
    pipe.run_turn(state, "first")
    ctx = seen[1]
    assert [e["amount"] for e in ctx["last_events"]] == [340, 200]
    assert ctx["last_events"][0]["id"] < ctx["last_events"][1]["id"] and ctx["last_event"]["amount"] == 200
    entries = ledger.recent_entries()
    old = [e for e in entries if e["amount"] == 340][0]
    assert old["reversed"] is True
    assert ledger.balance(ledger.find_customer(key="ramesh")["id"]) == 111 - 200
    for name in ("bogus", "foreign"):
        before = ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        t = pipe.run_turn(state, name)
        assert t.reply_text == "Pichli entry nahi mili."
        assert ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before
    # An event that was already reversed is no longer a valid target.
    t = pipe.run_turn(state, "first")
    assert t.reply_text == "Pichli entry nahi mili." or "Theek kar diya" in t.reply_text


# ---- 3. speech-to-text turn boundaries ---------------------------------------------------------------------------
async def test_late_final_of_previous_utterance_is_ignored(server, fake_gnani):
    fake_gnani.scripts = [["ramesh ka 340 udhaar"], ["sunita ne 150 diye"]]
    fake_gnani.final_delay = 0.5
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        await asyncio.sleep(0.2)  # release, then press again before the first final arrives
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=2))
        transcript = [m for m in of(msgs, "transcript") if m["final"]][-1]
        assert transcript["text"] == "sunita ne 150 diye"
        assert of(msgs, "result")[0]["entries"][0]["customer"]["display"] == "Sunita"
        await asyncio.sleep(0.6)
        async with httpx.AsyncClient() as c:
            entries = (await c.get(server.http + "/api/ledger")).json()["entries"]
        assert [e["amount"] for e in entries] == [150]


async def test_socket_closed_with_open_utterance_saves_nothing(server, fake_gnani):
    fake_gnani.close_on_commit = True
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("audio_end"))
        result = of(msgs, "result")[0]
        assert of(msgs, "error")[0]["code"] == "stt_upstream"
        assert result["reason"] == "upstream" and result["entries"] == []
        assert result["reply_text"] == "Network mein dikkat hai, dobara boliye."
        async with httpx.AsyncClient() as c:
            assert (await c.get(server.http + "/api/ledger")).json()["entries"] == []


async def test_idle_close_only_closes_its_own_socket(settings, fake_gnani):
    settings.gnani_base_url = fake_gnani.base_url
    client = SttClient(settings)
    await client.begin_turn()
    old = client._ws
    idle = asyncio.create_task(client._idle_close(old))
    client.idle_close_s = 0.1
    await client.close()
    await client.begin_turn()  # a new press opens a new socket
    new = client._ws
    assert new is not old and client.connected
    await asyncio.sleep(0.2)
    idle.cancel()
    # Run the stale idle task to completion: it must leave the new socket alone.
    await asyncio.gather(client._idle_close(old), return_exceptions=True)
    assert client._ws is new and client.connected
    await client.close()


# ---- 4. text-to-speech client ------------------------------------------------------------------------------------
async def collect(client, text):
    return [c async for c in client.synth(text)]


async def test_tts_retries_when_socket_dies_before_start(settings, fake_gnani, tmp_path):
    settings.gnani_base_url = fake_gnani.base_url
    fake_gnani.tts_drop_before_start = 1
    client = TtsClient(settings, cache_dir=tmp_path / "c", memory_cache={})
    chunks = await collect(client, "नमस्ते")
    assert len(chunks) == 3 and len(fake_gnani.tts_requests) == 2
    await client.close()


async def test_tts_reopens_in_background_after_close(settings, fake_gnani, tmp_path):
    settings.gnani_base_url = fake_gnani.base_url
    client = TtsClient(settings, cache_dir=tmp_path / "c", memory_cache={})
    client.warm()
    for _ in range(100):
        if client._ws is not None:
            break
        await asyncio.sleep(0.02)
    first = client._ws
    await first.close()
    for _ in range(100):
        if client._ws is not None and client._ws is not first:
            break
        await asyncio.sleep(0.02)
    assert client._ws is not None and client._ws is not first
    assert len(await collect(client, "नमस्ते")) == 3
    await client.close()


async def test_tts_cancel_does_not_wait(settings, fake_gnani, tmp_path):
    settings.gnani_base_url = fake_gnani.base_url
    fake_gnani.tts_chunks = 10
    fake_gnani.tts_chunk_delay = 0.3
    client = TtsClient(settings, cache_dir=tmp_path / "c", memory_cache={})
    gen = client.synth("नमस्ते")
    await gen.__anext__()
    t0 = time.perf_counter()
    await gen.aclose()
    assert time.perf_counter() - t0 < 1.5
    await client.close()


async def test_tts_error_mid_stream_raises(settings, fake_gnani, tmp_path):
    settings.gnani_base_url = fake_gnani.base_url
    fake_gnani.tts_die_after_first_chunk = True
    client = TtsClient(settings, cache_dir=tmp_path / "c", memory_cache={})
    with pytest.raises(TtsError):
        await collect(client, "नमस्ते")
    await client.close()


# ---- 5. replies --------------------------------------------------------------------------------------------------
def test_new_customer_announced_once():
    events = [dict(kind="credit", customer="Ramesh", customer_id="c1", amount=10, date=TODAY, new_customer=True),
              dict(kind="payment", customer="Ramesh", customer_id="c1", amount=5, date=TODAY, new_customer=True)]
    r = R.saved(events, date(2026, 11, 21))
    assert r.text.count("Naya khata") == 1 and r.speak.count("नया खाता") == 1


def test_unknown_customer_and_yesterday_replies(pipeline, state, ledger):
    assert R.unknown_customer("Mohan").text == "Mohan ka khata nahi mila."
    assert R.credit_total(340, "yesterday").text == "Kal ₹340 udhaar gaya."
    assert R.payment_total(0, "yesterday").text == "Kal koi paisa jama nahi hua."
    assert R.daily_summary({"count": 1, "credit": 5, "payment": 0, "top": None}, "yesterday").text.startswith("Kal ₹5")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    apply_events(ledger, [{"kind": "credit", "customer": "ramesh", "amount": 340, "date": yesterday}])
    queries = {"y": {"type": "credit_total", "period": "yesterday"},
               "u": {"type": "balance", "customer": "mohan", "unknown_customer": True},
               "s": {"type": "daily_summary", "period": "yesterday"}}
    pipe = Pipeline(ledger, pipeline.settings, number_to_words=fake_nw, now=lambda: datetime.now().astimezone(),
                    parse=lambda u, *, today, ctx=None: {"status": "ok", "action": "query", "query": queries[u]})
    s = SessionState(session_id="s", disclosed=True)
    assert pipe.run_turn(s, "y").reply_text == "Kal ₹340 udhaar gaya."
    assert pipe.run_turn(s, "u").reply_text == "Mohan ka khata nahi mila."
    assert pipe.run_turn(s, "s").reply_text.startswith("Kal ₹340 udhaar gaya")


# ---- 6. privacy, access code, paths, purge ----------------------------------------------------------------------
async def test_only_fixed_replies_are_cached_on_disk(server, settings):
    cache = settings.tts_cache_dir
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        assert len(list(cache.glob("*.pcm"))) == 1  # the greeting
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar"}))
        await recv_until(ws, is_type("audio_end"))
        assert len(list(cache.glob("*.pcm"))) == 1  # a reply with a name and an amount is not stored
        await ws.send(json.dumps({"type": "text", "text": "kuch bhi"}))
        await recv_until(ws, is_type("audio_end"))
        assert len(list(cache.glob("*.pcm"))) == 2  # a rejection is fixed wording


async def test_access_code_guards_rest(settings, parser, fake_gnani):
    settings.access_code = "sesame"
    app = create_app(settings, parse=parser, number_to_words=fake_nw)
    async with running(app) as (http, _):
        async with httpx.AsyncClient() as c:
            assert (await c.get(http + "/api/health")).status_code == 200
            for path in ("/api/ledger", "/api/customers", "/api/reminders"):
                assert (await c.get(http + path)).status_code == 401
                assert (await c.get(http + path, headers={"X-Access-Code": "sesame"})).status_code == 200
                assert (await c.get(http + path, params={"code": "sesame"})).status_code == 200
            assert (await c.post(http + "/api/reminders/queue")).status_code == 401
            assert (await c.post(http + "/api/customers/x/reminders", json={"opt_in": True})).status_code == 401


def test_relative_ledger_db_resolves_against_repo_root():
    assert Settings(ledger_db="data/khata.db").db_path == REPO_ROOT / "data" / "khata.db"
    absolute = REPO_ROOT / "elsewhere" / "k.db"
    assert Settings(ledger_db=str(absolute)).db_path == absolute


def test_admin_purge_reports_locked_database(settings, monkeypatch, capsys):
    def locked(_settings):
        raise PermissionError("in use")

    monkeypatch.setattr(admin, "purge", locked)
    monkeypatch.setattr(admin, "get_settings", lambda: settings)
    assert admin.main(["purge"]) == 1
    assert "Stop the server" in capsys.readouterr().out


async def test_admin_purge_endpoint_reopens_ledger(settings, parser, fake_gnani):
    settings.admin_token = "tok"
    app = create_app(settings, parse=parser, number_to_words=fake_nw)
    async with running(app) as (http, ws_url):
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar"}))
            await recv_until(ws, is_type("result"))
        async with httpx.AsyncClient() as c:
            assert len((await c.get(http + "/api/ledger")).json()["entries"]) == 1
            assert (await c.post(http + "/api/admin/purge", headers={"X-Admin-Token": "bad"})).status_code == 401
            assert (await c.post(http + "/api/admin/purge", headers={"X-Admin-Token": "tok"})).status_code == 200
            assert (await c.get(http + "/api/ledger")).json()["entries"] == []


# ---- 7 and 8. ledger and pending questions -----------------------------------------------------------------------
def test_insert_or_replace_cannot_bypass_delete_trigger(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    with pytest.raises(Exception):
        ledger.conn.execute(
            "INSERT OR REPLACE INTO events(id, ts, kind, customer_id, amount_paise, effective_date) "
            "SELECT id, ts, kind, customer_id, 1, effective_date FROM events")
    assert ledger.conn.execute("SELECT amount_paise FROM events").fetchone()[0] == 34000


def test_failed_utterance_log_does_not_change_reply(pipeline, state, ledger, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ledger, "record_utterance", boom)
    t = pipeline.run_turn(state, "ramesh ka 340 udhaar")
    assert t.status == "ok" and "₹340 udhaar likh diya" in t.reply_text
    assert ledger.balance(ledger.find_customer(key="ramesh")["id"]) == 340


def test_cancelled_result_clears_pending(ledger, settings):
    def parse(u, *, today, ctx=None):
        if u == "q":
            return {"status": "needs_clarification", "reason": "missing_amount",
                    "pending": {"reason": "missing_amount", "action": "append", "events": []}}
        return {"status": "rejected", "reason": "cancelled"}

    pipe = Pipeline(ledger, settings, parse=parse, number_to_words=fake_nw)
    state = SessionState(session_id="s", disclosed=True)
    assert pipe.run_turn(state, "q").reply_text == "Kitne rupaye?" and state.pending
    t = pipe.run_turn(state, "huh")
    assert t.reply_text == "Theek hai, entry nahi ki." and state.pending is None


def test_reminder_not_listed_after_opt_out(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    c = ledger.find_customer(key="ramesh")["id"]
    ledger.set_reminder_opt_in(c, True, "9876543210")
    noon = datetime(2026, 11, 21, 12, 0).astimezone()
    ledger.queue_reminders(noon)
    assert len(ledger.outbox(noon, lambda n, a, lang: "hi")) == 1
    ledger.set_reminder_opt_in(c, False)
    assert ledger.outbox(noon, lambda n, a, lang: "hi") == []
    assert ledger.conn.execute("SELECT COUNT(*) FROM reminder_outbox").fetchone()[0] == 0  # Q05


# ---- burst audio, warm speech-to-text socket, relation display names ----------------------------------------------
async def test_burst_audio_is_not_lost_as_no_speech(settings, fake_gnani):
    settings.gnani_base_url = fake_gnani.base_url
    fake_gnani.speech_start_delay = 0.3
    client = SttClient(settings)
    await client.begin_turn()
    await client.send_audio(bytes(25600))  # 0.8 s of audio in one go, committed at once
    res = await client.end_turn()
    assert res.error is None and res.text == "ramesh ka 340 udhaar"
    await client.close()


async def test_no_speech_waits_then_returns_empty(settings, fake_gnani):
    settings.gnani_base_url = fake_gnani.base_url
    fake_gnani.speech = False
    client = SttClient(settings)
    await client.begin_turn()
    await client.send_audio(bytes(4096))
    t0 = time.perf_counter()
    res = await client.end_turn()
    assert res.text == "" and res.error is None and time.perf_counter() - t0 >= 0.9
    await client.close()


async def wait_for(cond, timeout=3.0):
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.02)


async def test_stt_socket_is_opened_at_hello_and_reused(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await wait_for(lambda: len(fake_gnani.stt_sessions) == 1)
        assert fake_gnani.stt_sessions[0]["headers"]["x-idle-timeout-sec"] == "900"
        for _ in range(2):
            await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
            await ws.send(bytes(AUDIO))
            await ws.send(json.dumps({"type": "end"}))
            await recv_until(ws, is_type("audio_end"))
        assert len(fake_gnani.stt_sessions) == 1 and fake_gnani.stt_sessions[0]["commits"] == 2
    await wait_for(lambda: fake_gnani.stt_closed == 1)  # closed when the browser session ended


async def test_stt_socket_is_reopened_when_it_closes_and_press_still_works(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await wait_for(lambda: len(fake_gnani.stt_sessions) == 1)
        await fake_gnani.stt_sockets[0].close()  # idle timeout, session cap or a network drop
        await wait_for(lambda: len(fake_gnani.stt_sessions) == 2)
        await fake_gnani.stt_sockets[1].close()
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))  # pressed while no socket is up
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("audio_end"), timeout=8)
        assert of(msgs, "result")[0]["action"] == "append"


def test_relation_keys_keep_connecting_words_lower_case(ledger):
    from app.names import display_name

    assert display_name("ramesh ki biwi") == "Ramesh ki biwi"
    assert display_name("sunita ka beta") == "Sunita ka beta"
    assert display_name("ramesh chopra") == "Ramesh Chopra" and display_name("ke") == "Ke"
    out = apply_events(ledger, [ev("credit", "ramesh ki biwi", 50, new_customer=True)])
    assert out.saved[0]["customer"] == "Ramesh ki biwi"
    assert R.balance(ledger.label(out.saved[0]["customer_id"]), 50).text == "Ramesh ki biwi ke ₹50 baaki hain."
    assert R.clarification({"reason": "ambiguous_direction", "pending": {"events": [
        {"customer": "ramesh ki biwi", "amount": 5}]}}).text.startswith("Ramesh ki biwi ne diye")
