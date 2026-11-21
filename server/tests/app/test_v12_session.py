"""CONTRACT v1.2 session rules (section 3.3) over a real WebSocket against the fake Gnani server."""
from __future__ import annotations

import asyncio
import json

import httpx
import websockets

from app import session as session_module

from .test_session import AUDIO, hello, is_type, of, recv_until


async def entries(server):
    async with httpx.AsyncClient() as c:
        return (await c.get(server.http + "/api/ledger")).json()["entries"]


async def press(ws, n_bytes=AUDIO, **start):
    await ws.send(json.dumps({"type": "start", "mode": "ptt", **start}))
    await ws.send(bytes(n_bytes))
    await ws.send(json.dumps({"type": "end", "client_ts": "2026-11-21T10:00:00+05:30"}))


async def test_K01_O02_text_retry_with_same_utt_id_saves_once(server, ledger):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        for i in range(2):
            await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar", "utt_id": "tap-1",
                                      "client_ts": "2026-11-21T09:59:00+05:30"}))
            msgs = await recv_until(ws, is_type("audio_end", turn_id=i + 1))
            result = of(msgs, "result")[0]
            assert result["status"] == "ok" and result["entries"][0]["amount"] == 340
            assert result.get("duplicate", False) is (i == 1)
    assert len(await entries(server)) == 1


async def test_M08_audio_retry_with_same_utt_id_saves_once(server, settings):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        for i in range(2):
            await press(ws, utt_id="press-7")
            msgs = await recv_until(ws, is_type("audio_end", turn_id=i + 1))
            assert of(msgs, "result")[0].get("duplicate", False) is (i == 1)
    assert len(await entries(server)) == 1


async def test_L05_resume_drops_open_question_and_returns_last_result(server):
    async with websockets.connect(server.url) as ws:
        sid = of(await hello(ws), "ready")[0]["session_id"]
        await ws.send(json.dumps({"type": "text", "text": "ramesh 340"}))
        await recv_until(ws, is_type("audio_end", turn_id=1))
    async with websockets.connect(server.url) as ws:
        await ws.send(json.dumps({"type": "hello", "resume": sid}))
        ready = (await recv_until(ws, is_type("ready")))[-1]
        assert ready["last_turn_id"] == 1 and ready["last_result"]["question"] == "Ramesh ne diye, ya Ramesh ko udhaar?"
        await ws.send(json.dumps({"type": "text", "text": "udhaar"}))
        msgs = await recv_until(ws, is_type("result"))
        assert msgs[-1]["status"] == "rejected" and msgs[-1]["turn_id"] == 2
    assert await entries(server) == []


async def test_N08_P06_private_mode_keeps_answers_on_screen(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws, private=True)
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
        assert "<340>" in fake_gnani.tts_requests[-1]["text"]  # an entry is still read back
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka total"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=2))
        assert of(msgs, "result")[0]["reply_text"] == "Ramesh ke ₹340 baaki hain."
        assert fake_gnani.tts_requests[-1]["text"] == "जवाब स्क्रीन पर है।"
        await ws.send(json.dumps({"type": "settings", "private": False}))
        assert (await recv_until(ws, is_type("settings")))[-1]["private"] is False
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka total"}))
        await recv_until(ws, is_type("audio_end", turn_id=3))
        assert "<340>" in fake_gnani.tts_requests[-1]["text"]


async def test_M07_recording_cut_at_30_seconds_saves_nothing(server, monkeypatch):
    monkeypatch.setattr(session_module, "MAX_AUDIO_BYTES", 20000)
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        for _ in range(3):
            await ws.send(bytes(8000))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
        result = of(msgs, "result")[0]
        assert result["reason"] == "too_long" and result["action"] == "none"
        assert result["reply_text"] == "Bahut lamba ho gaya. Chhote vaakya mein boliye."
        await ws.send(json.dumps({"type": "end"}))  # the release after the cut starts nothing
        await asyncio.sleep(0.3)
    assert await entries(server) == []


