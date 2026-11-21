"""Mock Gnani Prisma v3.0 (STT) and Timbre v3.0 (TTS) WebSocket services.

Message shapes follow docs/CONTRACT.md section 4. Behaviour is scriptable through
POST /__mock/script, and every connection is recorded for GET /__mock/log.

Script body (every key optional):
  transcripts          queue of turns; see `Turn` for the accepted shapes (text, segments, partials, silence,
                       no_transcript)
  stt_delay_ms         wait between `commit` and the final transcript
  partial_interval_ms  spacing of the generated partial transcripts
  send_processing      send `processing` after `commit` (default true)
  tts_first_chunk_delay_ms, tts_chunk_ms   text-to-speech pacing
  tts_fail             number of the next text-to-speech requests that fail
  tts_fail_mode        "error" (an `error` message, socket stays open) or "close" (the socket is closed)
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import struct
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

FRAME_BYTES = 1024          # 512 samples of 16-bit mono PCM at 16 kHz
FRAME_MS = 32
SPEECH_START_AFTER_FRAMES = 3
MS_PER_CHAR = 70
TTS_CHUNK_AUDIO_MS = 100    # audio carried by one TTS chunk
TTS_MODELS = {"timbre-v3.0", "timbre-v2.5"}
TTS_REQUIRED = ("text", "voice", "model", "language")
DEFAULT_SAMPLE_RATE = 48000  # Gnani's default when audio_config is absent


class MockState:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.transcripts: list[Any] = []
        self.tts_fail = 0
        self.tts_fail_mode = "error"
        self.stt_delay_ms = 0
        self.tts_first_chunk_delay_ms = 0
        self.tts_chunk_ms = 10
        self.send_processing = True
        self.partial_interval_ms = 450
        self.stt_sessions: list[dict[str, Any]] = []
        self.tts_requests: list[dict[str, Any]] = []


class Turn:
    """One scripted speech-to-text turn, normalised from the shapes `POST /__mock/script` accepts.

    - a string: one final transcript
    - a list of strings: several final transcripts (segments), sent one after another
    - an object with any of: `text` (string or list, the final transcript), `partials` (list of strings sent as
      partial transcripts before the final one), `silence` (true: the turn has no speech, so the mock sends nothing
      for it) and `no_transcript` (true: speech starts and the turn is processed, but no transcript ever arrives)
    """

    def __init__(self, item: Any) -> None:
        self.partials: list[str] = []
        self.silence = False
        self.no_transcript = False
        if item is None:
            self.silence = True
            self.segments: list[str] = []
        elif isinstance(item, dict):
            self.silence = bool(item.get("silence"))
            self.no_transcript = bool(item.get("no_transcript"))
            self.partials = [str(p) for p in item.get("partials") or []]
            text = item.get("text", item.get("final", ""))
            self.segments = [str(t) for t in text] if isinstance(text, list) else [str(text or "")]
        elif isinstance(item, list):
            self.segments = [str(t) for t in item]
        else:
            self.segments = [str(item)]

    @property
    def full_text(self) -> str:
        return " ".join(self.segments)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msg(type_: str, **fields: Any) -> str:
    return json.dumps({"type": type_, "timestamp": _now(), **fields})


def tone_pcm(n_samples: int, sample_rate: int, start: int = 0) -> bytes:
    """A quiet 220 Hz sine tone as 16-bit little-endian PCM."""
    amp = 1000
    vals = [int(amp * math.sin(2 * math.pi * 220 * (start + i) / sample_rate)) for i in range(n_samples)]
    return struct.pack(f"<{n_samples}h", *vals)


def _header(ws: WebSocket, *names: str) -> str | None:
    for name in names:
        value = ws.headers.get(name)
        if value:
            return value
    return None


async def _deny(ws: WebSocket, status: int, text: str) -> None:
    """Refuse the upgrade with an HTTP status; fall back to closing when the server cannot."""
    try:
        await ws.send_denial_response(JSONResponse({"detail": text}, status_code=status))
    except Exception:
        await ws.close(code=1008)


def create_app() -> FastAPI:
    app = FastAPI(title="mock-gnani")
    state = MockState()
    app.state.mock = state

    @app.post("/__mock/reset")
    async def reset() -> dict:
        state.reset()
        return {"ok": True}

    @app.post("/__mock/script")
    async def script(request: Request) -> dict:
        body = await request.json()
        if "transcripts" in body:
            state.transcripts = list(body["transcripts"])
        if "send_processing" in body:
            state.send_processing = bool(body["send_processing"])
        for key in ("stt_delay_ms", "tts_first_chunk_delay_ms", "tts_chunk_ms", "partial_interval_ms", "tts_fail"):
            if key in body:
                setattr(state, key, int(body[key]))
        if "tts_fail_mode" in body:
            if body["tts_fail_mode"] not in ("error", "close"):
                return JSONResponse({"ok": False, "detail": "tts_fail_mode is 'error' or 'close'"}, status_code=422)
            state.tts_fail_mode = body["tts_fail_mode"]
        return {"ok": True, "queued": len(state.transcripts)}

    @app.get("/__mock/log")
    async def log() -> dict:
        return {"stt_sessions": state.stt_sessions, "tts_requests": state.tts_requests}

    @app.websocket("/stt/v3/stream")
    async def stt(ws: WebSocket) -> None:
        if not _header(ws, "x-api-key-id"):
            await _deny(ws, 401, "MISSING_API_KEY")
            return
        await ws.accept()
        headers = {k.lower(): v for k, v in ws.headers.items()}
        language = _header(ws, "language_code", "lang_code") or ""
        if "," in language:  # Gnani closes a comma-separated language list with 1008
            await ws.send_text(_msg("error", message="invalid language_code"))
            await ws.close(code=1008)
            return
        partials = headers.get("x-partials", "").lower() == "true"
        session = {"headers": headers, "frames": 0, "bad_frames": 0, "bad_frame_sizes": [], "commits": 0}
        state.stt_sessions.append(session)
        request_id = uuid.uuid4().hex[:12]
        config = {
            "sample_rate": int(headers.get("x-sample-rate", 16000)),
            "chunk_size": 512,
            "language_code": _header(ws, "language_code", "lang_code"),
            "format": _header(ws, "format", "x-format"),
            "model": _header(ws, "model", "x-model"),
            "partials_enabled": partials,
            "partial_interval_ms": state.partial_interval_ms,
            "partial_max_window_s": 30,
        }
        await ws.send_text(_msg("connected", message="connected", config=config, request_id=request_id))
        frames_in_utterance = 0
        utterance_no = 0
        segment_no = 0
        speech_started = False
        partial_seq = 0
        last_partial = time.monotonic()
        try:
            while True:
                data = await ws.receive()
                if data["type"] == "websocket.disconnect":
                    break
                if data.get("bytes") is not None:
                    n = len(data["bytes"])
                    session["frames"] += 1
                    if n != FRAME_BYTES:
                        session["bad_frames"] += 1
                        session["bad_frame_sizes"].append(n)
                    frames_in_utterance += 1
                    upcoming = Turn(state.transcripts[0]) if state.transcripts else None
                    if upcoming is not None and upcoming.silence:
                        continue  # a turn scripted as silence: the service hears no speech
                    if frames_in_utterance == SPEECH_START_AFTER_FRAMES and not speech_started:
                        speech_started = True
                        utterance_no += 1
                        await ws.send_text(_msg("speech_start", utterance_id=f"{request_id}-utt-{utterance_no}",
                                                t_ms=frames_in_utterance * FRAME_MS))
                    if partials and speech_started and state.transcripts and (
                            time.monotonic() - last_partial) * 1000 >= state.partial_interval_ms:
                        last_partial = time.monotonic()
                        partial_seq += 1
                        full = upcoming.full_text if upcoming else ""
                        words = full.split()
                        cut = max(1, len(words) * 2 // 3)
                        await ws.send_text(_msg(
                            "partial_transcript", text=full, stable_text=" ".join(words[:cut]),
                            volatile_text=" ".join(words[cut:]), seq=partial_seq,
                            utterance_id=f"{request_id}-utt-{utterance_no}", is_final=False))
                    continue
                text = data.get("text")
                if text is None:
                    continue
                try:
                    obj = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(obj, dict) or obj.get("type") != "commit":
                    continue
                session["commits"] += 1
                if frames_in_utterance == 0:
                    continue  # nothing was said: Gnani sends nothing
                turn = Turn(state.transcripts[0]) if state.transcripts else Turn("")
                if turn.silence:
                    state.transcripts.pop(0)
                    frames_in_utterance = 0
                    continue
                if not speech_started:
                    utterance_no += 1
                audio_ms = frames_in_utterance * FRAME_MS
                utterance_id = f"{request_id}-utt-{utterance_no}"
                frames_in_utterance = 0
                speech_started = False
                if partials:
                    await ws.send_text(_msg("speech_end", utterance_id=utterance_id, audio_ms=audio_ms, t_ms=audio_ms))
                if state.send_processing:
                    await ws.send_text(_msg("processing", utterance_id=utterance_id))
                if state.transcripts:
                    state.transcripts.pop(0)
                if partials:
                    for text in turn.partials:
                        partial_seq += 1
                        words = text.split()
                        cut = max(1, len(words) * 2 // 3)
                        await ws.send_text(_msg(
                            "partial_transcript", text=text, stable_text=" ".join(words[:cut]),
                            volatile_text=" ".join(words[cut:]), seq=partial_seq, utterance_id=utterance_id,
                            is_final=False))
                await asyncio.sleep(state.stt_delay_ms / 1000)
                if turn.no_transcript:
                    continue
                for seg in turn.segments:
                    segment_no += 1
                    fields: dict[str, Any] = {
                        "text": seg,
                        "audio_duration_ms": audio_ms,
                        "segment_id": f"{request_id}-seg-{segment_no}",
                        "segment_index": segment_no,
                        "latency": state.stt_delay_ms,
                        "utterance_id": utterance_id,
                        "is_final": True,
                    }
                    if config["format"] != "transliterate" and seg:
                        fields["detected_language_code"] = "hi-IN"
                    if partials:
                        fields["prefetched"] = False
                        await ws.send_text(_msg("final_transcript", **fields))
                    else:
                        await ws.send_text(_msg("transcript", **fields))
        except (WebSocketDisconnect, RuntimeError):
            pass

    @app.websocket("/api/v1/tts")
    async def tts(ws: WebSocket) -> None:
        if not ws.headers.get("x-api-key-id"):
            await _deny(ws, 401, "MISSING_API_KEY")
            return
        await ws.accept()
        connection_id = uuid.uuid4().hex[:12]
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    req = json.loads(raw)
                except ValueError:
                    req = None
                if not isinstance(req, dict):
                    await ws.send_text(_msg("error", message="request must be a JSON object"))
                    continue
                entry = dict(req)
                entry.update({"chunks_sent": 0, "completed": False})
                state.tts_requests.append(entry)
                missing = [k for k in TTS_REQUIRED if not req.get(k)]
                if missing:
                    await ws.send_text(_msg("error", message=f"missing required field: {', '.join(missing)}"))
                    continue
                if req["model"] not in TTS_MODELS:
                    await ws.send_text(_msg("error", message=f"unknown model: {req['model']}"))
                    continue
                if state.tts_fail > 0:
                    state.tts_fail -= 1
                    entry["failed"] = state.tts_fail_mode
                    if state.tts_fail_mode == "close":
                        await ws.close(code=1011)
                        return
                    await ws.send_text(_msg("start", message="started", request_id=connection_id))
                    await ws.send_text(_msg("error", message="synthesis failed"))
                    continue
                await _stream_tts(ws, state, req, entry, connection_id)
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app


async def _stream_tts(ws: WebSocket, state: MockState, req: dict, entry: dict, request_id: str) -> None:
    cfg = req.get("audio_config") or {}
    rate = int(cfg.get("sample_rate", DEFAULT_SAMPLE_RATE))
    total_ms = MS_PER_CHAR * len(str(req["text"]))
    total_samples = rate * total_ms // 1000
    chunk_samples = rate * TTS_CHUNK_AUDIO_MS // 1000
    await ws.send_text(_msg("start", message="started", request_id=request_id))
    await asyncio.sleep(state.tts_first_chunk_delay_ms / 1000)
    sent = 0
    index = 0
    while sent < total_samples:
        n = min(chunk_samples, total_samples - sent)
        pcm = tone_pcm(n, rate, sent)
        payload = {"chunk_index": index, "audio": base64.b64encode(pcm).decode(), "is_final": False}
        await ws.send_text(_msg("audio", data=payload))
        entry["chunks_sent"] = index + 1
        sent += n
        index += 1
        if sent < total_samples:
            await asyncio.sleep(state.tts_chunk_ms / 1000)
    await ws.send_text(
        _msg("complete", request_id=request_id, data={"chunk_index": index, "audio": "", "is_final": True})
    )
    await ws.send_text(_msg("complete", message="Streaming completed", request_id=request_id))
    entry["completed"] = True
