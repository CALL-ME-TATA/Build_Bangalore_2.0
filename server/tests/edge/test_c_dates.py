"""C. Dates and time (docs/EDGE_CASES.md section C, CONTRACT 1.5, 2.1 and 3.3)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from .kit import IST, expect_ask, expect_nothing_saved, expect_reject, expect_saved


def test_C01_kal_diya_tha_is_payment_dated_yesterday(rs):
    expect_saved(rs.say("Ramesh ka 340 udhaar"), ("credit", "ramesh", 340), shop=rs)
    expect_saved(rs.say("kal 200 diya tha"), ("payment", "ramesh", 200, 1), shop=rs)


def test_C01_kal_with_a_name(rs):
    expect_saved(rs.say("Ramesh ne kal 200 diye"), ("payment", "ramesh", 200, 1), shop=rs)


@pytest.mark.parametrize("text", ["parso Ramesh ka 100 udhaar", "Ramesh ka parso 100 udhaar"])
def test_C02_parso_is_two_days_ago(rs, text):
    expect_saved(rs.say(text), ("credit", "ramesh", 100, 2), shop=rs)


@pytest.mark.parametrize("text", ["kal dunga", "kal dega", "Ramesh kal 500 dega"])
def test_C03_a_promise_is_not_saved(rs, text):
    t = rs.say(text)
    expect_reject(t, "future")


@pytest.mark.parametrize("text", [
    "Ramesh ne pichle hafte 200 diye", "Ramesh ne Monday ko 200 diye", "Ramesh ne 1 tarikh ko 200 diye"])
def test_C04_unclear_day_asks(rs, text):
    expect_ask(rs.say(text), "unclear_date")


def test_C05_after_6_30_pm_ist_uses_the_ist_date(make_shop):
    s = make_shop(start=datetime(2026, 11, 21, 19, 0, tzinfo=IST), env={"SHOP_TZ": "Asia/Kolkata"})
    s.seed(("ramesh", "credit", 100))
    t = s.say("Ramesh ka 340 udhaar")
    expect_saved(t, ("credit", "ramesh", 340), shop=s)
    assert s.today.isoformat() == "2026-11-21"
    assert all(r["ts"].endswith("+05:30") for r in s.rows()), "ledger ts must carry the shop offset"


def test_C05_default_clock_reads_shop_time_when_the_server_runs_in_utc(shop, monkeypatch):
    """The server's clock says 19:30 UTC on the 21st; the shop day is the 22nd (01:00 IST)."""
    import app.pipeline as pipeline_module
    from app.pipeline import Pipeline, SessionState

    class UtcServer(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 11, 21, 19, 30, tzinfo=timezone.utc)
            return base.astimezone(tz) if tz else base

    monkeypatch.setattr(pipeline_module, "datetime", UtcServer)
    shop.seed(("ramesh", "credit", 100))
    pipe = Pipeline(shop.ledger, shop.settings)
    before = shop.count()
    out = pipe.run_turn(SessionState(session_id="utc0001", disclosed=True), "Ramesh ka 340 udhaar")
    rows = shop.rows()[before:]
    assert out.status == "ok" and [r["date"] for r in rows] == ["2026-11-22"], (out.reply_text, rows)
    assert rows[0]["ts"].endswith("+05:30"), rows[0]["ts"]


def test_C06_five_past_midnight_is_the_new_shop_day(make_shop):
    s = make_shop(start=datetime(2026, 11, 22, 0, 5, tzinfo=IST))
    s.seed(("ramesh", "credit", 100, 1))
    expect_saved(s.say("Ramesh ka 340 udhaar"), ("credit", "ramesh", 340), shop=s)
    assert s.rows()[-1]["date"] == "2026-11-22"
    expect_saved(s.say("kal 200 diya tha"), ("payment", "ramesh", 200, 1), shop=s)
    assert s.rows()[-1]["date"] == "2026-11-21"
    t = s.say("Aaj kitna udhaar gaya")
    assert "340" in t.reply_text, t.describe()


@pytest.mark.parametrize("start,expected", [
    (datetime(2027, 1, 1, 10, 0, tzinfo=IST), "2026-12-30"),
    (datetime(2026, 12, 1, 10, 0, tzinfo=IST), "2026-11-29"),
    (datetime(2026, 3, 1, 10, 0, tzinfo=IST), "2026-02-27"),
])
def test_C07_parso_across_month_and_year_ends(make_shop, start, expected):
    s = make_shop(start=start)
    s.seed(("ramesh", "credit", 1000))
    t = s.say("Ramesh ne parso 200 diye")
    assert [r["date"] for r in t.saved] == [expected], t.describe()


def test_C07_kal_on_the_first_is_the_last_of_the_month(make_shop):
    s = make_shop(start=datetime(2027, 1, 1, 10, 0, tzinfo=IST))
    s.seed(("ramesh", "credit", 1000))
    t = s.say("Ramesh ne kal 50 diye")
    assert [r["date"] for r in t.saved] == ["2026-12-31"], t.describe()


def test_C03_future_words_with_no_amount_save_nothing(rs):
    expect_nothing_saved(rs.say("Ramesh kal aayega"))


def test_C07_din_pehle_counts_back(rs):
    t = rs.say("Ramesh ne teen sau do din pehle diye")
    expect_saved(t, ("payment", "ramesh", 300, 2), shop=rs)


def test_C03_future_is_not_confused_with_past_kal(rs):
    t = rs.say("Ramesh ne kal 300 diye")
    assert [r["date"] for r in t.saved] == [(rs.today - timedelta(days=1)).isoformat()], t.describe()


def test_C08_screen_order_is_by_event_date_and_audit_order_by_creation(live_stack):
    live_stack.seed_customer("ramesh")
    live_stack.add_event("ramesh", "credit", 111, days_ago=0)
    live_stack.add_event("ramesh", "credit", 222, days_ago=3)
    by_created = live_stack.get("/api/ledger", params={"order": "created"}).json()["entries"]
    by_date = live_stack.get("/api/ledger", params={"order": "date"}).json()["entries"]
    assert [e["amount"] for e in by_created] == [222, 111], f"order=created: {[e['amount'] for e in by_created]}"
    assert [e["amount"] for e in by_date] == [111, 222], f"order=date: {[e['amount'] for e in by_date]}"
    only = live_stack.get("/api/ledger", params={"order": "date", "customer_id": by_date[0]["customer"]["id"]})
    assert len(only.json()["entries"]) == 2


def test_C09_wrong_phone_clock_is_kept_apart_from_the_server_time(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    c = live_stack.session()
    turn = c.text("Ramesh ne 40 diye", utt_id="utt-c09", client_ts="2001-01-01T00:00:00+00:00")
    assert turn.result["status"] == "ok", turn.result
    saved = [r for r in live_stack.rows() if r["session_id"] != "seed"][-1]
    server_day = live_stack.clock().astimezone(IST).date().isoformat()
    assert saved["date"] == server_day and saved["ts"].startswith(server_day), saved
    assert live_stack.ledger.read_utterance("utt-c09").get("device_ts") == "2001-01-01T00:00:00+00:00"
