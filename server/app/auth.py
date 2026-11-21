"""Google sign-in (OAuth 2.0 authorization code flow, done on the server).

Switched on when GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set. Only emails in ALLOWED_EMAILS get in: the
ledger is one shop's money, so an empty list lets nobody in rather than everybody.

The signed-in user is kept in an HttpOnly cookie signed with HMAC-SHA256 (key in data/session.key, created on
first run, or SESSION_SECRET). No token from Google is stored: the code is exchanged once for the verified email.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SESSION_COOKIE = "kv_session"
STATE_COOKIE = "kv_oauth_state"
SESSION_TTL_S = 7 * 24 * 3600
STATE_TTL_S = 10 * 60
CALLBACK_PATH = "/api/auth/google/callback"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_secret(configured: str, path: Path) -> bytes:
    """SESSION_SECRET if set, else a random key kept in `path` (so sign-ins survive a restart)."""
    if configured:
        return configured.encode()
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    path.write_bytes(key)
    return key


def sign(payload: dict, secret: bytes) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def verify(token: str | None, secret: bytes, now: float | None = None) -> dict | None:
    """The payload of a cookie signed by `sign`, or None when it is missing, tampered with or expired."""
    if not token or token.count(".") != 1:
        return None
    body, mac = token.split(".")
    want = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, want):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < (now or time.time()):
        return None
    return payload


def allowed(email: str, allowed_emails: str) -> bool:
    wanted = {e.strip().lower() for e in allowed_emails.split(",") if e.strip()}
    return email.strip().lower() in wanted


def login_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "prompt": "select_account"})


def new_state() -> str:
    return secrets.token_urlsafe(24)


async def exchange(code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict[str, Any]:
    """Swap the authorization code for the user's verified Google profile: {email, email_verified, name, picture}."""
    async with httpx.AsyncClient(timeout=10) as client:
        tok = await client.post(TOKEN_URL, data={
            "code": code, "client_id": client_id, "client_secret": client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        tok.raise_for_status()
        access = tok.json()["access_token"]
        info = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
        info.raise_for_status()
        return info.json()
