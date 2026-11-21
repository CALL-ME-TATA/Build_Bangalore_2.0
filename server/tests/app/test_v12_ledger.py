"""CONTRACT v1.2, group 2: queries, ordering, confusions, metrics, customers, consent, reminders, scale, prewarm,
pronunciation and static files."""
from __future__ import annotations

import base64
import logging
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app import main as main_module
from app.config import Settings
from app.crypto import Crypto
from app.gnani.tts import TtsClient
from app.ledger import Ledger, period_range
from app.main import create_app, pick_web_dir, prewarm, prewarm_enabled
from app.pipeline import Pipeline, SessionState
from app.replies import Replier, fixed_replies

from .conftest import TEST_KEY, _ev, apply_events, fake_nw
from .test_review_fixes import running

TODAY = date(2026, 11, 21)  # a Saturday
NOON = datetime(2026, 11, 21, 12, 0).astimezone()
R = Replier(fake_nw)
EN = R.with_lang("en")


def ev(kind, customer, amount, day=TODAY, **extra):
    return _ev(kind, customer, amount, day, **extra)


def at_noon(day: date = TODAY):
    return lambda: datetime(day.year, day.month, day.day, 12, 0).astimezone()


@pytest.fixture
def noon_pipe(ledger, settings, parser):
    return Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw, now=at_noon())


def query(parser, pipe, q, lang="hi", private=False):
    parser.canned["q"] = {"status": "ok", "action": "query", "query": q}
    return pipe.run_turn(SessionState(session_id="sq", disclosed=True, lang=lang, private=private), "q")


# ---- 8. queries -------------------------------------------------------------------------------------------------
def test_period_ranges_monday_to_sunday_and_months():
    assert period_range("this_week", TODAY) == (date(2026, 11, 16), TODAY)
    assert period_range("last_week", TODAY) == (date(2026, 11, 9), date(2026, 11, 15))
    assert period_range("this_week", date(2026, 11, 16)) == (date(2026, 11, 16), date(2026, 11, 16))
    assert period_range("last_week", date(2026, 11, 22)) == (date(2026, 11, 9), date(2026, 11, 15))
    assert period_range("this_month", TODAY) == (date(2026, 11, 1), TODAY)
    assert period_range("last_month", TODAY) == (date(2026, 10, 1), date(2026, 10, 31))
    assert period_range("last_month", date(2027, 1, 5)) == (date(2026, 12, 1), date(2026, 12, 31))
    assert period_range("yesterday", date(2027, 3, 1)) == (date(2027, 2, 28), date(2027, 2, 28))


def test_J06_period_totals_and_replies(noon_pipe, parser, ledger):
    apply_events(ledger, [ev("credit", "ramesh", 100, date(2026, 11, 16)), ev("payment", "ramesh", 40, TODAY),
                          ev("credit", "sunita", 500, date(2026, 11, 15)), ev("credit", "sunita", 70, date(2026, 10, 31)),
                          ev("writeoff", "sunita", 30, TODAY)])
    t = query(parser, noon_pipe, {"type": "daily_summary", "period": "this_week"})
    assert t.reply_text == "Is hafte ₹100 udhaar gaya, ₹40 jama hue."
    assert query(parser, noon_pipe, {"type": "credit_total", "period": "last_week"}).reply_text == \
        "Pichle hafte ₹500 udhaar gaya."
    assert query(parser, noon_pipe, {"type": "credit_total", "period": "this_month"}).reply_text == \
        "Is mahine ₹600 udhaar gaya."
    assert query(parser, noon_pipe, {"type": "payment_total", "period": "last_month"}).reply_text == \
        "Pichle mahine koi paisa jama nahi hua."
    assert query(parser, noon_pipe, {"type": "daily_summary", "period": "this_week"}, "en").reply_text == \
        "This week: ₹100 credit, ₹40 received."
    assert query(parser, noon_pipe, {"type": "daily_summary", "period": "pichle_saal"}).reply_text == \
        "Kaunsa din? Aaj, kal ya parso boliye."


