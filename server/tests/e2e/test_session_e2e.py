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
    """Audio as the page sends it: 8 frames (256 ms) of near-silence before the press (the pre-roll), the tone as
    speech, then 9 frames of near-silence (the tail). A recording under half a second is sent without padding."""
    n = SAMPLE_RATE * ms // 1000
    tone = [int(2000 * ((i // 40) % 2 * 2 - 1)) for i in range(n)]
    if ms < 500:
        return struct.pack(f"<{n}h", *tone)
    quiet = lambda frames: [20 if (i // 7) % 2 else -20 for i in range(512 * frames)]  # noqa: E731
    samples = quiet(8) + tone + quiet(9)
    return struct.pack(f"<{len(samples)}h", *samples)

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
        "CONFIRM_NEW_CUSTOMER": "0",  # the new-customer question is covered by tests/edge (E04, E09)
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
    async def open(cls, stack, resume=None, lang="hi"):
        ws = await connect("ws" + stack["app_url"][4:] + "/ws/session", max_size=None)
        client = cls(ws, stack)
        hello = {"type": "hello", "lang": lang}
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

    async def collect_turn(self, timeout=10.0, expect_audio=True, min_turn=0):
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
            if t in ("result", "audio_start", "audio_end", "timing") and msg.get("turn_id", min_turn) < min_turn:
                continue  # belongs to an earlier turn, for example a cancelled greeting
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

    async def speak(self, transcript, audio=None, **script):
        await self.script(transcripts=[transcript], **script)
        await self.ws.send(json.dumps({"type": "start", "mode": "ptt"}))
        audio = audio or pcm_audio()
        for i in range(0, len(audio), CHUNK_BYTES):
            await self.ws.send(audio[i:i + CHUNK_BYTES])
            await asyncio.sleep(0.01)  # audio arrives at roughly real-time cadence, as from a browser
        await self.ws.send(json.dumps({"type": "end"}))
        return await self.collect_turn(min_turn=1)

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
    u2 = await c.speak("undo karo")  # CONTRACT 1.15: after an undo the next one is checked first
    assert u2["result"]["status"] == "needs_clarification" and u2["result"]["entries"] == []
    customers, _ = await ledger(stack)
    assert balance_of(customers, "geeta") == [100], "nothing may change before the yes"
    u2 = await c.speak("haan")
    assert u2["result"]["action"] == "undo" and u2["result"]["entries"][0]["amount"] == 100
    assert [e["reversed"] for e in u2["result"]["entries"]] == [True]
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


# ---- behaviour added after the first review (CONTRACT 1.12, 1.13, 3.1, 3.2) -----------------------

async def test_greeting_in_english_when_hello_lang_is_en(stack):
    c = await Client.open(stack, lang="en")
    try:
        await c.script(tts_chunk_ms=5)
        turn = await c.greet()
        assert turn["result"]["reply_text"].startswith("Hello!") and "AI" in turn["result"]["reply_text"]
    finally:
        await c.close()


async def test_disclosure_is_repeated_when_greeting_is_interrupted(stack):
    """The app under test has its own TTS voice, so its greeting is never in the reply-audio cache and always
    streams from the mock, slowly enough to be interrupted by the first button press."""
    import uuid

    from app.config import Settings

    main = importlib.import_module("app.main")
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings.from_env({
            "GNANI_BASE_URL": stack["mock_url"], "GNANI_API_KEY": "test-key",
            "GNANI_TTS_VOICE": "TestVoice" + uuid.uuid4().hex[:8],
            "LEDGER_DB": os.path.join(tmp, "khata.db"), "LEDGER_KEY": base64.b64encode(b"u" * 32).decode(),
            "CONFIRM_NEW_CUSTOMER": "0",
        })
        app_url, stop_app = await serve_app(main.create_app(settings), lifespan="auto")
        own = dict(stack, app_url=app_url)
        c = None
        try:
            await own["mock"].post("/__mock/script", json={
                "transcripts": ["lata ka 100 udhaar"], "tts_first_chunk_delay_ms": 400, "tts_chunk_ms": 60})
            c = await Client.open(own)
            while True:  # wait until the greeting has really started streaming
                msg = await c.recv()
                if isinstance(msg, bytes):
                    break
            await own["mock"].post("/__mock/script", json={
                "transcripts": ["lata ka 100 udhaar"], "tts_first_chunk_delay_ms": 0, "tts_chunk_ms": 5})
            await c.ws.send(json.dumps({"type": "start", "mode": "ptt"}))
            audio = pcm_audio()
            for i in range(0, len(audio), CHUNK_BYTES):
                await c.ws.send(audio[i:i + CHUNK_BYTES])
                await asyncio.sleep(0.01)
            await c.ws.send(json.dumps({"type": "end"}))
            turn = await c.collect_turn(min_turn=1)
            assert turn["result"]["status"] == "ok"
            greeting_end = [m for m in turn["msgs"] if m["type"] == "audio_end" and m.get("turn_id") == 0]
            assert greeting_end and greeting_end[0].get("cancelled") is True
            log = (await own["mock"].get("/__mock/log")).json()["tts_requests"]
            assert "एआई" in log[-1]["text"]  # the Devanagari word for "AI" is in the spoken reply
            # once a reply has been heard to the end the disclosure is not repeated
            await c.speak("lata ka 50 udhaar")
            log = (await own["mock"].get("/__mock/log")).json()["tts_requests"]
            assert "एआई" not in log[-1]["text"]
        finally:
            await own["mock"].post("/__mock/script", json={"tts_first_chunk_delay_ms": 0, "tts_chunk_ms": 5})
            if c:
                await c.close()
            await stop_app()


async def test_whole_utterance_sent_in_one_burst_still_gets_the_entry(greeted, stack):
    c = greeted
    await c.script(transcripts=["burst ka 275 udhaar"])
    await c.ws.send(json.dumps({"type": "start", "mode": "ptt"}))
    audio = pcm_audio()
    for i in range(0, len(audio), CHUNK_BYTES):
        await c.ws.send(audio[i:i + CHUNK_BYTES])  # no pacing: the whole utterance arrives at once
    await c.ws.send(json.dumps({"type": "end"}))
    turn = await c.collect_turn(min_turn=1)
    assert turn["result"]["status"] == "ok" and turn["result"]["entries"][0]["amount"] == 275
    customers, _ = await ledger(stack)
    assert balance_of(customers, "burst") == [275]


async def test_nahi_with_two_entries_asks_which_one(greeted, stack):
    c = greeted
    first = await c.speak(["dinesh ka 340 udhaar", "dinesh ne 200 diye"])
    assert [e["amount"] for e in first["result"]["entries"]] == [340, 200]
    turn = await c.speak("nahi 430")
    result = turn["result"]
    assert result["status"] == "needs_clarification" and result["reason"] == "unclear_correction"
    assert result["entries"] == [] and "340" in result["question"] and "200" in result["question"]
    customers, _ = await ledger(stack)
    assert balance_of(customers, "dinesh") == [140]


async def test_old_amount_correction_picks_the_right_entry(greeted, stack):
    c = greeted
    await c.speak(["hari ka 340 udhaar", "hari ne 200 diye"])
    turn = await c.speak("340 nahi 430")
    result = turn["result"]
    assert result["status"] == "ok" and result["action"] == "amend"
    old, new = result["entries"]
    assert old["reversed"] is True and old["amount"] == 340 and old["kind"] == "credit"
    assert new["amount"] == 430 and new["kind"] == "credit"
    customers, _ = await ledger(stack)
    assert balance_of(customers, "hari") == [230]


async def test_english_sentence_gets_english_reply_and_hinglish_switches_back(greeted, stack):
    c = greeted
    # CONTRACT 1.18: with CONFIRM_NEW_CUSTOMER off a new name is accepted only before a particle, so the customer is
    # opened by a Hindi sentence first.
    await c.speak("lakshmi ka 700 udhaar")
    en = await c.speak("Lakshmi paid five hundred rupees")
    assert en["result"]["status"] == "ok" and en["result"]["lang"] == "en"
    assert en["result"]["entries"][0]["kind"] == "payment" and en["result"]["entries"][0]["amount"] == 500
    assert "Received ₹500 from Lakshmi" in en["result"]["reply_text"]
    log = (await stack["mock"].get("/__mock/log")).json()
    assert log["tts_requests"][-1]["language"] == "en-IN"
    hi = await c.speak("lakshmi ka 100 udhaar")
    assert hi["result"]["lang"] == "hi"
    assert "udhaar" in hi["result"]["reply_text"]
    log = (await stack["mock"].get("/__mock/log")).json()
    assert log["tts_requests"][-1]["language"] == "hi-IN"


async def test_first_person_diye_is_a_credit_for_the_customer_named_with_wahi(greeted, stack):
    c = greeted
    await c.speak("tarun ka 100 udhaar")
    asked = await c.speak("Maine 455 rupaye diye")  # CONTRACT 1.15: a new turn with no name asks whose account
    assert asked["result"]["status"] == "needs_clarification" and asked["result"]["entries"] == []
    turn = await c.speak("wahi")
    entry = turn["result"]["entries"][0]
    assert turn["result"]["status"] == "ok"
    assert entry["kind"] == "credit" and entry["amount"] == 455 and entry["customer"]["display"].lower() == "tarun"
    customers, _ = await ledger(stack)
    assert balance_of(customers, "tarun") == [555]


async def test_relation_is_not_answered_with_the_customers_own_balance(greeted, stack):
    c = greeted
    await c.speak("mukesh ka 700 udhaar")
    turn = await c.speak("mukesh ki biwi ka khata")
    result = turn["result"]
    assert result["entries"] == []
    assert "700" not in result["reply_text"]
    customers, _ = await ledger(stack)
    assert balance_of(customers, "mukesh") == [700]


async def test_natural_answer_resolves_the_direction_question(greeted, stack):
    c = greeted
    q = await c.speak("ganesh ka 500")  # CONTRACT 1.18: with the switch off a new name is accepted only before a particle
    assert q["result"]["status"] == "needs_clarification" and q["result"]["reason"] == "ambiguous_direction"
    assert q["result"]["entries"] == []
    ans = await c.speak("ganesh ne diye")
    entry = ans["result"]["entries"][0]
    assert ans["result"]["status"] == "ok"
    assert entry["kind"] == "payment" and entry["amount"] == 500
    customers, _ = await ledger(stack)
    assert balance_of(customers, "ganesh") == [-500]


# ---- noise handling (CONTRACT 3.5) ----------------------------------------------------------------------------

def noisy_audio(ms: int = 1600) -> bytes:
    """Loud steady background from the first frame to the last, with the "speech" only a little above it."""
    import random

    rng = random.Random(7)
    n = SAMPLE_RATE * ms // 1000
    samples = [int(rng.uniform(-1500, 1500)) + (int(2000 * ((i // 40) % 2 * 2 - 1)) if n // 4 < i < 3 * n // 4 else 0)
               for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


def noise_of(turn):
    timing = turn["timing"]
    return (timing.get("ms") or {}).get("noise") or timing.get("noise")


async def test_a_clean_spoken_turn_saves_directly_and_reports_the_noise_measure(greeted, stack):
    turn = await greeted.speak("yashodhara ka 265 udhaar")
    assert turn["result"]["status"] == "ok" and turn["result"]["entries"][0]["amount"] == 265
    noise = noise_of(turn)
    assert noise and noise["noisy"] is False, noise
    customers, _ = await ledger(stack)
    assert balance_of(customers, "yashodhara") == [265]


async def test_a_noisy_turn_is_confirmed_first_and_a_spoken_yes_saves(greeted, stack):
    turn = await greeted.speak("zubaida ka 215 udhaar", audio=noisy_audio())
    assert noise_of(turn)["noisy"] is True, noise_of(turn)
    result = turn["result"]
    assert result["status"] == "needs_clarification" and result["reason"] == "confirm_entry", result
    assert result["entries"] == [] and "215" in result["reply_text"]
    customers, _ = await ledger(stack)
    assert balance_of(customers, "zubaida") == []
    done = await greeted.speak("haan")
    assert done["result"]["status"] == "ok" and done["result"]["entries"][0]["amount"] == 215
    customers, _ = await ledger(stack)
    assert balance_of(customers, "zubaida") == [215]


async def test_a_noisy_turn_is_confirmed_first_and_a_typed_yes_saves(greeted, stack):
    turn = await greeted.speak("wazir ka 225 udhaar", audio=noisy_audio())
    assert turn["result"]["reason"] == "confirm_entry"
    await greeted.ws.send(json.dumps({"type": "text", "text": "haan"}))
    done = await greeted.collect_turn()
    assert done["result"]["status"] == "ok" and done["result"]["entries"][0]["amount"] == 225
    assert noise_of(done) is None, "a typed turn has no noise measure"


async def test_a_typed_turn_has_no_noise_in_timing(greeted):
    await greeted.ws.send(json.dumps({"type": "text", "text": "tabassum ka 120 udhaar"}))
    turn = await greeted.collect_turn()
    assert turn["result"]["status"] == "ok" and noise_of(turn) is None


async def test_with_the_confirmation_switched_off_a_noisy_turn_saves_directly(stack):
    from app.config import Settings

    main = importlib.import_module("app.main")
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings.from_env({
            "GNANI_BASE_URL": stack["mock_url"], "GNANI_API_KEY": "test-key",
            "LEDGER_DB": os.path.join(tmp, "khata.db"), "LEDGER_KEY": base64.b64encode(b"n" * 32).decode(),
            "CONFIRM_NEW_CUSTOMER": "0", "NOISE_CONFIRM_DB": "0",
        })
        app_url, stop_app = await serve_app(main.create_app(settings), lifespan="auto")
        own = dict(stack, app_url=app_url)
        c = await Client.open(own)
        try:
            await c.greet()
            turn = await c.speak("ishaan ka 180 udhaar", audio=noisy_audio())
            assert turn["result"]["status"] == "ok" and turn["result"]["entries"][0]["amount"] == 180, turn["result"]
        finally:
            await c.close()
            await stop_app()
