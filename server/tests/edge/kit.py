"""Test kit for the edge-case suite: a shop (real parser, real pipeline, temporary ledger, injected clock) and
assertion helpers that describe what a turn did in one line.

The expectations in the tests come from docs/CONTRACT.md and docs/EDGE_CASES.md. This module only provides
plumbing: it reads the ledger through SQL so that the checks do not depend on the ledger's own helper methods.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from app.crypto import Crypto
from app.ledger import Ledger
from app.pipeline import Pipeline, SessionState
from nlu.parser import parse as nlu_parse

IST = ZoneInfo("Asia/Kolkata")
KEY = base64.b64encode(bytes(range(32))).decode()
T0 = datetime(2026, 11, 21, 11, 0, 0, tzinfo=IST)  # a Saturday
TODAY = T0.date()


class Clock:
    def __init__(self, start: datetime = T0) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t


def iso(offset_days: int = 0, base: date = TODAY) -> str:
    """The date `offset_days` before `base`, as YYYY-MM-DD."""
    return (base - timedelta(days=offset_days)).isoformat()


def parse(text: str, ctx: dict | None = None, today: date = TODAY) -> dict:
    """The parser alone."""
    return nlu_parse(text, today=today, ctx=ctx)


def roster(*names: str | tuple) -> list[dict]:
    """A parser roster: each item is a name or (name, tags)."""
    out = []
    for i, n in enumerate(names):
        name, tags = (n, []) if isinstance(n, str) else (n[0], list(n[1]))
        out.append({"id": f"c{i + 1}", "name": name, "tags": tags})
    return out


class Turn:
    """What one `say` did: the pipeline result plus the ledger rows it added."""

    def __init__(self, text: str, result: Any, before_max_id: int, rows: list[dict], message: dict) -> None:
        self.text = text
        self.result = result
        self.msg = message
        self.status = result.status
        self.action = result.action
        self.reason = result.reason
        self.reply_text = result.reply_text
        self.speak_text = result.speak_text
        self.added = [r for r in rows if r["id"] > before_max_id]
        self.saved = [r for r in self.added if r["kind"] != "reversal"]
        self.reversals = [r for r in self.added if r["kind"] == "reversal"]
        self.candidates = message.get("candidates")
        self.confirm = message.get("confirm")

    def describe(self) -> str:
        rows = "; ".join(f"{r['kind']} {r['amount']} {r['customer']} {r['date']}" for r in self.added) or "no rows"
        why = f"/{self.reason}" if self.reason else ""
        return f"{self.text!r} -> {self.status}/{self.action}{why} [{rows}] says {self.reply_text!r}"


class Shop:
    """A shop with a temporary ledger and a clock the test controls."""

    def __init__(self, tmp_path, start: datetime = T0, env: dict | None = None, parse_fn=None,
                 disclosed: bool = True) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.dir = tmp_path
        e = {"GNANI_API_KEY": "k", "GNANI_BASE_URL": "http://127.0.0.1:9", "LEDGER_KEY": KEY,
             "LEDGER_DB": str(tmp_path / "khata.db")}
        e.update(env or {})
        self.settings = Settings.from_env(e)
        self.ledger = Ledger(self.settings.ledger_db, Crypto(base64.b64decode(KEY)))
        self.clock = Clock(start)
        kw = {"parse": parse_fn} if parse_fn else {}
        self.pipeline = Pipeline(self.ledger, self.settings, now=self.clock, **kw)
        self._disclosed = disclosed
        self._sessions = 0
        self.state = self._fresh_state()
        self._cids: dict[tuple[str, str | None], str] = {}

    # ---- sessions and time -------------------------------------------------------------------------------------
    def _fresh_state(self) -> SessionState:
        self._sessions += 1
        return SessionState(session_id=f"sess{self._sessions:04d}", disclosed=self._disclosed)

    def new_session(self, disclosed: bool | None = None) -> SessionState:
        self._disclosed = self._disclosed if disclosed is None else disclosed
        self.state = self._fresh_state()
        return self.state

    def wait(self, seconds: float) -> None:
        self.clock.t += timedelta(seconds=seconds)

    @property
    def today(self) -> date:
        return self.clock.t.astimezone(IST).date()

    def day(self, offset: int = 0) -> str:
        return iso(offset, self.today)

    def close(self) -> None:
        self.ledger.close()

    # ---- talking ---------------------------------------------------------------------------------------------
    def say(self, text: str, state: SessionState | None = None, advance: float = 2.0) -> Turn:
        """Run one turn through the pipeline two seconds after the previous one."""
        self.wait(advance)
        before = self._max_id()
        result = self.pipeline.run_turn(state or self.state, text)
        try:
            message = result.message(0)
        except TypeError:
            message = result.message()
        return Turn(text, result, before, self.rows(since=before), message)

    def parse(self, text: str, **ctx: Any) -> dict:
        return parse(text, ctx=ctx or None, today=self.today)

    # ---- seeding ---------------------------------------------------------------------------------------------
    def customer(self, name: str, tags: list[str] | None = None) -> str:
        """Create a customer with no entries and return its id."""
        cid = self.ledger.create_customer(name, tags=tags, now=self.clock.t)["id"]
        self._cids[(name, (tags or [None])[0])] = cid
        return cid

    def seed(self, *items: tuple) -> None:
        """Seed entries: (name, kind, amount[, days_ago[, tag]]). Customers are created on first use.

        Seed rows belong to a session of their own, so they never count as the current session's last entry.
        """
        for it in items:
            name, kind, amount = it[0], it[1], it[2]
            days_ago = it[3] if len(it) > 3 else 0
            tag = it[4] if len(it) > 4 else None
            cid = self._cids.get((name, tag)) or self.customer(name, [tag] if tag else None)
            self.ledger.apply(
                {"status": "ok", "action": "append",
                 "events": [{"kind": kind, "customer": name, "customer_id": cid, "amount": amount,
                             "date": iso(days_ago, self.today)}]},
                now=self.clock.t, session_id="seed", utterance_id=None)
            self.wait(1)

    def cid(self, name: str, tag: str | None = None) -> str:
        return self._cids[(name, tag)]

    # ---- reading the ledger ------------------------------------------------------------------------------------
    def _max_id(self) -> int:
        return int(self.ledger.conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0])

    def count(self) -> int:
        return int(self.ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def rows(self, since: int = 0) -> list[dict]:
        """Ledger rows with id above `since`. Which rows are active is decided against the whole table."""
        names = {c["id"]: c["name"] for c in self.ledger.customers_for_parser()}
        raw = [dict(r) for r in self.ledger.conn.execute("SELECT * FROM events WHERE id > ? ORDER BY id", (since,))]
        reversed_ids = {r[0] for r in self.ledger.conn.execute(
            "SELECT supersedes_id FROM events WHERE kind='reversal' AND supersedes_id IS NOT NULL")} if raw else set()
        out = []
        for r in raw:
            kind = r["kind"]
            if kind == "payment" and r.get("adjustment") == "writeoff":
                kind = "writeoff"
            out.append({"id": r["id"], "kind": kind, "customer": names.get(r["customer_id"], "?"),
                        "customer_id": r["customer_id"], "amount": r["amount_paise"] // 100,
                        "paise": r["amount_paise"], "date": r["effective_date"], "ts": r["ts"],
                        "utterance_id": r["utterance_id"], "session_id": r["session_id"],
                        "supersedes_id": r["supersedes_id"], "replaces_id": r["replaces_id"],
                        "active": kind != "reversal" and r["id"] not in reversed_ids})
        return out

    def entries(self, active_only: bool = False) -> list[dict]:
        rows = [r for r in self.rows() if r["kind"] != "reversal"]
        return [r for r in rows if r["active"]] if active_only else rows

    def balance(self, name: str) -> int:
        """What the named customers owe, from the active rows (credit adds; payment and write-off subtract)."""
        total = 0
        for r in self.entries(active_only=True):
            if r["customer"] == name:
                total += r["amount"] if r["kind"] == "credit" else -r["amount"]
        return total

    def customers(self) -> list[dict]:
        return self.ledger.customers_for_parser()


# ---- assertions ---------------------------------------------------------------------------------------------------

def _fail(t: Turn, why: str) -> None:
    raise AssertionError(f"{why}: {t.describe()}")


def expect_saved(t: Turn, *want: tuple, shop: Shop | None = None) -> None:
    """The turn saved exactly these events, in order: (kind, customer, amount[, days_ago])."""
    if t.status != "ok":
        _fail(t, f"expected a save, got {t.status}")
    got = [(r["kind"], r["customer"], r["amount"], r["date"]) for r in t.saved]
    base = shop.today if shop else TODAY
    exp = [(w[0], w[1], w[2], iso(w[3] if len(w) > 3 else 0, base)) for w in want]
    if got != exp:
        _fail(t, f"saved {got}, expected {exp}")


def expect_nothing_saved(t: Turn, why: str = "expected no ledger row") -> None:
    if t.added:
        _fail(t, why)


def expect_ask(t: Turn, reason: str | tuple | None = None) -> None:
    if t.status != "needs_clarification":
        _fail(t, "expected a question")
    if reason is not None:
        allowed = (reason,) if isinstance(reason, str) else reason
        if t.reason not in allowed:
            _fail(t, f"expected question reason {allowed}")
    expect_nothing_saved(t, "a question must not write a ledger row")


def expect_reject(t: Turn, reason: str | tuple | None = None) -> None:
    if t.status != "rejected":
        _fail(t, "expected a rejection")
    if reason is not None:
        allowed = (reason,) if isinstance(reason, str) else reason
        if t.reason not in allowed:
            _fail(t, f"expected rejection reason {allowed}")
    expect_nothing_saved(t, "a rejection must not write a ledger row")


def expect_query(t: Turn) -> None:
    if t.status != "ok" or t.action != "query":
        _fail(t, "expected a query answer")
    expect_nothing_saved(t, "a query must not write a ledger row")


def first_line(exc: BaseException) -> str:
    return (str(exc).strip().splitlines() or [""])[0]
