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


def test_broker_down_never_blocks_the_caller():
    def down():
        raise ConnectionError("no broker")

    n = KafkaNotifier("nowhere:9092", "khata.notifications", producer_factory=down)
    t0 = time.perf_counter()
    for i in range(50):
        n.publish({"type": "entry_append", "amount": i})
    assert time.perf_counter() - t0 < 0.1
    n.close()
