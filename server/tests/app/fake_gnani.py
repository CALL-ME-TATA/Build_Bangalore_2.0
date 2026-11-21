"""A small fake Gnani server for tests, following the messages in CONTRACT section 4."""
from __future__ import annotations

import asyncio
import base64
import json

import websockets


class FakeGnani:
    def __init__(self) -> None:
        self.transcripts: list[str] = ["ramesh ka 340 udhaar"]
        self.speech = True
        self.tts_chunks = 3
        self.tts_chunk_delay = 0.0
        self.stt_sessions: list[dict] = []
        self.tts_requests: list[dict] = []
        self.tts_closed = 0
        self.tts_headers: list[dict] = []
        self.second_complete = True  # the real service sends a second `complete` without `data`
        self.server = None
        self.port = 0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> None:
        self.server = await websockets.serve(self._handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def _handler(self, ws) -> None:
        path = ws.request.path
        if path.startswith("/stt/v3/stream"):
            await self._stt(ws)
        elif path.startswith("/api/v1/tts"):
            await self._tts(ws)
        else:
            await ws.close(1008)

    async def _stt(self, ws) -> None:
        rec = {"headers": dict(ws.request.headers.items()), "frames": [], "commits": 0}
        self.stt_sessions.append(rec)
        await ws.send(json.dumps({"type": "connected", "config": {}, "request_id": "r1"}))
        started = False
        partials = rec["headers"].get("x-partials") == "true"
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    rec["frames"].append(len(raw))
                    if self.speech and not started:
                        started = True
                        await ws.send(json.dumps({"type": "speech_start", "utterance_id": "u1"}))
                        if partials and self.transcripts:
                            first = self.transcripts[0].split()[0]
                            await ws.send(json.dumps({"type": "partial_transcript", "text": first,
                                                      "stable_text": "", "volatile_text": first, "seq": 1,
                                                      "utterance_id": "u1"}))
                elif json.loads(raw).get("type") == "commit":
                    rec["commits"] += 1
                    if self.speech:
                        await ws.send(json.dumps({"type": "speech_end" if partials else "processing",
                                                  "utterance_id": "u1"}))
                        for i, text in enumerate(self.transcripts):
                            await ws.send(json.dumps({
                                "type": "final_transcript" if partials else "transcript", "text": text, "segment_index": i, "latency": 123,
                                "is_final": True, "utterance_id": "u1", "audio_duration_ms": 1000}))
                    started = False
        except websockets.ConnectionClosed:
            pass

    async def _tts(self, ws) -> None:
        self.tts_headers.append(dict(ws.request.headers.items()))
        try:
            async for raw in ws:
                req = json.loads(raw)
                self.tts_requests.append(req)
                await ws.send(json.dumps({"type": "start", "request_id": "t1"}))
                for i in range(self.tts_chunks):
                    if self.tts_chunk_delay:
                        await asyncio.sleep(self.tts_chunk_delay)
                    audio = base64.b64encode(bytes([i + 1]) * 4800).decode()
                    await ws.send(json.dumps({"type": "audio", "data": {"chunk_index": i, "audio": audio,
                                                                       "is_final": False}}))
                await ws.send(json.dumps({"type": "complete", "data": {"is_final": True}}))
                if self.second_complete:
                    await ws.send(json.dumps({"type": "complete", "message": "done", "request_id": "t1"}))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.tts_closed += 1
