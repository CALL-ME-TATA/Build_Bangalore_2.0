"""Fixtures for the app tests: temporary directories, a test key, a fake parser and a fake Gnani server."""
from __future__ import annotations

import asyncio
import base64
from datetime import date, datetime

import pytest
import pytest_asyncio
import uvicorn

from app.config import Settings
from app.crypto import Crypto
from app.gnani import tts as tts_module
from app.ledger import Ledger
from app.main import create_app
from app.pipeline import Pipeline, SessionState

from .fake_gnani import FakeGnani

TEST_KEY = base64.b64encode(bytes(range(32))).decode()


def fake_nw(n: int, script: str = "deva") -> str:
    return f"<{n}>"


def _ev(kind, customer, amount, today, **extra):
    return {"kind": kind, "customer": customer, "amount": amount, "date": today.isoformat(), **extra}


class FakeParser:
    """Canned parser results shaped as CONTRACT 1.2, keyed by lowercase transcript."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, utterance: str, *, today: date, ctx: dict | None = None) -> dict:
        self.calls.append({"utterance": utterance, "ctx": ctx})
        u = utterance.lower().strip()
        ctx = ctx or {}
        if u == "ramesh ka 340 udhaar":
            return {"status": "ok", "action": "append", "events": [_ev("credit", "ramesh", 340, today)]}
        if u == "sunita ne 150 diye":
            return {"status": "ok", "action": "append", "events": [_ev("payment", "sunita", 150, today)]}
        if u == "ramesh 340":
            return {"status": "needs_clarification", "reason": "ambiguous_direction",
                    "question": "Ramesh ne diye, ya Ramesh ko udhaar?",
                    "pending": {"reason": "ambiguous_direction", "action": "append",
                                "events": [{"customer": "ramesh", "amount": 340, "date": today.isoformat()}]}}
        if u == "udhaar" and ctx.get("pending"):
            ev = dict(ctx["pending"]["events"][0], kind="credit")
            return {"status": "ok", "action": "append", "events": [ev]}
        if u == "nahi 430":
            last = ctx.get("last_event")
            if not last:
                return {"status": "rejected", "reason": "no_last_event"}
            ev = _ev(last["kind"], last["customer"], 430, today, customer_id=last.get("customer_id"))
            return {"status": "ok", "action": "amend", "target": "last", "events": [ev]}
        if u == "undo karo":
            if not ctx.get("last_event"):
                return {"status": "rejected", "reason": "no_last_event"}
            return {"status": "ok", "action": "undo", "target": "last"}
        if u == "ramesh ka total":
            return {"status": "ok", "action": "query", "query": {"type": "balance", "customer": "ramesh"}}
        if u == "aaj ka hisaab":
            return {"status": "ok", "action": "query", "query": {"type": "daily_summary", "period": "today"}}
        return {"status": "rejected", "reason": "not_ledger"}


@pytest.fixture(autouse=True)
def _clear_tts_memory_cache():
    tts_module._memory_cache.clear()
    yield
    tts_module._memory_cache.clear()


@pytest.fixture
def settings(tmp_path):
    return Settings(gnani_api_key="test-key", gnani_base_url="http://127.0.0.1:9", ledger_key=TEST_KEY,
                    ledger_db=str(tmp_path / "data" / "khata.db"))


@pytest.fixture
def ledger(settings):
    led = Ledger(settings.ledger_db, Crypto(base64.b64decode(TEST_KEY)))
    yield led
    led.close()


@pytest.fixture
def parser():
    return FakeParser()


@pytest.fixture
def pipeline(ledger, settings, parser):
    return Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw)


@pytest.fixture
def state():
    return SessionState(session_id="sess0001")


def apply_events(ledger, events, session="sess0001", now=None):
    now = now or datetime.now().astimezone()
    return ledger.apply({"action": "append", "events": events}, now=now, session_id=session)


@pytest_asyncio.fixture
async def fake_gnani():
    fake = FakeGnani()
    await fake.start()
    yield fake
    await fake.stop()


@pytest_asyncio.fixture
async def server(settings, parser, fake_gnani):
    """The real app served by uvicorn in this event loop, pointed at the fake Gnani server."""
    settings.gnani_base_url = fake_gnani.base_url
    app = create_app(settings, parse=parser, number_to_words=fake_nw)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.01)
    port = srv.servers[0].sockets[0].getsockname()[1]
    srv.url = f"ws://127.0.0.1:{port}/ws/session"
    srv.http = f"http://127.0.0.1:{port}"
    yield srv
    srv.should_exit = True
    await task
