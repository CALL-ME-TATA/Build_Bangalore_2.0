"""R. Screen and experience. Screen behaviour is checked by hand (docs/EDGE_REPORT.md lists it as manual); these two
cases are about what the server sends."""
from __future__ import annotations

import time


def test_R04_latest_entries_list_shows_the_saved_entry(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    c = live_stack.session()
    c.text("Ramesh ne 40 diye")
    body = live_stack.get("/api/ledger", params={"limit": 5}).json()
    newest = body["entries"][0]
    assert (newest["kind"], newest["amount"], newest["customer"]["display"], newest["reversed"]) == (
        "payment", 40, "Ramesh", False), newest
    assert {"id", "date", "ts"} <= set(newest), newest
    assert body["totals"]["payment_today"] == 40, body["totals"]


def test_R12_the_entry_is_committed_before_anything_is_spoken(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    c = live_stack.session()
    before = live_stack.count()
    c.send({"type": "text", "text": "Ramesh ne 40 diye"})
    audio_before_result, deadline = False, time.monotonic() + 10
    while time.monotonic() < deadline:
        msg = c.recv(5)
        if isinstance(msg, bytes) or (isinstance(msg, dict) and msg["type"] == "audio_start"):
            audio_before_result = True
        if isinstance(msg, dict) and msg["type"] == "result":
            assert live_stack.count() == before + 1, "the result was sent before the entry was committed"
            break
    else:
        raise AssertionError("no result")
    assert not audio_before_result, "audio started before the result message"
