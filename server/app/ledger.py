"""SQLite ledger: append-only events, integer paise, field-level AES-256-GCM (CONTRACT section 2).

Names, aliases, tags, phones, transcripts and reply texts are encrypted. Ids, kinds, amounts and dates stay in plain
columns so balances and totals are plain SQL. Triggers abort every UPDATE and DELETE on `events` and `utterances`;
purging means deleting the database file, never deleting rows.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .crypto import Crypto

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
CREATE INDEX IF NOT EXISTS events_customer ON events(customer_id);
CREATE INDEX IF NOT EXISTS events_supersedes ON events(supersedes_id);
CREATE INDEX IF NOT EXISTS events_date ON events(effective_date);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS utterances_no_update BEFORE UPDATE ON utterances
  BEGIN SELECT RAISE(ABORT, 'utterances is append-only'); END;
CREATE TRIGGER IF NOT EXISTS utterances_no_delete BEFORE DELETE ON utterances
  BEGIN SELECT RAISE(ABORT, 'utterances is append-only'); END;
"""

# An event is active when it is a credit or payment that no reversal points at.
ACTIVE = (
    "e.kind IN ('credit','payment') AND NOT EXISTS "
    "(SELECT 1 FROM events r WHERE r.kind='reversal' AND r.supersedes_id = e.id)"
)
SIGNED = "CASE e.kind WHEN 'credit' THEN e.amount_paise ELSE -e.amount_paise END"


def rupees(paise: int) -> int:
    """Whole rupees. Amounts are always saved as whole rupees times 100."""
    return paise // 100


