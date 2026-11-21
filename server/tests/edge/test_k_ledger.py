"""K. Ledger integrity (docs/EDGE_CASES.md section K, CONTRACT 2 and 2.1)."""
from __future__ import annotations

import base64
import sqlite3
import threading
import time
from datetime import datetime

import pytest

from app.crypto import Crypto
from app.ledger import Ledger

from .kit import IST, KEY, expect_ask, expect_saved, iso


def _ev(kind="credit", customer="ramesh", amount=10, date=None):
    return {"status": "ok", "action": "append", "events": [
        {"kind": kind, "customer": customer, "amount": amount, "date": date or iso(0)}]}


def test_K01_same_utt_id_twice_changes_the_balance_once(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    c = live_stack.session()
    first = c.text("Ramesh ne 40 diye", utt_id="utt-k01-a")
    second = c.text("Ramesh ne 40 diye", utt_id="utt-k01-a")
    assert first["result"]["status"] == "ok" and first["result"]["entries"], first["result"]
    assert second["result"].get("duplicate") is True, second["result"]
    assert live_stack.balance("ramesh") == 60


def test_K01_same_sentence_twice_within_30_seconds_is_asked(rs):
    expect_saved(rs.say("Ramesh ne 100 diye"), ("payment", "ramesh", 100), shop=rs)
    t = rs.say("Ramesh ne 100 diye")
    expect_ask(t, "confirm_entry")
    assert (t.confirm or {}).get("type") == "duplicate", t.describe()


def test_K01_carry_over_form_is_never_asked_as_a_duplicate(rs):
    rs.say("Ramesh ka 100 udhaar")
    expect_saved(rs.say("aur 200"), ("credit", "ramesh", 200), shop=rs)
    expect_saved(rs.say("aur 200"), ("credit", "ramesh", 200), shop=rs)


def test_K02_events_have_no_real_column_and_amounts_are_integers(rs):
    rs.say("Ramesh ka 2.5k udhaar")
    cols = rs.ledger.conn.execute("PRAGMA table_info(events)").fetchall()
    bad = [c["name"] for c in cols if any(w in (c["type"] or "").upper() for w in ("REAL", "FLOA", "DOUB", "NUMERIC"))]
    assert not bad, f"floating point columns in events: {bad}"
    types = {r[0] for r in rs.ledger.conn.execute("SELECT DISTINCT typeof(amount_paise) FROM events")}
    assert types == {"integer"}, types
    assert all(isinstance(r["amount"], int) for r in rs.entries())


def test_K02_a_float_amount_is_refused_by_the_ledger(rs):
    n = rs.count()
    with pytest.raises(Exception):
        rs.ledger.apply(_ev(amount=340.5), now=rs.clock.t, session_id="x")
    assert rs.count() == n


def test_K03_a_customer_row_cannot_be_deleted(rs):
    cid = rs.cid("ramesh")
    with pytest.raises(sqlite3.DatabaseError):
        rs.ledger.conn.execute("DELETE FROM customers WHERE id=?", (cid,))
    assert rs.ledger.conn.execute("SELECT COUNT(*) FROM customers WHERE id=?", (cid,)).fetchone()[0] == 1


def test_K03_an_event_row_cannot_be_deleted_or_changed(rs):
    with pytest.raises(sqlite3.DatabaseError):
        rs.ledger.conn.execute("DELETE FROM events")
    with pytest.raises(sqlite3.DatabaseError):
        rs.ledger.conn.execute("UPDATE events SET amount_paise = 1")


def _hammer(ledgers, per_thread=20):
    errors = []

    def work(ledger, tag):
        try:
            for i in range(per_thread):
                ledger.apply(_ev(customer=f"cust{tag}", amount=i + 1), now=_now(), session_id=f"s{tag}")
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=work, args=(lg, i)) for i, lg in enumerate(ledgers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return errors


def _now():
    return datetime.now(IST)


def test_K04_threads_on_one_ledger_never_hit_a_lock_error(shop):
    errors = _hammer([shop.ledger] * 8)
    assert not errors, errors[:3]
    assert shop.count() == 8 * 20


def test_K04_two_ledger_objects_on_one_file_never_hit_a_lock_error(shop):
    other = Ledger(shop.settings.ledger_db, Crypto(base64.b64decode(KEY)))
    try:
        errors = _hammer([shop.ledger, other, shop.ledger, other, shop.ledger, other])
        assert not errors, errors[:3]
        assert shop.count() == 6 * 20
    finally:
        other.close()


def test_K05_ten_thousand_events_keep_queries_under_50_ms(shop):
    for i in range(50):
        shop.ledger.create_customer(f"cust{chr(97 + i // 26)}{chr(97 + i % 26)}")
    cids = [c["id"] for c in shop.customers()]
    ts = shop.clock.t.isoformat()
    rows = [(ts, "credit" if i % 3 else "payment", cids[i % 50], 100 * (1 + i % 7), iso(i % 40))
            for i in range(10_000)]
    conn = shop.ledger.conn
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO events(ts, kind, customer_id, amount_paise, effective_date, session_id) "
                     "VALUES (?,?,?,?,?,'bulk')", rows)
    conn.execute("COMMIT")
    assert shop.count() == 10_000
    shop.seed(("ramesh", "credit", 100))
    probes = {
        "context build": lambda: shop.pipeline.build_ctx(shop.state, shop.clock.t),
        "customers_for_parser": shop.ledger.customers_for_parser,
        "balance query": lambda: shop.say("Ramesh ka total?"),
        "daily summary": lambda: shop.say("Aaj ka hisaab batao"),
        "top dues": lambda: shop.say("Sabse zyada udhaar kiska hai?"),
        "recent entries": lambda: shop.ledger.recent_entries(50),
    }
    slow = {}
    for name, fn in probes.items():
        best = min(_timed(fn) for _ in range(5))
        if best >= 0.050:
            slow[name] = round(best * 1000, 1)
    assert not slow, f"slower than 50 ms with 10,000 events (ms): {slow}"


