"""CONTRACT 3.7: the copy of every shop's ledger in Supabase, against a fake REST API (no network)."""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.cloud_sync import DEFAULT_SHOP, CloudSync, project_ref, shop_ledgers
from app.config import Settings
from app.crypto import Crypto
from app.ledger import Ledger

from .conftest import TEST_KEY

URL = "https://abcdefgh.supabase.co"
SECRET = "sb_secret_test_key_never_logged"
KEYS = {"khata_customers": ("shop", "id"), "khata_events": ("shop", "id"), "khata_utterances": ("shop", "id"),
        "khata_consent_log": ("shop", "id"), "khata_confusions": ("shop", "heard", "meant")}


class FakeSupabase:
    """Enough of PostgREST (select max, upsert) and of the Management API (database/query) for these tests."""

    def __init__(self, tables_exist: bool = True):
        self.tables: dict[str, dict[tuple, dict]] = {t: {} for t in KEYS} if tables_exist else {}
        self.requests: list[httpx.Request] = []
        self.created_with: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        u = urlsplit(str(req.url))
        if u.hostname == "api.supabase.com":
            assert u.path == "/v1/projects/abcdefgh/database/query"
            assert req.headers["Authorization"] == "Bearer sbp_access"
            self.created_with.append(json.loads(req.content)["query"])
            self.tables = {t: {} for t in KEYS}
            return httpx.Response(201, json=[])
        table = u.path.removeprefix("/rest/v1/")
        if table not in self.tables:
            return httpx.Response(404, json={"code": "PGRST205", "message": f"Could not find the table '{table}'"})
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if req.method == "GET":
            col = q["select"]
            shop = q["shop"].removeprefix("eq.")
            vals = [r[col] for r in self.tables[table].values() if r["shop"] == shop]
            return httpx.Response(200, json=[{col: max(vals)}] if vals else [])
        assert req.method == "POST" and q["on_conflict"] == ",".join(KEYS[table])
        assert "resolution=merge-duplicates" in req.headers["Prefer"]
        for row in json.loads(req.content):
            key = tuple(row[k] for k in KEYS[table])
            self.tables[table][key] = {**self.tables[table].get(key, {}), **row}
        return httpx.Response(201)

    def rows(self, table: str, shop: str = DEFAULT_SHOP) -> list[dict]:
        return sorted((r for r in self.tables[table].values() if r["shop"] == shop), key=lambda r: str(r.get("id")))


def make_ledger(path) -> Ledger:
    return Ledger(path, Crypto(base64.b64decode(TEST_KEY)))


def entry(led: Ledger, name: str, amount: int, kind: str = "credit", sid: str = "s1") -> None:
    now = datetime.now().astimezone()
    led.apply({"action": "append", "events": [{"kind": kind, "customer": name, "amount": amount,
                                                "date": now.date().isoformat()}]}, now=now, session_id=sid)


@pytest.fixture
def shop(tmp_path):
    led = make_ledger(tmp_path / "data" / "khata.db")
    entry(led, "ramesh", 340)
    entry(led, "sunita", 150, "payment")
    led.record_utterance("u1", "s1", datetime.now().astimezone(), transcript="Ramesh ka 340 udhaar", status="ok",
                         reply_text="likh diya")
    cid = led.find_customer(key="ramesh")["id"]
    led.set_reminder_opt_in(cid, True, "9876543210", now=datetime.now().astimezone())
    yield led, tmp_path / "data"
    led.close()


def syncer(fake: FakeSupabase, **kw) -> CloudSync:
    clock = lambda: datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc)  # noqa: E731
    return CloudSync(URL, kw.pop("key", SECRET), transport=httpx.MockTransport(fake.handler), clock=clock, **kw)


def test_first_push_copies_every_table_encrypted(shop):
    led, data = shop
    fake = FakeSupabase()
    result = syncer(fake).sync_all(led.path, data)
    assert result.ok and result.rows[DEFAULT_SHOP]["events"] == 2 and result.rows[DEFAULT_SHOP]["customers"] == 2
    events = fake.rows("khata_events")
    assert [(e["kind"], e["amount_paise"]) for e in events] == [("credit", 34000), ("payment", 15000)]
    assert len(fake.rows("khata_utterances")) == 1 and len(fake.rows("khata_consent_log")) == 1
    # Names, phone numbers and transcripts never leave the machine in clear text.
    sent = b"".join(r.content for r in fake.requests if r.method == "POST").lower()
    for secret_text in (b"ramesh", b"sunita", b"9876543210", b"udhaar", b"likh diya"):
        assert secret_text not in sent
    # The encrypted blobs are the ledger's own bytes, so the shop can restore them with its key.
    cust = next(c for c in fake.rows("khata_customers") if c["reminders_opt_in"])
    blob = base64.b64decode(cust["ident"])
    assert led.crypto.decrypt(blob, f"customers:{cust['id']}")["key"] == "ramesh"


