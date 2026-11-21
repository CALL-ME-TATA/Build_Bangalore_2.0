"""Streaming speech-to-text client for Gnani Prisma v3.0 (CONTRACT section 4).

One socket is kept per browser session. It is opened on the first push-to-talk press, reused while turns continue
and closed after `idle_close_s` seconds without use. Browser audio is re-framed to exactly 1,024 bytes (32 ms at
16 kHz); the last frame of a turn is padded with zeros. On release the client sends `{"type":"commit"}` so Gnani
closes the open utterance at once, then joins the transcript segments of the turn with a space.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import websockets

from ..config import STT_MODEL, Settings

log = logging.getLogger("khata.stt")

FRAME_BYTES = 1024
COMMIT_WAIT_S = 2.5
OPEN_GRACE_S = 0.2
LEDGER_WORDS = ["udhaar", "jama", "rupaye", "hazaar", "dedh", "dhai", "saade", "sawa", "paune"]

# Called with ("hearing" | "transcribing", None) or ("partial", text of the whole turn so far).
EventCallback = Callable[[str, str | None], Awaitable[None]]


@dataclass
class SttResult:
    text: str = ""
    segments: list[str] = field(default_factory=list)
    latency_ms: float | None = None
    error: str | None = None


def build_headers(settings: Settings, keyterms: list[str] | None = None) -> dict[str, str]:
    headers = {
        "x-api-key-id": settings.gnani_api_key,
        "model": STT_MODEL,
        # Gnani closes the socket (1008) on a comma-separated list, so exactly one code is sent.
        "language_code": settings.stt_language.split(",")[0].strip(),
        "format": settings.stt_format,
        "x-sample-rate": "16000",
        "x-idle-timeout-sec": "60",
    }
    terms = list(dict.fromkeys((keyterms or []) + LEDGER_WORDS))[:200]
    headers["keyterms"] = json.dumps(terms, ensure_ascii=True)
    if settings.stt_partials:
        headers["x-partials"] = "true"
    if settings.stt_min_silence_ms is not None:
        headers["x-min-silence-ms"] = str(settings.stt_min_silence_ms)
    return headers


def reframe(buf: bytearray, chunk: bytes) -> list[bytes]:
    """Append `chunk` to `buf` and return every complete 1,024-byte frame, leaving the remainder in `buf`."""
    buf.extend(chunk)
    frames = []
    while len(buf) >= FRAME_BYTES:
        frames.append(bytes(buf[:FRAME_BYTES]))
        del buf[:FRAME_BYTES]
    return frames


class SttClient:
    def __init__(self, settings: Settings, keyterms: Callable[[], list[str]] | None = None, *,
                 idle_close_s: float = 45.0, commit_wait_s: float = COMMIT_WAIT_S):
        self.settings = settings
        self._keyterms = keyterms or (lambda: [])
        self.idle_close_s = idle_close_s
        self.commit_wait_s = commit_wait_s
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._idle: asyncio.Task | None = None
        self._changed = asyncio.Event()
        self._on_event: EventCallback | None = None
        self._buf = bytearray()
        self._sent_frames = 0
        self._reset_turn()

    def _reset_turn(self) -> None:
        self._open: set[str] = set()
        self._segments: list[str] = []
        self._latency: float | None = None
        self._error: str | None = None
        self._buf = bytearray()
        self._sent_frames = 0

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._reader is not None and not self._reader.done()

    # ---- connection -------------------------------------------------------------------------------------------
    async def _connect(self) -> None:
        headers = build_headers(self.settings, self._keyterms())
        self._ws = await websockets.connect(self.settings.stt_url, additional_headers=headers, max_size=None,
                                            open_timeout=5, ping_interval=20, ping_timeout=20)
        self._reader = asyncio.create_task(self._read(self._ws))

    async def _emit(self, kind: str, text: str | None = None) -> None:
        if self._on_event is not None:
            try:
                await self._on_event(kind, text)
            except Exception:
                log.exception("stt event callback failed")

    async def _read(self, ws) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                kind = msg.get("type")
                uid = str(msg.get("utterance_id") or "?")
                if kind == "speech_start":
                    self._open.add(uid)
                    await self._emit("hearing")
                elif kind in ("processing", "speech_end"):
                    self._open.add(uid)
                    await self._emit("transcribing")
                elif kind == "partial_transcript":
                    self._open.add(uid)
                    partial = (msg.get("text") or "").strip()
                    await self._emit("partial", " ".join(self._segments + ([partial] if partial else [])))
                elif kind in ("transcript", "final_transcript"):
                    text = (msg.get("text") or "").strip()
                    if text:
                        self._segments.append(text)
                    lat = msg.get("latency")
                    if isinstance(lat, (int, float)):
                        self._latency = float(lat)
                    if uid in self._open:
                        self._open.discard(uid)
                    elif self._open:
                        self._open.pop()
                elif kind == "error":
                    self._error = str(msg.get("message") or "stt error")
                    self._open.clear()
                self._changed.set()
        except websockets.ConnectionClosed:
            pass
        except Exception:
            log.exception("stt reader failed")
        finally:
            if self._ws is ws:
                self._ws = None
            self._open.clear()
            self._changed.set()

    # ---- turn API ---------------------------------------------------------------------------------------------
    async def begin_turn(self, on_event: EventCallback | None = None) -> None:
        """Open (or reuse) the socket and reset per-turn state. A connection failure is reported by `end_turn`."""
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        self._on_event = on_event
        self._reset_turn()
        if not self.connected:
            try:
                await self._connect()
            except Exception as exc:
                log.warning("stt connect failed: %s", type(exc).__name__)
                self._error = f"connect failed: {type(exc).__name__}"

    async def send_audio(self, pcm: bytes) -> None:
        if self._error or not self.connected:
            return
        for frame in reframe(self._buf, pcm):
            try:
                await self._ws.send(frame)
                self._sent_frames += 1
            except websockets.ConnectionClosed:
                self._error = "connection closed"
                return

    async def end_turn(self) -> SttResult:
        """Send the padded last frame and `commit`, wait per the rule in CONTRACT section 4, return the text."""
        try:
            return await self._end_turn()
        finally:
            self._on_event = None
            self._idle = asyncio.create_task(self._idle_close())

    async def _end_turn(self) -> SttResult:
        if self._error and not self._segments:
            return SttResult(error=self._error)
        if self.connected:
            try:
                if self._buf:
                    await self._ws.send(bytes(self._buf) + bytes(FRAME_BYTES - len(self._buf)))
                    self._buf = bytearray()
                    self._sent_frames += 1
                if self._sent_frames:
                    await self._ws.send(json.dumps({"type": "commit"}))
            except websockets.ConnectionClosed:
                self._error = "connection closed"
        if self._sent_frames and not self._error:
            loop = asyncio.get_running_loop()
            if not self._open and not self._segments:
                # Allow a short grace period for a speech_start that is still in flight.
                self._changed.clear()
                try:
                    await asyncio.wait_for(self._changed.wait(), OPEN_GRACE_S)
                except asyncio.TimeoutError:
                    pass
            deadline = loop.time() + self.commit_wait_s
            while self._open and not self._error:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                self._changed.clear()
                if not self._open:
                    break
                try:
                    await asyncio.wait_for(self._changed.wait(), remaining)
                except asyncio.TimeoutError:
                    break
        segments = list(self._segments)
        if self._error and not segments:
            return SttResult(error=self._error)
        return SttResult(text=" ".join(segments), segments=segments, latency_ms=self._latency)

    async def _idle_close(self) -> None:
        try:
            await asyncio.sleep(self.idle_close_s)
        except asyncio.CancelledError:
            return
        await self.close()

    async def close(self) -> None:
        if self._idle is not None and self._idle is not asyncio.current_task():
            self._idle.cancel()
        self._idle = None
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
