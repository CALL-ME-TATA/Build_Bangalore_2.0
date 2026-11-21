"""CONTRACT 3.6: hand edits on the khata screens (entries, customer details) and the voice-session safety rule."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pipeline import SessionState, default_parse

from .conftest import TEST_KEY

GOOGLE = {"google_client_id": "cid.apps.googleusercontent.com", "google_client_secret": "shh",
          "allowed_emails": "owner@gmail.com"}


def make_settings(tmp_path, **kw) -> Settings:
    return Settings(gnani_api_key="test-key", gnani_base_url="http://127.0.0.1:9", ledger_key=TEST_KEY,
                    ledger_db=str(tmp_path / "data" / "khata.db"), tts_prewarm=False, **kw)


@pytest.fixture
def client(tmp_path):
    app = create_app(make_settings(tmp_path), parse=default_parse, web_dir=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        c.ctx = app.state.ctx
        yield c


def say(client, state, text):
    return client.ctx.pipeline.run_turn(state, text)


def seed(client, *texts):
    """Saves the spoken entries in one session and returns that session's state."""
    state = SessionState(session_id="voice001")
    state.disclosed = True
    for t in texts:
        r = say(client, state, t)
        if r.reason == "new_customer":
            r = say(client, state, "haan")
        assert r.status == "ok", (t, r.reason)
    return state


def customers(client):
    return {c["display"]: c for c in client.get("/api/customers").json()["customers"]}


def ledger_entries(client, **q):
    return client.get("/api/ledger", params={"limit": 100, **q}).json()["entries"]


def rows(client, table="events"):
    return client.ctx.ledger.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def today(client):
    return client.ctx.pipeline.now().date()


def err(resp, status, code):
    assert resp.status_code == status, resp.text
    assert resp.json()["detail"] == code


# ---- entries ---------------------------------------------------------------------------------------------------
def test_add_entry_shape_and_defaults(client):
    seed(client, "Ramesh ka 340 udhaar")
    cid = customers(client)["Ramesh"]["id"]
    r = client.post("/api/entries", json={"customer_id": cid, "kind": "payment", "amount": 100})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and len(body["entries"]) == 1
    e = body["entries"][0]
    assert e["kind"] == "payment" and e["amount"] == 100 and e["date"] == today(client).isoformat()
    assert e["reversed"] is False and e["replaces"] is None and e["customer"]["id"] == cid
    assert body["balances"] == [{"customer_id": cid, "display": "Ramesh", "balance": 240}]


def test_add_entry_on_an_earlier_date(client):
    cid = client.ctx.ledger.create_customer("asha")["id"]
    day = (today(client) - timedelta(days=3)).isoformat()
    r = client.post("/api/entries", json={"customer_id": cid, "kind": "credit", "amount": 50, "date": day})
    assert r.json()["entries"][0]["date"] == day


def test_events_written_here_have_portal_session_and_no_utterance(client):
    cid = client.ctx.ledger.create_customer("asha")["id"]
    before = rows(client, "utterances")
    client.post("/api/entries", json={"customer_id": cid, "kind": "credit", "amount": 50})
    row = client.ctx.ledger.conn.execute("SELECT * FROM events").fetchone()
    assert row["session_id"] == "portal" and row["utterance_id"] is None and row["trace_id"]
    assert rows(client, "utterances") == before
    assert client.get("/api/metrics").json()["turns"] == 0 if "turns" in client.get("/api/metrics").json() else True


def test_writeoff_is_stored_as_a_payment_adjustment(client):
    seed(client, "Ramesh ka 340 udhaar")
    cid = customers(client)["Ramesh"]["id"]
    r = client.post("/api/entries", json={"customer_id": cid, "kind": "writeoff", "amount": 340})
    assert r.json()["entries"][0]["kind"] == "writeoff" and r.json()["balances"][0]["balance"] == 0
    row = client.ctx.ledger.conn.execute("SELECT kind, adjustment FROM events ORDER BY id DESC").fetchone()
    assert (row["kind"], row["adjustment"]) == ("payment", "writeoff")


