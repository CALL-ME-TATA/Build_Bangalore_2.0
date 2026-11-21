"""G. What is not a command (docs/EDGE_CASES.md section G, CONTRACT 1.12 and 1.14)."""
from __future__ import annotations

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_query, expect_reject, expect_saved


def test_G01_a_plan_is_not_saved(rs):
    expect_reject(rs.say("Ramesh ko 500 dena hai"), "future")


def test_G02_a_conditional_is_not_saved(rs):
    expect_reject(rs.say("Agar Sunita 200 de to..."), "future")


def test_G03_a_tag_question_is_asked_or_answered_never_saved(rs):
    t = rs.say("Kal Ramesh ne 300 diya tha na?")
    assert t.status == "needs_clarification" or t.action == "query", t.describe()
    expect_nothing_saved(t)
    if t.status == "needs_clarification":
        assert t.reason == "confirm_entry" and (t.confirm or {}).get("type") == "hearsay", t.describe()


def test_G04_hearsay_is_asked_before_saving(rs):
    t = rs.say("Ramesh bol raha tha 340 udhaar")
    expect_ask(t, "confirm_entry")
    assert (t.confirm or {}).get("type") == "hearsay", t.describe()


def test_G04_hearsay_declined_saves_nothing(rs):
    rs.say("Ramesh bol raha tha 340 udhaar")
    expect_reject(rs.say("nahi"), "cancelled")


def test_G04_hearsay_confirmed_saves_the_entry_as_heard(rs):
    rs.say("Ramesh bol raha tha 340 udhaar")
    expect_saved(rs.say("haan"), ("credit", "ramesh", 340), shop=rs)


def test_G05_ten_lakh_is_confirmed(rs):
    t = rs.say("Ramesh ka toh 10 lakh udhaar hai!")
    expect_ask(t, ("plausibility", "confirm_entry"))


@pytest.mark.parametrize("text", ["haan", "nahi", "yes", "no"])
def test_G06_bare_yes_or_no_with_nothing_open(shop, text):
    t = shop.say(text)
    expect_reject(t, "no_question")


def test_G07_an_unrelated_sentence_is_not_an_answer_and_two_failures_drop_the_question(rs):
    expect_ask(rs.say("Sunita ka 500"), "ambiguous_direction")
    t1 = rs.say("mausam achha hai")
    expect_nothing_saved(t1)
    t2 = rs.say("kuch bhi nahi pata")
    expect_nothing_saved(t2)
    expect_nothing_saved(rs.say("udhaar"), "the dropped question must not be completed")


def test_G08_a_full_command_replaces_the_open_question(rs):
    expect_ask(rs.say("Sunita ka 500"), "ambiguous_direction")
    expect_saved(rs.say("Ramesh ne 200 diye"), ("payment", "ramesh", 200), shop=rs)
    expect_nothing_saved(rs.say("udhaar"), "the replaced question must be gone")


def test_G09_question_word_wins_over_the_amount(rs):
    t = rs.say("Ramesh ka 340 kitna hua?")
    expect_query(t)
    assert "1000" in t.reply_text.replace(",", ""), t.describe()


def test_G10_aaj_kitna_udhaar_gaya_is_a_query(rs):
    expect_query(rs.say("Aaj kitna udhaar gaya?"))


def test_G11_total_is_never_an_entry(rs):
    t = rs.say("Ramesh ka total?")
    expect_query(t)
    assert "1000" in t.reply_text.replace(",", ""), t.describe()
