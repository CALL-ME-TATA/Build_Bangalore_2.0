"""SQLite ledger: append-only events, integer paise, field-level AES-256-GCM (CONTRACT sections 2 and 2.1).

Names, aliases, tags, phones, transcripts, reply texts and stored results are encrypted. Ids, kinds, amounts and
dates stay in plain columns so balances and totals are plain SQL. Triggers abort every UPDATE and DELETE on `events`,
`utterances` and `consent_log`, and every DELETE on `customers`; purging means deleting the database file.

A write-off is stored as `kind='payment'` with `adjustment='writeoff'`: balances are unchanged by the extra column,
payment totals leave write-offs out, and the API reports the kind as `"writeoff"`.
"""
from __future__ import annotations

import sqlite3
import statistics
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .crypto import Crypto
from .edits import EditError, customer_key, phone_hint, phone_number, tag_list
from .names import SpokenName, display_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(
  id TEXT PRIMARY KEY, ident BLOB NOT NULL,
  reminders_opt_in INTEGER NOT NULL DEFAULT 0, created_ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('credit','payment','reversal')),
  customer_id TEXT NOT NULL REFERENCES customers(id),
  amount_paise INTEGER NOT NULL CHECK (amount_paise > 0), effective_date TEXT NOT NULL,
  utterance_id TEXT, supersedes_id INTEGER REFERENCES events(id), replaces_id INTEGER REFERENCES events(id),
  session_id TEXT, trace_id TEXT);
CREATE TABLE IF NOT EXISTS utterances(
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT, body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS reminder_outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  amount_paise INTEGER NOT NULL, body BLOB NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS confusions(
  heard INTEGER NOT NULL, meant INTEGER NOT NULL, n INTEGER NOT NULL, last_ts TEXT NOT NULL,
  PRIMARY KEY(heard, meant));
CREATE TABLE IF NOT EXISTS consent_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, customer_id TEXT NOT NULL REFERENCES customers(id),
  opt_in INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS events_customer ON events(customer_id);
CREATE INDEX IF NOT EXISTS events_supersedes ON events(supersedes_id);
CREATE INDEX IF NOT EXISTS events_date ON events(effective_date);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, id);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS utterances_no_update BEFORE UPDATE ON utterances
  BEGIN SELECT RAISE(ABORT, 'utterances is append-only'); END;
CREATE TRIGGER IF NOT EXISTS utterances_no_delete BEFORE DELETE ON utterances
  BEGIN SELECT RAISE(ABORT, 'utterances is append-only'); END;
