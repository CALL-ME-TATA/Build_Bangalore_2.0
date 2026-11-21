"""Streaming speech-to-text client for Gnani Prisma v3.0 (CONTRACT section 4).

One socket is kept per browser session. It is opened ahead of time (`warm`, called at `hello`), asks Gnani for the
longest idle timeout, is reused for every turn and is reopened in the background whenever it closes (idle timeout,
session cap, network drop). A press never waits for a handshake when a socket is up. `idle_close_s` can still be set
to close an unused socket. Browser audio is re-framed to exactly 1,024 bytes (32 ms at
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
# The websockets library logs upgrade headers (keyterms hold customer names) and frames at DEBUG level.
WS_LOG = logging.getLogger("khata.ws")
WS_LOG.setLevel(logging.INFO)
WS_LOG.propagate = False

FRAME_BYTES = 1024
COMMIT_WAIT_S = 2.5
OPEN_WAIT_S = 1.0  # after commit: how long to wait for an utterance to open when audio was sent
LEDGER_WORDS = ["udhaar", "jama", "rupaye", "hazaar", "dedh", "dhai", "saade", "sawa", "paune"]

# Called with ("hearing" | "transcribing", None) or ("partial", text of the whole turn so far).
EventCallback = Callable[[str, str | None], Awaitable[None]]


@dataclass
class SttResult:
    text: str = ""
    segments: list[str] = field(default_factory=list)
    latency_ms: float | None = None
    error: str | None = None
    heard: bool = False  # Gnani reported speech in this turn (speech_start, processing, a partial or a transcript)


def build_headers(settings: Settings, keyterms: list[str] | None = None) -> dict[str, str]:
    headers = {
        "x-api-key-id": settings.gnani_api_key,
        "model": STT_MODEL,
        # Gnani closes the socket (1008) on a comma-separated list, so exactly one code is sent.
        "language_code": settings.stt_language.split(",")[0].strip(),
        "format": settings.stt_format,
        "x-sample-rate": "16000",
        "x-idle-timeout-sec": "900",
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
                 idle_close_s: float | None = None, commit_wait_s: float = COMMIT_WAIT_S):
        self.settings = settings
        self._keyterms = keyterms or (lambda: [])
        self.idle_close_s = idle_close_s
        self.commit_wait_s = commit_wait_s
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._idle: asyncio.Task | None = None
        self._closed = False
        self._conn_lock = asyncio.Lock()
        self._bg: set[asyncio.Task] = set()
        self._changed = asyncio.Event()
        self._on_event: EventCallback | None = None
        self._buf = bytearray()
        self._sent_frames = 0
        # Audio of a turn was sent and the turn has not finished normally (it was cancelled or is still closing).
        # The next turn then gets a fresh socket, so the old utterance can never leak into it.
        self._dirty = False
        self._reset_turn()

    def _reset_turn(self) -> None:
        # Utterances still open when a new turn begins belong to the previous turn; their events are ignored.
        self._stale = set(getattr(self, "_open", set())) | set(getattr(self, "_stale", set()))
        self._lost = False
        self._heard = False
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
                                            open_timeout=5, ping_interval=20, ping_timeout=20, logger=WS_LOG)
        self._reader = asyncio.create_task(self._read(self._ws))

    async def ensure_connected(self) -> None:
        """Connect unless a socket is up. Concurrent callers share one handshake."""
        async with self._conn_lock:
            if not self.connected:
                await self._connect()

    def warm(self) -> None:
        """Open the socket in the background (called at hello and whenever the socket closes)."""
        if self._closed or self.connected:
            return
        task = asyncio.create_task(self._warm())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _warm(self) -> None:
        try:
            await self.ensure_connected()
        except Exception as exc:
            log.warning("stt warm-up failed: %s", type(exc).__name__)

    async def _emit(self, kind: str, text: str | None = None) -> None:
        if self._on_event is not None:
            try:
                await self._on_event(kind, text)
            except Exception:
                log.exception("stt event callback failed")

    async def _read(self, ws) -> None:
        try:
            async for raw in ws:
                if self._ws is not ws:
                    break  # a replaced socket: its events belong to an abandoned turn
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                kind = msg.get("type")
                uid = str(msg.get("utterance_id") or "?")
                if uid in self._stale and kind != "error":
                    continue
                if kind in ("speech_start", "processing", "speech_end", "partial_transcript", "transcript",
                            "final_transcript"):
                    self._heard = True
                if kind == "speech_start":
                    self._open.add(uid)
                    self._changed.set()
                    await self._emit("hearing")
                elif kind in ("processing", "speech_end"):
                    self._open.add(uid)
                    self._changed.set()
                    await self._emit("transcribing")
                elif kind == "partial_transcript":
                    self._open.add(uid)
                    self._changed.set()
                    partial = (msg.get("text") or "").strip()
                    await self._emit("partial", " ".join(self._segments + ([partial] if partial else [])))
                elif kind in ("transcript", "final_transcript"):
                    text = (msg.get("text") or "").strip()
                    if text:
                        self._segments.append(text)
                    lat = msg.get("latency")
                    if isinstance(lat, (int, float)):
                        self._latency = float(lat)
                    self._open.discard(uid)
                    self._changed.set()
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
                self._lost = True
                self.warm()  # replace the socket in the background
            self._changed.set()

    # ---- turn API ---------------------------------------------------------------------------------------------
    async def begin_turn(self, on_event: EventCallback | None = None) -> None:
        """Open (or reuse) the socket and reset per-turn state. A connection failure is reported by `end_turn`."""
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        self._on_event = on_event
        self._closed = False
        if self._dirty:
            await self._replace_socket()
        self._reset_turn()
        if not self.connected:
            try:
                await self.ensure_connected()
            except Exception as exc:
                log.warning("stt connect failed: %s", type(exc).__name__)
                self._error = f"connect failed: {type(exc).__name__}"

    async def _replace_socket(self) -> None:
        """Drop the current socket (the previous turn's utterance is unresolved) and forget its open utterances."""
        self._dirty = False
        ws, self._ws = self._ws, None
        reader, self._reader = self._reader, None
        self._open = set()
        self._stale = set()
        if reader is not None:
            reader.cancel()
        tail = bytes(self._buf) + bytes(FRAME_BYTES - len(self._buf)) if self._buf else b""
        self._buf = bytearray()
        if ws is not None:
            task = asyncio.create_task(self._close_quietly(ws, tail))
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)

    @staticmethod
    async def _close_quietly(ws, tail: bytes = b"") -> None:
        """Commit the abandoned audio (so its utterance is closed upstream), then close the socket."""
        try:
            if tail:
                await ws.send(tail)
            await ws.send(json.dumps({"type": "commit"}))
        except Exception:
            pass
        try:
            await asyncio.wait_for(ws.close(), 1.0)
        except Exception:
            pass

    async def send_audio(self, pcm: bytes) -> None:
        if self._error or self._lost or not self.connected:
            return
        if pcm:
            self._dirty = True
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
            result = await self._end_turn()
            self._dirty = False
            return result
        finally:
            self._on_event = None
            if self.idle_close_s:
                self._idle = asyncio.create_task(self._idle_close(self._ws))

    async def _end_turn(self) -> SttResult:
        if self._error and not self._segments:
            return SttResult(error=self._error)
        if self._lost and self._sent_frames:
            return SttResult(error="connection closed")
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
            # Audio was sent but nothing has opened yet: a burst of buffered audio can be committed before Gnani
            # reports speech_start. Wait for an utterance, a transcript or an error before concluding "no speech".
            opened_by = loop.time() + OPEN_WAIT_S
            while not (self._open or self._segments or self._error or self._lost):
                remaining = opened_by - loop.time()
                if remaining <= 0:
                    break
                self._changed.clear()
                try:
                    await asyncio.wait_for(self._changed.wait(), remaining)
                except asyncio.TimeoutError:
                    break
            deadline = loop.time() + self.commit_wait_s
            while self._open and not self._error and not self._lost:
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
        if self._sent_frames and not self._error:
            # A half sentence must never be saved: an utterance that never finished, or a socket that closed
            # after audio was sent without a final transcript, is an error.
            if self._open:
                self._error = "connection closed" if self._lost else "no final transcript"
            elif self._lost and not segments:
                self._error = "connection closed"
        if self._error:
            return SttResult(error=self._error, heard=self._heard)
        return SttResult(text=" ".join(segments), segments=segments, latency_ms=self._latency, heard=self._heard)

    async def _idle_close(self, ws) -> None:
        """Close the socket this task was scheduled for, and only that one."""
        try:
            await asyncio.sleep(self.idle_close_s or 0)
        except asyncio.CancelledError:
            return
        if ws is not None and self._ws is ws:
            self._ws = None
            try:
                await ws.close()
            except Exception:
                pass

    async def close(self) -> None:
        """Close the socket for good (the browser session ended). No replacement is opened."""
        self._closed = True
        for task in list(self._bg):
            task.cancel()
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