def test_amend_is_append_only_and_keeps_history(client):
    seed(client, "Ramesh ka 340 udhaar")
    old = ledger_entries(client)[0]
    n = rows(client)
    snapshot = [tuple(r) for r in client.ctx.ledger.conn.execute("SELECT * FROM events ORDER BY id")]
    r = client.post(f"/api/entries/{old['id']}/amend", json={"amount": 430})
    assert r.status_code == 200
    body = r.json()
    reversed_e, saved = body["entries"]
    assert reversed_e["id"] == old["id"] and reversed_e["reversed"] is True
    assert saved["amount"] == 430 and saved["kind"] == "credit" and saved["replaces"] == old["id"]
    assert saved["date"] == old["date"] and saved["reversed"] is False
    assert body["balances"][0]["balance"] == 430
    assert rows(client) == n + 2  # a reversal and the new event
    now_rows = [tuple(r) for r in client.ctx.ledger.conn.execute("SELECT * FROM events ORDER BY id")]
    assert now_rows[:n] == snapshot  # nothing already written changed
    shown = {e["id"]: e for e in ledger_entries(client)}
    assert shown[old["id"]]["reversed"] is True and shown[saved["id"]]["replaces"] == old["id"]


def test_amend_changes_only_the_given_fields(client):
    seed(client, "Ramesh ka 340 udhaar")
    old = ledger_entries(client)[0]
    day = (today(client) - timedelta(days=2)).isoformat()
    saved = client.post(f"/api/entries/{old['id']}/amend", json={"kind": "payment", "date": day}).json()["entries"][1]
    assert (saved["kind"], saved["amount"], saved["date"]) == ("payment", 340, day)


def test_amend_to_another_customer_moves_the_balance(client):
    seed(client, "Ramesh ka 340 udhaar", "Sita ka 200 udhaar")
    c = customers(client)
    entry = next(e for e in ledger_entries(client) if e["customer"]["id"] == c["Ramesh"]["id"])
    body = client.post(f"/api/entries/{entry['id']}/amend", json={"customer_id": c["Sita"]["id"]}).json()
    assert {b["display"]: b["balance"] for b in body["balances"]} == {"Ramesh": 0, "Sita": 540}
    assert customers(client)["Ramesh"]["balance"] == 0 and customers(client)["Sita"]["balance"] == 540


def test_portal_amend_counts_no_confusion(client):
    seed(client, "Ramesh ka 340 udhaar")
    entry = ledger_entries(client)[0]
    before = rows(client, "confusions")
    client.post(f"/api/entries/{entry['id']}/amend", json={"amount": 430})
    assert rows(client, "confusions") == before == 0


def test_remove_reverses_one_entry(client):
    seed(client, "Ramesh ka 340 udhaar")
    entry = ledger_entries(client)[0]
    n = rows(client)
    body = client.post(f"/api/entries/{entry['id']}/remove").json()
    assert [e["id"] for e in body["entries"]] == [entry["id"]] and body["entries"][0]["reversed"] is True
    assert body["balances"][0]["balance"] == 0 and rows(client) == n + 1
    row = client.ctx.ledger.conn.execute("SELECT * FROM events ORDER BY id DESC").fetchone()
    assert row["kind"] == "reversal" and row["supersedes_id"] == entry["id"] and row["session_id"] == "portal"


def test_if_balance(client):
    seed(client, "Ramesh ka 340 udhaar")
    cid = customers(client)["Ramesh"]["id"]
    n = rows(client)
    err(client.post("/api/entries", json={"customer_id": cid, "kind": "credit", "amount": 10, "if_balance": 300}),
        409, "balance_changed")
    assert rows(client) == n
    ok = client.post("/api/entries", json={"customer_id": cid, "kind": "credit", "amount": 10, "if_balance": 340})
    assert ok.status_code == 200 and ok.json()["balances"][0]["balance"] == 350


