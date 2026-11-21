"""O. Offline and sync (docs/EDGE_CASES.md section O). The browser queue itself is manual; these check the server
side: deduplication by utterance id, one ledger for several phones, atomic writes and encryption at rest."""
from __future__ import annotations

import pytest

from .kit import iso


def test_O02_the_same_queued_entry_sent_twice_is_saved_once(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    c = live_stack.session()
    first = c.text("Ramesh ka 250 udhaar", utt_id="utt-o02")
    n = live_stack.count()
    second = c.text("Ramesh ka 250 udhaar", utt_id="utt-o02")
    assert first.result["status"] == "ok"
    assert live_stack.count() == n and second.result.get("duplicate") is True, second.result
    assert live_stack.balance("ramesh") == 350


def test_O02_an_old_retry_in_a_new_session_is_still_a_duplicate(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    a = live_stack.session()
    a.text("Ramesh ne 30 diye", utt_id="utt-o02b")
    b = live_stack.session()
    again = b.text("Ramesh ne 30 diye", utt_id="utt-o02b")
    assert again.result.get("duplicate") is True and live_stack.balance("ramesh") == 70, again.result


def test_O03_two_phones_write_to_one_ledger(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    a, b = live_stack.session(), live_stack.session()
    a.text("Ramesh ka 10 udhaar")
    b.text("Ramesh ne 14 diye")
    a.text("Ramesh ka 20 udhaar")
    assert live_stack.balance("ramesh") == 116
    listed = live_stack.get("/api/ledger", params={"limit": 20}).json()["entries"]
    assert {10, 14, 20} <= {e["amount"] for e in listed}, listed
    ids = [e["id"] for e in listed]
    assert ids == sorted(ids, reverse=True), "the audit order is newest first by creation"


def test_O05_a_failed_save_writes_nothing_and_a_retry_works(rs):
    n = rs.count()
    bad = {"status": "ok", "action": "append", "events": [
        {"kind": "credit", "customer": "ramesh", "amount": 50, "date": iso(0)},
        {"kind": "credit", "customer": "sunita", "amount": 0, "date": iso(0)}]}
    with pytest.raises(Exception):
        rs.ledger.apply(bad, now=rs.clock.t, session_id="s", utterance_id="u-o05")
    assert rs.count() == n, "the first event must roll back with the second"
    good = {"status": "ok", "action": "append", "events": bad["events"][:1]}
    rs.ledger.apply(good, now=rs.clock.t, session_id="s", utterance_id="u-o05")
    assert rs.count() == n + 1


def test_O06_names_and_transcripts_are_not_readable_in_the_database_files(shop):
    shop.seed(("zorawar", "credit", 100))
    shop.say("Zorawar ka 4321 udhaar")
    shop.ledger.conn.execute("PRAGMA wal_checkpoint(FULL)")
    blob = b""
    for p in shop.dir.glob("khata.db*"):
        blob += p.read_bytes().lower()
    assert b"zorawar" not in blob, "a customer name is stored in plain text"
    assert b"4321 udhaar" not in blob and b"ka 4321" not in blob, "a transcript is stored in plain text"
