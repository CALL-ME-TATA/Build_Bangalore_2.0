"""Consume KhataVaani notifications from Kafka: `python -m app.notify_worker` (from server/, with KAFKA_BOOTSTRAP set).

Every event is logged. A `reminder_queued` event is also delivered as an SMS through Twilio when TWILIO_* is set
(CONTRACT 3.8). The event carries ids only, so the worker reads the reminder from the shop's own ledger on this
machine (the same files and ledger key as the server) and sends nothing unless every check passes:
- sending hours (09:00 to 20:00 shop time), the row still pending (not sent before, not removed by an opt-out),
  the customer still opted in, still owing, with a phone number, and no reminder sent to them in the last 24 hours;
- the number is in TWILIO_ALLOWED_TO.
The message is rebuilt from the current balance in the customer's language (the same text as the WhatsApp link).
After Twilio accepts it the row is marked sent, so a repeated event sends nothing. Phone numbers, names and message
text never go into Kafka or the log.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Settings, get_settings
from .sms import SmsError, TwilioSms, from_settings as sms_from_settings, to_e164

log = logging.getLogger("khata.notify_worker")
_ACCOUNT_SHOP = re.compile(r"^[0-9a-f]{24}$")


class ReminderSender:
    """Delivers `reminder_queued` events as SMS. `deliver` returns the outcome word that is logged."""

    def __init__(self, cfg: Settings, sms: TwilioSms, *, clock: Callable[[], datetime] | None = None):
        from .crypto import Crypto, load_key
        from .replies import Replier

        self.cfg = cfg
        self.sms = sms
        self._crypto = Crypto(load_key(cfg.ledger_key, cfg.key_path))
        self._replier = Replier()
        self._ledgers: dict[str, Any] = {}
        self._clock = clock or (lambda: datetime.now(ZoneInfo(cfg.shop_tz)))

    def _ledger(self, shop: Any):
        from .ledger import Ledger

        if shop == "default":
            path = self.cfg.db_path
        elif isinstance(shop, str) and _ACCOUNT_SHOP.match(shop):
            path = self.cfg.data_dir / "users" / shop / "khata.db"
        else:
            return None
        if shop not in self._ledgers:
            if not path.exists():
                return None
            self._ledgers[shop] = Ledger(path, self._crypto)
        return self._ledgers[shop]

    def _message(self, name: str, amount: int, lang: str) -> str:
        return self._replier.with_lang(lang).reminder_message(name, amount)

    def deliver(self, event: dict) -> str:
        rid = event.get("reminder_id")
        if not isinstance(rid, int) or isinstance(rid, bool):
            return "skipped: bad_event"
        led = self._ledger(event.get("shop"))
        if led is None:
            return "skipped: unknown_shop"
        item, reason = led.reminder_to_send(rid, self._clock(), self._message)
        if item is None:
            return f"skipped: {reason}"
        to = to_e164(item["phone"])
        if to is None:
            return "skipped: bad_phone"
        if not self.sms.allowed(to):
            return "skipped: not_allowed"
        try:
            sid = self.sms.send(to, item["message"])
        except SmsError as exc:
            return f"failed: {exc}"
        led.mark_reminder_sent(rid)
        return f"sent: {sid}"

    def close(self) -> None:
        for led in self._ledgers.values():
            led.close()
        self._ledgers.clear()
        self.sms.close()


def handle(event: dict, sender: ReminderSender | None = None) -> None:
    kind = event.get("type")
    if kind == "reminder_queued":
        outcome = sender.deliver(event) if sender is not None else "logged (SMS off)"
        log.info("reminder %s: shop=%s customer=%s amount=%s -> %s", event.get("reminder_id"), event.get("shop"),
                 event.get("customer_id"), event.get("amount"), outcome)
    else:
        log.info("%s: shop=%s customer=%s %s %s", kind, event.get("shop"), event.get("customer_id"),
                 event.get("kind"), event.get("amount"))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines would print the account id
    cfg = get_settings()
    if not cfg.kafka_bootstrap:
        print("KAFKA_BOOTSTRAP is not set", file=sys.stderr)
        return 2
    sms = sms_from_settings(cfg)
    sender = ReminderSender(cfg, sms) if sms is not None else None
    if sender is None:
        log.info("SMS reminders off (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and a sender are not all set)")
    else:
        allowed = "any number" if sms._allowed is None else f"{len(sms._allowed)} allowed number(s)"
        log.info("SMS reminders on through Twilio: %s", allowed)
    from kafka import KafkaConsumer

    consumer = KafkaConsumer(cfg.kafka_topic, bootstrap_servers=cfg.kafka_bootstrap, group_id="khata-notify",
                             auto_offset_reset="earliest", value_deserializer=lambda b: json.loads(b))
    log.info("listening on %s at %s", cfg.kafka_topic, cfg.kafka_bootstrap)
    try:
        for msg in consumer:
            try:
                handle(msg.value, sender)
            except Exception as exc:  # one bad event must not stop the worker
                log.warning("event not handled: %s", type(exc).__name__)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        if sender is not None:
            sender.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