@pytest.mark.parametrize("body,code", [
    ({"kind": "gift", "amount": 5}, "bad_kind"), ({"amount": 5}, "bad_kind"),
    ({"kind": "credit", "amount": 0}, "bad_amount"), ({"kind": "credit", "amount": -4}, "bad_amount"),
    ({"kind": "credit", "amount": 1.5}, "bad_amount"), ({"kind": "credit", "amount": True}, "bad_amount"),
    ({"kind": "credit", "amount": "50"}, "bad_amount"), ({"kind": "credit", "amount": 10 ** 9}, "bad_amount"),
    ({"kind": "credit", "amount": 5, "date": "tomorrow"}, "bad_date"),
    ({"kind": "credit", "amount": 5, "date": "1999-12-31"}, "bad_date"),
    ({"kind": "credit", "amount": 5, "date": "2999-01-01"}, "bad_date"),
])
def test_add_entry_validation(client, body, code):
    cid = client.ctx.ledger.create_customer("asha")["id"]
    err(client.post("/api/entries", json={"customer_id": cid, **body}), 400, code)
    assert rows(client) == 0


def test_add_entry_unknown_customer(client):
    err(client.post("/api/entries", json={"customer_id": "c_nope", "kind": "credit", "amount": 5}), 404,
        "unknown_customer")


def test_date_today_is_allowed_and_tomorrow_is_not(client):
    cid = client.ctx.ledger.create_customer("asha")["id"]
    day = today(client)
    assert client.post("/api/entries", json={"customer_id": cid, "kind": "credit", "amount": 5,
                                             "date": day.isoformat()}).status_code == 200
    err(client.post("/api/entries", json={"customer_id": cid, "kind": "credit", "amount": 5,
                                          "date": (day + timedelta(days=1)).isoformat()}), 400, "bad_date")


def test_entry_error_codes(client):
    seed(client, "Ramesh ka 340 udhaar", "Sita ka 200 udhaar")
    entries = ledger_entries(client)
    sita = entries[0]
    err(client.post("/api/entries/99999/amend", json={"amount": 5}), 404, "unknown_entry")
    err(client.post("/api/entries/99999/remove"), 404, "unknown_entry")
    err(client.post(f"/api/entries/{sita['id']}/amend", json={}), 400, "nothing_changed")
    err(client.post(f"/api/entries/{sita['id']}/amend", json={"amount": 200, "kind": "credit"}), 400,
        "nothing_changed")
    err(client.post(f"/api/entries/{sita['id']}/amend", json={"customer_id": "c_nope"}), 404, "unknown_customer")
    err(client.post(f"/api/entries/{sita['id']}/amend", json={"amount": 0}), 400, "bad_amount")
    n = rows(client)
    assert client.post(f"/api/entries/{sita['id']}/remove").status_code == 200
    err(client.post(f"/api/entries/{sita['id']}/remove"), 409, "not_active")
    err(client.post(f"/api/entries/{sita['id']}/amend", json={"amount": 5}), 409, "not_active")
    reversal = client.ctx.ledger.conn.execute("SELECT id FROM events WHERE kind='reversal'").fetchone()["id"]
    err(client.post(f"/api/entries/{reversal}/remove"), 409, "not_active")
    assert rows(client) == n + 1


def test_failed_amend_rolls_back(client):
    seed(client, "Ramesh ka 340 udhaar")
    entry = ledger_entries(client)[0]
    n = rows(client)
    err(client.post(f"/api/entries/{entry['id']}/amend", json={"amount": 5, "customer_id": "c_nope"}), 404,
        "unknown_customer")
    assert rows(client) == n and customers(client)["Ramesh"]["balance"] == 340