def test_C05_C06_shop_day_is_the_calendar_day_in_shop_tz(ledger, settings, parser):
    from zoneinfo import ZoneInfo

    utc_evening = datetime(2026, 11, 21, 19, 0, tzinfo=ZoneInfo("UTC"))  # 00:30 on the 22nd in Kolkata
    pipe = Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw)
    assert pipe.now().tzinfo is not None and str(pipe.now().tzinfo) == "Asia/Kolkata"
    pipe = Pipeline(ledger, settings, parse=parser, number_to_words=fake_nw,
                    now=lambda: utc_evening.astimezone(ZoneInfo(settings.shop_tz)))
    st = SessionState(session_id="s", disclosed=True)
    pipe.run_turn(st, "ramesh ka 340 udhaar")
    assert parser.calls[-1]["ctx"] is not None
    assert ledger.recent_entries()[0]["date"] == "2026-11-22"


def test_J09_outstanding_total(noon_pipe, parser, ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340), ev("credit", "sunita", 500), ev("payment", "mohan", 50),
                          ev("credit", "geeta", 100), ev("payment", "geeta", 100)])
    assert ledger.outstanding_total() == {"amount": 840, "customers": 2}
    t = query(parser, noon_pipe, {"type": "outstanding_total"})
    assert t.reply_text == "Kul baaki ₹840 hai, 2 grahakon par." and t.query == {"type": "outstanding_total"}


def test_J07_due_since_settles_oldest_credit_first(noon_pipe, parser, ledger):
    apply_events(ledger, [ev("credit", "ramesh", 100, date(2026, 11, 1)), ev("credit", "ramesh", 200, date(2026, 11, 5)),
                          ev("credit", "ramesh", 50, date(2026, 11, 10)), ev("payment", "ramesh", 120, TODAY)])
    rid = ledger.find_customer(key="ramesh")["id"]
    assert ledger.due_since(rid) == date(2026, 11, 5)
    t = query(parser, noon_pipe, {"type": "due_since", "customer": "ramesh"})
    assert t.reply_text == "Ramesh ka 5 navambar se baaki hai." and t.query["customer_id"] == rid
    apply_events(ledger, [ev("writeoff", "ramesh", 180, TODAY)])
    assert ledger.due_since(rid) == date(2026, 11, 10)
    apply_events(ledger, [ev("payment", "ramesh", 50, TODAY)])
    assert ledger.due_since(rid) is None
    assert query(parser, noon_pipe, {"type": "due_since", "customer": "ramesh"}).reply_text == \
        "Ramesh ka hisaab barabar hai."


async def test_C08_K06_ledger_order_and_customer_filter(server, ledger):
    apply_events(ledger, [ev("credit", "ramesh", 100, TODAY)])
    apply_events(ledger, [ev("credit", "sunita", 200, TODAY - timedelta(days=3))])  # entered later, dated earlier
    apply_events(ledger, [ev("payment", "ramesh", 50, TODAY - timedelta(days=1))])
    rid = ledger.find_customer(key="ramesh")["id"]
    async with httpx.AsyncClient() as c:
        created = (await c.get(server.http + "/api/ledger")).json()["entries"]
        by_date = (await c.get(server.http + "/api/ledger", params={"order": "date"})).json()["entries"]
        mine = (await c.get(server.http + "/api/ledger", params={"customer_id": rid})).json()["entries"]
        assert (await c.get(server.http + "/api/ledger", params={"order": "x"})).status_code == 400
    assert [e["amount"] for e in created] == [50, 200, 100]
    assert [e["amount"] for e in by_date] == [100, 50, 200]
    assert [e["amount"] for e in mine] == [50, 100]


# ---- 10. confusions and metrics ---------------------------------------------------------------------------------
def test_A19_amount_only_amends_feed_confusables(pipeline, parser, ledger):
    st = SessionState(session_id="sess0001", disclosed=True)
    for _ in range(2):
        pipeline.run_turn(st, "ramesh ka 340 udhaar")
        pipeline.run_turn(st, "nahi 430")
    assert ledger.confusables() == {"340": [430]}
    pipeline.run_turn(st, "aaj ka hisaab")
    assert parser.calls[-1]["ctx"]["confusables"] == {"340": [430]}
    # A customer change is not a misheard amount.
    c = ledger.find_customer(key="ramesh")["id"]
    parser.canned["nahi sunita"] = {"status": "ok", "action": "amend", "target": "last",
                                    "events": [ev("credit", "sunita", 999)]}
    pipeline.run_turn(st, "nahi sunita")
    n = ledger.conn.execute("SELECT COUNT(*) FROM confusions WHERE heard=430").fetchone()[0]
    assert n == 0 and c


