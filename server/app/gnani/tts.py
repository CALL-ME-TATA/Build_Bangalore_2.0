"""Text-to-speech client for Gnani Timbre v3.0 (CONTRACT section 4).

One socket is kept per browser session and opened ahead of time (`warm`), so a reply does not wait for a handshake.
Gnani accepts one request at a time on a socket and the socket stays open for the next request. A reply is
cancelled by closing the socket; a new one is then opened in the background. Audio is cached by the hash of
(text, voice, model, sample rate) in memory and under `data/tts_cache/`.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import AsyncIterator

import websockets

from ..config import TTS_MODEL, Settings

log = logging.getLogger("khata.tts")

CACHE_CHUNK = 9600  # bytes sent per frame when audio comes from the cache (200 ms at 24 kHz)
_memory_cache: dict[str, bytes] = {}


class TtsError(Exception):
    pass


def cache_key(settings: Settings, text: str) -> str:
    # The service address is part of the key, so audio from a mock server is never replayed as real speech.
    raw = "\x1f".join([text, settings.tts_voice, TTS_MODEL, str(settings.tts_sample_rate),
                       settings.tts_language, settings.gnani_base_url])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def strip_wav_header(chunk: bytes) -> bytes:
    """Drop a RIFF/WAV header if the chunk starts with one; raw PCM passes through unchanged."""
    if chunk[:4] != b"RIFF":
        return chunk
    idx = chunk.find(b"data", 12)
    if idx == -1 or idx + 8 > len(chunk):
        return b""
    return chunk[idx + 8:]


class TtsClient:
    def __init__(self, settings: Settings, cache_dir: Path | None = None, memory_cache: dict[str, bytes] | None = None):
        self.settings = settings
        self.cache_dir = cache_dir if cache_dir is not None else settings.tts_cache_dir
        self._mem = memory_cache if memory_cache is not None else _memory_cache
        self._ws = None
        self._lock = asyncio.Lock()
        self._warm_task: asyncio.Task | None = None
        self.busy = False
        self.closed = False

    # ---- socket -----------------------------------------------------------------------------------------------
    async def _connect(self):
        return await websockets.connect(self.settings.tts_url,
                                        additional_headers={"X-API-Key-ID": self.settings.gnani_api_key},
                                        max_size=None, open_timeout=5, ping_interval=20, ping_timeout=20)

    def warm(self) -> None:
        """Start opening the socket in the background."""
        if self.closed or self._warm_task is not None and not self._warm_task.done():
            return
        self._warm_task = asyncio.create_task(self._warm())

    async def _warm(self) -> None:
        try:
            async with self._lock:
                if self._ws is None and not self.closed:
                    self._ws = await self._connect()
        except Exception as exc:
            log.warning("tts warm-up failed: %s", type(exc).__name__)

    async def _drop_socket(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    async def cancel(self) -> None:
        """Drop the in-flight request by closing the socket, then reopen one in the background."""
        if not self.busy:
            return
        await self._drop_socket()
        self.warm()

    async def close(self) -> None:
        self.closed = True
        if self._warm_task is not None:
            self._warm_task.cancel()
        await self._drop_socket()

    # ---- cache ------------------------------------------------------------------------------------------------
    def cached(self, text: str) -> bytes | None:
        key = cache_key(self.settings, text)
        if key in self._mem:
            return self._mem[key]
        path = self.cache_dir / f"{key}.pcm"
        if path.exists():
            data = path.read_bytes()
            self._mem[key] = data
            return data
        return None

    def _store(self, text: str, pcm: bytes) -> None:
        key = cache_key(self.settings, text)
        self._mem[key] = pcm
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.pcm").write_bytes(pcm)
        except OSError:
            log.warning("tts cache write failed")

    # ---- synthesis --------------------------------------------------------------------------------------------
    def _request(self, text: str) -> str:
        return json.dumps({
            "text": text, "voice": self.settings.tts_voice, "model": TTS_MODEL,
            "language": self.settings.tts_language, "speed": 1.0,
            "audio_config": {"sample_rate": self.settings.tts_sample_rate, "num_channels": 1, "sample_width": 2,
                             "encoding": "linear_pcm", "container": "raw"},
        }, ensure_ascii=False)

    async def synth(self, text: str) -> AsyncIterator[bytes]:
        """Yield PCM chunks (16-bit little-endian). Cached audio is served without touching the network."""
        hit = self.cached(text)
        if hit is not None:
            for i in range(0, len(hit), CACHE_CHUNK):
                yield hit[i:i + CACHE_CHUNK]
            return
        async with self._lock:
            self.busy = True
            done = False
            collected = bytearray()
            carry = b""
            try:
                for attempt in (1, 2):
                    if self._ws is None:
                        self._ws = await self._connect()
                    try:
                        await self._ws.send(self._request(text))
                        break
                    except websockets.ConnectionClosed:
                        self._ws = None
                        if attempt == 2:
                            raise TtsError("connection closed")
                ws = self._ws
                # Gnani sends a second `complete` (with `message`, without `data`) after each reply, and
                # start.request_id names the connection. Messages before this request's `start` are discarded.
                seen_start = False
                async for raw in ws:
                    msg = json.loads(raw)
                    kind = msg.get("type")
                    if kind == "start":
                        seen_start = True
                        continue
                    if kind == "error":
                        raise TtsError(str(msg.get("message") or "tts error"))
                    if not seen_start:
                        continue
                    if kind == "audio":
                        data = base64.b64decode((msg.get("data") or {}).get("audio") or "")
                        data = carry + strip_wav_header(data)
                        if len(data) % 2:
                            carry, data = data[-1:], data[:-1]
                        else:
                            carry = b""
                        if data:
                            collected.extend(data)
                            yield data
                    elif kind == "complete":
                        done = True
                        break
                    elif kind == "error":
                        raise TtsError(str(msg.get("message") or "tts error"))
                else:
                    raise TtsError("connection closed before complete")
                if collected:
                    self._store(text, bytes(collected))
            except websockets.ConnectionClosed as exc:
                raise TtsError("connection closed") from exc
            finally:
                self.busy = False
                if not done:
                    # An unfinished request is dropped by closing the socket; a fresh one opens in the background.
                    await self._drop_socket()
                    if not self.closed:
                        self.warm_later()

    def warm_later(self) -> None:
        """Schedule a background reconnect without awaiting the socket lock held by the caller."""
        if self.closed:
            return
        loop = asyncio.get_running_loop()
        loop.call_soon(self.warm)
