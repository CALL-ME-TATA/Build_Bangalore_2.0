"""Ledger maths, one-transaction rule, and the Responsible AI rules of CONTRACT section 7."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pytest

from app import admin

from .conftest import apply_events

TODAY = date(2026, 11, 21).isoformat()


def ev(kind, customer, amount, **extra):
    return {"kind": kind, "customer": customer, "amount": amount, "date": TODAY, **extra}


def now():
    return datetime.now().astimezone()


def cid(ledger, key):
    return ledger.find_customer(key=key)["id"]


def test_balance_after_credit_and_payment(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    apply_events(ledger, [ev("payment", "ramesh", 100)])
    assert ledger.balance(cid(ledger, "ramesh")) == 240
    assert ledger.credit_total(date(2026, 11, 21)) == 340
    assert ledger.payment_total(date(2026, 11, 21)) == 100


def test_undo_and_second_undo_walk_back(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    apply_events(ledger, [ev("credit", "ramesh", 200)])
    c = cid(ledger, "ramesh")
    out = ledger.apply({"action": "undo"}, now=now(), session_id="sess0001")
    assert out.reversed[0]["amount"] == 200
    assert ledger.balance(c) == 340
    out = ledger.apply({"action": "undo"}, now=now(), session_id="sess0001")
    assert out.reversed[0]["amount"] == 340
    assert ledger.balance(c) == 0
    out = ledger.apply({"action": "undo"}, now=now(), session_id="sess0001")
    assert out.nothing


def test_amend_is_reversal_plus_new_event(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    c = cid(ledger, "ramesh")
    out = ledger.apply({"action": "amend", "events": [ev("credit", "ramesh", 430, customer_id=c)]},
                       now=now(), session_id="sess0001")
    assert ledger.balance(c) == 430
    rows = ledger.conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    assert [r["kind"] for r in rows] == ["credit", "reversal", "credit"]
    assert rows[1]["supersedes_id"] == rows[0]["id"]
    assert rows[2]["replaces_id"] == rows[0]["id"]
    assert out.reversed[0]["id"] == rows[0]["id"] and out.saved[0]["amount"] == 430


def test_one_utterance_is_one_transaction(ledger):
    bad = [ev("credit", "ramesh", 340), ev("payment", "ramesh", 0)]
    with pytest.raises(ValueError):
        apply_events(ledger, bad)
    assert ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert ledger.find_customer(key="ramesh") is None
    apply_events(ledger, [ev("credit", "ramesh", 340), ev("payment", "ramesh", 200)])
    utter = {r["utterance_id"] for r in ledger.conn.execute("SELECT * FROM events")}
    assert ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    assert len(utter) == 1


def test_amounts_are_stored_as_paise(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    assert ledger.conn.execute("SELECT amount_paise FROM events").fetchone()[0] == 34000


def test_new_customer_and_tag_learning(ledger):
    out = apply_events(ledger, [ev("credit", "ramesh", 340, new_customer=True, tags=["chai wale"])])
    assert out.saved[0]["new_customer"] is True
    c = ledger.customers_for_parser()
    assert c[0]["name"] == "ramesh" and c[0]["tags"] == ["chai wale"]
    out = apply_events(ledger, [ev("credit", "ramesh", 10, customer_id=c[0]["id"])])
    assert out.saved[0]["new_customer"] is False


def test_top_dues_and_summary(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340), ev("credit", "sunita", 500), ev("payment", "mohan", 50)])
    assert ledger.top_dues(3) == [("Sunita", 500), ("Ramesh", 340)]
    s = ledger.daily_summary(date(2026, 11, 21))
    assert s["credit"] == 840 and s["payment"] == 50 and s["top"] == ("Sunita", 500)
    balances = {c["display"]: c["balance"] for c in ledger.customer_summaries()}
    assert balances["Mohan"] == -50


def test_entries_never_list_reversal_rows(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    ledger.apply({"action": "undo"}, now=now(), session_id="sess0001")
    entries = ledger.recent_entries()
    assert len(entries) == 1 and entries[0]["reversed"] is True and entries[0]["amount"] == 340


# ---- Responsible AI rules ----------------------------------------------------------------------------------------
def test_events_reject_update_and_delete(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    ledger.record_utterance("u1", "s", now(), transcript="hello", status="ok", reply_text="hi")
    for sql in ("UPDATE events SET amount_paise=1", "DELETE FROM events",
                "UPDATE utterances SET ts='x'", "DELETE FROM utterances"):
        with pytest.raises(sqlite3.DatabaseError):
            ledger.conn.execute(sql)
    assert ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_db_file_has_no_plaintext_names(ledger, settings):
    apply_events(ledger, [ev("credit", "zorbaxname", 340, tags=["chaiwalatag"])])
    ledger.record_utterance("u1", "s", now(), transcript="zorbaxname ka transcriptword", status="ok",
                            reply_text="replytextword")
    ledger.close()
    from pathlib import Path

    raw = b"".join(p.read_bytes() for p in Path(settings.ledger_db).parent.glob("khata.db*"))
    for secret in (b"zorbaxname", b"Zorbaxname", b"chaiwalatag", b"transcriptword", b"replytextword"):
        assert secret not in raw
    ledger.open()


def test_purge_removes_database(ledger, settings):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    ledger.close()
    from pathlib import Path

    assert Path(settings.ledger_db).exists()
    admin.purge(settings)
    assert not list(Path(settings.ledger_db).parent.glob("khata.db*"))
    ledger.open()


def test_seed_adds_synthetic_customers(ledger, settings):
    assert admin.seed(ledger, settings) == 5
    assert len(ledger.customer_summaries()) == 5


def test_reminders_only_for_opted_in_customers(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340), ev("credit", "sunita", 500)])
    r = ledger.find_customer(key="ramesh")["id"]
    noon = datetime(2026, 11, 21, 12, 0).astimezone()
    assert ledger.queue_reminders(noon) == []
    ledger.set_reminder_opt_in(r, True, "98765 43210")
    queued = ledger.queue_reminders(noon)
    assert len(queued) == 1
    box = ledger.outbox(noon, lambda n, a, lang: f"Namaste {n}, {a}")
    assert box[0]["customer"]["display"] == "Ramesh" and box[0]["message"] == "Namaste Ramesh, 340"
    assert box[0]["wa_link"].startswith("https://wa.me/919876543210?text=")
    assert ledger.queue_reminders(noon) == []


def test_same_name_customers_are_labelled_with_first_tag(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 280, new_customer=True, tags=["chai wale"])])
    c1 = ledger.find_customer(key="ramesh")["id"]
    assert ledger.label(c1) == "Ramesh"  # unique name keeps the plain name even with tags
    out = apply_events(ledger, [ev("credit", "ramesh", 50, new_customer=True, tags=["gali number 3"])])
    assert out.saved[0]["customer"] == "Ramesh gali number 3" and out.saved[0]["new_customer"] is True
    assert ledger.label(c1) == "Ramesh chai wale"
    assert ledger.top_dues(3) == [("Ramesh chai wale", 280), ("Ramesh gali number 3", 50)]
    undone = ledger.apply({"action": "undo"}, now=now(), session_id="sess0001")
    assert undone.reversed[0]["customer"] == "Ramesh gali number 3"
