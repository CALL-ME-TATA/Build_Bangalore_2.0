"""Fixtures for the app tests: temporary directories, a test key, a fake parser and a fake Gnani server."""
from __future__ import annotations

import asyncio
import base64
import copy
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


def _customer(ctx, key):
    return next((c for c in ctx.get("customers") or [] if c["name"] == key), None)


def _v12(u: str, today: date, ctx: dict) -> dict | None:
    """Canned results of the CONTRACT 1.14 shapes (v1.2)."""
    pending = ctx.get("pending") or {}
    if u == "ramesh ka 999999999999 udhaar":  # a result the server cannot voice or save
        return {"status": "ok", "action": "append", "lang": "hi", "events": [_ev("credit", "ramesh", 999999999999, today)]}
    if u in ("haan", "yes") and pending.get("reason") in ("confirm_entry", "plausibility", "new_customer"):
        if pending.get("action") == "reminder":
            return {"status": "ok", "action": "reminder", "customer": pending.get("customer"),
                    "customer_id": pending.get("customer_id")}
        return {"status": "ok", "action": pending.get("action", "append"), "events": pending.get("events") or []}
    if u == "haan":
        return {"status": "rejected", "reason": "no_question"}
    rejected = {"ramesh kal dega": "future", "ramesh ne nahi diya": "negated", "kiraya 500 diya": "out_of_scope",
                "ek crore crore": "too_large", "minus 50": "invalid_number"}
    if u in rejected:
        return {"status": "rejected", "reason": rejected[u], "lang": "hi"}
    if u == "mohan ko 200 udhaar":
        c = _customer(ctx, "mohan")
        if c:
            return {"status": "ok", "action": "append", "events": [_ev("credit", "mohan", 200, today, customer_id=c["id"])]}
        ev = _ev("credit", "mohan", 200, today, new_customer=True)
        if (ctx.get("limits") or {}).get("confirm_new_customer"):
            return {"status": "needs_clarification", "reason": "new_customer", "question": "Mohan naya hai? (roman)",
                    "candidates": [], "pending": {"reason": "new_customer", "action": "append", "events": [ev]}}
        return {"status": "ok", "action": "append", "events": [ev]}
    if u == "ramesh":
        c = _customer(ctx, "ramesh")
        if c is None:
            return {"status": "rejected", "reason": "not_ledger"}
        ev = {"customer": "ramesh", "customer_id": c["id"]}
        return {"status": "needs_clarification", "reason": "missing_amount", "question": "Ramesh ka kya likhun?",
                "pending": {"reason": "missing_amount", "action": "append", "events": [ev]}}
    if u == "ramesh ko 2 kilo chawal udhaar":
        ev = {"kind": "credit", "customer": "ramesh", "date": today.isoformat()}
        return {"status": "needs_clarification", "reason": "missing_amount", "question": "Kitne ka?",
                "quantity": True, "pending": {"reason": "missing_amount", "action": "append", "events": [ev]}}
    settle = {"ramesh ne poora de diya": ("settle", "payment"), "ramesh ka baaki chhod do": ("writeoff", "writeoff")}
    if u in settle:
        ctype, kind = settle[u]
        c = _customer(ctx, "ramesh")
        bal = c.get("balance") if c else None
        if not c or not bal or bal <= 0:
            return {"status": "ok", "action": "query", "query": {"type": "balance", "customer": "ramesh"}}
        ev = _ev(kind, "ramesh", bal, today, customer_id=c["id"])
        confirm = {"type": ctype, "balance": bal}
        return {"status": "needs_clarification", "reason": "confirm_entry", "confirm": confirm,
                "question": "(roman question)",
                "pending": {"reason": "confirm_entry", "action": "append", "events": [ev], "confirm": confirm}}
    return None


class FakeParser:
    """Canned parser results shaped as CONTRACT 1.2, keyed by lowercase transcript."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        # Extra canned results, keyed by lowercase transcript: a dict, or a function (today, ctx) -> dict.
        self.canned: dict = {}

    def __call__(self, utterance: str, *, today: date, ctx: dict | None = None) -> dict:
        self.calls.append({"utterance": utterance, "ctx": ctx})
        u = utterance.lower().strip()
        ctx = ctx or {}
        if u in self.canned:
            item = self.canned[u]
            return copy.deepcopy(item(today, ctx) if callable(item) else item)
        v12 = _v12(u, today, ctx)
        if v12 is not None:
            return v12
        if u == "ramesh ka 340 udhaar":
            return {"status": "ok", "action": "append", "lang": "hi", "events": [_ev("credit", "ramesh", 340, today)]}
        if u == "sunita paid 150":
            return {"status": "ok", "action": "append", "lang": "en",
                    "events": [_ev("payment", "sunita", 150, today)]}
        if u == "yes":  # a bare answer carries no `lang`
            return {"status": "rejected", "reason": "not_ledger"}
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
                return {"status": "rejected", "reason": "no_last_event", "action": "undo"}
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
