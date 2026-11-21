"""D. Compound sentences, corrections and undo (docs/EDGE_CASES.md section D, CONTRACT 1.6, 1.12, 1.14)."""
from __future__ import annotations

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_reject, expect_saved


def test_D01_two_events_in_one_sentence(rs):
    t = rs.say("Ramesh ka 340 udhaar, kal 200 diya tha")
    expect_saved(t, ("credit", "ramesh", 340), ("payment", "ramesh", 200, 1), shop=rs)


def test_D02_nahi_amount_amends_the_last_entry(rs):
    expect_saved(rs.say("Ramesh ka 340 udhaar"), ("credit", "ramesh", 340), shop=rs)
    t = rs.say("nahi, 430")
    assert t.status == "ok" and t.action == "amend", t.describe()
    assert [(r["kind"], r["amount"]) for r in t.saved] == [("credit", 430)], t.describe()
    assert len(t.reversals) == 1 and t.reversals[0]["amount"] == 340, t.describe()
    assert rs.balance("ramesh") == 1430


def test_D03_correction_with_no_earlier_entry(rs):
    t = rs.say("nahi, 430")
    expect_reject(t, "no_last_event")
    assert t.reply_text == "Pehle koi entry nahi hai.", t.describe()


def test_D04_nahi_x_nahi_y_changes_the_customer_only(rs):
    rs.say("Ramesh ka 200 udhaar")
    t = rs.say("nahi, Ramesh ka nahi, Sunita ka 200")
    assert t.status == "ok" and t.action == "amend", t.describe()
    assert [(r["kind"], r["customer"], r["amount"]) for r in t.saved] == [("credit", "sunita", 200)], t.describe()
    assert rs.balance("ramesh") == 1000 and rs.balance("sunita") == 1200


def test_D05_correction_after_two_entries_asks_which(rs):
    expect_saved(rs.say("Ramesh ka 340 udhaar, kal 200 diya tha"),
                 ("credit", "ramesh", 340), ("payment", "ramesh", 200, 1), shop=rs)
    t = rs.say("nahi, 430")
    expect_ask(t, "unclear_correction")
    t2 = rs.say("pehli")
    assert t2.status == "ok" and t2.action == "amend", t2.describe()
    assert [(r["kind"], r["amount"]) for r in t2.saved] == [("credit", 430)], t2.describe()
    assert rs.balance("ramesh") == 1000 + 430 - 200


def test_D06_aur_keeps_customer_and_kind(rs):
    rs.say("Ramesh ka 340 udhaar")
    expect_saved(rs.say("aur 200"), ("credit", "ramesh", 200), shop=rs)
    assert rs.balance("ramesh") == 1540


def test_D06_aur_after_a_payment_is_a_payment(rs):
    rs.say("Ramesh ne 50 diye")
    expect_saved(rs.say("aur 20"), ("payment", "ramesh", 20), shop=rs)


def test_D07_aur_after_a_query_asks_direction(rs):
    rs.say("Ramesh ka 340 udhaar")
    rs.say("Ramesh ka total")
    expect_ask(rs.say("aur 200"), "ambiguous_direction")


def test_D08_undo_adds_a_reversal(rs):
    rs.say("Ramesh ka 340 udhaar")
    before = rs.count()
    t = rs.say("undo karo")
    assert t.status == "ok" and t.action == "undo", t.describe()
    assert rs.count() == before + 1 and len(t.reversals) == 1 and not t.saved, t.describe()
    assert rs.balance("ramesh") == 1000
    assert len([r for r in rs.entries() if r["amount"] == 340]) == 1, "the original row stays"


def test_D09_undo_with_nothing_to_undo(rs):
    t = rs.say("undo karo")
    expect_reject(t, "no_last_event")
    assert t.reply_text == "Undo karne ke liye kuch nahi hai.", t.describe()


def _undo(shop):
    """`undo karo`; CONTRACT 1.15 may answer with the undo-check question, which `haan` confirms."""
    t = shop.say("undo karo")
    if t.status == "needs_clarification":
        assert t.reason == "unclear_correction", t.describe()
        t = shop.say("haan")
    return t


def test_D10_second_undo_reverses_the_previous_entry_and_nothing_twice(rs):
    rs.say("Ramesh ka 100 udhaar")
    rs.say("Ramesh ka 50 udhaar")
    u1 = _undo(rs)
    u2 = _undo(rs)
    assert [r["amount"] for r in u1.reversals] == [50], u1.describe()
    assert [r["amount"] for r in u2.reversals] == [100], u2.describe()
    assert rs.balance("ramesh") == 1000
    u3 = rs.say("undo karo")
    expect_reject(u3, "no_last_event")
    targets = [r["supersedes_id"] for r in rs.rows() if r["kind"] == "reversal"]
    assert len(targets) == len(set(targets)), "an entry was reversed twice"


def test_D11_correction_after_undo_is_blocked(rs):
    rs.say("Ramesh ka 100 udhaar")
    rs.say("Ramesh ka 340 udhaar")
    rs.say("undo karo")
    n = rs.count()
    t = rs.say("nahi, 430")
    expect_reject(t, "no_last_event")
    assert rs.count() == n
    assert rs.balance("ramesh") == 1100, "an older entry must not be amended in place of the removed one"


@pytest.mark.parametrize("text", ["Ramesh ka 340 nahi 430 ruko", "Ramesh ka 340 udhaar ruko", "ruko"])
def test_D12_ruko_stops_it(rs, text):
    expect_reject(rs.say(text), "cancelled")


@pytest.mark.parametrize("word", ["cancel", "chhodo", "rehne do"])
def test_D13_cancel_words_clear_the_open_question(rs, word):
    expect_ask(rs.say("Sunita ka 500"), "ambiguous_direction")
    expect_reject(rs.say(word), "cancelled")
    t = rs.say("udhaar")
    expect_nothing_saved(t, "the dropped question must not be completed by a later answer")


def test_D14_two_customers_in_one_sentence(rs):
    t = rs.say("Ramesh ka 340 udhaar aur Sunita ka 200 payment")
    expect_saved(t, ("credit", "ramesh", 340), ("payment", "sunita", 200), shop=rs)


@pytest.mark.parametrize("text,want", [
    ("uh Ramesh ka matlab 340 udhaar", ("credit", "ramesh", 340)),
    ("wo na Sunita ne bhai 200 diye", ("payment", "sunita", 200)),
    ("umm Ramesh ka 50 udhaar hmm", ("credit", "ramesh", 50)),
])
def test_D15_fillers_are_ignored(rs, text, want):
    expect_saved(rs.say(text), want, shop=rs)


@pytest.mark.parametrize("text", ["Ramesh ka 340 udhaar, nahi 430", "Ramesh ka 340 nahi nahi 430 udhaar"])
def test_D16_self_correction_inside_one_sentence(rs, text):
    t = rs.say(text)
    expect_saved(t, ("credit", "ramesh", 430), shop=rs)
    assert rs.balance("ramesh") == 1430


def test_D16_self_correction_without_a_direction_word_asks_direction_for_430(rs):
    """`Ramesh ka 340, nahi 430` has no direction word (1.4), so it asks; the amount asked about is 430."""
    t = rs.say("Ramesh ka 340, nahi 430")
    expect_ask(t, "ambiguous_direction")
    pending = rs.state.pending or {}
    assert [e.get("amount") for e in pending.get("events", [])] == [430], pending
    expect_saved(rs.say("udhaar"), ("credit", "ramesh", 430), shop=rs)