# ---- customers --------------------------------------------------------------------------------------------------
def test_customer_answer_shape_and_say_lang_still_work(client):
    cid = client.ctx.ledger.create_customer("ramesh")["id"]
    body = client.post(f"/api/customers/{cid}", json={"say": "Rameysh", "lang": "en"}).json()
    assert body["ok"] is True and body["customer"]["say"] == "Rameysh" and body["customer"]["lang"] == "en"
    assert body["customer"] == customers(client)["Ramesh"]
    err(client.post("/api/customers/c_nope", json={"lang": "en"}), 404, "unknown_customer")
    assert client.post(f"/api/customers/{cid}", json={"lang": "fr"}).status_code == 400


def test_rename_keeps_the_old_name_for_voice(client):
    state = seed(client, "Ramesh ka 340 udhaar")
    cid = customers(client)["Ramesh"]["id"]
    body = client.post(f"/api/customers/{cid}", json={"display": "  Ramesh   Kumar "}).json()
    assert body["customer"]["display"] == "Ramesh Kumar"
    assert client.ctx.ledger.find_customer(key="ramesh")["id"] == cid  # alias
    assert client.ctx.ledger.find_customer(key="ramesh kumar")["id"] == cid
    for spoken in ("Ramesh ka 100 udhaar", "Ramesh Kumar ka 50 udhaar"):
        r = say(client, state, spoken)
        assert r.status == "ok", (spoken, r.reason)
    assert len(customers(client)) == 1 and customers(client)["Ramesh Kumar"]["balance"] == 490


def test_rename_survives_a_restart_and_drops_the_new_key_from_aliases(client):
    led = client.ctx.ledger
    cid = led.create_customer("ramesh")["id"]
    client.post(f"/api/customers/{cid}", json={"display": "ramesh kumar"})
    client.post(f"/api/customers/{cid}", json={"display": "Ramesh"})  # back to the first name
    led._cache = None
    c = led.find_customer(customer_id=cid)
    assert c["key"] == "ramesh" and c["aliases"] == ["ramesh kumar"]
    assert led.label(cid) == "Ramesh"


def test_devanagari_rename_is_romanised(client):
    cid = client.ctx.ledger.create_customer("ramesh")["id"]
    body = client.post(f"/api/customers/{cid}", json={"display": "सुनीता"}).json()
    assert body["customer"]["display"].isascii() and body["customer"]["display"].lower().startswith("sun")
    assert client.ctx.ledger.find_customer(key="ramesh")["id"] == cid


def test_name_taken(client):
    led = client.ctx.ledger
    a, b = led.create_customer("ramesh")["id"], led.create_customer("sita")["id"]
    led.update_customer(a, display="ramesh kumar")  # "ramesh" is now an alias of a
    err(client.post(f"/api/customers/{b}", json={"display": "Ramesh"}), 409, "name_taken")
    err(client.post(f"/api/customers/{b}", json={"display": "Ramesh Kumar"}), 409, "name_taken")
    assert led.find_customer(customer_id=b)["key"] == "sita"
    assert client.post(f"/api/customers/{b}", json={"display": "Sita"}).status_code == 200  # same name


@pytest.mark.parametrize("name", ["", "A", "x" * 41, "Ramesh 2", "Ram@esh", "500", "paanch sau", "do hazaar",
                                  "badal", "edit amount", 5, None, ["a"]])
def test_bad_name(client, name):
    cid = client.ctx.ledger.create_customer("ramesh")["id"]
    err(client.post(f"/api/customers/{cid}", json={"display": name}), 400, "bad_name")
    assert client.ctx.ledger.find_customer(customer_id=cid)["key"] == "ramesh"


def test_name_punctuation_is_allowed(client):
    cid = client.ctx.ledger.create_customer("ramesh")["id"]
    body = client.post(f"/api/customers/{cid}", json={"display": "Mary-Ann D'Souza Jr."}).json()
    assert body["customer"]["display"] == "Mary-ann D'souza Jr."


