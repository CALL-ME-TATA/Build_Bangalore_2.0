"""L. Session state (docs/EDGE_CASES.md section L, CONTRACT 1.14 and 3.3)."""
from __future__ import annotations

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_saved


def test_L01_add_kar_do_right_after_an_entry_carries_over(rs):
    rs.say("Ramesh ka 340 udhaar")
    expect_saved(rs.say("200 add kar do"), ("credit", "ramesh", 200), shop=rs)


def test_L01_a_form_without_direction_takes_the_kind_of_the_last_entry(rs):
    rs.say("Ramesh ne 100 diye")
    expect_saved(rs.say("50 add kar do"), ("payment", "ramesh", 50), shop=rs)


def test_L02_after_60_seconds_the_customer_does_not_carry_over(rs):
    rs.say("Ramesh ka 340 udhaar")
    rs.wait(61)
    expect_ask(rs.say("200 add kar do"), "missing_customer")


def test_L02_within_60_seconds_it_still_carries_over(rs):
    rs.say("Ramesh ka 340 udhaar")
    rs.wait(50)
    expect_saved(rs.say("200 add kar do"), ("credit", "ramesh", 200), shop=rs)


def test_L03_no_recent_customer_asks(rs):
    expect_ask(rs.say("200 add kar do"), "missing_customer")


@pytest.mark.parametrize("text", [
    "Ramesh ke khate mein 100 add kar do", "Ramesh ke khate mein 100 likh do",
    "Ramesh ke khate mein 100 daal do", "Ramesh ke khate mein 100 chadha do",
    "put 100 on Ramesh's account", "note 100 for Ramesh", "Ramesh 100 note kar lo",
])
def test_L04_action_words(rs, text):
    expect_saved(rs.say(text), ("credit", "ramesh", 100), shop=rs)


def test_L05_refresh_clears_the_open_question(live_stack):
    live_stack.seed_customer("sunita", credit=100)
    a = live_stack.session()
    asked = a.text("Sunita ka 500")
    assert asked["result"]["status"] == "needs_clarification", asked["result"]
    sid = a.session_id
    a.close()
    b = live_stack.session(resume=sid)
    n = live_stack.count()
    answered = b.text("udhaar")
    assert live_stack.count() == n, "the question must not survive a page refresh"
    assert answered["result"]["status"] != "ok", answered["result"]


def test_L05_an_automatic_reconnect_with_keep_pending_keeps_the_question(live_stack):
    live_stack.seed_customer("sunita", credit=100)
    a = live_stack.session()
    assert a.text("Sunita ka 500")["result"]["status"] == "needs_clarification"
    sid = a.session_id
    a.close()
    b = live_stack.session(resume=sid, keep_pending=True)
    done = b.text("udhaar")
    assert done["result"]["status"] == "ok" and live_stack.balance("sunita") == 600, done["result"]


def test_L06_aur_after_a_query_asks_direction(rs):
    rs.say("Sunita ka total?")
    expect_ask(rs.say("aur 200"), "ambiguous_direction")
