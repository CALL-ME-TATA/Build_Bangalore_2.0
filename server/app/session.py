"""Browser WebSocket session (CONTRACT section 3).

Text frames are JSON, binary frames are 16 kHz PCM16 audio. The server assigns every `turn_id` (an integer: 0 for
the greeting, then one more per turn). A turn that is transcribing or speaking runs in a task, so `start`
(barge-in) and `cancel` are handled while it runs and cancel it.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import time
import uuid
from contextlib import aclosing
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import Any, Callable

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .audio import TurnAudio
from .config import Settings
from .gnani.stt import FRAME_BYTES, SttClient
from .gnani.tts import TtsClient, TtsError
from .ledger import Ledger
from .logsafe import describe
from .pipeline import Pipeline, SessionState, TurnResult, clean_device_ts, clean_utt_id
from .regional import REGIONAL, is_regional

log = logging.getLogger("khata.session")

MAX_AUDIO_BYTES = 30 * 16000 * 2  # 30 s of 16 kHz PCM16: the turn is cut with the too-long reply (M07)
MIN_AUDIO_BYTES = 16000 * 2 // 2  # 0.5 s: a shorter recording is ignored (M03)
FINAL_WAIT_S = 5.0  # no final transcript this long after `end` -> the upstream-failure reply (M09)
RESUME_TTL_S = 300.0
_SESSION_ID = re.compile(r"^[0-9a-f]{8,32}$")


@dataclass
class AppContext:
    settings: Settings
    ledger: Ledger
    pipeline: Pipeline
    stt_factory: Callable[[Settings, Callable[[], list[str]]], SttClient]
    tts_factory: Callable[[Settings], TtsClient]
    registry: dict[str, tuple[SessionState, float]] = field(default_factory=dict)

    def keep(self, state: SessionState) -> None:
        now = time.monotonic()
        self.registry = {k: v for k, v in self.registry.items() if v[1] > now}
        self.registry[state.session_id] = (state, now + RESUME_TTL_S)

    def resume(self, session_id: str) -> SessionState | None:
        item = self.registry.pop(session_id, None)
        if item and item[1] > time.monotonic():
            return item[0]
        return None


def _noise_ms(noise: dict | None) -> dict:
    """The `timing.noise` entry of a spoken turn (3.5); typed turns have none."""
    return {"noise": noise} if noise else {}


def _client_ts(data: dict) -> str | None:
    return clean_device_ts(data.get("client_ts"))


def _ms(since: float) -> float:
    return round((time.perf_counter() - since) * 1000, 1)


class Session:
    def __init__(self, ws: WebSocket, app: AppContext):
        self.ws = ws
        self.app = app
        self.state: SessionState | None = None
        self.stt: SttClient | None = None
        self.tts: TtsClient | None = None
        self._task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._audio_open: int | None = None
        self._collecting = False
        self._audio_bytes = 0
        self._turn_utt: str | None = None  # client `utt_id` sent with `start`
        # Noise handling (3.5): one TurnAudio per spoken turn, fed 1,024-byte frames; `_abuf` holds a partial frame.
        self._turn_audio: TurnAudio | None = None
        self._abuf = bytearray()

    @property
    def turn_id(self) -> int:
        return self.state.turn_id if self.state else -1

    # ---- sending ----------------------------------------------------------------------------------------------
    async def _send(self, msg: dict) -> None:
        if msg.get("type") == "result" and self.state is not None:
            self.state.last_result = msg
            self.state.last_turn_id = msg.get("turn_id")
        async with self._send_lock:
            await self.ws.send_text(json.dumps(msg, ensure_ascii=False))

    async def _send_bytes(self, data: bytes) -> None:
        async with self._send_lock:
            await self.ws.send_bytes(data)

    async def _state_msg(self, turn_id: int, state: str) -> None:
        if turn_id == self.turn_id:
            await self._send({"type": "state", "turn_id": turn_id, "state": state})

    # ---- main loop --------------------------------------------------------------------------------------------
    async def run(self) -> None:
        await self.ws.accept()
        try:
            while True:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await self._on_audio(msg["bytes"])
                elif msg.get("text") is not None:
                    try:
                        data = json.loads(msg["text"])
                    except ValueError:
                        await self._send({"type": "error", "code": "bad_json", "message": "invalid JSON"})
                        continue
                    if isinstance(data, dict):
                        if not await self._on_message(data):
                            break
        except WebSocketDisconnect:
            pass
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
        if self.stt:
            await self.stt.close()
        if self.tts:
            await self.tts.close()
        if self.state:
            self.app.keep(self.state)

    def _spawn(self, coro) -> None:
        self._task = asyncio.create_task(self._guard(coro))
        # A task cancelled before it starts never runs `coro`; close it so it is not left un-awaited.
        self._task.add_done_callback(lambda _t, c=coro: c.close())

    async def _guard(self, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("turn failed: %s", describe(exc))
            try:
                await self._send({"type": "error", "turn_id": self.turn_id, "code": "internal",
                                  "message": "turn failed"})
                await self._send({"type": "result", "turn_id": self.turn_id, "trace_id": uuid.uuid4().hex[:16],
                                  "status": "rejected", "action": "none", "reason": "internal", "entries": [],
                                  "reply_text": self.app.pipeline.replies.with_lang(self._lang()).rejected().text,
                                  "lang": self._lang()})
                await self._state_msg(self.turn_id, "idle")
            except Exception:
                pass

    async def _interrupt(self) -> None:
        """Stop the running turn and any audio still being sent; tell the client the audio was cancelled."""
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except BaseException:
                pass
        if self.tts:
            await self.tts.cancel()
        if self._audio_open is not None:
            tid, self._audio_open = self._audio_open, None
            await self._send({"type": "audio_end", "turn_id": tid, "cancelled": True})

    def _ensure_stt(self) -> SttClient:
        if self.stt is None:
            settings = self.app.settings
            if is_regional(self._lang()):  # Gnani STT in kn-IN / mr-IN / ta-IN
                settings = dc_replace(settings, stt_language=REGIONAL[self._lang()][0], stt_format="transcribe")
            self.stt = self.app.stt_factory(
                settings, lambda: [c["name"] for c in self.app.ledger.customers_for_parser()])
        return self.stt

    def _ensure_state(self, session_id: str | None = None) -> SessionState:
        if self.state is None:
            self.state = SessionState(session_id=session_id or uuid.uuid4().hex[:16])
        if self.tts is None:
            self.tts = self.app.tts_factory(self.app.settings)
            self.tts.warm()
        return self.state

    # ---- client messages --------------------------------------------------------------------------------------
    async def _on_message(self, data: dict) -> bool:
        kind = data.get("type")
        code = self.app.settings.access_code
        if code and kind != "ping" and self.state is None and kind != "hello":
            await self._send({"type": "error", "code": "hello_required", "message": "send hello first"})
            return True
        if kind == "hello":
            return await self._hello(data)
        if kind == "ping":
            await self._send({"type": "pong", "t": data.get("t")})
        elif kind == "start":
            await self._interrupt()
            state = self._ensure_state()
            state.turn_id += 1
            self._collecting = True
            self._audio_bytes = 0
            self._turn_utt = clean_utt_id(data.get("utt_id"))
            self._new_turn_audio()  # the pre-roll frames the page sends first are its first frames
            self._ensure_stt()
            tid = state.turn_id
            await self._state_msg(tid, "listening")

            async def on_event(kind: str, text: str | None = None, tid=tid) -> None:
                if kind == "partial":
                    if tid == self.turn_id and text:
                        await self._send({"type": "transcript", "turn_id": tid, "text": text,
                                          "segment": 0, "final": False})
                else:
                    await self._state_msg(tid, kind)

            await self.stt.begin_turn(on_event)
        elif kind == "end":
            if self._collecting:
                self._collecting = False
                t_end = time.perf_counter()
                device_ts = _client_ts(data)
                noise = await self._close_turn_audio()  # the held frames go out before the commit
                if self._audio_bytes < MIN_AUDIO_BYTES:
                    self._spawn(self._short_turn(self.turn_id))
                else:
                    self._spawn(self._audio_turn(self.turn_id, t_end, self._turn_utt, device_ts, noise))
        elif kind == "text":
            text = str(data.get("text") or "").strip()
            await self._interrupt()
            state = self._ensure_state()
            state.turn_id += 1
            self._collecting = False
            t0 = time.perf_counter()
            if not text:
                self._spawn(self._none_turn(state.turn_id))
            else:
                self._spawn(self._respond(state.turn_id, text, t0, {"stt_final": 0.0},
                                          utt_id=clean_utt_id(data.get("utt_id")), device_ts=_client_ts(data)))
        elif kind == "settings":
            state = self._ensure_state()
            if "private" in data:
                state.private = bool(data.get("private"))
            lang = self._hello_lang(data) if "lang" in data else None
            if lang and lang != state.lang:
                # Language switched mid-conversation: replies follow it, and speech-to-text is reopened in it.
                state.lang = lang
                if self.stt is not None:
                    await self.stt.close()
                    self.stt = None
            await self._send({"type": "settings", "private": state.private,
                              "lang": state.lang if state.lang in ("hi", "en") else "en"})
        elif kind == "cancel":
            recording = self._collecting
            await self._interrupt()
            self._collecting = False
            self._discard_turn_audio()
            if recording:
                # An accidental press: the open recording ends like one shorter than half a second.
                self._spawn(self._short_turn(self.turn_id, "cancelled"))
            else:
                await self._state_msg(self.turn_id, "idle")
        return True

    def _lang(self) -> str:
        return self.state.lang if self.state else "hi"

    @staticmethod
    def _hello_lang(data: dict) -> str | None:
        lang = str(data.get("lang") or "").lower()[:2]
        return lang if lang in ("hi", "en", "kn", "mr", "ta") else None

    async def _hello(self, data: dict) -> bool:
        code = self.app.settings.access_code
        if code and not hmac.compare_digest(str(data.get("access_code") or ""), code):
            await self._send({"type": "error", "code": "access_denied", "message": "access code required"})
            await self.ws.close(code=1008)
            return False
        if self.state is not None:
            # A second hello on this socket: the old conversation ends and the new one starts (or resumes).
            await self._interrupt()
            self._collecting = False
            self.app.keep(self.state)
            self.state = None
        resume = data.get("resume")
        resumed = None
        if isinstance(resume, str) and _SESSION_ID.match(resume):
            resumed = self.app.resume(resume)
        if resumed is not None:
            self.state = resumed
            self._ensure_state()
            self._ensure_stt().warm()
            self.state.lang = self._hello_lang(data) or self.state.lang
            if "private" in data:
                resumed.private = bool(data.get("private"))
            if not data.get("keep_pending"):
                resumed.clear_pending()  # a reloaded page starts from a safe state (L05)
            ready = {"type": "ready", "session_id": resumed.session_id, "last_turn_id": resumed.turn_id}
            if resumed.last_result is not None:
                ready["last_result"] = resumed.last_result
            await self._send(ready)
            return True
        state = self._ensure_state()
        self._ensure_stt().warm()  # open the speech-to-text socket now, so the first press does not wait for it
        state.turn_id = 0
        state.lang = self._hello_lang(data) or "hi"
        state.private = bool(data.get("private"))
        await self._send({"type": "ready", "session_id": state.session_id})
        self._spawn(self._greeting_turn())
        return True

    async def _on_audio(self, pcm: bytes) -> None:
        if not self._collecting or self.stt is None:
            return
        self._audio_bytes += len(pcm)
        if self._turn_audio is None:
            self._new_turn_audio()
        self._abuf.extend(pcm)
        while len(self._abuf) >= FRAME_BYTES:
            frame = bytes(self._abuf[:FRAME_BYTES])
            del self._abuf[:FRAME_BYTES]
            for out in self._turn_audio.push(frame):
                await self.stt.send_audio(out)
        if self._audio_bytes >= MAX_AUDIO_BYTES:
            self._collecting = False
            noise = await self._close_turn_audio()
            self._spawn(self._too_long_turn(self.turn_id, noise))

    # ---- noise handling (CONTRACT 3.5) --------------------------------------------------------------------------
    def _new_turn_audio(self) -> None:
        s = self.app.settings
        self._turn_audio = TurnAudio(trim=s.noise_trim, trim_db=s.noise_trim_db, confirm_db=s.noise_confirm_db)
        self._abuf = bytearray()

    def _discard_turn_audio(self) -> None:
        """A cancelled recording: its audio goes nowhere and nothing of it reaches the next turn."""
        self._turn_audio = None
        self._abuf = bytearray()

    async def _close_turn_audio(self) -> dict | None:
        """Send the partial last frame and the frames the gate still holds, in order; return the turn's noise
        measurement for `timing` ({"separation_db","noisy","turned_down_ms"}) or None when there was no audio."""
        ta, self._turn_audio = self._turn_audio, None
        if ta is None:
            self._abuf = bytearray()
            return None
        held: list[bytes] = []
        if self._abuf:
            held += ta.push(bytes(self._abuf))
            self._abuf = bytearray()
        held += ta.flush()
        if self.stt is not None:
            for out in held:
                await self.stt.send_audio(out)
        stats = ta.stats()
        if not stats.get("frames"):
            return None
        return {"separation_db": stats["separation_db"], "noisy": bool(stats["noisy"]),
                "turned_down_ms": stats["turned_down_ms"]}

    # ---- turns ------------------------------------------------------------------------------------------------
    async def _greeting_turn(self) -> None:
        tid = self.turn_id
        t0 = time.perf_counter()
        turn = self.app.pipeline.greeting(self.state)
        await self._send(turn.message(tid))
        await self._speak(tid, turn, t0, {"stt_final": 0.0})

    async def _none_turn(self, tid: int, reason: str | None = None) -> None:
        trace = uuid.uuid4().hex[:16]
        msg = {"type": "result", "turn_id": tid, "trace_id": trace, "status": "rejected", "action": "none",
               "entries": [], "reply_text": "", "lang": self._lang()}
        if reason:
            msg["reason"] = reason
        await self._send(msg)
        await self._state_msg(tid, "idle")

    async def _drain_stt(self) -> None:
        """Close the open speech-to-text utterance of a turn whose words are not used."""
        try:
            await asyncio.wait_for(self.stt.end_turn(), FINAL_WAIT_S)
        except (asyncio.TimeoutError, Exception):
            pass

    async def _short_turn(self, tid: int, reason: str = "too_short") -> None:
        """A recording shorter than half a second, or cancelled while open: `action: "none"`, nothing spoken (M03)."""
        await self._none_turn(tid, reason)
        await self._drain_stt()

    async def _too_long_turn(self, tid: int, noise: dict | None = None) -> None:
        """A recording cut at 30 seconds: the too-long reply, nothing parsed or saved (M07)."""
        t0 = time.perf_counter()
        await self._state_msg(tid, "transcribing")
        await self._drain_stt()
        if tid != self.turn_id:
            return
        turn = self.app.pipeline.too_long(self.state)
        await self._send(turn.message(tid))
        await self._speak(tid, turn, t0, _noise_ms(noise))

    async def _fixed_turn(self, tid: int, turn: TurnResult, t_end: float, noise: dict | None = None) -> None:
        await self._send(turn.message(tid))
        await self._speak(tid, turn, t_end, _noise_ms(noise))

    async def _audio_turn(self, tid: int, t_end: float, utt_id: str | None = None,
                          device_ts: str | None = None, noise: dict | None = None) -> None:
        await self._state_msg(tid, "transcribing")
        try:
            res = await asyncio.wait_for(self.stt.end_turn(), FINAL_WAIT_S)
        except asyncio.TimeoutError:
            res = None
        stt_ms = _ms(t_end)
        if tid != self.turn_id:
            return
        if res is None or res.error:
            message = res.error if res is not None else "no final transcript"
            await self._send({"type": "error", "turn_id": tid, "code": "stt_upstream", "message": message})
            await self._upstream_failure(tid, t_end, noise)
            return
        if not res.text.strip():
            if res.heard:
                await self._fixed_turn(tid, self.app.pipeline.empty_transcript(self.state), t_end, noise)
            else:
                await self._fixed_turn(tid, self.app.pipeline.silence(self.state), t_end, noise)
            return
        last = len(res.segments) - 1
        for i in range(len(res.segments) - 1):
            await self._send({"type": "transcript", "turn_id": tid, "text": " ".join(res.segments[:i + 1]),
                              "segment": i, "final": False})
        await self._send({"type": "transcript", "turn_id": tid, "text": res.text, "segment": last, "final": True})
        await self._respond(tid, res.text, t_end, {"stt_final": stt_ms, "gnani_stt_latency": res.latency_ms,
                                                   **_noise_ms(noise)},
                            utt_id=utt_id, device_ts=device_ts, noisy=bool(noise and noise["noisy"]))

    async def _upstream_failure(self, tid: int, t_end: float, noise: dict | None = None) -> None:
        turn = self.app.pipeline.upstream_failure(self.state)
        await self._send(turn.message(tid))
        await self._speak(tid, turn, t_end, _noise_ms(noise))

    async def _respond(self, tid: int, text: str, t_start: float, base: dict, *, utt_id: str | None = None,
                       device_ts: str | None = None, noisy: bool = False) -> None:
        await self._state_msg(tid, "thinking")
        # `run_turn` is synchronous: a `start` that arrives while it runs is handled after it, so a saved entry is
        # always reported and only its speech can be cancelled (M10).
        turn = self.app.pipeline.run_turn(self.state, text, utt_id=utt_id, device_ts=device_ts, noisy=noisy)
        if turn.error_code:
            await self._send({"type": "error", "turn_id": tid, "code": turn.error_code,
                              "message": "this utt_id was already used for another sentence or session"})
            await self._state_msg(tid, "idle")
            return
        await self._send(turn.message(tid))
        if tid != self.turn_id:
            return
        await self._speak(tid, turn, t_start, {**base, **turn.timings})

    async def _speak(self, tid: int, turn: TurnResult, t_start: float, ms: dict) -> None:
        """Stream the reply audio. This runs only after the database transaction has committed."""
        await self._state_msg(tid, "speaking")
        timing = {"stt_final": None, "parse": None, "db": None, "tts_first_chunk": None,
                  "end_to_first_audio": None, "gnani_stt_latency": None}
        timing.update(ms)
        t_req = time.perf_counter()
        first = True
        completed = False
        try:
            if self.tts is None:
                self._ensure_state()
            async with aclosing(self.tts.synth(turn.speak_text, persist=turn.cacheable, lang=turn.lang)) as chunks:
                async for chunk in chunks:
                    if tid != self.turn_id:
                        return
                    if first:
                        first = False
                        timing["tts_first_chunk"] = _ms(t_req)
                        timing["end_to_first_audio"] = _ms(t_start)
                        rate = self.app.settings.tts_sample_rate
                        await self._send({"type": "audio_start", "turn_id": tid, "sample_rate": rate,
                                          "encoding": "pcm_s16le", "channels": 1})
                        self._audio_open = tid
                        await self._send_bytes(chunk)
                        await self._send({"type": "timing", "turn_id": tid, "trace_id": turn.trace_id, "ms": timing})
                    else:
                        await self._send_bytes(chunk)
            completed = True
        except TtsError as exc:
            await self._send({"type": "error", "turn_id": tid, "code": "tts_upstream", "message": str(exc)})
        except Exception as exc:
            log.error("speaking failed: %s", describe(exc))
            await self._send({"type": "error", "turn_id": tid, "code": "tts_upstream", "message": type(exc).__name__})
        # audio_end is always sent for audio that was started (a cancel is reported by `_interrupt` instead).
        if self._audio_open == tid:
            self._audio_open = None
            await self._send({"type": "audio_end", "turn_id": tid})
        if completed and not first:
            # The disclosure counts only once the audio that carries it has been sent to its end.
            self.app.pipeline.mark_spoken(self.state, turn)
        if first and tid == self.turn_id:
            await self._send({"type": "timing", "turn_id": tid, "trace_id": turn.trace_id, "ms": timing})
        await self._state_msg(tid, "idle")