def test_tags(client):
    cid = client.ctx.ledger.create_customer("ramesh")["id"]
    body = client.post(f"/api/customers/{cid}", json={"tags": [" Dukaan  Wala ", "Kanpur", "dukaan wala"]}).json()
    assert body["customer"]["tags"] == ["dukaan wala", "kanpur"]
    assert client.post(f"/api/customers/{cid}", json={"tags": []}).json()["customer"]["tags"] == []
    for bad in (["a", "b", "c", "d"], ["x" * 25], ["12"], [""], [5], "kanpur"):
        err(client.post(f"/api/customers/{cid}", json={"tags": bad}), 400, "bad_tag")
    assert client.post(f"/api/customers/{cid}", json={"tags": ["x" * 24]}).status_code == 200


def test_phone_set_clear_and_hint(client):
    cid = client.ctx.ledger.create_customer("ramesh")["id"]
    assert customers(client)["Ramesh"]["phone_hint"] is None
    client.post(f"/api/customers/{cid}/reminders", json={"opt_in": True})
    for given in ("9876543210", "+91 98765 43210", "919876543210", "09876543210"):
        body = client.post(f"/api/customers/{cid}", json={"phone": given}).json()
        assert body["customer"]["phone_hint"] == "•••• 3210"
        assert client.ctx.ledger.find_customer(customer_id=cid)["phone"] == "9876543210"
        assert "9876543210" not in client.get("/api/customers").text
    assert body["customer"]["reminders_opt_in"] is True  # opt-in unchanged
    cleared = client.post(f"/api/customers/{cid}", json={"phone": None}).json()["customer"]
    assert cleared["phone_hint"] is None and client.ctx.ledger.find_customer(customer_id=cid)["phone"] is None
    for bad in ("12345", "5876543210", "98765abcde", "98765432101234", 9876543210):
        err(client.post(f"/api/customers/{cid}", json={"phone": bad}), 400, "bad_phone")


def test_a_refused_field_changes_nothing_in_the_same_call(client):
    cid = client.ctx.ledger.create_customer("ramesh")["id"]
    err(client.post(f"/api/customers/{cid}", json={"display": "Naya Naam", "phone": "12"}), 400, "bad_phone")
    assert client.ctx.ledger.find_customer(customer_id=cid)["key"] == "ramesh"


# ---- guard -------------------------------------------------------------------------------------------------------
def all_calls(c):
    return [c.post("/api/entries", json={"customer_id": "x", "kind": "credit", "amount": 1}),
            c.post("/api/entries/1/amend", json={"amount": 2}), c.post("/api/entries/1/remove"),
            c.post("/api/customers/x", json={"display": "Asha"})]