CREATE TRIGGER IF NOT EXISTS customers_no_delete BEFORE DELETE ON customers
  BEGIN SELECT RAISE(ABORT, 'customers are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS consent_no_update BEFORE UPDATE ON consent_log
  BEGIN SELECT RAISE(ABORT, 'consent_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS consent_no_delete BEFORE DELETE ON consent_log
  BEGIN SELECT RAISE(ABORT, 'consent_log is append-only'); END;
"""

# Columns added after the first release, created with ALTER TABLE when an older database lacks them.
ADDED_COLUMNS = {
    "events": [("adjustment", "TEXT")],
    "utterances": [("device_ts", "TEXT"), ("status", "TEXT"), ("action", "TEXT"), ("noisy", "INTEGER")],
}

# An event is active when it is a credit or payment that no reversal points at.
ACTIVE = (
    "e.kind IN ('credit','payment') AND NOT EXISTS "
    "(SELECT 1 FROM events r WHERE r.kind='reversal' AND r.supersedes_id = e.id)"
)
SIGNED = "CASE e.kind WHEN 'credit' THEN e.amount_paise ELSE -e.amount_paise END"
NOT_WRITEOFF = "e.adjustment IS NULL"
ENTRY_KINDS = ("credit", "payment", "writeoff")
PORTAL_SESSION = "portal"  # session id of events written on the khata screens
_UNSET: Any = object()
PERIODS = ("today", "yesterday", "this_week", "last_week", "this_month", "last_month")
QUIET_START_HOUR = 9   # reminders are queued and listed only from 09:00
QUIET_END_HOUR = 20    # ... to 20:00 shop time

# One write lock per database file and process, shared by every Ledger opened on that file.
_WRITE_LOCKS: dict[str, threading.RLock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def _write_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(key, threading.RLock())


def rupees(paise: int) -> int:
    """Whole rupees. Amounts are always saved as whole rupees times 100."""
    return paise // 100


def api_kind(kind: str, adjustment: str | None) -> str:
    """The kind shown by the API: a payment stored with adjustment 'writeoff' is a `writeoff`."""
    return "writeoff" if kind == "payment" and adjustment == "writeoff" else kind


def period_range(period: str, today: date) -> tuple[date, date]:
    """First and last shop day (inclusive) of a query period. Weeks run Monday to Sunday."""
    if period == "yesterday":
        d = today - timedelta(days=1)
        return d, d
    if period == "this_week":
        return today - timedelta(days=today.weekday()), today
    if period == "last_week":
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=6), end
    if period == "this_month":
        return today.replace(day=1), today
    if period == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    return today, today


def in_quiet_hours(now: datetime) -> bool:
    """True outside 09:00 to 20:00 of `now` (which is shop time)."""
    return not (QUIET_START_HOUR <= now.hour < QUIET_END_HOUR)


@dataclass
class Outcome:
    """What `Ledger.apply` did. `saved` holds new events, `reversed` the events cancelled by undo or amend."""

    action: str
    saved: list[dict] = field(default_factory=list)
    reversed: list[dict] = field(default_factory=list)
    nothing: bool = False


class DuplicateUtterance(Exception):
    """The utterance id was already recorded: the turn must not be saved again."""

    def __init__(self, record: dict):
        super().__init__("utterance already recorded")
        self.record = record


def wa_me_link(phone: str, message: str) -> str:
    """Prefilled wa.me link. A ten-digit number gets the 91 country code."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}?text={quote(message)}"


class Ledger:
    def __init__(self, db_path: str | Path, crypto: Crypto):
        self.path = Path(db_path)
        self.crypto = crypto
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _write_lock(self.path)
        self._cache: dict[str, dict] | None = None
        self._stats: dict | None = None  # balances and usual amounts; cleared on every write
        self._keys: tuple[int, dict[str, int]] | None = None
        self._conn: sqlite3.Connection | None = None
        self.open()

    # ---- connection -------------------------------------------------------------------------------------------
    def open(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            # Without this, INSERT OR REPLACE deletes the old row without firing the delete trigger.
            conn.execute("PRAGMA recursive_triggers=ON")
            conn.executescript(SCHEMA)
            for table, cols in ADDED_COLUMNS.items():
                have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                for name, decl in cols:
                    if name not in have:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            self._conn = conn
            self._cache = None
            self._stats = None

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            self._cache = None
            self._stats = None

    @property
    def conn(self) -> sqlite3.Connection:
        assert self._conn is not None, "ledger is closed"
        return self._conn

    def _begin(self) -> None:
        self.conn.execute("BEGIN IMMEDIATE")

    # ---- customers --------------------------------------------------------------------------------------------
    def _customers(self) -> dict[str, dict]:
        """All customers, decrypted once and cached in memory."""
        if self._cache is None:
            cache = {}
            for row in self.conn.execute("SELECT id, ident, reminders_opt_in FROM customers ORDER BY created_ts, id"):
                ident = self.crypto.decrypt(row["ident"], f"customers:{row['id']}")
                ident["id"] = row["id"]
                ident["display"] = display_name(ident["key"])
                ident["reminders_opt_in"] = bool(row["reminders_opt_in"])
                ident.setdefault("aliases", [])
                ident.setdefault("tags", [])
                cache[row["id"]] = ident
            self._cache = cache
            self._keys = None
        return self._cache

    def _store_ident(self, cid: str, ident: dict) -> None:
        body = {k: ident.get(k) for k in ("key", "display", "aliases", "tags", "phone", "lang", "say")}
        blob = self.crypto.encrypt(body, f"customers:{cid}")
        self.conn.execute("UPDATE customers SET ident=? WHERE id=?", (blob, cid))

    def _create_customer(self, key: str, now: datetime, tags: list[str] | None = None) -> dict:
        cid = "c_" + uuid.uuid4().hex[:10]
        ident = {"key": key, "display": display_name(key), "aliases": [], "tags": list(tags or []), "phone": None}
        blob = self.crypto.encrypt(ident, f"customers:{cid}")
        self.conn.execute(
            "INSERT INTO customers(id, ident, reminders_opt_in, created_ts) VALUES (?,?,0,?)",
            (cid, blob, now.isoformat()),
        )
        ident = dict(ident, id=cid, reminders_opt_in=False)
        self._customers()[cid] = ident
        return ident

    def create_customer(self, key: str, *, tags: list[str] | None = None, phone: str | None = None,
                        now: datetime | None = None) -> dict:
        """Create a customer outside a parser result (seed data, admin use)."""
        with self._lock:
            now = now or datetime.now().astimezone()
            ident = self._create_customer(key.lower(), now, tags)
            if phone:
                ident["phone"] = phone
                self._store_ident(ident["id"], ident)
            if self._stats is not None:
                self._stats["balances"][ident["id"]] = 0
            return dict(ident)

    def update_customer(self, customer_id: str, *, say: str | None = None, lang: str | None = None,
                        display: Any = _UNSET, tags: Any = _UNSET, phone: Any = _UNSET) -> bool:
        """Set the pronunciation (`say`, empty clears it), the reminder language, the name, the tags or the phone.

        `display` renames the customer: the new key replaces the old one, which stays as an alias. `tags` replaces
        the tag list and `phone` sets the number (None clears it). Raises `EditError` for a refused value; nothing
        is changed then. Returns False for an unknown customer.
        """
        with self._lock:
            c = self._customers().get(customer_id)
            if c is None:
                return False
            changes: dict[str, Any] = {}
            if display is not _UNSET:
                key = customer_key(display)
                if key != c["key"]:
                    for other in self._customers().values():
                        if other["id"] != customer_id and (other["key"] == key or key in other.get("aliases", [])):
                            raise EditError(409, "name_taken")
                    aliases = [a for a in c.get("aliases", []) if a != key]
                    if c["key"] not in aliases:
                        aliases.append(c["key"])
                    changes.update(key=key, display=display_name(key), aliases=aliases)
            if tags is not _UNSET:
                changes["tags"] = tag_list(tags)
            if phone is not _UNSET:
                changes["phone"] = phone_number(phone)
            if say is not None:
                changes["say"] = say.strip() or None
            if lang is not None:
                changes["lang"] = lang if lang in ("hi", "en") else None
            c.update(changes)
            self._store_ident(customer_id, c)
            if "key" in changes:
                self._keys = None
            return True

    def label(self, customer_id: str) -> str:
        """Name used in replies: the display name, followed by the first tag when another customer shares the name.

        When the customer has a pronunciation (`say`), the label carries it for the spoken text.
        """
        with self._lock:
            customers = self._customers()
            c = customers[customer_id]
            same = self._key_counts().get(c["key"], 0)
            text, spoken = c["display"], c.get("say") or c["display"]
            if same > 1 and c["tags"]:
                text, spoken = f"{text} {c['tags'][0]}", f"{spoken} {c['tags'][0]}"
            return SpokenName(text, spoken) if c.get("say") else text

    def _key_counts(self) -> dict[str, int]:
        """How many customers share each key (cached with the customer rows)."""
        customers = self._customers()
        if self._keys is None or self._keys[0] != len(customers):
            counts: dict[str, int] = {}
            for c in customers.values():
                counts[c["key"]] = counts.get(c["key"], 0) + 1
            self._keys = (len(customers), counts)
        return self._keys[1]

    def find_customer(self, key: str | None = None, customer_id: str | None = None) -> dict | None:
        with self._lock:
            customers = self._customers()
            if customer_id and customer_id in customers:
                return dict(customers[customer_id])
            if key:
                k = key.lower()
                for c in customers.values():
                    if c["key"] == k or k in c.get("aliases", []):
                        return dict(c)
        return None

    def _refresh_stats(self, customer_ids: set[str]) -> None:
        """Recompute the cached balance and usual amount of the customers a write touched (indexed by customer),
        so a write never forces the full recompute that start-up does."""
        if self._stats is None:
            return
        for cid in customer_ids:
            cur = self.conn.execute(
                f"SELECT e.kind, e.amount_paise FROM events e WHERE e.customer_id=? AND {ACTIVE}", (cid,))
            cur.row_factory = None
            total, credits, any_row = 0, [], False
            for kind, amount in cur:
                any_row = True
                if kind == "credit":
                    total += amount
                    credits.append(amount)
                else:
                    total -= amount
            self._stats["balances"][cid] = int(rupees(total))
            if len(credits) >= 3:
                self._stats["usual"][cid] = int(rupees(int(statistics.median(credits))))
            else:
                self._stats["usual"].pop(cid, None)
            (self._stats["active"].add if any_row else self._stats["active"].discard)(cid)

    def _stats_now(self) -> dict:
        """Balances (rupees) and usual credit amounts per customer, computed with two grouped queries and cached."""
        if self._stats is None:
            paise = {cid: 0 for cid in self._customers()}
            credits: dict[str, list[int]] = {}
            active: set[str] = set()
            cur = self.conn.execute(f"SELECT e.customer_id, e.kind, e.amount_paise FROM events e WHERE {ACTIVE}")
            cur.row_factory = None  # plain tuples: this reads every active event
            for cid, kind, amount in cur:
                active.add(cid)
                if kind == "credit":
                    paise[cid] = paise.get(cid, 0) + amount
                    credits.setdefault(cid, []).append(amount)
                else:
                    paise[cid] = paise.get(cid, 0) - amount
            balances = {cid: int(rupees(p)) for cid, p in paise.items()}
            usual = {cid: int(rupees(int(statistics.median(v)))) for cid, v in credits.items() if len(v) >= 3}
            self._stats = {"balances": balances, "usual": usual, "active": active}
        return self._stats

    def customers_for_parser(self) -> list[dict]:
        """The roster for `ctx.customers`: id, key, tags, aliases, balance and (with three credits or more) usual."""
        with self._lock:
            stats = self._stats_now()
            out = []
            for c in self._customers().values():
                item = {"id": c["id"], "name": c["key"], "tags": list(c["tags"]),
                        "aliases": list(c.get("aliases", [])), "balance": stats["balances"].get(c["id"], 0)}
                if c["id"] in stats["usual"]:
                    item["usual"] = stats["usual"][c["id"]]
                out.append(item)
            return out

    def _resolve(self, ev: dict, now: datetime, cache: dict[str, dict], created: set[str]) -> dict:
        """Return the customer for a parser event, creating one when the name is new. Learns spoken tags."""
        cid = ev.get("customer_id")
        customer = self._customers().get(cid) if cid else None
        if customer is None:
            key = (ev.get("customer") or "").strip().lower()
            if not key:
                raise ValueError("event has no customer")
            # The parser has already matched the name against the roster. `new_customer` means that no existing
            # customer fits, even when another one has the same name (for example with a different tag).
            is_new = bool(ev.get("new_customer"))
            cache_key = ("new:" if is_new else "") + key
            customer = cache.get(cache_key)
            if customer is None:
                found = None if is_new else self.find_customer(key=key)
                if found is not None:
                    customer = self._customers()[found["id"]]
                else:
                    customer = self._create_customer(key, now)
                    created.add(customer["id"])
                cache[cache_key] = customer
        new_tags = [t for t in (ev.get("tags") or []) if t and t not in customer["tags"]]
        if new_tags:
            customer["tags"] = list(customer["tags"]) + new_tags
            self._store_ident(customer["id"], customer)
        return customer

    # ---- writes -----------------------------------------------------------------------------------------------
    def _insert_event(self, kind: str, customer_id: str, paise: int, eff: str, now: datetime, *,
                      utterance_id: str | None, session_id: str | None, trace_id: str | None,
                      supersedes_id: int | None = None, replaces_id: int | None = None,
                      adjustment: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO events(ts, kind, customer_id, amount_paise, effective_date, utterance_id, supersedes_id,"
            " replaces_id, session_id, trace_id, adjustment) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (now.isoformat(), kind, customer_id, paise, eff, utterance_id, supersedes_id, replaces_id,
             session_id, trace_id, adjustment),
        )
        return int(cur.lastrowid)

    def _event_info(self, event_id: int, kind: str, customer: dict, paise: int, eff: str, created: bool = False) -> dict:
        return {"id": event_id, "kind": kind, "customer_id": customer["id"], "customer": self.label(customer["id"]),
                "key": customer["key"], "amount": rupees(paise), "date": eff, "new_customer": created}

    def _last_active_row(self, session_id: str | None) -> sqlite3.Row | None:
        sql = f"SELECT e.* FROM events e WHERE {ACTIVE}"
        args: list[Any] = []
        if session_id is not None:
            sql += " AND e.session_id = ?"
            args.append(session_id)
        return self.conn.execute(sql + " ORDER BY e.id DESC LIMIT 1", args).fetchone()

    def apply(self, result: dict, *, now: datetime, session_id: str | None = None, trace_id: str | None = None,
              utterance_id: str | None = None, finish: Callable[[Outcome], dict] | None = None,
              device_ts: str | None = None) -> Outcome:
        """Apply an ok parser result (append, amend or undo) in one transaction: all events are saved or none.

        With `finish`, the utterance row is written in the same transaction: `finish(outcome)` returns the
        utterance body (transcript, status, reply, result). An exception in `finish` rolls everything back. A
        repeated `utterance_id` raises `DuplicateUtterance` with the stored record and saves nothing.
        """
        action = result.get("action")
        if action not in ("append", "amend", "undo"):
            raise ValueError("cannot apply this action")
        with self._lock:
            if finish is not None and utterance_id:
                prior = self.find_utterance(utterance_id)
                if prior is not None:
                    raise DuplicateUtterance(prior)
            self._begin()
            try:
                outcome = self._apply_locked(action, result, now, session_id, trace_id, utterance_id)
                self._refresh_stats({e["customer_id"] for e in outcome.saved + outcome.reversed})
                if finish is not None:
                    body = finish(outcome)
                    self._insert_utterance(utterance_id or uuid.uuid4().hex[:12], session_id, now, body, device_ts)
                self.conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self.conn.execute("ROLLBACK")
                self._cache = None
                self._stats = None
                prior = self.find_utterance(utterance_id) if utterance_id else None
                if prior is not None:
                    raise DuplicateUtterance(prior) from exc
                raise
            except BaseException:
                self.conn.execute("ROLLBACK")
                self._cache = None
                self._stats = None
                raise
            return outcome

    def _apply_locked(self, action: str, result: dict, now: datetime, session_id, trace_id, utterance_id) -> Outcome:
        out = Outcome(action=action)
        kw = {"utterance_id": utterance_id, "session_id": session_id, "trace_id": trace_id}
        cache: dict[str, dict] = {}
        created: set[str] = set()
        old = None
        if action in ("amend", "undo"):
            target = result.get("target")
            if isinstance(target, dict) and "event_id" in target:
                old = self._active_row(target["event_id"], session_id)
            else:
                old = self._last_active_row(session_id)
            if old is None:
                out.nothing = True
                return out
            owner = self._customers()[old["customer_id"]]
            self._insert_event("reversal", old["customer_id"], old["amount_paise"], old["effective_date"],
                               now, supersedes_id=old["id"], adjustment=old["adjustment"], **kw)
            out.reversed.append(self._event_info(old["id"], api_kind(old["kind"], old["adjustment"]), owner,
                                                 old["amount_paise"], old["effective_date"]))
            if action == "undo":
                return out
        events = result.get("events") or []
        if action == "amend":
            events = events[:1]
        if not events:
            raise ValueError("no events to save")
        for ev in events:
            kind = ev.get("kind")
            amount = ev.get("amount")
            if kind not in ENTRY_KINDS:
                raise ValueError("bad event kind")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                raise ValueError("bad event amount")
            customer = self._resolve(ev, now, cache, created)
            eff = ev.get("date") or now.date().isoformat()
            paise = amount * 100
            stored, adjustment = ("payment", "writeoff") if kind == "writeoff" else (kind, None)
            eid = self._insert_event(stored, customer["id"], paise, eff, now, adjustment=adjustment,
                                     replaces_id=old["id"] if old is not None else None, **kw)
            out.saved.append(self._event_info(eid, kind, customer, paise, eff, customer["id"] in created))
        if action == "amend" and old is not None and out.saved:
            new = out.saved[0]
            same_entry = (new["customer_id"] == old["customer_id"] and new["date"] == old["effective_date"]
                          and new["kind"] == api_kind(old["kind"], old["adjustment"]))
            if same_entry and new["amount"] != rupees(old["amount_paise"]):
                self._count_confusion(rupees(old["amount_paise"]), new["amount"], now)
        return out

    def _count_confusion(self, heard: int, meant: int, now: datetime) -> None:
        self.conn.execute(
            "INSERT INTO confusions(heard, meant, n, last_ts) VALUES (?,?,1,?) "
            "ON CONFLICT(heard, meant) DO UPDATE SET n = n + 1, last_ts = excluded.last_ts",
            (heard, meant, now.isoformat()))

    # ---- utterances -------------------------------------------------------------------------------------------
    def _insert_utterance(self, utterance_id: str, session_id: str | None, now: datetime, body: dict,
                          device_ts: str | None) -> None:
        blob = self.crypto.encrypt(body, f"utterances:{utterance_id}")
        result = body.get("result") or {}
        self.conn.execute(
            "INSERT INTO utterances(id, ts, session_id, body, device_ts, status, action, noisy)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (utterance_id, now.isoformat(), session_id, blob, (device_ts or None) and str(device_ts)[:64],
             body.get("status"), result.get("action"), 1 if body.get("noisy") else 0))

    def record_utterance(self, utterance_id: str, session_id: str | None, now: datetime, *, transcript: str,
                         status: str, reply_text: str, timings: dict | None = None, result: dict | None = None,
                         device_ts: str | None = None, fingerprint: str | None = None,
                         noisy: bool = False) -> None:
        body = {"transcript": transcript, "status": status, "reply_text": reply_text, "timings": timings or {}}
        if noisy:
            body["noisy"] = True
        if result is not None:
            body["result"] = result
        if fingerprint is not None:
            body["fingerprint"] = fingerprint
        with self._lock:
            self._insert_utterance(utterance_id, session_id, now, body, device_ts)

    def read_utterance(self, utterance_id: str) -> dict:
        """The decrypted body of an utterance with its `device_ts` (KeyError when the id is unknown)."""
        body = self.find_utterance(utterance_id)
        if body is None:
            raise KeyError(utterance_id)
        return body

    def find_utterance(self, utterance_id: str) -> dict | None:
        """The decrypted body of an utterance with its `device_ts`, or None when the id is unknown."""
        with self._lock:
            row = self.conn.execute("SELECT body, device_ts FROM utterances WHERE id=?", (utterance_id,)).fetchone()
            if row is None:
                return None
            body = self.crypto.decrypt(row["body"], f"utterances:{utterance_id}")
            body["device_ts"] = row["device_ts"]
            return body

    # ---- hand edits (khata screens, CONTRACT 3.6) -------------------------------------------------------------
    def _live_balance(self, customer_id: str) -> int:
        """Whole rupees owed, read from the table inside the current transaction."""
        row = self.conn.execute(
            f"SELECT COALESCE(SUM({SIGNED}),0) AS b FROM events e WHERE e.customer_id=? AND {ACTIVE}",
            (customer_id,)).fetchone()
        return int(rupees(row["b"]))

    def _portal_customer(self, customer_id: Any) -> dict:
        c = self._customers().get(customer_id) if isinstance(customer_id, str) else None
        if c is None:
            raise EditError(404, "unknown_customer")
        return c

    def _portal_write(self, body: Callable[[datetime, str], tuple[list[int], list[int], set[str]]],
                      now: datetime | None) -> dict:
        """Run `body(now, trace_id)` in one transaction. It returns (reversed ids, saved ids, touched customers)."""
        with self._lock:
            now = now or datetime.now().astimezone()
            trace_id = uuid.uuid4().hex[:16]
            self._begin()
            try:
                reversed_ids, saved_ids, touched = body(now, trace_id)
                self._refresh_stats(touched)
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                self._cache = None
                self._stats = None
                raise
            return {"reversed": reversed_ids, "saved": saved_ids, "touched": sorted(touched)}

    def _insert_portal(self, kind: str, customer_id: str, amount: int, eff: str, now: datetime, trace_id: str,
                       replaces_id: int | None = None) -> int:
        stored, adjustment = ("payment", "writeoff") if kind == "writeoff" else (kind, None)
        return self._insert_event(stored, customer_id, amount * 100, eff, now, utterance_id=None,
                                  session_id=PORTAL_SESSION, trace_id=trace_id, replaces_id=replaces_id,
                                  adjustment=adjustment)

    def add_entry(self, customer_id: str, kind: str, amount: int, eff: str, *, if_balance: int | None = None,
                  now: datetime | None = None) -> dict:
        """Append one entry. With `if_balance`, refuses (`balance_changed`) when the balance has moved."""
        def body(at: datetime, trace_id: str):
            self._portal_customer(customer_id)
            if if_balance is not None and self._live_balance(customer_id) != if_balance:
                raise EditError(409, "balance_changed")
            eid = self._insert_portal(kind, customer_id, amount, eff, at, trace_id)
            return [], [eid], {customer_id}
        return self._portal_write(body, now)

    def _entry_row(self, event_id: int) -> sqlite3.Row:
        """The active credit or payment with this id, else `unknown_entry` or `not_active`."""
        row = self.conn.execute("SELECT e.* FROM events e WHERE e.id=?", (event_id,)).fetchone()
        if row is None:
            raise EditError(404, "unknown_entry")
        if self._active_row(event_id, None) is None:
            raise EditError(409, "not_active")
        return row

    def _reverse_row(self, row: sqlite3.Row, now: datetime, trace_id: str) -> None:
        self._insert_event("reversal", row["customer_id"], row["amount_paise"], row["effective_date"], now,
                           utterance_id=None, session_id=PORTAL_SESSION, trace_id=trace_id,
                           supersedes_id=row["id"], adjustment=row["adjustment"])

    def amend_entry(self, event_id: int, *, kind: str | None = None, amount: int | None = None,
                    eff: str | None = None, customer_id: str | None = None, now: datetime | None = None) -> dict:
        """Reverse an active entry and save the changed copy (`replaces_id` = the old id) in one transaction.

        A field left as None keeps its value; the entry may move to another customer.
        """
        def body(at: datetime, trace_id: str):
            row = self._entry_row(event_id)
            target = self._portal_customer(customer_id) if customer_id is not None else None
            old = (api_kind(row["kind"], row["adjustment"]), rupees(row["amount_paise"]), row["effective_date"],
                   row["customer_id"])
            new = (kind if kind is not None else old[0], amount if amount is not None else old[1],
                   eff if eff is not None else old[2], target["id"] if target is not None else old[3])
            if new == old:
                raise EditError(400, "nothing_changed")
            self._reverse_row(row, at, trace_id)
            eid = self._insert_portal(new[0], new[3], new[1], new[2], at, trace_id, replaces_id=event_id)
            return [event_id], [eid], {old[3], new[3]}
        return self._portal_write(body, now)

    def remove_entry(self, event_id: int, *, now: datetime | None = None) -> dict:
        """Reverse one active entry."""
        def body(at: datetime, trace_id: str):
            row = self._entry_row(event_id)
            self._reverse_row(row, at, trace_id)
            return [event_id], [], {row["customer_id"]}
        return self._portal_write(body, now)

    def active_ids(self, ids: list[int]) -> set[int]:
        """The ids among `ids` that are still active entries."""
        with self._lock:
            return {i for i in ids if self._active_row(i, None) is not None}

    # ---- reads ------------------------------------------------------------------------------------------------
    def _active_row(self, event_id: Any, session_id: str | None) -> sqlite3.Row | None:
        """The event with this id when it is active and belongs to the session, else None."""
        if not isinstance(event_id, int) or isinstance(event_id, bool):
            return None
        sql = f"SELECT e.* FROM events e WHERE e.id = ? AND {ACTIVE}"
        args: list[Any] = [event_id]
        if session_id is not None:
            sql += " AND e.session_id = ?"
            args.append(session_id)
        return self.conn.execute(sql, args).fetchone()

    def _event_ctx(self, row: sqlite3.Row, now: datetime | None) -> dict:
        c = self._customers()[row["customer_id"]]
        ev = {"id": row["id"], "kind": api_kind(row["kind"], row["adjustment"]), "customer": c["key"],
              "customer_id": c["id"], "amount": rupees(row["amount_paise"]), "date": row["effective_date"]}
        if now is not None:
            ev["age_s"] = max(0, int((now - datetime.fromisoformat(row["ts"])).total_seconds()))
        return ev

    def last_events(self, session_id: str | None, now: datetime | None = None) -> list[dict]:
        """Active events saved by the session's previous saving utterance, oldest first, with ids."""
        with self._lock:
            last = self._last_active_row(session_id)
            if last is None:
                return []
            sql = f"SELECT e.* FROM events e WHERE {ACTIVE} AND e.session_id IS ? AND e.utterance_id IS ?"
            rows = self.conn.execute(sql + " ORDER BY e.id", (last["session_id"], last["utterance_id"])).fetchall()
            return [self._event_ctx(r, now) for r in rows]

    def last_active_event(self, session_id: str | None, now: datetime | None = None) -> dict | None:
        """Most recent active event of a session, shaped as the parser's `ctx.last_event`."""
        with self._lock:
            row = self._last_active_row(session_id)
            if row is None:
                return None
            return self._event_ctx(row, now)

    def balance(self, customer_id: str) -> int:
        """Whole rupees the customer owes (negative when they have paid ahead)."""
        with self._lock:
            return self._stats_now()["balances"].get(customer_id, 0)

    def has_entries(self, customer_id: str) -> bool:
        """True when the customer has at least one active entry."""
        with self._lock:
            return customer_id in self._stats_now()["active"]

    def totals(self, start: date, end: date) -> dict:
        """Credit and payment totals (rupees) and the number of active entries between two shop days, inclusive.

        Write-offs count as entries but are left out of the payment total.
        """
        with self._lock:
            row = self.conn.execute(
                f"SELECT COALESCE(SUM(CASE WHEN e.kind='credit' THEN e.amount_paise END),0) AS c, "
                f"COALESCE(SUM(CASE WHEN e.kind='payment' AND {NOT_WRITEOFF} THEN e.amount_paise END),0) AS p, "
                f"COUNT(*) AS n FROM events e WHERE e.effective_date BETWEEN ? AND ? AND {ACTIVE}",
                (start.isoformat(), end.isoformat())).fetchone()
            return {"credit": int(rupees(row["c"])), "payment": int(rupees(row["p"])), "count": int(row["n"])}

    def credit_total(self, day: date, end: date | None = None) -> int:
        return self.totals(day, end or day)["credit"]

    def payment_total(self, day: date, end: date | None = None) -> int:
        return self.totals(day, end or day)["payment"]

    def balances(self) -> dict[str, int]:
        """Balance in rupees for every customer id."""
        with self._lock:
            return dict(self._stats_now()["balances"])

    def top_dues(self, n: int = 3) -> list[tuple[str, int]]:
        """Customers with the largest positive balance, as (label, rupees)."""
        with self._lock:
            customers = self._customers()
            owed = [(b, customers[cid]["display"], cid) for cid, b in self._stats_now()["balances"].items()
                    if b > 0 and cid in customers]
            owed.sort(key=lambda d: (-d[0], d[1]))
            return [(self.label(cid), b) for b, _, cid in owed[:n]]

    def outstanding_total(self) -> dict:
        """The sum of the positive balances and how many customers owe."""
        with self._lock:
            owed = [b for b in self._stats_now()["balances"].values() if b > 0]
            return {"amount": sum(owed), "customers": len(owed)}

    def due_since(self, customer_id: str) -> date | None:
        """Effective date of the oldest credit not fully settled; payments and write-offs settle oldest first."""
        with self._lock:
            rows = self.conn.execute(
                f"SELECT e.kind, e.amount_paise, e.effective_date FROM events e WHERE e.customer_id=? AND {ACTIVE} "
                f"ORDER BY e.effective_date, e.id", (customer_id,)).fetchall()
        paid = sum(r["amount_paise"] for r in rows if r["kind"] == "payment")
        for r in rows:
            if r["kind"] != "credit":
                continue
            if paid >= r["amount_paise"]:
                paid -= r["amount_paise"]
                continue
            return date.fromisoformat(r["effective_date"])
        return None

    def daily_summary(self, day: date, end: date | None = None) -> dict:
        t = self.totals(day, end or day)
        top = self.top_dues(1)
        return {"count": t["count"], "credit": t["credit"], "payment": t["payment"], "top": top[0] if top else None}

    def confusables(self, min_count: int = 2) -> dict[str, list[int]]:
        """Amounts corrected at least `min_count` times: heard -> meant values, most frequent first."""
        with self._lock:
            out: dict[str, list[int]] = {}
            for row in self.conn.execute("SELECT heard, meant FROM confusions WHERE n >= ? ORDER BY heard, n DESC, "
                                         "last_ts DESC", (min_count,)):
                out.setdefault(str(row["heard"]), []).append(int(row["meant"]))
            return out

    def metrics(self) -> dict:
        """Counts since the database was created. No names, no transcripts."""
        with self._lock:
            def count(where: str = "1=1") -> int:
                return int(self.conn.execute(f"SELECT COUNT(*) FROM utterances WHERE {where}").fetchone()[0])

            pairs = [{"heard": r["heard"], "meant": r["meant"], "n": r["n"]}
                     for r in self.conn.execute("SELECT heard, meant, n FROM confusions ORDER BY n DESC, heard")]
            return {"turns": count(), "saves": count("status='ok' AND action='append'"),
                    "questions": count("status='needs_clarification'"), "rejections": count("status='rejected'"),
                    "corrections": count("status='ok' AND action='amend'"),
                    "undos": count("status='ok' AND action='undo'"), "noisy_turns": count("noisy=1"),
                    "confusions": pairs}

    def _entry(self, row: sqlite3.Row) -> dict:
        c = self._customers().get(row["customer_id"], {"id": row["customer_id"], "display": "?", "tags": []})
        return {
            "id": row["id"], "kind": api_kind(row["kind"], row["adjustment"]),
            "customer": {"id": c["id"], "display": c["display"], "tags": list(c["tags"])},
            "amount": rupees(row["amount_paise"]), "date": row["effective_date"], "ts": row["ts"],
            "reversed": bool(row["reversed"]), "reversal_of": None, "replaces": row["replaces_id"],
        }

    _ENTRY_SQL = ("SELECT e.*, EXISTS(SELECT 1 FROM events r WHERE r.kind='reversal' AND r.supersedes_id=e.id) "
                  "AS reversed FROM events e ")

    def entries_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        with self._lock:
            rows = self.conn.execute(self._ENTRY_SQL + f"WHERE e.id IN ({marks}) ORDER BY e.id", ids).fetchall()
            return [self._entry(r) for r in rows]

    def recent_entries(self, limit: int = 50, *, order: str = "created", customer_id: str | None = None) -> list[dict]:
        """Entries without reversal rows (they only set `reversed`).

        `order="created"`: newest first by creation (the audit order). `order="date"`: newest effective date
        first, then newest creation, for display.
        """
        sql = self._ENTRY_SQL + "WHERE e.kind != 'reversal'"
        args: list[Any] = []
        if customer_id:
            sql += " AND e.customer_id = ?"
            args.append(customer_id)
        sql += " ORDER BY e.effective_date DESC, e.id DESC" if order == "date" else " ORDER BY e.id DESC"
        with self._lock:
            rows = self.conn.execute(sql + " LIMIT ?", (*args, limit)).fetchall()
            return [self._entry(r) for r in rows]

    def _summary(self, c: dict, balance: int) -> dict:
        return {"id": c["id"], "display": c["display"], "tags": list(c["tags"]), "balance": balance,
                "reminders_opt_in": c["reminders_opt_in"], "lang": c.get("lang") or "hi",
                "say": c.get("say"), "phone_hint": phone_hint(c.get("phone"))}

    def customer_summaries(self) -> list[dict]:
        with self._lock:
            balances = self._stats_now()["balances"]
            return [self._summary(c, balances.get(c["id"], 0)) for c in self._customers().values()]

    def customer_summary(self, customer_id: str) -> dict | None:
        """One `/api/customers` item, built from the in-memory customer and balance caches."""
        with self._lock:
            c = self._customers().get(customer_id)
            return None if c is None else self._summary(c, self._stats_now()["balances"].get(customer_id, 0))

    def balance_items(self, customer_ids: list[str]) -> list[dict]:
        """`[{"customer_id","display","balance"}]` for the given customers, in order, without repeats."""
        with self._lock:
            balances = self._stats_now()["balances"]
            out, seen = [], set()
            for cid in customer_ids:
                c = self._customers().get(cid)
                if c is None or cid in seen:
                    continue
                seen.add(cid)
                out.append({"customer_id": cid, "display": str(self.label(cid)), "balance": balances.get(cid, 0)})
            return out

    # ---- reminders (opt-in only) ------------------------------------------------------------------------------
    def set_reminder_opt_in(self, customer_id: str, opt_in: bool, phone: str | None = None,
                            now: datetime | None = None) -> bool:
        """Record consent in `consent_log`. Opting out removes the customer's pending reminders at once."""
        with self._lock:
            c = self._customers().get(customer_id)
            if c is None:
                return False
            now = now or datetime.now().astimezone()
            self._begin()
            try:
                self.conn.execute("UPDATE customers SET reminders_opt_in=? WHERE id=?",
                                  (1 if opt_in else 0, customer_id))
                self.conn.execute("INSERT INTO consent_log(ts, customer_id, opt_in) VALUES (?,?,?)",
                                  (now.isoformat(), customer_id, 1 if opt_in else 0))
                if not opt_in:
                    self.conn.execute("DELETE FROM reminder_outbox WHERE customer_id=? AND status='pending'",
                                      (customer_id,))
                if phone is not None:
                    c["phone"] = phone or None
                    self._store_ident(customer_id, c)
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                self._cache = None
                raise
            c["reminders_opt_in"] = bool(opt_in)
            return True

    def consent_history(self, customer_id: str) -> list[dict]:
        with self._lock:
            return [{"ts": r["ts"], "opt_in": bool(r["opt_in"])} for r in self.conn.execute(
                "SELECT ts, opt_in FROM consent_log WHERE customer_id=? ORDER BY id", (customer_id,))]

    def _queue_one(self, cid: str, bal: int, now: datetime) -> int | None:
        if self.conn.execute("SELECT 1 FROM reminder_outbox WHERE customer_id=? AND status='pending'",
                             (cid,)).fetchone():
            return None
        # The message is rebuilt from the balance whenever the outbox is read, so the row stores no text.
        cur = self.conn.execute(
            "INSERT INTO reminder_outbox(ts, customer_id, amount_paise, body, status) VALUES (?,?,?,?, 'pending')",
            (now.isoformat(), cid, bal * 100, b""))
        return int(cur.lastrowid)

    def queue_reminder(self, customer_id: str, now: datetime) -> int | None:
        """Queue one reminder for an opted-in customer who owes, inside sending hours. Returns the row id or None
        (also when a pending row already exists; the existing row is then returned)."""
        with self._lock:
            c = self._customers().get(customer_id)
            bal = self.balance(customer_id)
            if c is None or not c["reminders_opt_in"] or bal <= 0 or in_quiet_hours(now):
                return None
            rid = self._queue_one(customer_id, bal, now)
            if rid is None:
                row = self.conn.execute("SELECT id FROM reminder_outbox WHERE customer_id=? AND status='pending'",
                                        (customer_id,)).fetchone()
                rid = int(row["id"]) if row else None
            return rid

    def reminder_items(self, reminder_ids: list[int]) -> list[dict]:
        """`[{"reminder_id","customer_id","amount"}]` for outbox rows, in id order (amount in whole rupees)."""
        if not reminder_ids:
            return []
        marks = ",".join("?" * len(reminder_ids))
        with self._lock:
            rows = self.conn.execute(f"SELECT id, customer_id, amount_paise FROM reminder_outbox WHERE id IN ({marks})"
                                     " ORDER BY id", list(reminder_ids)).fetchall()
        return [{"reminder_id": r["id"], "customer_id": r["customer_id"], "amount": rupees(r["amount_paise"])}
                for r in rows]

    def queue_reminders(self, now: datetime) -> list[int]:
        """Add one pending outbox row per opted-in customer who owes money and has no pending row.

        Nothing is queued outside 09:00 to 20:00 shop time."""
        if in_quiet_hours(now):
            return []
        queued = []
        with self._lock:
            balances = self.balances()
            for cid, c in self._customers().items():
                bal = balances.get(cid, 0)
                if not c["reminders_opt_in"] or bal <= 0:
                    continue
                rid = self._queue_one(cid, bal, now)
                if rid is not None:
                    queued.append(rid)
        return queued

    def outbox(self, now: datetime, message_fn: Callable[[str, int, str], str], status: str = "pending") -> list[dict]:
        """Outbox rows with the message rebuilt from the current balance, in the customer's language.

        Customers who opted out or no longer owe are dropped. Outside sending hours the list is empty."""
        if in_quiet_hours(now):
            return []
        with self._lock:
            balances = self.balances()
            out = []
            for row in self.conn.execute("SELECT * FROM reminder_outbox WHERE status=? ORDER BY id", (status,)):
                c = self._customers().get(row["customer_id"])
                if c is None or not c["reminders_opt_in"]:
                    continue
                bal = balances.get(c["id"], 0)
                if bal <= 0:
                    continue
                lang = c.get("lang") or "hi"
                message = message_fn(c["display"], bal, lang)
                link = wa_me_link(c["phone"], message) if c.get("phone") else None
                out.append({"id": row["id"], "customer": {"id": c["id"], "display": c["display"]},
                            "amount": bal, "lang": lang, "message": message, "wa_link": link,
                            "status": row["status"]})
            return out

    def mark_reminder_sent(self, reminder_id: int) -> None:
        with self._lock:
            self.conn.execute("UPDATE reminder_outbox SET status='sent' WHERE id=?", (reminder_id,))

    def reminder_to_send(self, reminder_id: int, now: datetime, message_fn: Callable[[str, int, str], str],
                         gap_s: float = 24 * 3600) -> tuple[dict | None, str]:
        """What to send for one queued reminder, rebuilt from the current balance: ({"customer_id","phone","lang",
        "message","amount"}, "ok"), or (None, reason) when it must not go out: `quiet_hours`, `gone` (the row was
        removed, e.g. by an opt-out), `already_sent`, `not_opted_in`, `nothing_due`, `no_phone`, or `sent_recently`
        (this customer was sent a reminder less than `gap_s` ago)."""
        if in_quiet_hours(now):
            return None, "quiet_hours"
        with self._lock:
            self._cache = None  # another process (the server) may have changed customers since this one loaded them
            self._stats = None
            row = self.conn.execute("SELECT * FROM reminder_outbox WHERE id=?", (reminder_id,)).fetchone()
            if row is None:
                return None, "gone"
            if row["status"] != "pending":
                return None, "already_sent"
            c = self._customers().get(row["customer_id"])
            if c is None or not c["reminders_opt_in"]:
                return None, "not_opted_in"
            bal = self.balance(c["id"])
            if bal <= 0:
                return None, "nothing_due"
            if not c.get("phone"):
                return None, "no_phone"
            since = (now - timedelta(seconds=gap_s)).isoformat()
            recent = self.conn.execute("SELECT 1 FROM reminder_outbox WHERE customer_id=? AND status='sent' AND ts>=?",
                                       (c["id"], since)).fetchone()
            if recent:
                return None, "sent_recently"
            lang = c.get("lang") or "hi"
            return {"customer_id": c["id"], "phone": c["phone"], "lang": lang, "amount": bal,
                    "message": message_fn(c["display"], bal, lang)}, "ok"