def _timed(fn):
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def test_K06_past_dated_entry_is_ordered_by_date_for_display_and_by_creation_for_audit(live_stack):
    live_stack.seed_customer("ramesh", credit=1000)
    c = live_stack.session()
    c.text("Ramesh ne 10 diye")
    c.text("Ramesh ne parso 20 diye")
    by_created = live_stack.get("/api/ledger", params={"order": "created", "limit": 10}).json()["entries"]
    by_date = live_stack.get("/api/ledger", params={"order": "date", "limit": 10}).json()["entries"]
    assert [e["amount"] for e in by_created] == [20, 10, 1000], f"order=created is not newest first by creation: {[e['amount'] for e in by_created]}"
    assert [e["amount"] for e in by_date] == [10, 1000, 20], f"order=date is not by event date: {[e['amount'] for e in by_date]}"


@pytest.mark.parametrize("bad_id", [99999, "abc", -1, 0, True, None, "1; DROP TABLE events"])
def test_K07_undo_with_an_unknown_event_id_is_rejected(rs, bad_id):
    n = rs.count()
    out = rs.ledger.apply({"status": "ok", "action": "undo", "target": {"event_id": bad_id}},
                          now=rs.clock.t, session_id="seed")
    assert out.nothing and rs.count() == n


@pytest.mark.parametrize("bad_id", [99999, "abc", -1])
def test_K07_amend_with_an_unknown_event_id_saves_nothing(rs, bad_id):
    n = rs.count()
    out = rs.ledger.apply({"status": "ok", "action": "amend", "target": {"event_id": bad_id},
                           "events": [{"kind": "credit", "customer": "ramesh", "amount": 430,
                                       "date": rs.day(0)}]}, now=rs.clock.t, session_id="seed")
    assert out.nothing and rs.count() == n


def test_K07_the_pipeline_answers_an_unknown_target_cleanly(make_shop):
    def fake(utterance, *, today, ctx=None):
        return {"status": "ok", "action": "undo", "target": {"event_id": 424242}}

    s = make_shop(parse_fn=fake)
    s.seed(("ramesh", "credit", 100))
    n = s.count()
    t = s.say("undo karo")
    assert t.status == "rejected" and s.count() == n, t.describe()
