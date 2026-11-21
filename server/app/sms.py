"""Reminder SMS through Twilio's Messages API (CONTRACT 3.8), with httpx; no Twilio library.

Only the Kafka consumer (app/notify_worker.py) sends, after its own checks. This module adds the last one: a number
is sent to only when it is in TWILIO_ALLOWED_TO ("*" allows any number; empty allows none). The demo ledgers hold
made-up phone numbers that may belong to real people, so nobody gets a message unless named there.

The auth token, phone numbers and message text are never logged.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

API = "https://api.twilio.com/2010-04-01"
TIMEOUT_S = 10.0


class SmsError(Exception):
    """Twilio refused or could not be reached. `status` is the HTTP status (0: unreachable); `code` Twilio's code."""

    def __init__(self, status: int, code: str = ""):
        super().__init__(f"HTTP {status} {code}".strip())
        self.status, self.code = status, code


def to_e164(phone: str | None, country_code: str = "91") -> str | None:
    """+919876543210 for a stored Indian mobile number (10 digits, or with 0, 91 or +91 before it)."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith(country_code):
        digits = digits[2:]
    return f"+{country_code}{digits}" if re.fullmatch(r"[6-9]\d{9}", digits) else None


def parse_allowed(value: str) -> frozenset[str] | None:
    """The allowed numbers in E.164; None means any number ("*")."""
    items = [v.strip() for v in value.split(",") if v.strip()]
    if "*" in items:
        return None
    return frozenset(n for n in (to_e164(v) for v in items) if n)


class TwilioSms:
    def __init__(self, account_sid: str, auth_token: str, *, messaging_service_sid: str = "", from_number: str = "",
                 allowed_to: str = "", trial_template: str = "", transport: httpx.BaseTransport | None = None,
                 api: str = API):
        if not (messaging_service_sid or from_number):
            raise ValueError("a messaging service SID or a from number is needed")
        self.account_sid = account_sid
        # A trial account refuses custom text (Twilio error 572006): it sends only predefined templates by name.
        self.trial_template = trial_template.strip()
        self._auth = (account_sid, auth_token)
        self.messaging_service_sid = messaging_service_sid
        self.from_number = from_number
        self._allowed = parse_allowed(allowed_to)
        self._url = f"{api.rstrip('/')}/Accounts/{account_sid}/Messages.json"
        self._client = httpx.Client(timeout=TIMEOUT_S, transport=transport)

    def allowed(self, to: str) -> bool:
        return self._allowed is None or to in self._allowed

    def send(self, to: str, body: str) -> str:
        """Send one SMS; returns Twilio's message SID. Raises SmsError, or PermissionError for a number not allowed."""
        if not self.allowed(to):
            raise PermissionError("number not in TWILIO_ALLOWED_TO")
        form = {"To": to, "Body": self.trial_template or body}
        if self.messaging_service_sid:
            form["MessagingServiceSid"] = self.messaging_service_sid
        else:
            form["From"] = self.from_number
        try:
            resp = self._client.post(self._url, data=form, auth=self._auth)
        except httpx.HTTPError as exc:
            raise SmsError(0, type(exc).__name__) from exc
        if resp.status_code >= 300:
            code = ""
            try:
                code = str(resp.json().get("code") or "")
            except ValueError:
                pass
            raise SmsError(resp.status_code, code[:12])
        return str(resp.json().get("sid") or "")

    def close(self) -> None:
        self._client.close()


def from_settings(cfg: Any, transport: httpx.BaseTransport | None = None) -> TwilioSms | None:
    if not getattr(cfg, "sms_enabled", False):
        return None
    return TwilioSms(cfg.twilio_account_sid, cfg.twilio_auth_token,
                     messaging_service_sid=cfg.twilio_messaging_service_sid, from_number=cfg.twilio_from,
                     allowed_to=cfg.twilio_allowed_to, trial_template=getattr(cfg, "twilio_trial_template", ""),
                     transport=transport)
