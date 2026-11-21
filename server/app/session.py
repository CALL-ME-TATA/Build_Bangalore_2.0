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
from typing import Any, Callable

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .config import Settings
from .gnani.stt import SttClient
from .gnani.tts import TtsClient, TtsError
from .ledger import Ledger
from .pipeline import Pipeline, SessionState, TurnResult

log = logging.getLogger("khata.session")

MAX_AUDIO_BYTES = 30 * 16000 * 2  # 30 s of 16 kHz PCM16
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

    @property
    def turn_id(self) -> int:
        return self.state.turn_id if self.state else -1

    # ---- sending ----------------------------------------------------------------------------------------------
    async def _send(self, msg: dict) -> None:
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

    async def _guard(self, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("turn failed")
            try:
                await self._send({"type": "error", "turn_id": self.turn_id, "code": "internal",
                                  "message": "turn failed"})
                await self._send({"type": "result", "turn_id": self.turn_id, "trace_id": uuid.uuid4().hex[:16],
                                  "status": "rejected", "action": "none", "reason": "internal", "entries": [],
                                  "reply_text": self.app.pipeline.replies.rejected().text})
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
            if self.stt is None:
                s = self.app.settings
                self.stt = self.app.stt_factory(s, lambda: [c["name"] for c in self.app.ledger.customers_for_parser()])
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
                self._spawn(self._audio_turn(self.turn_id, time.perf_counter()))
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
                self._spawn(self._respond(state.turn_id, text, t0, {"stt_final": 0.0}))
        elif kind == "cancel":
            await self._interrupt()
            self._collecting = False
            await self._state_msg(self.turn_id, "idle")
        return True

    async def _hello(self, data: dict) -> bool:
        code = self.app.settings.access_code
        if code and not hmac.compare_digest(str(data.get("access_code") or ""), code):
            await self._send({"type": "error", "code": "access_denied", "message": "access code required"})
            await self.ws.close(code=1008)
            return False
        if self.state is not None:
            return True
        resume = data.get("resume")
        resumed = None
        if isinstance(resume, str) and _SESSION_ID.match(resume):
            resumed = self.app.resume(resume)
        if resumed is not None:
            self.state = resumed
            self._ensure_state()
            await self._send({"type": "ready", "session_id": resumed.session_id})
            return True
        state = self._ensure_state()
        state.turn_id = 0
        await self._send({"type": "ready", "session_id": state.session_id})
        self._spawn(self._greeting_turn())
        return True

    async def _on_audio(self, pcm: bytes) -> None:
        if not self._collecting or self.stt is None:
            return
        self._audio_bytes += len(pcm)
        await self.stt.send_audio(pcm)
        if self._audio_bytes >= MAX_AUDIO_BYTES:
            self._collecting = False
            self._spawn(self._audio_turn(self.turn_id, time.perf_counter()))

    # ---- turns ------------------------------------------------------------------------------------------------
    async def _greeting_turn(self) -> None:
        tid = self.turn_id
        t0 = time.perf_counter()
        turn = self.app.pipeline.greeting(self.state)
        await self._send(turn.message(tid))
        await self._speak(tid, turn, t0, {"stt_final": 0.0})

    async def _none_turn(self, tid: int, extra: dict | None = None) -> None:
        trace = uuid.uuid4().hex[:16]
        await self._send({"type": "result", "turn_id": tid, "trace_id": trace, "status": "rejected",
                          "action": "none", "entries": [], "reply_text": ""})
        await self._state_msg(tid, "idle")

    async def _audio_turn(self, tid: int, t_end: float) -> None:
        await self._state_msg(tid, "transcribing")
        res = await self.stt.end_turn()
        stt_ms = _ms(t_end)
        if tid != self.turn_id:
            return
        if res.error:
            await self._send({"type": "error", "turn_id": tid, "code": "stt_upstream", "message": res.error})
            await self._upstream_failure(tid, t_end)
            return
        if not res.text.strip():
            await self._none_turn(tid)
            return
        last = len(res.segments) - 1
        for i in range(len(res.segments) - 1):
            await self._send({"type": "transcript", "turn_id": tid, "text": " ".join(res.segments[:i + 1]),
                              "segment": i, "final": False})
        await self._send({"type": "transcript", "turn_id": tid, "text": res.text, "segment": last, "final": True})
        await self._respond(tid, res.text, t_end, {"stt_final": stt_ms, "gnani_stt_latency": res.latency_ms})

    async def _upstream_failure(self, tid: int, t_end: float) -> None:
        reply = self.app.pipeline.replies.upstream_failure()
        trace = uuid.uuid4().hex[:16]
        turn = TurnResult("rejected", "none", reply.text, reply.speak, trace, uuid.uuid4().hex[:12],
                          reason="upstream")
        await self._send(turn.message(tid))
        await self._speak(tid, turn, t_end, {})

    async def _respond(self, tid: int, text: str, t_start: float, base: dict) -> None:
        await self._state_msg(tid, "thinking")
        turn = self.app.pipeline.run_turn(self.state, text)
        if tid != self.turn_id:
            return
        await self._send(turn.message(tid))
        await self._speak(tid, turn, t_start, {**base, **turn.timings})

    async def _speak(self, tid: int, turn: TurnResult, t_start: float, ms: dict) -> None:
        """Stream the reply audio. This runs only after the database transaction has committed."""
        await self._state_msg(tid, "speaking")
        timing = {"stt_final": None, "parse": None, "db": None, "tts_first_chunk": None,
                  "end_to_first_audio": None, "gnani_stt_latency": None}
        timing.update(ms)
        t_req = time.perf_counter()
        first = True
        try:
            if self.tts is None:
                self._ensure_state()
            async with aclosing(self.tts.synth(turn.speak_text)) as chunks:
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
            if self._audio_open == tid:
                self._audio_open = None
                await self._send({"type": "audio_end", "turn_id": tid})
        except TtsError as exc:
            await self._send({"type": "error", "turn_id": tid, "code": "tts_upstream", "message": str(exc)})
            if self._audio_open == tid:
                self._audio_open = None
                await self._send({"type": "audio_end", "turn_id": tid})
        except Exception as exc:
            await self._send({"type": "error", "turn_id": tid, "code": "tts_upstream", "message": type(exc).__name__})
        if first and tid == self.turn_id:
            await self._send({"type": "timing", "turn_id": tid, "trace_id": turn.trace_id, "ms": timing})
        await self._state_msg(tid, "idle")
