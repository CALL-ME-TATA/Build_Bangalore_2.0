"""Q. Reminders (docs/EDGE_CASES.md section Q, CONTRACT 2.1, 3.3 and 5.1). Reminders go only to opted-in customers,
and the app only prepares a wa.me link: nothing is sent by the server."""
from __future__ import annotations

import re
from datetime import datetime

import pytest

from .kit import IST
from .scenarios import TONE_SENTENCES

PRESSURE = [
    "turant", "jaldi", "warna", "nahi to", "dhamki", "badnam", "sharam", "kanooni", "zabardasti", "abhi chukao",
    "abhi do", "abhi pay", "urgent", "immediately", "overdue", "penalty", "legal", "police", "court", "final notice",
    "last chance", "or else", "pay now", "pay up", "consequence", "shame", "default", "blacklist", "kharab",
]
ELEVEN = datetime(2026, 11, 21, 11, 0, tzinfo=IST)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 21, hour, minute, tzinfo=IST)


def opted_in(stack, name="ramesh", balance=340, phone="9876543210", **extra):
    cid = stack.seed_customer(name, credit=balance)
    r = stack.post(f"/api/customers/{cid}/reminders", json={"opt_in": True, "phone": phone, **extra})
    assert r.status_code == 200, r.text
    return cid


def outbox(stack) -> dict:
    return stack.get("/api/reminders").json()


def test_Q01_a_customer_who_has_not_opted_in_never_gets_a_reminder(live_stack):
    live_stack.clock.set(ELEVEN)
    live_stack.seed_customer("ramesh", credit=340)
    assert live_stack.post("/api/reminders/queue").json()["queued"] == []
    assert outbox(live_stack)["reminders"] == []
    c = live_stack.session()
    said = c.text("Ramesh ko reminder bhejo")
    assert "haan nahi kaha" in said.result["reply_text"], said.result
    assert outbox(live_stack)["reminders"] == []


def test_Q03_message_is_short_neutral_and_has_no_item_details(live_stack):
    live_stack.clock.set(ELEVEN)
    live_stack.seed_customer("sunita", credit=770)
    opted_in(live_stack, "ramesh", 340)
    live_stack.post("/api/reminders/queue")
    items = outbox(live_stack)["reminders"]
    assert len(items) == 1, items
    message = items[0]["message"]
    assert len(message.split()) <= 25, message
    assert re.findall(r"\d[\d,]*", message) == ["340"], f"only the amount may appear: {message!r}"
    assert "sunita" not in message.lower()


def test_Q04_a_customer_who_paid_in_the_meantime_is_recomputed_or_dropped(live_stack):
    live_stack.clock.set(ELEVEN)
    opted_in(live_stack, "ramesh", 340)
    live_stack.post("/api/reminders/queue")
    live_stack.add_event("ramesh", "payment", 100)
    items = outbox(live_stack)["reminders"]
    assert len(items) == 1 and items[0]["amount"] == 240, items
    assert "240" in items[0]["message"] and "340" not in items[0]["message"], items[0]["message"]
    live_stack.add_event("ramesh", "payment", 240)
    assert outbox(live_stack)["reminders"] == [], "a customer who no longer owes is dropped"


def test_Q05_opting_out_removes_the_pending_reminder_and_is_logged(live_stack):
    live_stack.clock.set(ELEVEN)
    cid = opted_in(live_stack, "ramesh", 340)
    live_stack.post("/api/reminders/queue")
    assert len(outbox(live_stack)["reminders"]) == 1
    assert live_stack.post(f"/api/customers/{cid}/reminders", json={"opt_in": False}).status_code == 200
    assert outbox(live_stack)["reminders"] == []
    assert live_stack.post("/api/reminders/queue").json()["queued"] == []
    log = [r[0] for r in live_stack.ledger.conn.execute("SELECT opt_in FROM consent_log ORDER BY id")]
    assert log[-2:] == [1, 0], log


@pytest.mark.parametrize("when,quiet", [(at(8, 30), True), (at(20, 30), True), (at(23, 0), True),
                                         (at(9, 30), False), (at(19, 30), False)])
def test_Q06_reminders_only_within_sending_hours(live_stack, when, quiet):
    live_stack.clock.set(ELEVEN)
    opted_in(live_stack, "ramesh", 340)
    live_stack.clock.set(when)
    queued = live_stack.post("/api/reminders/queue").json()["queued"]
    body = outbox(live_stack)
    if quiet:
        assert queued == [] and body == {"reminders": [], "quiet_hours": True}, (queued, body)
    else:
        assert len(queued) == 1 and len(body["reminders"]) == 1, (queued, body)


def test_Q07_message_follows_the_customers_language(live_stack):
    live_stack.clock.set(ELEVEN)
    opted_in(live_stack, "ramesh", 340, lang="en")
    opted_in(live_stack, "sunita", 340, lang="hi")
    live_stack.post("/api/reminders/queue")
    by_name = {i["customer"]["display"]: i["message"] for i in outbox(live_stack)["reminders"]}
    assert set(by_name) == {"Ramesh", "Sunita"}, by_name
    assert by_name["Ramesh"] != by_name["Sunita"], "the language preference changed nothing"
    assert not re.search(r"(?i)baaki|udhaar|hain", by_name["Ramesh"]), by_name["Ramesh"]


def test_Q08_a_wrong_amount_is_corrected_to_the_real_balance(live_stack):
    live_stack.clock.set(ELEVEN)
    opted_in(live_stack, "ramesh", 340)
    c = live_stack.session()
    asked = c.text("Send Ramesh a reminder for 850")
    r = asked.result
    assert r["status"] == "needs_clarification" and (r.get("confirm") or {}).get("type") == "reminder", r
    assert "340" in r["reply_text"], r
    assert outbox(live_stack)["reminders"] == [], "nothing may be queued before the yes"
    c.text("yes")
    items = outbox(live_stack)["reminders"]
    assert len(items) == 1 and items[0]["amount"] == 340, items


def test_Q09_no_reply_or_reminder_uses_pressure_language(make_shop):
    s = make_shop()
    s.seed(("ramesh", "credit", 100), ("sunita", "credit", 100))
    texts = [s.say(t).reply_text for t in TONE_SENTENCES]
    for lang in ("hi", "en"):
        r = s.pipeline.replies.with_lang(lang)
        texts.append(r.reminder("Ramesh", 340))
    low = " ".join(texts).lower()
    found = [w for w in PRESSURE if re.search(rf"\b{re.escape(w)}\b", low)]
    assert not found, f"pressure words in replies: {found}"


def test_Q10_the_app_prepares_a_whatsapp_link_and_sends_nothing(live_stack):
    live_stack.clock.set(ELEVEN)
    opted_in(live_stack, "ramesh", 340)
    live_stack.post("/api/reminders/queue")
    item = outbox(live_stack)["reminders"][0]
    assert item["wa_link"].startswith("https://wa.me/91"), item
    assert item["status"] == "pending", "only the shopkeeper marks a reminder sent"