def test_google_sign_in_guards_every_call(tmp_path):
    app = create_app(make_settings(tmp_path, **GOOGLE), parse=default_parse, web_dir=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        assert [r.status_code for r in all_calls(c)] == [401] * 4


def test_signed_in_edits_reach_only_the_accounts_own_khata(tmp_path, monkeypatch):
    """With sign-in on, every edit call works on the signed-in account's ledger: never on the one-shop ledger
    or on another account's, even where the entry ids are the same."""
    from urllib.parse import parse_qs, urlsplit

    from app import auth

    def sign_in_as(c, email):
        async def google(code, redirect_uri, client_id, client_secret):
            return {"email": email, "email_verified": True}
        monkeypatch.setattr(auth, "exchange", google)
        login = c.get("/api/auth/google/login", follow_redirects=False)
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        c.get(f"/api/auth/google/callback?code=x&state={state}", follow_redirects=False)

    def one_entry(led, name, amount):
        now = led_now
        cid = led.create_customer(name, now=now)["id"]
        led.apply({"action": "append", "events": [{"kind": "credit", "customer": name, "customer_id": cid,
                                                    "amount": amount, "date": now.date().isoformat()}]},
                  now=now, session_id="s1")
        return cid

    app = create_app(make_settings(tmp_path, **dict(GOOGLE, allowed_emails="owner@gmail.com, partner@gmail.com")),
                     parse=default_parse, web_dir=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as owner, \
            TestClient(app, base_url="http://127.0.0.1:8000") as partner:
        led_now = app.state.ctx.pipeline.now()
        shop = app.state.ctx.ledger                       # the one-shop ledger (used when sign-in is off)
        mine = app.state.tenant("owner@gmail.com").ledger
        theirs = app.state.tenant("partner@gmail.com").ledger
        one_entry(shop, "ramesh", 100)
        cid = one_entry(mine, "ramesh", 340)
        one_entry(theirs, "ramesh", 700)                  # every ledger has an entry with id 1
        sign_in_as(owner, "owner@gmail.com")
        sign_in_as(partner, "partner@gmail.com")

        r = owner.post("/api/entries/1/amend", json={"amount": 430})
        assert r.status_code == 200 and r.json()["balances"][0]["balance"] == 430
        r = owner.post("/api/entries", json={"customer_id": cid, "kind": "payment", "amount": 30, "if_balance": 430})
        assert r.status_code == 200 and r.json()["balances"][0]["balance"] == 400
        r = owner.post(f"/api/customers/{cid}", json={"display": "Ramesh Kumar"})
        assert r.status_code == 200 and r.json()["customer"]["display"] == "Ramesh Kumar"
        assert partner.post(f"/api/customers/{cid}", json={"display": "Asha"}).status_code == 404
        assert partner.post("/api/entries/2/remove").status_code == 404   # id 2 exists only in the owner's khata

        assert mine.balance(cid) == 400 and mine.find_customer(customer_id=cid)["key"] == "ramesh kumar"
        assert [c["balance"] for c in shop.customer_summaries()] == [100]
        assert [c["display"] for c in shop.customer_summaries()] == ["Ramesh"]
        assert [c["balance"] for c in theirs.customer_summaries()] == [700]
        assert [c["display"] for c in theirs.customer_summaries()] == ["Ramesh"]


def test_access_code_guards_every_call(tmp_path):
    app = create_app(make_settings(tmp_path, access_code="sesame"), parse=default_parse, web_dir=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        assert [r.status_code for r in all_calls(c)] == [401] * 4
        cid = app.state.ctx.ledger.create_customer("asha")["id"]
        r = c.post("/api/entries", json={"customer_id": cid, "kind": "credit", "amount": 5},
                   headers={"X-Access-Code": "sesame"})
        assert r.status_code == 200


# ---- voice sessions stay safe --------------------------------------------------------------------------------------
def test_correction_after_a_screen_change_is_refused(client):
    state = seed(client, "Ramesh ka 340 udhaar", "Sita ka 200 udhaar")
    sita = next(e for e in ledger_entries(client) if e["customer"]["display"] == "Sita")
    assert client.post(f"/api/entries/{sita['id']}/amend", json={"amount": 220}).status_code == 200
    before = rows(client)
    r = say(client, state, "nahi, 250")
    # The session's last turn is gone, so the parser treats Ramesh's entry as an older one and only asks.
    assert r.status == "needs_clarification" and r.reason == "confirm_entry" and "Ramesh" in r.reply_text
    assert rows(client) == before
    c = customers(client)
    assert c["Ramesh"]["balance"] == 340 and c["Sita"]["balance"] == 220


def test_bare_undo_after_a_screen_change_asks_which_entry(client):
    state = seed(client, "Ramesh ka 340 udhaar", "Sita ka 200 udhaar")
    sita = next(e for e in ledger_entries(client) if e["customer"]["display"] == "Sita")
    client.post(f"/api/entries/{sita['id']}/remove")
    before = rows(client)
    r = say(client, state, "hata do")
    assert r.status == "needs_clarification" and "Ramesh" in r.reply_text
    assert rows(client) == before and customers(client)["Ramesh"]["balance"] == 340


def test_removal_on_the_screen_also_stops_the_correction(client):
    state = seed(client, "Ramesh ka 340 udhaar")
    entry = ledger_entries(client)[0]
    client.post(f"/api/entries/{entry['id']}/remove")
    r = say(client, state, "nahi, 250")
    assert r.status == "rejected" and r.reason == "no_last_event"
    assert customers(client)["Ramesh"]["balance"] == 0


def test_correction_still_works_when_the_last_entry_is_untouched(client):
    state = seed(client, "Ramesh ka 340 udhaar", "Sita ka 200 udhaar")
    ramesh = next(e for e in ledger_entries(client) if e["customer"]["display"] == "Ramesh")
    client.post(f"/api/entries/{ramesh['id']}/amend", json={"amount": 360})  # not the last one
    r = say(client, state, "nahi, 250")
    assert r.status == "ok" and r.action == "amend"
    c = customers(client)
    assert c["Sita"]["balance"] == 250 and c["Ramesh"]["balance"] == 360


def test_event_ids_stay_out_of_the_parser_context(client):
    state = seed(client, "Ramesh ka 340 udhaar")
    assert state.last_turn["event_ids"]
    ctx = client.ctx.pipeline.build_ctx(state, client.ctx.pipeline.now())
    assert "event_ids" not in ctx["last_turn"] and ctx["last_turn"]["action"] == "append"


# ---- notifications (app/notify.py) --------------------------------------------------------------------------------
def test_hand_edits_publish_the_same_events_as_spoken_ones(client):
    from app.notify import Notifier

    class Capture(Notifier):
        def __init__(self):
            self.events = []

        def publish(self, event):
            self.events.append(event)

    seed(client, "Ramesh ka 340 udhaar")
    cap = client.ctx.pipeline.notifier = Capture()
    cid = customers(client)["Ramesh"]["id"]
    added = client.post("/api/entries", json={"customer_id": cid, "kind": "payment", "amount": 40}).json()
    amended = client.post(f"/api/entries/{added['entries'][0]['id']}/amend", json={"amount": 45}).json()
    new_id = amended["entries"][1]["id"]
    client.post(f"/api/entries/{new_id}/remove")
    assert client.post(f"/api/entries/{new_id}/remove").status_code == 409  # refused: nothing published
    assert [(e["type"], e["kind"], e["amount"]) for e in cap.events] == [
        ("entry_append", "payment", 40), ("entry_amend", "payment", 45), ("entry_undo", "payment", 45)]
    assert all(e["customer_id"] == cid and e["entry_id"] and e["shop"] for e in cap.events)
    assert "ramesh" not in str(cap.events).lower()  # names stay out of the broker


# ---- speed -------------------------------------------------------------------------------------------------------
def test_amends_stay_fast_on_a_large_ledger(client):
    import statistics
    import time

    led = client.ctx.ledger
    now = client.ctx.pipeline.now()
    ids = [led.create_customer(f"grahak{chr(97 + i // 26 % 26)}{chr(97 + i % 26)}x{i // 676}", now=now)["id"]
           for i in range(1000)]
    with led._lock:
        led._begin()
        for n in range(5000):
            led._insert_event("credit", ids[n % 1000], 10000 + n * 100, now.date().isoformat(), now,
                              utterance_id=None, session_id="seed", trace_id=None)
        led.conn.execute("COMMIT")
        led._stats = None
    client.get("/api/customers")  # warm the caches
    taken = []
    for n in range(200):
        t = time.perf_counter()
        r = client.post(f"/api/entries/{n + 1}/amend", json={"amount": 5000 + n})
        taken.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 200
    body = r.json()
    assert [e["reversed"] for e in body["entries"]] == [True, False] and len(body["balances"]) == 1
    assert statistics.median(taken) < 50, f"median {statistics.median(taken):.1f} ms"
