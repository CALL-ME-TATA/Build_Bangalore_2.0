"""CONTRACT 3.8: reminder SMS through Twilio, sent by the Kafka consumer after its checks (no network, no Kafka)."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import Settings
from app.crypto import Crypto
from app.ledger import Ledger
from app.notify_worker import ReminderSender, handle
from app.sms import SmsError, TwilioSms, parse_allowed, to_e164

from .conftest import TEST_KEY

IST = ZoneInfo("Asia/Kolkata")
ELEVEN = datetime(2026, 11, 22, 11, 0, tzinfo=IST)
OWNER = "+919812345678"
TOKEN = "twilio-token-never-logged"


class FakeTwilio:
    def __init__(self, status: int = 201):
        self.status = status
        self.sent: list[dict] = []
        self.auth: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/2010-04-01/Accounts/ACtest/Messages.json" and req.method == "POST"
        self.auth.append(req.headers["Authorization"])
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        if self.status >= 300:
            return httpx.Response(self.status, json={"code": 21608, "message": "unverified number"})
        self.sent.append(form)
        return httpx.Response(201, json={"sid": f"SM{len(self.sent):032d}", "status": "queued"})


def twilio(fake: FakeTwilio, allowed: str = OWNER) -> TwilioSms:
    return TwilioSms("ACtest", TOKEN, messaging_service_sid="MGtest", allowed_to=allowed,
                     transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def shop(tmp_path):
    """A one-shop ledger with Ramesh (opted in, owes ₹340, phone = the allowed number) and Sita (no opt-in)."""
    cfg = Settings(ledger_key=TEST_KEY, ledger_db=str(tmp_path / "data" / "khata.db"))
    led = Ledger(cfg.db_path, Crypto(base64.b64decode(TEST_KEY)))
    for name, amount in (("ramesh", 340), ("sita", 200)):
        led.apply({"action": "append", "events": [{"kind": "credit", "customer": name, "amount": amount,
                                                    "date": "2026-11-22"}]}, now=ELEVEN)
    ramesh = led.find_customer(key="ramesh")["id"]
    led.set_reminder_opt_in(ramesh, True, "98123 45678", now=ELEVEN)
    yield cfg, led, ramesh
    led.close()


def sender(cfg, fake, allowed=OWNER, at=ELEVEN) -> ReminderSender:
    return ReminderSender(cfg, twilio(fake, allowed), clock=lambda: at)


def queued(led, cid, at=ELEVEN) -> dict:
    rid = led.queue_reminder(cid, at)
    return {"type": "reminder_queued", "shop": "default", "reminder_id": rid, "customer_id": cid, "amount": 340}


# ---- numbers ------------------------------------------------------------------------------------------------------
def test_phone_numbers_become_e164():
    assert to_e164("98123 45678") == to_e164("+91 98123-45678") == to_e164("098123 45678") == "+919812345678"
    assert to_e164("12345") is None and to_e164(None) is None and to_e164("5812345678") is None


def test_allow_list_empty_means_nobody_star_means_anyone():
    assert parse_allowed("") == frozenset()
    assert parse_allowed("*") is None
    assert parse_allowed("+91 98123 45678, 9876543210") == {"+919812345678", "+919876543210"}


# ---- Twilio call --------------------------------------------------------------------------------------------------
def test_send_posts_the_form_twilio_expects():
    fake = FakeTwilio()
    sid = twilio(fake).send(OWNER, "Namaste Ramesh ji")
    assert sid.startswith("SM") and fake.sent == [{"To": OWNER, "MessagingServiceSid": "MGtest",
                                                   "Body": "Namaste Ramesh ji"}]
    assert fake.auth[0] == "Basic " + base64.b64encode(f"ACtest:{TOKEN}".encode()).decode()


def test_a_number_not_allowed_is_never_sent_to():
    fake = FakeTwilio()
    with pytest.raises(PermissionError):
        twilio(fake, allowed="").send(OWNER, "x")
    assert fake.sent == []


def test_twilio_refusal_carries_status_and_code():
    with pytest.raises(SmsError) as err:
        twilio(FakeTwilio(status=400)).send(OWNER, "x")
    assert (err.value.status, err.value.code) == (400, "21608")


# ---- the consumer's delivery --------------------------------------------------------------------------------------
def test_a_queued_reminder_is_sent_once_in_the_customers_words(shop):
    cfg, led, ramesh = shop
    fake = FakeTwilio()
    s = sender(cfg, fake)
    event = queued(led, ramesh)
    assert s.deliver(event).startswith("sent: SM")
    assert len(fake.sent) == 1 and fake.sent[0]["To"] == OWNER
    assert fake.sent[0]["Body"] == "Namaste Ramesh ji, aapke khate mein ₹340 baaki hain. Suvidha se bhej dijiye. Dhanyavaad."
    assert s.deliver(event) == "skipped: already_sent"  # Kafka may deliver an event twice
    assert len(fake.sent) == 1
    s.close()


def test_no_second_sms_to_the_same_customer_within_a_day(shop):
    cfg, led, ramesh = shop
    fake = FakeTwilio()
    s = sender(cfg, fake)
    s.deliver(queued(led, ramesh))
    again = queued(led, ramesh, ELEVEN + timedelta(hours=3))
    later = ReminderSender(cfg, twilio(fake), clock=lambda: ELEVEN + timedelta(hours=3))
    assert later.deliver(again) == "skipped: sent_recently" and len(fake.sent) == 1
    s.close(), later.close()


@pytest.mark.parametrize("case,expected", [
    ("not_allowed", "skipped: not_allowed"),
    ("quiet", "skipped: quiet_hours"),
    ("opted_out", "skipped: gone"),
    ("no_phone", "skipped: no_phone"),
    ("paid", "skipped: nothing_due"),
    ("bad_shop", "skipped: unknown_shop"),
])
def test_nothing_is_sent_when_a_check_fails(shop, case, expected):
    cfg, led, ramesh = shop
    fake = FakeTwilio()
    event = queued(led, ramesh)
    at = ELEVEN
    allowed = OWNER
    if case == "not_allowed":
        allowed = ""
    elif case == "quiet":
        at = ELEVEN.replace(hour=21)
    elif case == "opted_out":
        led.set_reminder_opt_in(ramesh, False, now=ELEVEN)
    elif case == "no_phone":
        led.set_reminder_opt_in(ramesh, True, "", now=ELEVEN)
    elif case == "paid":
        led.apply({"action": "append", "events": [{"kind": "payment", "customer": "ramesh", "customer_id": ramesh,
                                                    "amount": 340, "date": "2026-11-22"}]}, now=ELEVEN)
    elif case == "bad_shop":
        event["shop"] = "../../etc"
    s = sender(cfg, fake, allowed=allowed, at=at)
    assert s.deliver(event) == expected
    assert fake.sent == []
    s.close()


def test_a_failed_send_leaves_the_reminder_pending_for_a_later_press(shop, caplog):
    cfg, led, ramesh = shop
    event = queued(led, ramesh)
    s = ReminderSender(cfg, twilio(FakeTwilio(status=400)), clock=lambda: ELEVEN)
    with caplog.at_level("INFO", logger="khata.notify_worker"):
        handle(event, s)
    assert "failed: HTTP 400 21608" in caplog.text
    assert TOKEN not in caplog.text and "98123" not in caplog.text and "Ramesh" not in caplog.text
    ok = sender(cfg, FakeTwilio())
    assert ok.deliver(event).startswith("sent:")
    s.close(), ok.close()


def test_settings():
    s = Settings.from_env({"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_MESSAGING_SERVICE_SID": "MG1"})
    assert s.sms_enabled and "'t'" not in repr(s)
    assert not Settings.from_env({"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t"}).sms_enabled
    assert Settings.from_env({"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_FROM": "+1555"}).sms_enabled


# ---- the button queues one customer only ----------------------------------------------------------------------------
def test_the_button_queues_a_reminder_for_one_customer_only(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.notify import Notifier

    class Capture(Notifier):
        def __init__(self):
            self.events = []

        def publish(self, event):
            self.events.append(event)

    s = Settings(gnani_api_key="k", gnani_base_url="http://127.0.0.1:9", ledger_key=TEST_KEY,
                 ledger_db=str(tmp_path / "data" / "khata.db"), tts_prewarm=False)
    app = create_app(s, web_dir=tmp_path, now=lambda: ELEVEN)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        led = app.state.ctx.ledger
        cap = app.state.ctx.pipeline.notifier = Capture()
        ids = {}
        for name in ("ramesh", "sita", "mohan"):
            led.apply({"action": "append", "events": [{"kind": "credit", "customer": name, "amount": 100,
                                                        "date": "2026-11-22"}]}, now=ELEVEN)
            ids[name] = led.find_customer(key=name)["id"]
            led.set_reminder_opt_in(ids[name], True, "9812345678", now=ELEVEN)
        r = c.post(f"/api/customers/{ids['sita']}/remind").json()
        assert r["queued"] and r["quiet_hours"] is False and r["sms"] is False
        assert [e["customer_id"] for e in cap.events] == [ids["sita"]]  # nobody else is reminded
        assert c.post("/api/customers/c_nope/remind").status_code == 404