async def test_M01_speech_with_empty_transcript_gets_rejected_reply(server, fake_gnani):
    fake_gnani.transcripts = []  # no partial transcript
    fake_gnani.scripts = [[""]]
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await press(ws)
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
        result = of(msgs, "result")[0]
        assert result["reason"] == "empty_transcript"
        assert result["reply_text"] == "Maaf kijiye, samajh nahi aaya. Dobara boliye."


async def test_M09_no_final_transcript_within_wait_is_upstream_failure(server, fake_gnani, monkeypatch):
    monkeypatch.setattr(session_module, "FINAL_WAIT_S", 0.4)
    fake_gnani.final_delay = 1.2
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await press(ws)
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
        result = of(msgs, "result")[0]
        assert result["reason"] == "upstream" and result["reply_text"] == "Network mein dikkat hai, dobara boliye."
        await asyncio.sleep(1.2)  # the late transcript arrives and is not saved
    assert await entries(server) == []


async def test_M10_start_during_reply_keeps_the_save_and_cancels_speech(server, fake_gnani):
    fake_gnani.tts_chunks = 30
    fake_gnani.tts_chunk_delay = 0.03
    async with websockets.connect(server.url) as ws:
        await ws.send(json.dumps({"type": "hello"}))
        await recv_until(ws, is_type("audio_end", turn_id=0), timeout=10)
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar"}))
        msgs = await recv_until(ws, lambda m: isinstance(m, tuple))
        assert of(msgs, "result")[0]["entries"][0]["amount"] == 340
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        msgs = await recv_until(ws, is_type("state", state="listening"))
        assert any(m.get("cancelled") for m in of(msgs, "audio_end"))
        await ws.send(json.dumps({"type": "cancel"}))
    assert [e["amount"] for e in await entries(server)] == [340]


async def test_M10_start_during_transcription_drops_the_earlier_turn(server, fake_gnani):
    fake_gnani.scripts = [["ramesh ka 340 udhaar"], ["sunita ne 150 diye"]]
    fake_gnani.final_delay = 0.6
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await press(ws)
        await asyncio.sleep(0.1)
        await press(ws)
        msgs = await recv_until(ws, is_type("audio_end", turn_id=2))
        assert all(m["turn_id"] == 2 for m in of(msgs, "result"))
        await asyncio.sleep(0.8)
    assert [e["amount"] for e in await entries(server)] == [150]


async def test_C09_device_clock_is_kept_separately(server, ledger):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await press(ws, utt_id="p-ts")
        await recv_until(ws, is_type("audio_end", turn_id=1))
    rec = ledger.find_utterance("p-ts")
    assert rec["device_ts"] == "2026-11-21T10:00:00+05:30"
    row = ledger.conn.execute("SELECT ts FROM events").fetchone()
    assert row["ts"] != rec["device_ts"]


async def test_cancel_during_recording_closes_turn_without_speech(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        n_tts = len(fake_gnani.tts_requests)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "cancel"}))
        msgs = await recv_until(ws, is_type("result"))
        assert msgs[-1]["turn_id"] == 1 and msgs[-1]["action"] == "none" and msgs[-1]["reply_text"] == ""
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        msgs = await recv_until(ws, is_type("state", state="listening"))
        assert msgs[-1]["turn_id"] == 2
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=2))
        assert of(msgs, "result")[0]["action"] == "append"
        assert len(fake_gnani.tts_requests) == n_tts + 1  # only the second turn spoke
    assert len(await entries(server)) == 1


async def test_duplicate_result_is_the_first_result_with_the_flag(server):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        results = []
        for i in range(2):
            await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar", "utt_id": "dup-9"}))
            results.append(of(await recv_until(ws, is_type("audio_end", turn_id=i + 1)), "result")[0])
    first, again = results
    assert again.pop("duplicate") is True and again.pop("turn_id") == 2 and first.pop("turn_id") == 1
    assert again == first