def test_next_push_sends_only_what_is_new_and_customers_again(shop):
    led, data = shop
    fake = FakeSupabase()
    s = syncer(fake)
    s.sync_all(led.path, data)
    entry(led, "ramesh", 60)
    cid = led.find_customer(key="ramesh")["id"]
    led.update_customer(cid, display="Ramesh Kumar")  # a change in place
    second = s.sync_all(led.path, data).rows[DEFAULT_SHOP]
    assert second["events"] == 1 and second["consent_log"] == 0 and second["customers"] == 2
    assert second["utterances"] == 1  # the row at the last copied time is sent again (an upsert, no duplicate)
    assert len(fake.rows("khata_events")) == 3 and len(fake.rows("khata_utterances")) == 1
    cust = fake.tables["khata_customers"][(DEFAULT_SHOP, cid)]
    assert led.crypto.decrypt(base64.b64decode(cust["ident"]), f"customers:{cid}")["key"] == "ramesh kumar"


def test_each_signed_in_account_is_its_own_shop(shop, tmp_path):
    led, data = shop
    other = make_ledger(data / "users" / "a1b2c3d4e5f6a1b2c3d4e5f6" / "khata.db")
    entry(other, "mohan", 999)
    other.close()
    fake = FakeSupabase()
    result = syncer(fake).sync_all(led.path, data)
    assert set(result.rows) == {DEFAULT_SHOP, "a1b2c3d4e5f6a1b2c3d4e5f6"}
    assert [e["amount_paise"] for e in fake.rows("khata_events", "a1b2c3d4e5f6a1b2c3d4e5f6")] == [99900]
    assert len(fake.rows("khata_events")) == 2
    assert [s for s, _ in shop_ledgers(led.path, data)] == [DEFAULT_SHOP, "a1b2c3d4e5f6a1b2c3d4e5f6"]


def test_missing_tables_are_created_with_an_access_token(shop):
    led, data = shop
    fake = FakeSupabase(tables_exist=False)
    result = syncer(fake, access_token="sbp_access").sync_all(led.path, data)
    assert result.ok and len(fake.created_with) == 1
    assert "create table if not exists public.khata_events" in fake.created_with[0]
    assert "enable row level security" in fake.created_with[0]
    assert len(fake.rows("khata_events")) == 2


def test_missing_tables_without_a_token_say_what_to_run(shop, caplog):
    led, data = shop
    fake = FakeSupabase(tables_exist=False)
    with caplog.at_level(logging.WARNING, logger="khata.cloud"):
        result = syncer(fake).sync_all(led.path, data)
    assert not result.ok and "PGRST205" in result.errors[DEFAULT_SHOP]
    assert "supabase_schema.sql" in caplog.text and SECRET not in caplog.text


def test_a_secret_key_goes_in_apikey_only_and_a_legacy_key_also_as_bearer(shop):
    led, data = shop
    fake = FakeSupabase()
    syncer(fake).sync_all(led.path, data)
    assert all(r.headers["apikey"] == SECRET and "Authorization" not in r.headers for r in fake.requests)
    fake = FakeSupabase()
    syncer(fake, key="eyJlegacy.jwt.key").sync_all(led.path, data)
    assert all(r.headers["Authorization"] == "Bearer eyJlegacy.jwt.key" for r in fake.requests)


def test_network_failure_is_logged_never_raised(shop, caplog):
    led, data = shop

    def down(req):
        raise httpx.ConnectError("no route")

    s = CloudSync(URL, SECRET, transport=httpx.MockTransport(down))
    with caplog.at_level(logging.WARNING, logger="khata.cloud"):
        result = s.sync_all(led.path, data)
    assert not result.ok and result.errors[DEFAULT_SHOP] == "ConnectError"
    assert SECRET not in caplog.text


def test_refused_key_is_reported_with_status_and_code(shop):
    led, data = shop
    refuse = httpx.MockTransport(lambda req: httpx.Response(401, json={"code": "42501", "message": "denied"}))
    result = CloudSync(URL, SECRET, transport=refuse).sync_all(led.path, data)
    assert result.errors[DEFAULT_SHOP] == "HTTP 401 42501"


def test_settings_and_project_ref():
    s = Settings.from_env({"SUPABASE_URL": URL + "/", "SUPABASE_SERVICE_ROLE_KEY": "eyJx", "CLOUD_SYNC_INTERVAL_S": "5"})
    assert s.cloud_sync_enabled and s.supabase_url == URL and s.supabase_secret_key == "eyJx"
    assert s.cloud_sync_interval_s == 30  # never more often than every 30 s
    assert "eyJx" not in repr(s)
    assert not Settings.from_env({"SUPABASE_URL": URL}).cloud_sync_enabled
    assert Settings.from_env({}).cloud_sync_interval_s == 300
    assert project_ref(URL) == "abcdefgh" and project_ref("https://db.example.com") is None


def test_the_app_starts_the_copy_and_stops_it_cleanly(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main as main_mod

    calls = []

    def fake_sync_all(self, default_db, data_dir):
        calls.append(default_db)

    monkeypatch.setattr(main_mod.CloudSync, "sync_all", fake_sync_all)
    s = Settings(gnani_api_key="k", gnani_base_url="http://127.0.0.1:9", ledger_key=TEST_KEY,
                 ledger_db=str(tmp_path / "data" / "khata.db"), supabase_url=URL, supabase_secret_key=SECRET)
    with TestClient(main_mod.create_app(s, web_dir=tmp_path)) as c:
        assert c.get("/api/health").status_code == 200
        for _ in range(50):
            if calls:
                break
            import time
            time.sleep(0.02)
    assert calls and calls[0] == s.db_path
