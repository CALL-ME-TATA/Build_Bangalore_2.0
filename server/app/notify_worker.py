"""Consume KhataVaani notifications from Kafka: `python -m app.notify_worker` (from server/, with KAFKA_BOOTSTRAP set).

Each event is logged. `handle` is where a WhatsApp Business or SMS sender plugs in; reminders must still respect
opt-in and sending hours, which the server already checked before publishing.
"""
from __future__ import annotations

import json
import logging
import sys

from .config import get_settings

log = logging.getLogger("khata.notify_worker")


def handle(event: dict) -> None:
    kind = event.get("type")
    if kind == "reminder_queued":
        log.info("reminder ready: shop=%s customer=%s amount=%s", event.get("shop"), event.get("customer_id"),
                 event.get("amount"))
    else:
        log.info("%s: shop=%s customer=%s %s %s", kind, event.get("shop"), event.get("customer_id"),
                 event.get("kind"), event.get("amount"))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = get_settings()
    if not cfg.kafka_bootstrap:
        print("KAFKA_BOOTSTRAP is not set", file=sys.stderr)
        return 2
    from kafka import KafkaConsumer

    consumer = KafkaConsumer(cfg.kafka_topic, bootstrap_servers=cfg.kafka_bootstrap, group_id="khata-notify",
                             auto_offset_reset="earliest", value_deserializer=lambda b: json.loads(b))
    log.info("listening on %s at %s", cfg.kafka_topic, cfg.kafka_bootstrap)
    try:
        for msg in consumer:
            handle(msg.value)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