async def test_hello_without_resume_is_always_a_fresh_session_with_greeting(server):
    async with websockets.connect(server.url) as ws:
        sid = of(await hello(ws), "ready")[0]["session_id"]
        await ws.send(json.dumps({"type": "text", "text": "ramesh 340"}))
        await recv_until(ws, is_type("audio_end", turn_id=1))
        msgs = await hello(ws)  # the same socket says hello again
        assert of(msgs, "ready")[0]["session_id"] != sid and of(msgs, "result")[0]["action"] == "greeting"
        await ws.send(json.dumps({"type": "text", "text": "udhaar"}))  # the old question is gone
        assert (await recv_until(ws, is_type("result")))[-1]["status"] == "rejected"
    async with websockets.connect(server.url) as ws:
        msgs = await hello(ws)
        assert of(msgs, "ready")[0]["session_id"] != sid and of(msgs, "result")[0]["turn_id"] == 0


async def test_M10_quick_second_press_with_burst_audio_is_never_lost(server, fake_gnani):
    """The second press comes before the first turn has committed; the first turn is dropped, the second saved."""
    fake_gnani.scripts = [["ramesh ka 340 udhaar"], ["sunita ne 150 diye"]]
    fake_gnani.final_delay = 0.6
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))  # at once: turn 1 has not committed yet
        await ws.send(bytes(AUDIO))
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=2), timeout=8)
        result = of(msgs, "result")[-1]
        assert result["turn_id"] == 2 and result["status"] == "ok"
        assert result["entries"][0]["customer"]["display"] == "Sunita"
        await asyncio.sleep(0.8)
    assert [e["amount"] for e in await entries(server)] == [150]


def test_P05_websockets_library_loggers_are_kept_at_warning(settings, parser):
    import logging

    from app.main import create_app

    from .conftest import fake_nw

    logging.getLogger("websockets").setLevel(logging.DEBUG)
    logging.getLogger("websockets.client").setLevel(logging.DEBUG)
    create_app(settings, parse=parser, number_to_words=fake_nw)
    for name in ("websockets", "websockets.client", "websockets.server"):
        assert not logging.getLogger(name).isEnabledFor(logging.DEBUG), name


async def test_default_parser_is_warmed_at_start_up_and_injected_one_is_not(settings, parser, monkeypatch):
    import nlu.parser

    from app.main import create_app

    from .conftest import fake_nw
    from .test_review_fixes import running

    calls = []
    monkeypatch.setattr(nlu.parser, "warm", lambda: calls.append(1))
    async with running(create_app(settings, number_to_words=fake_nw)):
        assert calls == [1]
    async with running(create_app(settings, parse=parser, number_to_words=fake_nw)):
        assert calls == [1]


async def test_P05_no_logger_records_a_name_transcript_or_amount_at_debug(server, fake_gnani, ledger, caplog):
    """Root and websockets loggers at DEBUG; a full voice turn and a typed turn for a customer in the roster."""
    import logging

    secret_name, secret_amount = "zorbaxian", "7341"
    ledger.create_customer(secret_name)
    fake_gnani.transcripts = [f"{secret_name} ka {secret_amount} udhaar"]
    server_parser = server.config.app.state.ctx.pipeline.parse
    server_parser.canned[f"{secret_name} ka {secret_amount} udhaar"] = lambda today, ctx: {
        "status": "ok", "action": "append",
        "events": [{"kind": "credit", "customer": secret_name, "amount": int(secret_amount),
                    "date": today.isoformat()}]}
    caplog.set_level(logging.DEBUG)
    for name in ("websockets", "websockets.client", "websockets.server", "websockets.protocol", "uvicorn",
                 "uvicorn.error", "httpx"):
        caplog.set_level(logging.DEBUG, logger=name)
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await press(ws)
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
        assert of(msgs, "result")[0]["entries"][0]["amount"] == int(secret_amount)
        await ws.send(json.dumps({"type": "text", "text": f"{secret_name} ka {secret_amount} udhaar"}))
        await recv_until(ws, is_type("audio_end", turn_id=2))
    records = "\n".join(f"{r.name}: {r.getMessage()} {r.exc_text or ''}" for r in caplog.records
                        if not r.name.startswith("fake_gnani"))  # the test double, not the app
    assert caplog.records  # the loggers were live
    for secret in (secret_name, secret_name.capitalize(), secret_amount, "udhaar", "उधार"):
        assert secret not in records, secret
