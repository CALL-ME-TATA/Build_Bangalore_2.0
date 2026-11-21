"""Session protocol over a real WebSocket, against a fake Gnani server and a fake parser."""
from __future__ import annotations

import asyncio
import json

import httpx
import websockets


async def get(url):
    async with httpx.AsyncClient() as c:
        return await c.get(url)


async def recv_until(ws, pred, timeout=5.0):
    """Collect messages (JSON dicts, or ('bin', n) for audio frames) until pred(msg) is true."""
    out = []
    async with asyncio.timeout(timeout):
        while True:
            raw = await ws.recv()
            msg = ("bin", len(raw)) if isinstance(raw, bytes) else json.loads(raw)
            out.append(msg)
            if pred(msg):
                return out


def is_type(t, **kw):
    return lambda m: isinstance(m, dict) and m.get("type") == t and all(m.get(k) == v for k, v in kw.items())


async def hello(ws, **extra):
    await ws.send(json.dumps({"type": "hello", "lang": "hi", **extra}))
    return await recv_until(ws, is_type("audio_end"))


def of(msgs, t):
    return [m for m in msgs if isinstance(m, dict) and m.get("type") == t]


async def test_greeting_carries_disclosure(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        msgs = await hello(ws)
        assert of(msgs, "ready")[0]["session_id"]
        result = of(msgs, "result")[0]
        assert result["action"] == "greeting" and result["turn_id"] == 0
        assert "ek AI sahayak" in result["reply_text"]
        assert any(m[0] == "bin" for m in msgs if isinstance(m, tuple))
        assert of(msgs, "audio_start")[0]["sample_rate"] == 24000
        assert of(msgs, "audio_end")[0]["turn_id"] == 0
        assert fake_gnani.tts_requests[0]["model"] == "timbre-v3.0"
        assert "AI" in fake_gnani.tts_requests[0]["text"] or "एआई" in fake_gnani.tts_requests[0]["text"]
        assert fake_gnani.tts_headers[0]["x-api-key-id"] == "test-key"


async def test_text_turn_returns_result_audio_and_timing(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "text", "text": "Ramesh ka 340 udhaar"}))
        msgs = await recv_until(ws, is_type("audio_end"))
        result = of(msgs, "result")[0]
        assert result["turn_id"] == 1 and result["status"] == "ok" and result["action"] == "append"
        assert result["entries"][0]["amount"] == 340 and result["entries"][0]["customer"]["display"] == "Ramesh"
        assert result["reply_text"] == "Naya khata Ramesh. Ramesh ke khate mein ₹340 udhaar likh diya."
        order = [m["type"] if isinstance(m, dict) else "bin" for m in msgs if not is_type("state")(m)]
        assert order.index("result") < order.index("audio_start") < order.index("bin")
        timing = of(msgs, "timing")[0]
        assert timing["trace_id"] == result["trace_id"]
        assert timing["ms"]["end_to_first_audio"] > 0 and timing["ms"]["tts_first_chunk"] is not None
        assert timing["ms"]["parse"] is not None and timing["ms"]["db"] is not None
        assert "<340>" in fake_gnani.tts_requests[-1]["text"]
        r = await get(server.http + "/api/ledger")
        assert r.json()["entries"][0]["amount"] == 340 and r.json()["totals"]["credit_today"] == 340


async def test_audio_turn_reframes_and_commits(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await recv_until(ws, is_type("state", state="listening"))
        for _ in range(5):
            await ws.send(bytes(700))  # 3,500 bytes: three full frames and a partial one
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("audio_end"))
        states = [m["state"] for m in of(msgs, "state")]
        assert "transcribing" in states and "thinking" in states and "speaking" in states
        transcript = of(msgs, "transcript")[-1]
        assert transcript["final"] is True and transcript["text"] == "ramesh ka 340 udhaar"
        assert of(msgs, "result")[0]["action"] == "append"
        assert of(msgs, "timing")[0]["ms"]["gnani_stt_latency"] == 123
        sess = fake_gnani.stt_sessions[0]
        assert sess["frames"] == [1024, 1024, 1024, 1024] and sess["commits"] == 1
        assert sess["headers"]["model"] == "prisma-v3.0" and sess["headers"]["x-sample-rate"] == "16000"
        assert sess["headers"]["format"] == "transliterate" and "udhaar" in sess["headers"]["keyterms"]
        # The socket is reused for the next turn.
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(1024))
        await ws.send(json.dumps({"type": "end"}))
        await recv_until(ws, is_type("audio_end"))
        assert len(fake_gnani.stt_sessions) == 1 and fake_gnani.stt_sessions[0]["commits"] == 2


async def test_barge_in_cancels_audio(server, fake_gnani):
    fake_gnani.tts_chunks = 30
    fake_gnani.tts_chunk_delay = 0.05
    async with websockets.connect(server.url) as ws:
        await ws.send(json.dumps({"type": "hello"}))
        await recv_until(ws, lambda m: isinstance(m, tuple))  # first audio frame of the greeting
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        msgs = await recv_until(ws, is_type("state", state="listening"))
        cancelled = [m for m in msgs if is_type("audio_end")(m)]
        assert cancelled and cancelled[0]["cancelled"] is True and cancelled[0]["turn_id"] == 0
        assert msgs[-1]["turn_id"] == 1
        # No more greeting audio arrives after the cancel.
        await ws.send(json.dumps({"type": "cancel"}))
        later = await recv_until(ws, is_type("state", state="idle", turn_id=1))
        assert not any(isinstance(m, tuple) for m in later)
        await asyncio.sleep(0.2)
        assert fake_gnani.tts_closed >= 1  # the TTS socket was dropped


