"""A live stack for the edge tests that need the real WebSocket session: the app, the mock Gnani server and a
synchronous client, all driven from plain (non-async) tests.

The app and the mock run on an event loop in a background thread. The app's clock is controllable, so
tests about opening hours do not depend on the time of day.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from websockets.sync.client import connect

IST = ZoneInfo("Asia/Kolkata")
SAMPLE_RATE = 16000
CHUNK_BYTES = 640  # 20 ms of 16 kHz PCM16


class LiveClock:
    """The app's clock: real shop time unless a test fixes it."""

    def __init__(self) -> None:
        self.fixed: datetime | None = None

    def __call__(self) -> datetime:
        return self.fixed or datetime.now(IST)

    def set(self, value: datetime | None) -> None:
        self.fixed = value


def pcm_audio(ms: int = 800) -> bytes:
    n = SAMPLE_RATE * ms // 1000
    return struct.pack(f"<{n}h", *[int(2000 * ((i // 40) % 2 * 2 - 1)) for i in range(n)])


class Collected(dict):
    """The messages of one turn, sorted into fields."""

    @property
    def result(self) -> dict:
        return self["result"]

    @property
    def types(self) -> list[str]:
        return [m["type"] for m in self["msgs"]]

    def of(self, kind: str) -> list[dict]:
        return [m for m in self["msgs"] if m["type"] == kind]


class WsClient:
    def __init__(self, stack: "LiveStack", cm) -> None:
        self.stack = stack
        self._cm = cm
        self.ws = cm.__enter__()
        self.session_id: str | None = None
        self.turn = -1
        self.ready: dict | None = None

    # ---- raw ------------------------------------------------------------------------------------------------
    def send(self, msg: dict) -> None:
        self.ws.send(json.dumps(msg))

    def recv(self, timeout: float = 10.0):
        raw = self.ws.recv(timeout=timeout)
        return raw if isinstance(raw, bytes) else json.loads(raw)

    def close(self) -> None:
        try:
            self._cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass

    # ---- collecting -------------------------------------------------------------------------------------------
    def collect(self, min_turn: int = 0, timeout: float = 12.0, settle: float = 1.5) -> Collected:
        """Read until the turn's result has arrived and its audio and state messages are done."""
        out = Collected(msgs=[], frames=0, result=None, audio_start=None, audio_end=None, timing=None,
                        errors=[], ready=None)
        end = time.monotonic() + timeout
        result_seen_at = None
        while True:
            now = time.monotonic()
            if now >= end or (result_seen_at is not None and now - result_seen_at > settle):
                break
            try:
                msg = self.recv(min(0.5, max(0.05, end - now)))
            except TimeoutError:
                continue
            if isinstance(msg, bytes):
                out["frames"] += 1
                continue
            out["msgs"].append(msg)
            kind = msg["type"]
            tid = msg.get("turn_id", min_turn)
            if kind == "ready":
                self.session_id = msg["session_id"]
                out["ready"] = msg
                self.ready = msg
            elif tid < min_turn:
                continue
            elif kind == "result":
                out["result"] = msg
                result_seen_at = now
                self.turn = max(self.turn, tid)
            elif kind == "audio_start":
                out["audio_start"] = msg
            elif kind == "audio_end":
                out["audio_end"] = msg
            elif kind == "timing":
                out["timing"] = msg
            elif kind == "error":
                out["errors"].append(msg)
            elif kind == "state" and msg.get("state") == "idle" and out["result"] is not None:
                break
        if out["result"] is None:
            raise AssertionError(f"no result within {timeout}s; messages: {[m['type'] for m in out['msgs']]} "
                                 f"errors: {out['errors']}")
        return out

    # ---- turns ------------------------------------------------------------------------------------------------
    def text(self, text: str, utt_id: str | None = None, client_ts: str | None = None, **extra) -> Collected:
        msg: dict[str, Any] = {"type": "text", "text": text, **extra}
        if utt_id:
            msg["utt_id"] = utt_id
        if client_ts:
            msg["client_ts"] = client_ts
        self.send(msg)
        return self.collect(min_turn=self.turn + 1)

    def speak(self, transcript, audio_ms: int = 800, realtime: bool = True, utt_id: str | None = None,
              collect: bool = True, **script) -> Collected | None:
        """Script the mock with `transcript` (any shape the mock accepts), then press, send audio and release."""
        body = {"transcripts": [transcript], **script}
        self.stack.mock_script(**body)
        start: dict[str, Any] = {"type": "start", "mode": "ptt"}
        if utt_id:
            start["utt_id"] = utt_id
        self.send(start)
        audio = pcm_audio(audio_ms)
        for i in range(0, len(audio), CHUNK_BYTES):
            self.ws.send(audio[i:i + CHUNK_BYTES])
            if realtime:
                time.sleep(0.005)
        self.send({"type": "end"})
        return self.collect(min_turn=self.turn + 1) if collect else None


class LiveStack:
    def __init__(self, tmp_path, env: dict | None = None) -> None:
        self.tmp = tmp_path
        self.env = env or {}
        self.clock = LiveClock()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._stops: list = []
        self.clients: list[WsClient] = []
        self.http: httpx.Client | None = None
        self.mock_http: httpx.Client | None = None

    # ---- life cycle -------------------------------------------------------------------------------------------
    def start(self) -> "LiveStack":
        from mock_gnani.testing import serve_app, start_mock

        self.thread.start()
        self.tmp.mkdir(parents=True, exist_ok=True)

        async def boot():
            from app.config import Settings
            from app.main import create_app

            mock_url, stop_mock = await start_mock()
            env = {"GNANI_API_KEY": "test-key", "GNANI_BASE_URL": mock_url,
                   "LEDGER_DB": str(self.tmp / "khata.db"),
                   "LEDGER_KEY": base64.b64encode(b"k" * 32).decode(), "SHOP_TZ": "Asia/Kolkata",
                   "TTS_PREWARM": "0"}
            env.update(self.env)
            app = create_app(Settings.from_env(env), now=self.clock)
            app_url, stop_app = await serve_app(app, lifespan="auto")
            return mock_url, app_url, app, stop_mock, stop_app

        mock_url, app_url, app, stop_mock, stop_app = asyncio.run_coroutine_threadsafe(boot(), self.loop).result(60)
        self.mock_url, self.app_url, self.app = mock_url, app_url, app
        self._stops = [stop_app, stop_mock]
        self.http = httpx.Client(base_url=app_url, timeout=10)
        self.mock_http = httpx.Client(base_url=mock_url, timeout=10)
        return self

    def stop(self) -> None:
        for c in self.clients:
            c.close()
        for client in (self.http, self.mock_http):
            if client:
                client.close()

        async def shutdown():
            for stop in self._stops:
                await stop()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(20)
        except Exception:  # noqa: BLE001
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)

    # ---- helpers -------------------------------------------------------------------------------------------------
    @property
    def ledger(self):
        return self.app.state.ctx.ledger

    @property
    def pipeline(self):
        return self.app.state.ctx.pipeline

    def mock_script(self, **body) -> None:
        r = self.mock_http.post("/__mock/script", json=body)
        r.raise_for_status()

    def mock_reset(self) -> None:
        self.mock_http.post("/__mock/reset")

    def mock_log(self) -> dict:
        return self.mock_http.get("/__mock/log").json()

    def get(self, path: str, **kw) -> httpx.Response:
        return self.http.get(path, **kw)

    def post(self, path: str, **kw) -> httpx.Response:
        return self.http.post(path, **kw)

    def seed_customer(self, name: str, credit: int = 0, tags: list[str] | None = None, days_ago: int = 0) -> str:
        """Create a customer and, when `credit` is above zero, one credit entry for it."""
        now = self.clock()
        cid = self.ledger.create_customer(name, tags=tags, now=now)["id"]
        if credit:
            self.add_event(name, "credit", credit, days_ago, cid)
        return cid

    def add_event(self, name: str, kind: str, amount: int, days_ago: int = 0, cid: str | None = None) -> None:
        from datetime import timedelta

        now = self.clock()
        day = (now.astimezone(IST).date() - timedelta(days=days_ago)).isoformat()
        ev = {"kind": kind, "customer": name, "amount": amount, "date": day}
        if cid:
            ev["customer_id"] = cid
        self.ledger.apply({"status": "ok", "action": "append", "events": [ev]}, now=now, session_id="seed")

    def rows(self) -> list[dict]:
        names = {c["id"]: c["name"] for c in self.ledger.customers_for_parser()}
        raw = [dict(r) for r in self.ledger.conn.execute("SELECT * FROM events ORDER BY id")]
        reversed_ids = {r["supersedes_id"] for r in raw if r["kind"] == "reversal"}
        return [{"id": r["id"], "kind": r["kind"], "customer": names.get(r["customer_id"]),
                 "amount": r["amount_paise"] // 100, "date": r["effective_date"], "ts": r["ts"],
                 "active": r["kind"] != "reversal" and r["id"] not in reversed_ids,
                 "session_id": r["session_id"], "utterance_id": r["utterance_id"]} for r in raw]

    def balance(self, name: str) -> int:
        return sum((r["amount"] if r["kind"] == "credit" else -r["amount"])
                   for r in self.rows() if r["active"] and r["customer"] == name)

    def count(self) -> int:
        return int(self.ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def session(self, lang: str = "hi", greet: bool = True, **hello) -> WsClient:
        """Open a session. With `greet`, wait for the greeting turn to finish."""
        cm = connect(self.app_url.replace("http", "ws", 1) + "/ws/session", max_size=None,
                 logger=logging.getLogger("edgeharness"))
        client = WsClient(self, cm)
        self.clients.append(client)
        client.send({"type": "hello", "lang": lang, **hello})
        if greet and "resume" not in hello:
            client.collect(min_turn=0, timeout=15)
            client.turn = 0
        elif "resume" in hello:
            first = client.recv(10)
            while first.get("type") != "ready":
                first = client.recv(10)
            client.session_id = first["session_id"]
            client.ready = first
        return client