@dataclass
class Outcome:
    """What `Ledger.apply` did. `saved` holds new events, `reversed` the events cancelled by undo or amend."""

    action: str
    saved: list[dict] = field(default_factory=list)
    reversed: list[dict] = field(default_factory=list)
    nothing: bool = False


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
        self._lock = threading.RLock()
        self._cache: dict[str, dict] | None = None
        self._conn: sqlite3.Connection | None = None
        self.open()

    # ---- connection -------------------------------------------------------------------------------------------
    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        self._conn = conn
        self._cache = None

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            self._cache = None

    @property
    def conn(self) -> sqlite3.Connection:
        assert self._conn is not None, "ledger is closed"
        return self._conn

    # ---- customers --------------------------------------------------------------------------------------------
    def _customers(self) -> dict[str, dict]:
        """All customers, decrypted and cached in memory (customer rows are few)."""
        if self._cache is None:
            cache = {}
            for row in self.conn.execute("SELECT id, ident, reminders_opt_in FROM customers ORDER BY created_ts, id"):
                ident = self.crypto.decrypt(row["ident"], f"customers:{row['id']}")
                ident["id"] = row["id"]
                ident["reminders_opt_in"] = bool(row["reminders_opt_in"])
                cache[row["id"]] = ident
            self._cache = cache
        return self._cache

    def _store_ident(self, cid: str, ident: dict) -> None:
        body = {k: ident.get(k) for k in ("key", "display", "aliases", "tags", "phone")}
        blob = self.crypto.encrypt(body, f"customers:{cid}")
        self.conn.execute("UPDATE customers SET ident=? WHERE id=?", (blob, cid))

    def _create_customer(self, key: str, now: datetime, tags: list[str] | None = None) -> dict:
        cid = "c_" + uuid.uuid4().hex[:10]
        ident = {"key": key, "display": key.title(), "aliases": [], "tags": list(tags or []), "phone": None}
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
            return dict(ident)

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

    def customers_for_parser(self) -> list[dict]:
        with self._lock:
            return [
                {"id": c["id"], "name": c["key"], "tags": list(c["tags"]), "aliases": list(c.get("aliases", []))}
                for c in self._customers().values()
            ]

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
                      supersedes_id: int | None = None, replaces_id: int | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO events(ts, kind, customer_id, amount_paise, effective_date, utterance_id, supersedes_id,"
            " replaces_id, session_id, trace_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (now.isoformat(), kind, customer_id, paise, eff, utterance_id, supersedes_id, replaces_id,
             session_id, trace_id),
        )
        return int(cur.lastrowid)

    @staticmethod
    def _event_info(event_id: int, kind: str, customer: dict, paise: int, eff: str, created: bool = False) -> dict:
        return {"id": event_id, "kind": kind, "customer_id": customer["id"], "customer": customer["display"],
                "key": customer["key"], "amount": rupees(paise), "date": eff, "new_customer": created}

    def _last_active_row(self, session_id: str | None) -> sqlite3.Row | None:
        sql = f"SELECT e.* FROM events e WHERE {ACTIVE}"
        args: list[Any] = []
        if session_id is not None:
            sql += " AND e.session_id = ?"
            args.append(session_id)
        return self.conn.execute(sql + " ORDER BY e.id DESC LIMIT 1", args).fetchone()

    def apply(self, result: dict, *, now: datetime, session_id: str | None = None, trace_id: str | None = None,
              utterance_id: str | None = None) -> Outcome:
        """Apply an ok parser result (append, amend or undo) in one transaction: all events are saved or none."""
        action = result.get("action")
        if action not in ("append", "amend", "undo"):
            raise ValueError(f"cannot apply action {action!r}")
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                outcome = self._apply_locked(action, result, now, session_id, trace_id, utterance_id)
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                self._cache = None
                raise
            return outcome

    def _apply_locked(self, action: str, result: dict, now: datetime, session_id, trace_id, utterance_id) -> Outcome:
        out = Outcome(action=action)
        kw = {"utterance_id": utterance_id, "session_id": session_id, "trace_id": trace_id}
        cache: dict[str, dict] = {}
        created: set[str] = set()
        old = None
        if action in ("amend", "undo"):
            old = self._last_active_row(session_id)
            if old is None:
                out.nothing = True
                return out
            owner = self._customers()[old["customer_id"]]
            self._insert_event("reversal", old["customer_id"], old["amount_paise"], old["effective_date"],
                               now, supersedes_id=old["id"], **kw)
            out.reversed.append(self._event_info(old["id"], old["kind"], owner, old["amount_paise"],
                                                 old["effective_date"]))
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
            if kind not in ("credit", "payment"):
                raise ValueError(f"bad event kind {kind!r}")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                raise ValueError(f"bad event amount {amount!r}")
            customer = self._resolve(ev, now, cache, created)
            eff = ev.get("date") or now.date().isoformat()
            paise = amount * 100
            eid = self._insert_event(kind, customer["id"], paise, eff, now,
                                     replaces_id=old["id"] if old is not None else None, **kw)
            out.saved.append(self._event_info(eid, kind, customer, paise, eff, customer["id"] in created))
        return out

    def record_utterance(self, utterance_id: str, session_id: str | None, now: datetime, *, transcript: str,
                         status: str, reply_text: str, timings: dict | None = None) -> None:
        body = {"transcript": transcript, "status": status, "reply_text": reply_text, "timings": timings or {}}
        blob = self.crypto.encrypt(body, f"utterances:{utterance_id}")
        with self._lock:
            self.conn.execute("INSERT INTO utterances(id, ts, session_id, body) VALUES (?,?,?,?)",
                              (utterance_id, now.isoformat(), session_id, blob))

    def read_utterance(self, utterance_id: str) -> dict:
        row = self.conn.execute("SELECT body FROM utterances WHERE id=?", (utterance_id,)).fetchone()
        return self.crypto.decrypt(row["body"], f"utterances:{utterance_id}")

    # ---- reads ------------------------------------------------------------------------------------------------
    def last_active_event(self, session_id: str | None, now: datetime | None = None) -> dict | None:
        """Most recent active event of a session, shaped as the parser's `ctx.last_event`."""
        with self._lock:
            row = self._last_active_row(session_id)
            if row is None:
                return None
            c = self._customers()[row["customer_id"]]
            ev = {"kind": row["kind"], "customer": c["key"], "customer_id": c["id"],
                  "amount": rupees(row["amount_paise"]), "date": row["effective_date"]}
            if now is not None:
                age = (now - datetime.fromisoformat(row["ts"])).total_seconds()
                ev["age_s"] = max(0, int(age))
            return ev

    def balance(self, customer_id: str) -> int:
        """Whole rupees the customer owes (negative when they have paid ahead)."""
        row = self.conn.execute(
            f"SELECT COALESCE(SUM({SIGNED}),0) AS b FROM events e WHERE e.customer_id=? AND {ACTIVE}",
            (customer_id,)).fetchone()
        return int(rupees(row["b"]))

    def _total(self, kind: str, day: str) -> int:
        row = self.conn.execute(
            f"SELECT COALESCE(SUM(e.amount_paise),0) AS t FROM events e WHERE e.kind=? AND e.effective_date=? "
            f"AND {ACTIVE}", (kind, day)).fetchone()
        return int(rupees(row["t"]))

    def credit_total(self, day: date) -> int:
        return self._total("credit", day.isoformat())

    def payment_total(self, day: date) -> int:
        return self._total("payment", day.isoformat())

    def balances(self) -> dict[str, int]:
        """Balance in rupees for every customer id."""
        with self._lock:
            result = {cid: 0 for cid in self._customers()}
            for row in self.conn.execute(
                    f"SELECT e.customer_id AS cid, SUM({SIGNED}) AS b FROM events e WHERE {ACTIVE} "
                    f"GROUP BY e.customer_id"):
                result[row["cid"]] = int(rupees(row["b"]))
            return result

    def top_dues(self, n: int = 3) -> list[tuple[str, int]]:
        """Customers with the largest positive balance, as (display name, rupees)."""
        with self._lock:
            customers = self._customers()
            dues = [(customers[cid]["display"], b) for cid, b in self.balances().items() if b > 0]
        dues.sort(key=lambda d: (-d[1], d[0]))
        return dues[:n]

    def daily_summary(self, day: date) -> dict:
        iso = day.isoformat()
        count = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM events e WHERE e.effective_date=? AND {ACTIVE}", (iso,)).fetchone()["n"]
        top = self.top_dues(1)
        return {"count": int(count), "credit": self.credit_total(day), "payment": self.payment_total(day),
                "top": top[0] if top else None}

    def _entry(self, row: sqlite3.Row) -> dict:
        c = self._customers().get(row["customer_id"], {"id": row["customer_id"], "display": "?", "tags": []})
        return {
            "id": row["id"], "kind": row["kind"],
            "customer": {"id": c["id"], "display": c["display"], "tags": list(c["tags"])},
            "amount": rupees(row["amount_paise"]), "date": row["effective_date"], "ts": row["ts"],
            "reversed": bool(row["reversed"]), "reversal_of": None,
        }

    def entries_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        with self._lock:
            rows = self.conn.execute(
                f"SELECT e.*, EXISTS(SELECT 1 FROM events r WHERE r.kind='reversal' AND r.supersedes_id=e.id) "
                f"AS reversed FROM events e WHERE e.id IN ({marks}) ORDER BY e.id", ids).fetchall()
            return [self._entry(r) for r in rows]

    def recent_entries(self, limit: int = 50) -> list[dict]:
        """Newest first. Reversal rows are not listed; they only set `reversed` on the entry they cancel."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT e.*, EXISTS(SELECT 1 FROM events r WHERE r.kind='reversal' AND r.supersedes_id=e.id) "
                "AS reversed FROM events e WHERE e.kind != 'reversal' ORDER BY e.id DESC LIMIT ?", (limit,)).fetchall()
            return [self._entry(r) for r in rows]

    def customer_summaries(self) -> list[dict]:
        with self._lock:
            balances = self.balances()
            return [{"id": c["id"], "display": c["display"], "tags": list(c["tags"]), "balance": balances[c["id"]],
                     "reminders_opt_in": c["reminders_opt_in"]} for c in self._customers().values()]

    # ---- reminders (opt-in only) ------------------------------------------------------------------------------
    def set_reminder_opt_in(self, customer_id: str, opt_in: bool, phone: str | None = None) -> bool:
        with self._lock:
            c = self._customers().get(customer_id)
            if c is None:
                return False
            self.conn.execute("UPDATE customers SET reminders_opt_in=? WHERE id=?", (1 if opt_in else 0, customer_id))
            c["reminders_opt_in"] = bool(opt_in)
            if phone is not None:
                c["phone"] = phone or None
                self._store_ident(customer_id, c)
            return True

    def queue_reminders(self, now: datetime, message_fn: Callable[[str, int], str]) -> list[int]:
        """Add one pending outbox row per opted-in customer who owes money and has no pending row."""
        queued = []
        with self._lock:
            balances = self.balances()
            for cid, c in self._customers().items():
                bal = balances.get(cid, 0)
                if not c["reminders_opt_in"] or bal <= 0:
                    continue
                if self.conn.execute("SELECT 1 FROM reminder_outbox WHERE customer_id=? AND status='pending'",
                                     (cid,)).fetchone():
                    continue
                cur = self.conn.execute(
                    "INSERT INTO reminder_outbox(ts, customer_id, amount_paise, body, status) "
                    "VALUES (?,?,?,?, 'pending')", (now.isoformat(), cid, bal * 100, b""))
                rid = int(cur.lastrowid)
                blob = self.crypto.encrypt({"message": message_fn(c["display"], bal)}, f"reminder_outbox:{rid}")
                self.conn.execute("UPDATE reminder_outbox SET body=? WHERE id=?", (blob, rid))
                queued.append(rid)
        return queued

    def outbox(self, status: str = "pending") -> list[dict]:
        with self._lock:
            out = []
            for row in self.conn.execute("SELECT * FROM reminder_outbox WHERE status=? ORDER BY id", (status,)):
                c = self._customers().get(row["customer_id"])
                if c is None:
                    continue
                message = self.crypto.decrypt(row["body"], f"reminder_outbox:{row['id']}")["message"]
                link = wa_me_link(c["phone"], message) if c.get("phone") else None
                out.append({"id": row["id"], "customer": {"id": c["id"], "display": c["display"]},
                            "amount": rupees(row["amount_paise"]), "message": message, "wa_link": link,
                            "status": row["status"]})
            return out

    def mark_reminder_sent(self, reminder_id: int) -> None:
        with self._lock:
            self.conn.execute("UPDATE reminder_outbox SET status='sent' WHERE id=?", (reminder_id,))
