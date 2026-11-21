"""Kafka notifications (app/notify.py): one event per committed write, no names, never blocks or breaks a turn."""
from __future__ import annotations

import time

from app.notify import KafkaNotifier, Notifier
from app.pipeline import Pipeline, SessionState

from .conftest import fake_nw


class Capture(Notifier):
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def test_a_saved_entry_publishes_one_event_without_names(ledger, settings, parser):
    p = Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw)
    p.notifier, p.shop = Capture(), "shop1"
    s = SessionState(session_id="sess0001")
    p.run_turn(s, "ramesh ka 340 udhaar")
    p.run_turn(s, "mohan ko 200 udhaar")  # asks first: nothing saved, nothing published
    evs = p.notifier.events
    assert [(e["type"], e["kind"], e["amount"], e["shop"]) for e in evs] == [("entry_append", "credit", 340, "shop1")]
    assert evs[0]["customer_id"] and evs[0]["entry_id"] and evs[0]["ts"]
    assert "ramesh" not in str(evs).lower()  # names stay out of the broker


def test_kafka_notifier_hands_events_to_the_producer_in_the_background():
    sent = []

    class FakeProducer:
        def send(self, topic, key=None, value=None):
            sent.append((topic, key, value))

        def flush(self, timeout=None):
            pass

        def close(self, timeout=None):
            pass

    n = KafkaNotifier("broker:9092", "khata.notifications", producer_factory=FakeProducer)
    n.publish({"type": "entry_append", "shop": "s1", "customer_id": "c1", "amount": 340})
    for _ in range(40):
        if sent:
            break
        time.sleep(0.05)
    n.close()
    assert sent and sent[0][0] == "khata.notifications" and sent[0][1] == "s1:c1" and sent[0][2]["amount"] == 340


def test_reminders_queued_from_the_screen_carry_customer_and_amount(tmp_path):
    """POST /api/reminders/queue publishes the same reminder_queued event as a reminder queued by voice."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    from .conftest import TEST_KEY

    eleven = datetime(2026, 11, 21, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # inside sending hours
    s = Settings(gnani_api_key="test-key", gnani_base_url="http://127.0.0.1:9", ledger_key=TEST_KEY,
                 ledger_db=str(tmp_path / "data" / "khata.db"), tts_prewarm=False)
    app = create_app(s, web_dir=tmp_path, now=lambda: eleven)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        ctx = app.state.ctx
        cap = ctx.pipeline.notifier = Capture()
        cid = ctx.ledger.create_customer("ramesh", now=eleven)["id"]
        ctx.ledger.apply({"action": "append", "events": [{"kind": "credit", "customer": "ramesh", "customer_id": cid,
                                                           "amount": 340, "date": "2026-11-21"}]}, now=eleven)
        ctx.ledger.set_reminder_opt_in(cid, True, "9876543210", now=eleven)
        queued = c.post("/api/reminders/queue").json()["queued"]
    assert len(queued) == 1
    assert [(e["type"], e["reminder_id"], e["customer_id"], e["amount"]) for e in cap.events] == [
        ("reminder_queued", queued[0], cid, 340)]
    assert "ramesh" not in str(cap.events).lower() and "9876543210" not in str(cap.events)


def test_a_refused_delivery_is_logged(caplog):
    class Sent:
        def add_errback(self, fn):
            fn(RuntimeError("topic not authorised"))

    class FakeProducer:
        def send(self, topic, key=None, value=None):
            return Sent()

        def flush(self, timeout=None):
            pass

        def close(self, timeout=None):
            pass

    n = KafkaNotifier("broker:9092", "khata.notifications", producer_factory=FakeProducer)
    with caplog.at_level("WARNING", logger="khata.notify"):
        n.publish({"type": "entry_append", "amount": 1})
        for _ in range(40):
            if "kafka delivery failed" in caplog.text:
                break
            time.sleep(0.05)
    n.close()
    assert "kafka delivery failed: RuntimeError" in caplog.text


def test_the_producer_gives_up_on_a_missing_broker_within_seconds(monkeypatch):
    import sys
    import types

    seen = {}

    class KafkaProducer:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setitem(sys.modules, "kafka", types.SimpleNamespace(KafkaProducer=KafkaProducer))
    n = KafkaNotifier.__new__(KafkaNotifier)  # no background thread: only the producer settings are checked
    n.bootstrap, n.topic = "broker:9092", "khata.notifications"
    n._kafka_producer()
    assert seen["bootstrap_servers"] == "broker:9092"
    assert seen["max_block_ms"] <= 5000 and seen["bootstrap_timeout_ms"] <= 5000


def test_broker_down_never_blocks_the_caller():
    def down():
        raise ConnectionError("no broker")

    n = KafkaNotifier("nowhere:9092", "khata.notifications", producer_factory=down)
    t0 = time.perf_counter()
    for i in range(50):
        n.publish({"type": "entry_append", "amount": i})
    assert time.perf_counter() - t0 < 0.1
    n.close()