async def test_no_speech_returns_action_none(server, fake_gnani):
    fake_gnani.speech = False
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(2048))
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("result"))
        assert msgs[-1]["action"] == "none" and msgs[-1]["entries"] == []
        await asyncio.sleep(0.2)
        n_tts = len(fake_gnani.tts_requests)
        await ws.send(json.dumps({"type": "ping", "t": 7}))
        pong = await recv_until(ws, is_type("pong"))
        assert pong[-1]["t"] == 7 and not any(isinstance(m, tuple) for m in pong)
        assert len(fake_gnani.tts_requests) == n_tts


async def test_resume_keeps_session_without_greeting(server):
    async with websockets.connect(server.url) as ws:
        msgs = await hello(ws)
        sid = of(msgs, "ready")[0]["session_id"]
        await ws.send(json.dumps({"type": "text", "text": "ramesh 340"}))
        await recv_until(ws, is_type("audio_end"))
    async with websockets.connect(server.url) as ws:
        await ws.send(json.dumps({"type": "hello", "resume": sid}))
        ready = await recv_until(ws, is_type("ready"))
        assert ready[-1]["session_id"] == sid
        await ws.send(json.dumps({"type": "text", "text": "udhaar"}))
        msgs = await recv_until(ws, is_type("result"))
        assert msgs[-1]["status"] == "ok" and msgs[-1]["turn_id"] == 2
        assert not any(m.get("action") == "greeting" for m in msgs if isinstance(m, dict))


async def test_access_code_required(settings, parser, fake_gnani):
    import uvicorn

    from app.main import create_app

    from .conftest import fake_nw

    settings.access_code = "sesame"
    settings.gnani_base_url = fake_gnani.base_url
    app = create_app(settings, parse=parser, number_to_words=fake_nw)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.01)
    url = f"ws://127.0.0.1:{srv.servers[0].sockets[0].getsockname()[1]}/ws/session"
    try:
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({"type": "hello", "access_code": "wrong"}))
            msgs = await recv_until(ws, is_type("error"))
            assert msgs[-1]["code"] == "access_denied"
        async with websockets.connect(url) as ws:
            msgs = await hello(ws, access_code="sesame")
            assert of(msgs, "ready")
    finally:
        srv.should_exit = True
        await task


async def test_rest_endpoints_and_purge(server, settings):
    assert (await get(server.http + "/api/health")).json()["ok"] is True
    assert (await get(server.http + "/")).status_code == 200
    assert (await get(server.http + "/api/customers")).json() == {"customers": []}
    # Purge is disabled while ADMIN_TOKEN is unset.
    async with httpx.AsyncClient() as c:
        assert (await c.post(server.http + "/api/admin/purge")).status_code == 403


async def test_partials_header_and_vocabulary(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        await ws.send(bytes(2048))
        await ws.send(json.dumps({"type": "end"}))
        msgs = await recv_until(ws, is_type("audio_end"))
        assert fake_gnani.stt_sessions[0]["headers"]["x-partials"] == "true"
        assert fake_gnani.stt_sessions[0]["headers"]["language_code"] == "hi-IN"
        transcripts = of(msgs, "transcript")
        assert [t["final"] for t in transcripts].count(True) == 1 and transcripts[-1]["final"] is True
        assert transcripts[0]["final"] is False and transcripts[0]["text"] == "ramesh"
        assert transcripts[-1]["text"] == "ramesh ka 340 udhaar"
        assert "transcribing" in [m["state"] for m in of(msgs, "state")]
        assert of(msgs, "result")[0]["action"] == "append"


async def test_legacy_vocabulary_without_partials(settings, parser, fake_gnani):
    import uvicorn

    from app.main import create_app

    from .conftest import fake_nw

    settings.stt_partials = False
    settings.gnani_base_url = fake_gnani.base_url
    app = create_app(settings, parse=parser, number_to_words=fake_nw)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.01)
    url = f"ws://127.0.0.1:{srv.servers[0].sockets[0].getsockname()[1]}/ws/session"
    try:
        async with websockets.connect(url) as ws:
            await hello(ws)
            await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
            await ws.send(bytes(2048))
            await ws.send(json.dumps({"type": "end"}))
            msgs = await recv_until(ws, is_type("audio_end"))
            assert "x-partials" not in fake_gnani.stt_sessions[0]["headers"]
            assert of(msgs, "transcript")[-1]["text"] == "ramesh ka 340 udhaar"
            assert of(msgs, "transcript")[-1]["final"] is True
    finally:
        srv.should_exit = True
        await task


async def test_second_reply_on_same_tts_socket_has_audio(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        for text in ("sunita ne 150 diye", "ramesh ka 340 udhaar", "ramesh ka total"):
            await ws.send(json.dumps({"type": "text", "text": text}))
            msgs = await recv_until(ws, is_type("audio_end"))
            assert [m for m in msgs if isinstance(m, tuple)], text
            assert not of(msgs, "error")
        assert len(fake_gnani.tts_headers) == 1  # one warm socket served every reply
