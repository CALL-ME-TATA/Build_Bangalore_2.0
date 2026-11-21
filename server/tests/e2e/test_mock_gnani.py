"""Behaviour of the mock Gnani server (docs/CONTRACT.md section 4), checked with a raw websockets client."""
from __future__ import annotations

import asyncio
import base64
import json
import time

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

FRAME = b"\x00\x01" * 512  # 1,024 bytes


async def recv_json(ws, timeout=3.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def stt_connect(mock, **headers):
    base = {"x-api-key-id": "test-key", "language_code": "hi-IN", "model": "prisma-v3.0", "format": "transliterate"}
    base.update(headers)
    base = {k: v for k, v in base.items() if v is not None}
    return connect(f"{mock.ws_url}/stt/v3/stream", additional_headers=base)


async def send_utterance(ws, frames=5):
    for _ in range(frames):
        await ws.send(FRAME)
    await ws.send(json.dumps({"type": "commit"}))


# ---- STT ----------------------------------------------------------------------------------------

async def test_stt_rejects_missing_key(mock):
    with pytest.raises(InvalidStatus) as exc:
        async with connect(f"{mock.ws_url}/stt/v3/stream", additional_headers={"language_code": "hi-IN"}):
            pass
    assert exc.value.response.status_code in (401, 403)


async def test_stt_connected_echoes_config_new_header_names(mock):
    async with await stt_connect(mock) as ws:
        msg = await recv_json(ws)
    assert msg["type"] == "connected"
    assert msg["config"]["language_code"] == "hi-IN"
    assert msg["config"]["model"] == "prisma-v3.0"
    assert msg["config"]["format"] == "transliterate"
    assert msg["config"]["chunk_size"] == 512
    assert msg["request_id"]


async def test_stt_accepts_old_header_names(mock):
    headers = {"x-api-key-id": "k", "lang_code": "hi-IN", "x-model": "prisma-v3.0", "x-format": "codemix"}
    async with connect(f"{mock.ws_url}/stt/v3/stream", additional_headers=headers) as ws:
        msg = await recv_json(ws)
    assert msg["config"]["language_code"] == "hi-IN"
    assert msg["config"]["model"] == "prisma-v3.0"
    assert msg["config"]["format"] == "codemix"


async def test_stt_transcript_flow_and_fields(mock):
    await mock.script(transcripts=["ramesh ka 340 udhaar"], stt_delay_ms=0)
    async with await stt_connect(mock) as ws:
        await recv_json(ws)  # connected
        await send_utterance(ws, frames=5)
        types = []
        transcript = None
        while transcript is None:
            msg = await recv_json(ws)
            types.append(msg["type"])
            if msg["type"] == "transcript":
                transcript = msg
    assert types == ["speech_start", "processing", "transcript"]
    assert transcript["text"] == "ramesh ka 340 udhaar"
    assert transcript["is_final"] is True
    assert transcript["segment_index"] == 1
    assert transcript["segment_id"].endswith("-seg-1")
    assert transcript["audio_duration_ms"] == 5 * 32
    assert transcript["utterance_id"]
    assert "latency" in transcript
    assert "detected_language_code" not in transcript  # transliterate format omits it


async def test_stt_speech_start_after_first_frames_only(mock):
    await mock.script(transcripts=["x"])
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        await ws.send(FRAME)
        await ws.send(FRAME)
        with pytest.raises(asyncio.TimeoutError):
            await recv_json(ws, timeout=0.3)
        await ws.send(FRAME)
        assert (await recv_json(ws))["type"] == "speech_start"


async def test_stt_delay_is_applied(mock):
    await mock.script(transcripts=["x"], stt_delay_ms=300)
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        await send_utterance(ws)
        while (await recv_json(ws))["type"] != "processing":
            pass
        t0 = time.perf_counter()
        msg = await recv_json(ws)
        elapsed = time.perf_counter() - t0
    assert msg["type"] == "transcript"
    assert msg["latency"] == 300
    assert 0.25 <= elapsed < 1.5


async def test_stt_segments_sent_separately(mock):
    await mock.script(transcripts=[["ramesh ka 340 udhaar", "sunita ne 200 diye"]])
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        await send_utterance(ws)
        transcripts = []
        while len(transcripts) < 2:
            msg = await recv_json(ws)
            if msg["type"] == "transcript":
                transcripts.append(msg)
    assert [t["text"] for t in transcripts] == ["ramesh ka 340 udhaar", "sunita ne 200 diye"]
    assert [t["segment_index"] for t in transcripts] == [1, 2]
    assert transcripts[0]["utterance_id"] == transcripts[1]["utterance_id"]


async def test_stt_scripts_are_consumed_in_order(mock):
    await mock.script(transcripts=["pehla", "doosra"])
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        texts = []
        for _ in range(2):
            await send_utterance(ws)
            while True:
                msg = await recv_json(ws)
                if msg["type"] == "transcript":
                    texts.append(msg["text"])
                    break
    assert texts == ["pehla", "doosra"]


async def test_stt_commit_without_audio_sends_nothing(mock):
    await mock.script(transcripts=["should not be sent"])
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        await ws.send(json.dumps({"type": "commit"}))
        with pytest.raises(asyncio.TimeoutError):
            await recv_json(ws, timeout=0.4)
    log = await mock.log()
    assert log["stt_sessions"][0]["commits"] == 1


async def test_stt_records_frames_and_bad_frames(mock):
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        for _ in range(4):
            await ws.send(FRAME)
        await ws.send(b"\x00" * 100)
        await ws.send(json.dumps({"type": "commit"}))
        await asyncio.sleep(0.2)
    log = await mock.log()
    session = log["stt_sessions"][0]
    assert session["frames"] == 5
    assert session["bad_frames"] == 1
    assert session["commits"] == 1
    assert session["headers"]["x-api-key-id"] == "test-key"
    assert session["headers"]["language_code"] == "hi-IN"


async def test_reset_clears_log_and_script(mock):
    await mock.script(transcripts=["a"], stt_delay_ms=50)
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
    assert (await mock.log())["stt_sessions"]
    await mock.reset()
    log = await mock.log()
    assert log == {"stt_sessions": [], "tts_requests": []}


# ---- TTS ----------------------------------------------------------------------------------------

def tts_request(text="namaste", **over):
    req = {
        "text": text, "voice": "Shivani", "model": "timbre-v3.0", "language": "hi-IN", "speed": 1.0,
        "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "raw"},
    }
    req.update(over)
    return req


async def tts_connect(mock, **headers):
    base = {"X-API-Key-ID": "test-key"}
    base.update(headers)
    return connect(f"{mock.ws_url}/api/v1/tts", additional_headers=base)


async def collect_reply(ws, timeout=5.0):
    msgs = []
    while True:
        msg = await recv_json(ws, timeout)
        msgs.append(msg)
        if msg["type"] == "complete" and msg.get("message") == "Streaming completed":
            return msgs
        if msg["type"] == "error":
            return msgs


async def test_tts_rejects_missing_key(mock):
    with pytest.raises(InvalidStatus) as exc:
        async with connect(f"{mock.ws_url}/api/v1/tts"):
            pass
    assert exc.value.response.status_code in (401, 403)


async def test_tts_audio_length_and_sequence(mock):
    text = "x" * 40  # 40 chars * 70 ms = 2,800 ms
    async with await tts_connect(mock) as ws:
        await ws.send(json.dumps(tts_request(text)))
        msgs = await collect_reply(ws)
    assert msgs[0]["type"] == "start" and msgs[0]["request_id"]
    assert msgs[-1]["type"] == "complete" and msgs[-1]["message"] == "Streaming completed"
    assert msgs[-2]["type"] == "complete" and msgs[-2]["data"]["is_final"] is True
    audio = [m for m in msgs if m["type"] == "audio"]
    assert [m["data"]["chunk_index"] for m in audio] == list(range(len(audio)))
    assert all(m["data"]["is_final"] is False for m in audio)
    pcm = b"".join(base64.b64decode(m["data"]["audio"]) for m in audio)
    assert len(pcm) == 24000 * 2800 // 1000 * 2
    assert any(pcm)  # not silence
    samples = [int.from_bytes(pcm[i:i + 2], "little", signed=True) for i in range(0, len(pcm), 2)]
    assert max(abs(s) for s in samples) < 3000  # quiet


async def test_tts_honours_requested_sample_rate(mock):
    async with await tts_connect(mock) as ws:
        await ws.send(json.dumps(tts_request("x" * 10, audio_config={"sample_rate": 16000})))
        msgs = await collect_reply(ws)
    pcm = b"".join(base64.b64decode(m["data"]["audio"]) for m in msgs if m["type"] == "audio")
    assert len(pcm) == 16000 * 700 // 1000 * 2


async def test_tts_first_chunk_delay_and_chunk_pacing(mock):
    await mock.script(tts_first_chunk_delay_ms=300, tts_chunk_ms=100)
    async with await tts_connect(mock) as ws:
        await ws.send(json.dumps(tts_request("x" * 10)))  # 700 ms of audio = 7 chunks
        t0 = time.perf_counter()
        assert (await recv_json(ws))["type"] == "start"
        first = await recv_json(ws)
        t_first = time.perf_counter() - t0
        assert first["type"] == "audio"
        await collect_reply(ws)
        t_total = time.perf_counter() - t0
    assert 0.25 <= t_first < 1.0
    assert t_total - t_first >= 0.5  # six more chunks, 100 ms apart


async def test_tts_error_for_unknown_model_and_socket_stays_open(mock):
    async with await tts_connect(mock) as ws:
        await ws.send(json.dumps(tts_request(model="timbre-v9")))
        msgs = await collect_reply(ws)
        assert msgs[-1]["type"] == "error" and "model" in msgs[-1]["message"]
        await ws.send(json.dumps(tts_request("abc")))
        msgs = await collect_reply(ws)
        assert msgs[-1]["type"] == "complete"


async def test_tts_error_for_missing_field_and_bad_json(mock):
    async with await tts_connect(mock) as ws:
        req = tts_request()
        del req["voice"]
        await ws.send(json.dumps(req))
        msgs = await collect_reply(ws)
        assert msgs[-1]["type"] == "error" and "voice" in msgs[-1]["message"]
        await ws.send("not json")
        assert (await recv_json(ws))["type"] == "error"


async def test_tts_socket_serves_several_requests_and_logs_them(mock):
    async with await tts_connect(mock) as ws:
        for text in ("pehla", "doosra jawab"):
            await ws.send(json.dumps(tts_request(text)))
            msgs = await collect_reply(ws)
            assert msgs[-1]["type"] == "complete"
    log = await mock.log()
    assert [r["text"] for r in log["tts_requests"]] == ["pehla", "doosra jawab"]
    assert log["tts_requests"][0]["model"] == "timbre-v3.0"
    assert log["tts_requests"][0]["audio_config"]["sample_rate"] == 24000


async def test_python_m_mock_gnani_starts_on_requested_port():
    import socket
    import subprocess
    import sys

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen([sys.executable, "-m", "mock_gnani", "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    r = await client.get(f"http://127.0.0.1:{port}/__mock/log")
                    break
                except httpx.TransportError:
                    await asyncio.sleep(0.1)
            else:
                pytest.fail("mock did not start")
        assert r.json() == {"stt_sessions": [], "tts_requests": []}
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ---- partial vocabulary, switchable processing, live-observed TTS and language behaviour ---------

async def test_partials_vocabulary_with_x_partials_header(mock):
    await mock.script(transcripts=["ramesh ka 340 udhaar"], partial_interval_ms=0, stt_delay_ms=0)
    async with await stt_connect(mock, **{"x-partials": "true"}) as ws:
        connected = await recv_json(ws)
        assert connected["config"]["partials_enabled"] is True
        assert "partial_interval_ms" in connected["config"] and "partial_max_window_s" in connected["config"]
        await send_utterance(ws, frames=6)
        types = []
        final = None
        while final is None:
            msg = await recv_json(ws)
            types.append(msg["type"])
            if msg["type"] == "final_transcript":
                final = msg
            if msg["type"] == "partial_transcript":
                assert msg["is_final"] is False and msg["seq"] >= 1
                assert msg["stable_text"] + (" " if msg["volatile_text"] else "") + msg["volatile_text"] == msg["text"]
    assert "partial_transcript" in types
    assert types.index("speech_end") < types.index("final_transcript")
    assert "transcript" not in types
    assert final["text"] == "ramesh ka 340 udhaar" and final["is_final"] is True and "prefetched" in final


async def test_no_partials_without_header(mock):
    await mock.script(transcripts=["x"], partial_interval_ms=0)
    async with await stt_connect(mock) as ws:
        connected = await recv_json(ws)
        assert connected["config"]["partials_enabled"] is False
        await send_utterance(ws, frames=6)
        types = []
        while "transcript" not in types:
            types.append((await recv_json(ws))["type"])
    assert "partial_transcript" not in types and "speech_end" not in types


async def test_processing_can_be_switched_off(mock):
    await mock.script(transcripts=["x"], send_processing=False)
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        await send_utterance(ws)
        types = []
        while "transcript" not in types:
            types.append((await recv_json(ws))["type"])
    assert "processing" not in types


async def test_stt_comma_language_list_closes_1008(mock):
    async with await stt_connect(mock, language_code="hi-IN,en-IN") as ws:
        with pytest.raises(Exception) as exc:
            while True:
                await asyncio.wait_for(ws.recv(), 3)
    assert getattr(exc.value, "rcvd", None) is not None and exc.value.rcvd.code == 1008


async def test_tts_connection_level_request_id_and_second_complete(mock):
    async with await tts_connect(mock) as ws:
        ids = []
        for _ in range(2):
            await ws.send(json.dumps(tts_request("abc")))
            msgs = []
            while True:
                msg = await recv_json(ws)
                msgs.append(msg)
                if msg["type"] == "complete" and msg.get("message") == "Streaming completed":
                    break
            assert msgs[0]["type"] == "start"
            completes = [m for m in msgs if m["type"] == "complete"]
            assert len(completes) == 2 and completes[0]["data"]["is_final"] is True
            assert completes[1]["request_id"] == msgs[0]["request_id"]
            ids.append(msgs[0]["request_id"])
    assert ids[0] == ids[1]


async def _read_until(ws, kinds):
    msgs = []
    while True:
        msg = await recv_json(ws)
        msgs.append(msg)
        if msg["type"] in kinds:
            return msgs


@pytest.mark.parametrize("partials", [False, True])
async def test_every_message_of_an_utterance_shares_one_id_and_each_press_gets_a_new_one(mock, partials):
    await mock.script(transcripts=["pehla vaakya", "doosra vaakya"], partial_interval_ms=0)
    extra = {"x-partials": "true"} if partials else {}
    final_kind = "final_transcript" if partials else "transcript"
    async with await stt_connect(mock, **extra) as ws:
        await recv_json(ws)
        ids = []
        for _ in range(2):
            await send_utterance(ws, frames=8)
            msgs = await _read_until(ws, {final_kind})
            utterance_msgs = [m for m in msgs if m["type"] != "processing"]
            assert utterance_msgs[0]["type"] == "speech_start"
            these = {m["utterance_id"] for m in utterance_msgs}
            assert len(these) == 1, utterance_msgs
            ids.append(these.pop())
    assert ids[0] != ids[1]


async def test_partials_never_precede_speech_start(mock):
    await mock.script(transcripts=["ramesh ka 340 udhaar"], partial_interval_ms=0)
    async with await stt_connect(mock, **{"x-partials": "true"}) as ws:
        await recv_json(ws)
        for _ in range(2):
            await ws.send(FRAME)
        with pytest.raises(asyncio.TimeoutError):
            await recv_json(ws, timeout=0.3)  # no speech_start yet, so no partial either
        await ws.send(FRAME)
        await ws.send(FRAME)
        msgs = await _read_until(ws, {"partial_transcript"})
    assert msgs[0]["type"] == "speech_start"
    assert msgs[-1]["utterance_id"] == msgs[0]["utterance_id"]


# ---- scripted turns: silence, missing transcript, partials, failing text-to-speech ----------------

async def test_silent_turn_sends_nothing_and_is_consumed(mock):
    await mock.script(transcripts=[{"silence": True}, "ramesh ka 340 udhaar"])
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        await send_utterance(ws, frames=8)
        with pytest.raises(asyncio.TimeoutError):
            await recv_json(ws, timeout=0.4)  # no speech_start, processing or transcript
        await send_utterance(ws, frames=8)
        msgs = await _read_until(ws, {"transcript"})
    assert msgs[-1]["text"] == "ramesh ka 340 udhaar"
    assert [m["type"] for m in msgs][0] == "speech_start"


async def test_turn_without_transcript_starts_speech_but_never_finishes(mock):
    await mock.script(transcripts=[{"no_transcript": True}])
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        await send_utterance(ws, frames=8)
        kinds = []
        with pytest.raises(asyncio.TimeoutError):
            while True:
                kinds.append((await recv_json(ws, timeout=0.6))["type"])
    assert kinds == ["speech_start", "processing"]


async def test_scripted_partials_precede_the_final_transcript(mock):
    await mock.script(transcripts=[{"partials": ["34", "340"], "text": "3400"}])
    async with await stt_connect(mock, **{"x-partials": "true"}) as ws:
        await recv_json(ws)
        await send_utterance(ws, frames=8)
        msgs = await _read_until(ws, {"final_transcript"})
    partials = [m for m in msgs if m["type"] == "partial_transcript"]
    assert [p["text"] for p in partials] == ["34", "340"]
    assert [p["seq"] for p in partials] == [1, 2]
    assert msgs[-1]["text"] == "3400"
    assert len({m["utterance_id"] for m in msgs if "utterance_id" in m}) == 1


async def test_scripted_partials_are_not_sent_without_the_partials_header(mock):
    await mock.script(transcripts=[{"partials": ["34", "340"], "text": "3400"}])
    async with await stt_connect(mock) as ws:
        await recv_json(ws)
        await send_utterance(ws, frames=8)
        msgs = await _read_until(ws, {"transcript"})
    assert not [m for m in msgs if m["type"] == "partial_transcript"]
    assert msgs[-1]["text"] == "3400"


async def test_tts_fail_error_mode_keeps_socket_open_and_counts_down(mock):
    await mock.script(tts_fail=1)
    async with await tts_connect(mock) as ws:
        await ws.send(json.dumps(tts_request("pehla")))
        failed = await collect_reply(ws)
        assert failed[-1]["type"] == "error"
        assert not [m for m in failed if m["type"] == "audio"]
        await ws.send(json.dumps(tts_request("doosra")))
        ok = await collect_reply(ws)
    assert [m for m in ok if m["type"] == "audio"]
    log = await mock.log()
    assert log["tts_requests"][0]["failed"] == "error"
    assert "failed" not in log["tts_requests"][1]


async def test_tts_fail_close_mode_closes_the_socket(mock):
    await mock.script(tts_fail=1, tts_fail_mode="close")
    async with await tts_connect(mock) as ws:
        await ws.send(json.dumps(tts_request("pehla")))
        with pytest.raises(Exception) as exc:
            await recv_json(ws)
    assert "1011" in str(exc.value) or "close" in str(exc.value).lower()


async def test_script_rejects_unknown_tts_fail_mode(mock):
    with pytest.raises(Exception):
        await mock.script(tts_fail=1, tts_fail_mode="explode")


async def test_reset_clears_tts_failure_script(mock):
    await mock.script(tts_fail=3, tts_fail_mode="close")
    await mock._http.post("/__mock/reset")
    async with await tts_connect(mock) as ws:
        await ws.send(json.dumps(tts_request("theek")))
        msgs = await collect_reply(ws)
    assert [m for m in msgs if m["type"] == "audio"]
