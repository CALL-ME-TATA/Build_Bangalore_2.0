"""Notifications to Kafka (topic KAFKA_TOPIC, default khata.notifications).

After a ledger write commits, the server publishes one small JSON event: `entry_append`, `entry_amend`,
`entry_undo` or `reminder_queued`. Events carry ids, kinds and amounts but no names or transcripts (names are
encrypted at rest and stay out of the broker). A worker (`python -m app.notify_worker`) consumes them; that is
where a WhatsApp or SMS sender plugs in. Nothing is sent to a customer automatically.

Publishing never slows or breaks a turn: events go on an in-memory queue and a background thread hands them to
Kafka. When the broker is down, events are dropped with a warning (the ledger and its reminder outbox stay the
source of truth). With KAFKA_BOOTSTRAP unset, the notifier does nothing.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any

log = logging.getLogger("khata.notify")
QUEUE_MAX = 1000


class Notifier:
    """No-op notifier (Kafka off)."""

    def publish(self, event: dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass


class KafkaNotifier(Notifier):
    def __init__(self, bootstrap: str, topic: str, producer_factory=None):
        self.bootstrap, self.topic = bootstrap, topic
        self._factory = producer_factory or self._kafka_producer
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._producer = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="kafka-notify", daemon=True)
        self._thread.start()

    def _kafka_producer(self):
        from kafka import KafkaProducer

        return KafkaProducer(bootstrap_servers=self.bootstrap, acks=1, linger_ms=5, retries=3,
                             value_serializer=lambda v: json.dumps(v, separators=(",", ":")).encode(),
                             key_serializer=lambda k: k.encode() if k else None)

    def publish(self, event: dict[str, Any]) -> None:
        try:
            self._q.put_nowait(dict(event, ts=event.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S%z")))
        except queue.Full:
            log.warning("notification queue full; event dropped")

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                event = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if self._producer is None:
                    self._producer = self._factory()
                    backoff = 1.0
                # Keyed by shop + customer, so one customer's events stay in order on one partition.
                key = f"{event.get('shop', '')}:{event.get('customer_id', '')}"
                self._producer.send(self.topic, key=key, value=event)
            except Exception as exc:  # broker down or refused: drop this event, retry the connection later
                log.warning("kafka publish failed: %s", type(exc).__name__)
                self._producer = None
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        if self._producer is not None:
            try:
                self._producer.flush(timeout=2)
                self._producer.close(timeout=2)
            except Exception:
                pass


def from_settings(cfg: Any) -> Notifier:
    bootstrap = getattr(cfg, "kafka_bootstrap", "")
    return KafkaNotifier(bootstrap, cfg.kafka_topic) if bootstrap else Notifier()
