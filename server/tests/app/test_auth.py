"""Google sign-in (app/auth.py): only allowed, verified emails reach the khata; cookies cannot be forged."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings
from app.main import create_app

from .conftest import TEST_KEY


def make(tmp_path, **kw):
    s = Settings(gnani_api_key="test-key", gnani_base_url="http://127.0.0.1:9", ledger_key=TEST_KEY,
                 ledger_db=str(tmp_path / "data" / "khata.db"), tts_prewarm=False, **kw)
    return TestClient(create_app(s, web_dir=tmp_path), base_url="http://127.0.0.1:8000")


ON = {"google_client_id": "cid.apps.googleusercontent.com", "google_client_secret": "shh",
      "allowed_emails": "owner@gmail.com, Partner@Gmail.com"}


def google_says(monkeypatch, **info):
    async def fake(code, redirect_uri, client_id, client_secret):
        assert code == "good-code" and redirect_uri == "http://127.0.0.1:8000/api/auth/google/callback"
        return {"email_verified": True, **info}
    monkeypatch.setattr(auth, "exchange", fake)


def sign_in(c):
    login = c.get("/api/auth/google/login", follow_redirects=False)
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    return c.get(f"/api/auth/google/callback?code=good-code&state={state}", follow_redirects=False)


def test_off_by_default_and_the_khata_stays_open(tmp_path):
    with make(tmp_path) as c:
        assert c.get("/api/auth/me").json() == {"enabled": False, "user": None}
        assert c.get("/api/customers").status_code == 200


def test_on_the_khata_needs_a_sign_in(tmp_path):
    with make(tmp_path, **ON) as c:
        assert c.get("/api/auth/me").json() == {"enabled": True, "user": None}
        assert c.get("/api/customers").status_code == 401
        assert c.get("/api/health").status_code == 200  # public


def test_login_redirects_to_google_with_state(tmp_path):
    with make(tmp_path, **ON) as c:
        r = c.get("/api/auth/google/login", follow_redirects=False)
        assert r.status_code == 302
        q = parse_qs(urlsplit(r.headers["location"]).query)
        assert r.headers["location"].startswith(auth.AUTH_URL)
        assert q["client_id"] == [ON["google_client_id"]] and q["scope"] == ["openid email profile"]
        assert q["redirect_uri"] == ["http://127.0.0.1:8000/api/auth/google/callback"]
        assert auth.STATE_COOKIE in r.cookies


def test_allowed_email_signs_in_and_can_sign_out(tmp_path, monkeypatch):
    google_says(monkeypatch, email="partner@gmail.com", name="Meena Rao")
    with make(tmp_path, **ON) as c:
        r = sign_in(c)
        assert r.status_code == 302 and r.headers["location"] == "/#/"
        assert c.get("/api/auth/me").json()["user"]["email"] == "partner@gmail.com"
        assert c.get("/api/customers").status_code == 200
        c.post("/api/auth/logout")
        assert c.get("/api/customers").status_code == 401


@pytest.mark.parametrize("info", [{"email": "stranger@gmail.com"},
                                  {"email": "owner@gmail.com", "email_verified": False}])
def test_other_or_unverified_emails_are_turned_away(tmp_path, monkeypatch, info):
    google_says(monkeypatch, **info)
    with make(tmp_path, **ON) as c:
        r = sign_in(c)
        assert r.headers["location"] == "/#/welcome?login=not_allowed"
        assert c.get("/api/customers").status_code == 401


def test_empty_allow_list_lets_nobody_in(tmp_path, monkeypatch):
    google_says(monkeypatch, email="owner@gmail.com")
    with make(tmp_path, **{**ON, "allowed_emails": ""}) as c:
        assert sign_in(c).headers["location"] == "/#/welcome?login=not_allowed"


def test_star_lets_any_verified_account_in_each_with_its_own_khata(tmp_path, monkeypatch):
    assert auth.allowed("Anyone@Example.com", "*") and auth.allowed("x@gmail.com", "owner@gmail.com, *")
    assert not auth.allowed("", "*")
    google_says(monkeypatch, email="stranger@gmail.com")
    with make(tmp_path, **{**ON, "allowed_emails": "*"}) as c:
        assert sign_in(c).headers["location"] == "/#/"
        assert c.get("/api/customers").json()["customers"] == []  # a fresh khata of their own
        assert c.app.state.tenant("stranger@gmail.com").ledger.path.parent.parent.name == "users"


def test_star_still_turns_away_unverified_emails(tmp_path, monkeypatch):
    google_says(monkeypatch, email="stranger@gmail.com", email_verified=False)
    with make(tmp_path, **{**ON, "allowed_emails": "*"}) as c:
        assert sign_in(c).headers["location"] == "/#/welcome?login=not_allowed"


def test_wrong_state_is_refused(tmp_path, monkeypatch):
    google_says(monkeypatch, email="owner@gmail.com")
    with make(tmp_path, **ON) as c:
        c.get("/api/auth/google/login", follow_redirects=False)
        r = c.get("/api/auth/google/callback?code=good-code&state=forged", follow_redirects=False)
        assert r.headers["location"] == "/#/welcome?login=failed"
        assert c.get("/api/customers").status_code == 401


def test_forged_or_expired_cookie_is_refused(tmp_path):
    secret = b"k" * 32
    good = auth.sign({"email": "owner@gmail.com", "exp": 2e9}, secret)
    assert auth.verify(good, secret)["email"] == "owner@gmail.com"
    body, mac = good.split(".")
    assert auth.verify(body + "." + mac[:-2] + "AA", secret) is None
    assert auth.verify(good, b"x" * 32) is None
    assert auth.verify(auth.sign({"email": "a", "exp": 1}, secret), secret) is None
    with make(tmp_path, **ON) as c:
        c.cookies.set(auth.SESSION_COOKIE, good)  # signed with another key
        assert c.get("/api/customers").status_code == 401


def test_websocket_needs_a_sign_in(tmp_path):
    with make(tmp_path, **ON) as c:
        with pytest.raises(Exception):
            with c.websocket_connect("/ws/session") as ws:
                ws.receive_json()


# ---- one khata per Google account -------------------------------------------------------------------------------
def _signed_in_client(tmp_path, monkeypatch, email):
    google_says(monkeypatch, email=email)
    c = make(tmp_path, **ON)
    c.__enter__()
    sign_in(c)
    return c


def test_each_account_has_its_own_khata(tmp_path, monkeypatch):
    from datetime import datetime
    owner = _signed_in_client(tmp_path, monkeypatch, "owner@gmail.com")
    try:
        app = owner.app
        now = datetime.now().astimezone()
        mine = app.state.tenant("owner@gmail.com").ledger
        c = mine.create_customer("ramesh", tags=[], now=now)
        mine.apply({"action": "append", "events": [{"kind": "credit", "customer": "ramesh", "customer_id": c["id"],
                                                     "amount": 340, "date": now.date().isoformat()}]},
                   now=now, session_id="s1")
        names = [x["display"] for x in owner.get("/api/customers").json()["customers"]]
        assert names == ["Ramesh"]

        # The partner signs in on another phone (same server): an empty khata of their own.
        google_says(monkeypatch, email="partner@gmail.com")
        partner = TestClient(app, base_url="http://127.0.0.1:8000")
        sign_in(partner)
        assert partner.get("/api/customers").json()["customers"] == []
        assert partner.get("/api/ledger").json()["entries"] == []
        assert owner.get("/api/ledger").json()["entries"][0]["amount"] == 340

        # Separate files, named by a hash (no email on disk), and the one-shop ledger is untouched.
        theirs = app.state.tenant("partner@gmail.com").ledger
        assert mine.path != theirs.path and mine.path.parent.parent.name == "users"
        assert "owner" not in str(mine.path) and "@" not in str(mine.path)
        assert app.state.tenant("OWNER@gmail.com ").ledger is mine  # same account whatever the case
    finally:
        owner.__exit__(None, None, None)


def test_signed_in_voice_socket_opens_on_the_accounts_khata(tmp_path, monkeypatch):
    owner = _signed_in_client(tmp_path, monkeypatch, "owner@gmail.com")
    try:
        # The test client does not send its cookie jar on a socket; a browser sends the session cookie itself.
        cookie = f"{auth.SESSION_COOKIE}={owner.cookies.get(auth.SESSION_COOKIE)}"
        with owner.websocket_connect("/ws/session", headers={"cookie": cookie}) as ws:
            ws.send_json({"type": "hello", "lang": "hi"})
            assert ws.receive_json()["type"]  # accepted (not closed with 1008)
    finally:
        owner.__exit__(None, None, None)
