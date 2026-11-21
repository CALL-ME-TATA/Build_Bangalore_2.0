"""Whole turns over /ws/session against the real app (app.main:app) with Gnani replaced by the mock server.

Each test opens its own session. The ledger is shared by the tests in this module, so every test that
checks balances uses customer names no other test uses. The module is skipped while app.main cannot be imported.
"""
from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import struct
import tempfile

import httpx
import pytest
import pytest_asyncio
from websockets.asyncio.client import connect

from mock_gnani.testing import serve_app, start_mock

pytestmark = pytest.mark.asyncio(loop_scope="module")

SAMPLE_RATE = 16000
CHUNK_BYTES = 640  # 20 ms of 16 kHz PCM16; the server re-frames to 1,024 bytes for Gnani
TIMING_KEYS = {"stt_final", "parse", "db", "tts_first_chunk", "end_to_first_audio", "gnani_stt_latency"}


def pcm_audio(ms: int = 800) -> bytes:
    n = SAMPLE_RATE * ms // 1000
    return struct.pack(f"<{n}h", *[int(2000 * ((i // 40) % 2 * 2 - 1)) for i in range(n)])


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def stack():
    mock_url, stop_mock = await start_mock()
    tmp = tempfile.TemporaryDirectory()
    env = {
        "GNANI_BASE_URL": mock_url,
        "GNANI_API_KEY": "test-key",
        "LEDGER_DB": os.path.join(tmp.name, "khata.db"),
        "LEDGER_KEY": base64.b64encode(b"k" * 32).decode(),
        "SHOP_TZ": "Asia/Kolkata",
    }
    saved = {k: os.environ.get(k) for k in [*env, "ACCESS_CODE", "ADMIN_TOKEN"]}
    os.environ.update(env)
    os.environ.pop("ACCESS_CODE", None)
    try:
        main = importlib.import_module("app.main")
    except ImportError as exc:
        pytest.skip(f"app.main cannot be imported yet: {exc}")
    app_url, stop_app = await serve_app(main.app, lifespan="auto")
    async with httpx.AsyncClient(base_url=mock_url) as mock_http:
        yield {"mock_url": mock_url, "app_url": app_url, "mock": mock_http}
    await stop_app()
    await stop_mock()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    tmp.cleanup()


class Client:
    def __init__(self, ws, stack):
        self.ws = ws
        self.stack = stack
        self.session_id = None
        self.pending: list = []

    @classmethod
    async def open(cls, stack, resume=None):
        ws = await connect("ws" + stack["app_url"][4:] + "/ws/session", max_size=None)
        client = cls(ws, stack)
        hello = {"type": "hello", "lang": "hi"}
        if resume:
            hello["resume"] = resume
        await ws.send(json.dumps(hello))
        return client

    async def script(self, **body):
        r = await self.stack["mock"].post("/__mock/script", json=body)
        r.raise_for_status()

    async def recv(self, timeout=10.0):
        raw = await asyncio.wait_for(self.ws.recv(), timeout)
        return raw if isinstance(raw, bytes) else json.loads(raw)

    async def collect_turn(self, timeout=10.0, expect_audio=True):
        """Read messages until the turn has a result, its audio has ended and its timing has arrived."""
        out = {"msgs": [], "frames": 0, "result": None, "audio_start": None, "audio_end": None, "timing": None}
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AssertionError(f"turn did not complete; messages so far: {out['msgs']}")
            msg = await self.recv(remaining)
            if isinstance(msg, bytes):
                out["frames"] += 1
                continue
            out["msgs"].append(msg)
            t = msg["type"]
            if t == "ready":
                self.session_id = msg["session_id"]
            elif t == "result":
                out["result"] = msg
            elif t == "audio_start":
                out["audio_start"] = msg
            elif t == "audio_end":
                out["audio_end"] = msg
            elif t == "timing":
                out["timing"] = msg
            elif t == "error":
                raise AssertionError(f"server error: {msg}")
            done = out["result"] is not None and (
                (out["audio_end"] is not None and out["timing"] is not None)
                or (not expect_audio and out["result"]["action"] == "none")
            )
            if done:
                return out

    async def greet(self):
        turn = await self.collect_turn()
        ready = next(m for m in turn["msgs"] if m["type"] == "ready")
        self.session_id = ready["session_id"]
        return turn

    async def speak(self, transcript, **script):
        await self.script(transcripts=[transcript], **script)
        await self.ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        audio = pcm_audio()
        for i in range(0, len(audio), CHUNK_BYTES):
            await self.ws.send(audio[i:i + CHUNK_BYTES])
        await self.ws.send(json.dumps({"type": "end"}))
        return await self.collect_turn()

    async def close(self):
        await self.ws.close()


@pytest_asyncio.fixture(loop_scope="module")
async def client(stack):
    c = await Client.open(stack)
    yield c
    await c.close()


@pytest_asyncio.fixture(loop_scope="module")
async def greeted(client):
    await client.script(tts_chunk_ms=5)
    client.greeting = await client.greet()
    return client


async def ledger(stack):
    async with httpx.AsyncClient(base_url=stack["app_url"]) as http:
        customers = (await http.get("/api/customers")).json()["customers"]
        entries = (await http.get("/api/ledger", params={"limit": 200})).json()["entries"]
    return customers, entries


def balance_of(customers, display):
    return [c["balance"] for c in customers if c["display"].lower() == display]


# ---- tests ----------------------------------------------------------------------------------------

async def test_greeting_discloses_ai(client):
    turn = await client.greet()
    result = turn["result"]
    assert result["action"] == "greeting"
    assert result["turn_id"] == 0
    assert "AI" in result["reply_text"]
    assert result["entries"] == []
    assert turn["audio_start"]["sample_rate"] == 24000
    assert turn["frames"] > 0
    assert turn["audio_end"]["turn_id"] == 0


async def test_credit_by_voice_returns_result_audio_and_timing(greeted, stack):
    await greeted.script(tts_chunk_ms=5)
    turn = await greeted.speak("kavita ka 340 udhaar")
    result = turn["result"]
    assert result["status"] == "ok" and result["action"] == "append"
    assert result["turn_id"] == 1
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["kind"] == "credit" and entry["amount"] == 340 and entry["customer"]["display"].lower() == "kavita"
    assert "340" in result["reply_text"]
    assert turn["frames"] > 0
    assert turn["audio_start"]["turn_id"] == 1 and turn["audio_end"]["turn_id"] == 1
    assert not turn["audio_end"].get("cancelled")
    ms = turn["timing"]["ms"]
    assert TIMING_KEYS <= set(ms)
    assert ms["end_to_first_audio"] > 0
    transcripts = [m for m in turn["msgs"] if m["type"] == "transcript"]
    assert transcripts and transcripts[-1]["final"] is True and transcripts[-1]["text"] == "kavita ka 340 udhaar"
    assert not any(t["final"] for t in transcripts[:-1])
    customers, _ = await ledger(stack)
    assert balance_of(customers, "kavita") == [340]
    log = (await stack["mock"].get("/__mock/log")).json()
    assert all(s["bad_frames"] == 0 for s in log["stt_sessions"])


async def test_amend_add_payment_and_balance_chain(greeted, stack):
    c = greeted
    t1 = await c.speak("ramesh ka 340 udhaar")
    assert t1["result"]["entries"][0]["amount"] == 340

    t2 = await c.speak("nahi 430")
    r2 = t2["result"]
    assert r2["status"] == "ok" and r2["action"] == "amend"
    old, new = r2["entries"]
    assert old["reversed"] is True and old["amount"] == 340
    assert new["reversed"] is False and new["amount"] == 430 and new["kind"] == "credit"
    assert r2["turn_id"] == 2

    t3 = await c.speak("aur 200 payment mila")
    r3 = t3["result"]
    assert r3["action"] == "append" and len(r3["entries"]) == 1
    assert r3["entries"][0]["kind"] == "payment" and r3["entries"][0]["amount"] == 200
    assert r3["entries"][0]["customer"]["display"].lower() == "ramesh"

    t4 = await c.speak("ramesh ka total")
    r4 = t4["result"]
    assert r4["action"] == "query" and r4["entries"] == []
    assert "230" in r4["reply_text"]
    customers, _ = await ledger(stack)
    assert balance_of(customers, "ramesh") == [230]


async def test_undo_chain_walks_back(greeted, stack):
    c = greeted
    await c.speak("geeta ka 100 udhaar")
    await c.speak("geeta ka 50 udhaar")
    u1 = await c.speak("undo karo")
    assert u1["result"]["action"] == "undo"
    assert [e["reversed"] for e in u1["result"]["entries"]] == [True]
    assert u1["result"]["entries"][0]["amount"] == 50
    u2 = await c.speak("undo karo")
    assert u2["result"]["entries"][0]["amount"] == 100
    customers, _ = await ledger(stack)
    assert balance_of(customers, "geeta") == [0]


async def test_compound_utterance_from_two_segments(greeted, stack):
    turn = await greeted.speak(["mohan ka 100 udhaar", "sunita ne 40 diye"])
    result = turn["result"]
    transcripts = [m for m in turn["msgs"] if m["type"] == "transcript"]
    assert transcripts[-1]["final"] is True and transcripts[-1]["text"] == "mohan ka 100 udhaar sunita ne 40 diye"
    assert not any(t["final"] for t in transcripts[:-1])
    assert result["status"] == "ok"
    kinds = [(e["customer"]["display"].lower(), e["kind"], e["amount"]) for e in result["entries"]]
    assert kinds == [("mohan", "credit", 100), ("sunita", "payment", 40)]


async def test_needs_clarification_saves_nothing(greeted, stack):
    before = await ledger(stack)
    turn = await greeted.speak("anil ko udhaar")
    result = turn["result"]
    assert result["status"] == "needs_clarification" and result["reason"] == "missing_amount"
    assert result["entries"] == [] and result["question"]
    assert turn["frames"] > 0  # the question is spoken
    assert await ledger(stack) == before
    answer = await greeted.speak("do sau")
    assert answer["result"]["status"] == "ok"
    assert answer["result"]["entries"][0]["amount"] == 200


async def test_same_name_question_and_answer(greeted, stack):
    c = greeted
    a = await c.speak("pooja chai wale ka 100 udhaar")
    assert a["result"]["status"] == "ok"
    b = await c.speak("pooja gali number 3 ka 50 udhaar")
    assert b["result"]["status"] == "ok"
    first_id = a["result"]["entries"][0]["customer"]["id"]
    second_id = b["result"]["entries"][0]["customer"]["id"]
    assert first_id != second_id

    q = await c.speak("pooja ka 200 udhaar")
    assert q["result"]["status"] == "needs_clarification" and q["result"]["reason"] == "same_name"
    assert q["result"]["entries"] == [] and q["result"]["question"]

    ans = await c.speak("chai wale")
    assert ans["result"]["status"] == "ok"
    entry = ans["result"]["entries"][0]
    assert entry["customer"]["id"] == first_id and entry["amount"] == 200 and entry["kind"] == "credit"
    customers, _ = await ledger(stack)
    balances = {c_["id"]: c_["balance"] for c_ in customers}
    assert balances[first_id] == 300 and balances[second_id] == 50


async def test_text_message_uses_the_same_pipeline(greeted, stack):
    await greeted.ws.send(json.dumps({"type": "text", "text": "naveen ne 90 diye"}))
    turn = await greeted.collect_turn()
    assert turn["result"]["entries"][0]["kind"] == "payment"
    assert turn["result"]["entries"][0]["amount"] == 90


async def test_silence_ends_with_action_none_and_no_audio(greeted):
    await greeted.script(transcripts=["should not be used"])
    await greeted.ws.send(json.dumps({"type": "start", "mode": "ptt"}))
    await greeted.ws.send(json.dumps({"type": "end"}))
    turn = await greeted.collect_turn(expect_audio=False)
    assert turn["result"]["action"] == "none"
    assert turn["frames"] == 0 and turn["audio_start"] is None


async def test_barge_in_cancels_reply_audio(greeted):
    c = greeted
    await c.script(tts_chunk_ms=60, tts_first_chunk_delay_ms=0)
    await c.ws.send(json.dumps({"type": "text", "text": "farhan ka 340 udhaar"}))
    turn_id = None
    while True:
        msg = await c.recv()
        if isinstance(msg, bytes):
            break  # first reply audio frame
        if msg["type"] == "audio_start":
            turn_id = msg["turn_id"]
    await c.ws.send(json.dumps({"type": "start", "mode": "ptt"}))
    frames_after = 0
    cancelled = None
    deadline = asyncio.get_running_loop().time() + 5
    while cancelled is None and asyncio.get_running_loop().time() < deadline:
        msg = await c.recv(5)
        if isinstance(msg, bytes):
            frames_after += 1
        elif msg["type"] == "audio_end" and msg["turn_id"] == turn_id:
            cancelled = msg.get("cancelled")
    assert cancelled is True
    assert frames_after < 10  # the reply is 25+ chunks long; most of it must not be sent
    await c.script(tts_chunk_ms=5)


async def test_resume_keeps_session_without_greeting(stack):
    c = await Client.open(stack)
    try:
        await c.script(tts_chunk_ms=5)
        await c.greet()
        await c.speak("rekha ka 120 udhaar")
        sid = c.session_id
    finally:
        await c.close()
    c2 = await Client.open(stack, resume=sid)
    try:
        msg = await c2.recv()
        assert msg["type"] == "ready" and msg["session_id"] == sid
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            while True:
                extra = await c2.recv(timeout=1.0)
                assert not (isinstance(extra, dict) and extra.get("action") == "greeting")
        # the resumed session still knows the last entry, so "aur 80" carries the customer
        turn = await c2.speak("aur 80")
        assert turn["result"]["entries"][0]["customer"]["display"].lower() == "rekha"
    finally:
        await c2.close()


async def test_ping_pong(greeted):
    await greeted.ws.send(json.dumps({"type": "ping", "t": 7}))
    while True:
        msg = await greeted.recv()
        if isinstance(msg, dict) and msg["type"] == "pong":
            assert msg.get("t") == 7
            return