async def test_metrics_endpoint_counts_turns_without_names(server, ledger):
    import json

    import websockets

    from .test_session import hello, is_type, recv_until

    async with websockets.connect(server.url) as ws:
        await hello(ws)
        for text in ("ramesh ka 340 udhaar", "nahi 430", "undo karo", "ramesh 340", "kuch bhi", "ramesh ka total"):
            await ws.send(json.dumps({"type": "text", "text": text}))
            await recv_until(ws, is_type("audio_end"))
    async with httpx.AsyncClient() as c:
        m = (await c.get(server.http + "/api/metrics")).json()
    assert m["turns"] == 6 and m["saves"] == 1 and m["corrections"] == 1 and m["undos"] == 1
    assert m["questions"] == 1 and m["rejections"] == 1
    assert m["confusions"] == [{"heard": 340, "meant": 430, "n": 1}]
    assert "ramesh" not in json.dumps(m).lower()


# ---- 11. customers, consent, reminders --------------------------------------------------------------------------
def test_K03_customers_cannot_be_deleted(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    with pytest.raises(sqlite3.DatabaseError):
        ledger.conn.execute("DELETE FROM customers")
    with pytest.raises(sqlite3.DatabaseError):
        ledger.conn.execute("INSERT OR REPLACE INTO customers(id, ident, reminders_opt_in, created_ts) "
                            "SELECT id, ident, 1, created_ts FROM customers")
    assert ledger.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1


def test_Q05_consent_log_is_append_only_and_opt_out_clears_outbox(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    rid = ledger.find_customer(key="ramesh")["id"]
    ledger.set_reminder_opt_in(rid, True, "9876543210", now=NOON)
    assert ledger.queue_reminders(NOON)
    ledger.set_reminder_opt_in(rid, False, now=NOON)
    assert [h["opt_in"] for h in ledger.consent_history(rid)] == [True, False]
    assert ledger.conn.execute("SELECT COUNT(*) FROM reminder_outbox").fetchone()[0] == 0
    for sql in ("UPDATE consent_log SET opt_in=1", "DELETE FROM consent_log"):
        with pytest.raises(sqlite3.DatabaseError):
            ledger.conn.execute(sql)


def test_Q04_reminder_rebuilt_from_current_balance_and_dropped_when_paid(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    rid = ledger.find_customer(key="ramesh")["id"]
    ledger.set_reminder_opt_in(rid, True, "9876543210", now=NOON)
    ledger.queue_reminders(NOON)
    apply_events(ledger, [ev("payment", "ramesh", 100)])
    box = ledger.outbox(NOON, lambda n, a, lang: R.with_lang(lang).reminder_message(n, a))
    assert box[0]["amount"] == 240 and "₹240" in box[0]["message"]
    apply_events(ledger, [ev("payment", "ramesh", 240)])
    assert ledger.outbox(NOON, lambda n, a, lang: "x") == []


def test_Q06_quiet_hours_nothing_queued_or_listed(ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    rid = ledger.find_customer(key="ramesh")["id"]
    ledger.set_reminder_opt_in(rid, True, "9876543210", now=NOON)
    late = datetime(2026, 11, 21, 21, 0).astimezone()
    early = datetime(2026, 11, 21, 8, 59).astimezone()
    assert ledger.queue_reminders(late) == [] and ledger.queue_reminders(early) == []
    ledger.queue_reminders(NOON)
    assert ledger.outbox(late, lambda n, a, lang: "x") == []
    assert len(ledger.outbox(datetime(2026, 11, 21, 19, 59).astimezone(), lambda n, a, lang: "x")) == 1


async def test_Q06_reminders_endpoint_reports_quiet_hours(settings, parser, fake_gnani):
    for hour, quiet in ((22, True), (11, False)):
        app = create_app(settings, parse=parser, number_to_words=fake_nw,
                         now=lambda h=hour: datetime(2026, 11, 21, h, 0).astimezone())
        async with running(app) as (http, _):
            async with httpx.AsyncClient() as c:
                body = (await c.get(http + "/api/reminders")).json()
                assert body["quiet_hours"] is quiet and body["reminders"] == []
                assert (await c.post(http + "/api/reminders/queue")).json()["quiet_hours"] is quiet


def test_Q03_Q07_Q09_reminder_text_short_polite_in_customer_language(ledger):
    pressure = ("turant", "jaldi", "warna", "nahi to", "last warning", "immediately", "legal", "police",
                "overdue", "penalty", "must", "abhi", "foran")
    for r in (R, EN):
        text = r.reminder_message("Ramesh", 340)
        assert len(text.split()) <= 16 and "₹340" in text
        assert not any(p in text.lower() for p in pressure), text
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    rid = ledger.find_customer(key="ramesh")["id"]
    ledger.update_customer(rid, lang="en")
    ledger.set_reminder_opt_in(rid, True, "9876543210", now=NOON)
    ledger.queue_reminders(NOON)
    box = ledger.outbox(NOON, lambda n, a, lang: R.with_lang(lang).reminder_message(n, a))
    assert box[0]["lang"] == "en" and box[0]["message"].startswith("Hello Ramesh")


# ---- 12. reminder action ----------------------------------------------------------------------------------------
def test_Q08_reminder_action(noon_pipe, parser, ledger):
    st = SessionState(session_id="s", disclosed=True)
    parser.canned["remind"] = {"status": "ok", "action": "reminder", "customer": "ramesh"}
    parser.canned["remind 850"] = {"status": "ok", "action": "reminder", "customer": "ramesh", "amount": 850}
    parser.canned["remind zubin"] = {"status": "ok", "action": "reminder", "customer": "zubin"}
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    rid = ledger.find_customer(key="ramesh")["id"]
    assert noon_pipe.run_turn(st, "remind zubin").reply_text == "Zubin ka khata nahi mila."
    assert noon_pipe.run_turn(st, "remind").reply_text == "Ramesh ne reminder ke liye haan nahi kaha hai."
    ledger.set_reminder_opt_in(rid, True, "9876543210", now=NOON)
    t = noon_pipe.run_turn(st, "remind 850")
    assert t.status == "needs_clarification" and t.reason == "confirm_entry"
    assert t.reply_text == "Ramesh ke ₹340 baaki hain, ₹850 nahi. ₹340 ka reminder banaun?"
    assert t.confirm == {"type": "reminder", "balance": 340, "said": 850}
    assert ledger.outbox(NOON, lambda n, a, lang: "x") == []
    t = noon_pipe.run_turn(st, "haan")
    assert t.reply_text == "Ramesh ka reminder taiyaar hai, screen par dekhiye."
    box = ledger.outbox(NOON, lambda n, a, lang: "x")
    assert len(box) == 1 and box[0]["amount"] == 340
    # The parser's yes to a reminder question: action "reminder" with no amount (and here, no customer).
    ledger.set_reminder_opt_in(rid, False, now=NOON)
    ledger.set_reminder_opt_in(rid, True, now=NOON)
    noon_pipe.run_turn(st, "remind 850")
    parser.canned["ji"] = {"status": "ok", "action": "reminder"}
    assert noon_pipe.run_turn(st, "ji").reply_text == "Ramesh ka reminder taiyaar hai, screen par dekhiye."
    assert len(ledger.outbox(NOON, lambda n, a, lang: "x")) == 1
    apply_events(ledger, [ev("payment", "ramesh", 340)])
    assert noon_pipe.run_turn(st, "remind").reply_text == "Ramesh ka kuch baaki nahi, reminder nahi banaya."
    apply_events(ledger, [ev("credit", "ramesh", 10)])
    late = Pipeline(ledger, noon_pipe.settings, parse=parser, number_to_words=fake_nw,
                    now=lambda: datetime(2026, 11, 21, 21, 0).astimezone())
    assert late.run_turn(st, "remind").reply_text == "Reminder subah 9 se raat 8 baje ke beech hi bante hain."


# ---- 13. scale and concurrency ----------------------------------------------------------------------------------
def test_K05_E15_ten_thousand_events_and_a_thousand_customers(tmp_path, parser):
    led = Ledger(tmp_path / "big.db", Crypto(base64.b64decode(TEST_KEY)))
    try:
        led._begin()
        ids = [led._create_customer(f"cust{i:04d}", NOON)["id"] for i in range(1000)]
        rows = []
        for i in range(10_000):
            kind = "credit" if i % 3 else "payment"
            day = (TODAY - timedelta(days=i % 90)).isoformat()
            rows.append((NOON.isoformat(), kind, ids[i % 1000], (100 + i % 900) * 100, day, f"u{i}", "s", "t"))
        led.conn.executemany("INSERT INTO events(ts, kind, customer_id, amount_paise, effective_date, utterance_id,"
                             " session_id, trace_id) VALUES (?,?,?,?,?,?,?,?)", rows)
        for i in range(0, 10_000, 50):  # some reversals
            led.conn.execute("INSERT INTO events(ts, kind, customer_id, amount_paise, effective_date, supersedes_id)"
                             " SELECT ts, 'reversal', customer_id, amount_paise, effective_date, id FROM events"
                             " WHERE id=?", (i + 1,))
        led.conn.execute("COMMIT")
        led._cache = None  # decrypt from disk as on start-up
        settings = Settings(ledger_db=str(tmp_path / "big.db"))
        pipe = Pipeline(led, settings, parse=parser, number_to_words=fake_nw, now=at_noon())
        state = SessionState(session_id="s")

        def timed(fn, cold=False):
            """Best of five runs (each cold when asked), so other work on the machine does not decide."""
            best = None
            for _ in range(5):
                if cold:
                    led._stats = None
                t0 = time.perf_counter()
                fn()
                ms = (time.perf_counter() - t0) * 1000
                best = ms if best is None else min(best, ms)
            return best

        timed(lambda: pipe.build_ctx(state, NOON))  # first call decrypts the customer rows once
        assert timed(lambda: led._customers()) < 5  # cached
        start_up = timed(lambda: pipe.build_ctx(state, NOON), cold=True)  # the full recompute, once at start-up
        assert start_up < 100, start_up
        warm = timed(lambda: pipe.build_ctx(state, NOON))
        # After a write only the touched customer is recomputed.
        pipe.run_turn(state, "ramesh ka 340 udhaar")
        after_write = timed(lambda: (apply_events(led, [ev("credit", "cust0003", 5)], session="s"),
                                     pipe.build_ctx(state, NOON)))
        assert warm < 50 and after_write < 50, (warm, after_write)
        assert led.balance(ids[3]) == led._stats_now()["balances"][ids[3]]
        full = dict(led._stats_now()["balances"])
        led._stats = None
        assert led._stats_now()["balances"] == full  # the incremental cache equals a full recompute
        rid = ids[7]
        checks = {
            "balance": lambda: led.balance(rid),
            "due_since": lambda: led.due_since(rid),
            "this_month": lambda: led.daily_summary(*period_range("this_month", TODAY)),
            "last_month": lambda: led.totals(*period_range("last_month", TODAY)),
            "today": lambda: led.daily_summary(TODAY),
            "top_dues": lambda: led.top_dues(3),
            "outstanding": lambda: led.outstanding_total(),
            "ledger_by_date": lambda: led.recent_entries(50, order="date"),
            "ledger_customer": lambda: led.recent_entries(50, customer_id=rid),
        }
        for name, fn in checks.items():
            assert timed(fn) < 50, name
        for q in ({"type": "balance", "customer": "cust0007"}, {"type": "outstanding_total"},
                  {"type": "daily_summary", "period": "this_month"}, {"type": "due_since", "customer": "cust0007"}):
            assert timed(lambda: query(parser, pipe, q)) < 50, q
    finally:
        led.close()


def test_K04_concurrent_writers_never_see_database_locked(settings):
    path = settings.ledger_db
    crypto = Crypto(base64.b64decode(TEST_KEY))
    ledgers = [Ledger(path, crypto), Ledger(path, crypto)]
    errors: list[Exception] = []

    def writer(led, n):
        try:
            for i in range(25):
                led.apply({"action": "append", "events": [ev("credit", f"w{n}", 10 + i)]},
                          now=datetime.now().astimezone(), session_id=f"s{n}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(ledgers[i % 2], i)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert errors == []
        assert ledgers[0].conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 100
    finally:
        for led in ledgers:
            led.close()


# ---- 14. prewarm ------------------------------------------------------------------------------------------------
async def test_N07_prewarm_synthesises_fixed_replies_once(settings, fake_gnani, tmp_path):
    settings.gnani_base_url = fake_gnani.base_url
    mem: dict = {}
    factory = lambda s: TtsClient(s, cache_dir=tmp_path / "tts", memory_cache=mem)  # noqa: E731
    n_fixed = len({r.speak for r in fixed_replies(R)}) + len({r.speak for r in fixed_replies(EN)})
    assert await prewarm(settings, R, factory) == n_fixed
    assert len(list((tmp_path / "tts").glob("*.pcm"))) == n_fixed
    assert {r["language"] for r in fake_gnani.tts_requests} == {"hi-IN", "en-IN"}
    mem.clear()
    assert await prewarm(settings, R, factory) == 0  # read back from disk


def test_prewarm_is_off_without_key_when_disabled_and_in_tests(monkeypatch):
    assert prewarm_enabled(Settings(gnani_api_key="k", tts_prewarm=True)) is False  # inside pytest
    assert prewarm_enabled(Settings.from_env({"GNANI_API_KEY": "k"})) is False  # default on, but not in tests
    assert prewarm_enabled(Settings.from_env({"GNANI_API_KEY": "k", "TTS_PREWARM": "1"})) is True  # asked for
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert prewarm_enabled(Settings(gnani_api_key="k", tts_prewarm=True)) is True
    assert prewarm_enabled(Settings(gnani_api_key="", tts_prewarm=True)) is False
    assert prewarm_enabled(Settings.from_env({"GNANI_API_KEY": "k", "TTS_PREWARM": "0"})) is False


# ---- 15. pronunciation ------------------------------------------------------------------------------------------
async def test_N02_say_replaces_display_name_in_speech_only(server, fake_gnani, ledger):
    import json

    import websockets

    from .test_session import hello, is_type, of, recv_until

    apply_events(ledger, [ev("credit", "ramesh", 10)])
    rid = ledger.find_customer(key="ramesh")["id"]
    async with httpx.AsyncClient() as c:
        assert (await c.post(server.http + f"/api/customers/{rid}", json={"say": "Rameysh"})).json() == {"ok": True}
        assert (await c.post(server.http + "/api/customers/nobody", json={"say": "x"})).status_code == 404
        assert (await c.post(server.http + f"/api/customers/{rid}", json={"lang": "fr"})).status_code == 400
    async with websockets.connect(server.url) as ws:
        await hello(ws)
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka total"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
    assert of(msgs, "result")[0]["reply_text"] == "Ramesh ke ₹10 baaki hain."
    assert fake_gnani.tts_requests[-1]["text"].startswith("Rameysh के")
    assert ledger.label(rid) == "Ramesh"


# ---- 16. static files -------------------------------------------------------------------------------------------
def test_static_dir_prefers_build_then_web_and_honours_env(tmp_path, monkeypatch):
    dist, web = tmp_path / "dist", tmp_path / "web"
    dist.mkdir()
    web.mkdir()
    monkeypatch.setattr(main_module, "DIST_DIR", dist)
    monkeypatch.setattr(main_module, "WEB_DIR", web)
    assert pick_web_dir(Settings()) == web  # no build yet
    (dist / "index.html").write_text("<p>built</p>")
    assert pick_web_dir(Settings()) == dist
    assert pick_web_dir(Settings(web_dir=str(web))) == web
    assert Settings.from_env({"WEB_DIR": "elsewhere"}).web_dir == "elsewhere"


async def test_root_serves_index_and_unknown_paths_404(settings, parser, fake_gnani, tmp_path):
    web = tmp_path / "site"
    web.mkdir()
    (web / "index.html").write_text("<p>home</p>")
    (web / "app.js").write_text("1")
    app = create_app(settings, parse=parser, number_to_words=fake_nw, web_dir=web)
    async with running(app) as (http, _):
        async with httpx.AsyncClient() as c:
            assert "home" in (await c.get(http + "/")).text
            assert (await c.get(http + "/app.js")).text == "1"
            assert (await c.get(http + "/no/such/page")).status_code == 404
            assert (await c.get(http + "/api/nothing")).status_code == 404


# ---- P05: logs ---------------------------------------------------------------------------------------------------
def test_P05_logs_hold_no_transcript_name_or_amount(pipeline, parser, ledger, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    logging.getLogger("khata.ws").debug("probe")  # the websockets logger never emits DEBUG records
    st = SessionState(session_id="s", disclosed=True)

    def boom(today, ctx):
        raise RuntimeError("zorbax 7341 in the message")

    parser.canned["zorbax ka 7341 udhaar boom"] = boom
    parser.canned["zorbax ka 7341 udhaar"] = {"status": "ok", "action": "append",
                                             "events": [ev("credit", "zorbax", 7341)]}
    parser.canned["bad zorbax"] = {"status": "ok", "action": "append", "events": [ev("credit", "zorbax", -7341)]}
    pipeline.run_turn(st, "zorbax ka 7341 udhaar boom")
    pipeline.run_turn(st, "zorbax ka 7341 udhaar")
    pipeline.run_turn(st, "bad zorbax")
    monkeypatch.setattr(ledger, "record_utterance", lambda *a, **k: (_ for _ in ()).throw(OSError("zorbax 7341")))
    pipeline.run_turn(st, "kuch bhi")
    text = "\n".join(r.getMessage() + (str(r.exc_info) if r.exc_info else "") for r in caplog.records)
    assert "turn failed" in text
    assert "zorbax" not in text.lower() and "7341" not in text and "probe" not in text


async def test_Q07_opt_in_endpoint_accepts_the_customer_language(server, ledger):
    apply_events(ledger, [ev("credit", "ramesh", 340)])
    rid = ledger.find_customer(key="ramesh")["id"]
    async with httpx.AsyncClient() as c:
        url = server.http + f"/api/customers/{rid}/reminders"
        assert (await c.post(url, json={"opt_in": True, "phone": "9876543210", "lang": "en"})).status_code == 200
        assert (await c.post(url, json={"opt_in": True, "lang": "xx"})).status_code == 400
    ledger._cache = None  # the server wrote through its own Ledger instance
    assert ledger.find_customer(customer_id=rid)["lang"] == "en"


def test_K05_incremental_stats_always_equal_a_full_recompute(ledger):
    import random

    rnd = random.Random(7)
    names = ["ramesh", "sunita", "mohan"]
    ledger.balances()  # build the cache, then keep it through every write
    for i in range(120):
        step = rnd.random()
        now = datetime.now().astimezone()
        if step < 0.55:
            kind = rnd.choice(["credit", "credit", "payment", "writeoff"])
            apply_events(ledger, [ev(kind, rnd.choice(names), rnd.randint(1, 900))])
        elif step < 0.75:
            ledger.apply({"action": "undo"}, now=now, session_id="sess0001")
        elif step < 0.9:
            last = ledger.last_active_event("sess0001")
            if last:
                ledger.apply({"action": "amend", "events": [ev(last["kind"], rnd.choice(names), rnd.randint(1, 900))]},
                             now=now, session_id="sess0001")
        else:
            with pytest.raises(ValueError):  # a rolled-back write leaves the cache right too
                apply_events(ledger, [ev("credit", "ramesh", 10), ev("credit", "ramesh", 0)])
        cached = {k: (dict(v) if isinstance(v, dict) else set(v)) for k, v in ledger._stats_now().items()}
        ledger._stats = None
        assert ledger._stats_now() == cached, i
