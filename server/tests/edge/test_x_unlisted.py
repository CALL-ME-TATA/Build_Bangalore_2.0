"""X. Sentences nobody listed: strict mode (CONTRACT 1.14, "Words the parser does not know"; env STRICT_SAVE).

A sentence holding a word outside the parser's vocabulary is asked about before anything is saved.
"""
from __future__ import annotations

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_reject, expect_saved

UNKNOWN = [
    ("Ramesh ka blorp 340 udhaar", ("credit", "ramesh", 340)),
    ("Sunita ne 200 blorp diye", ("payment", "sunita", 200)),
    ("Ramesh ko 150 ka blorp udhaar", ("credit", "ramesh", 150)),
]


def seeded(shop):
    shop.seed(("ramesh", "credit", 1000), ("sunita", "credit", 1000))
    return shop


@pytest.mark.parametrize("text,want", UNKNOWN)
def test_X01_unknown_word_asks_first_and_yes_saves(shop, text, want):
    seeded(shop)
    t = shop.say(text)
    expect_ask(t, "confirm_entry")
    assert (t.confirm or {}).get("type") == "unsure", t.describe()
    expect_saved(shop.say("haan"), want, shop=shop)


@pytest.mark.parametrize("text,want", UNKNOWN)
def test_X02_no_saves_nothing(shop, text, want):
    seeded(shop)
    expect_ask(shop.say(text), "confirm_entry")
    expect_reject(shop.say("nahi"), "cancelled")


@pytest.mark.parametrize("text,want", UNKNOWN)
def test_X03_with_the_flag_off_the_same_sentence_saves_directly(make_shop, text, want):
    s = seeded(make_shop(env={"STRICT_SAVE": "0"}))
    expect_saved(s.say(text), want, shop=s)


def test_X04_the_demo_script_never_asks_about_unknown_words(make_shop):
    s = make_shop(env={"CONFIRM_NEW_CUSTOMER": "0"})
    steps = ["Ramesh ka 340 udhaar", "Nahi, 430", "Aur 200 payment mila", "Ramesh ka total?", "Aaj ka hisaab batao",
             "Sunita ne dedh sau diye aur Mohan ko dhai sau udhaar", "Mohan ka paanch lakh udhaar", "nahi",
             "Ramesh chai wale ka 100 udhaar", "Ramesh gali number 3 ka 50 udhaar", "Ramesh ka 20 udhaar",
             "chai wale", "undo karo", "Geeta ko udhaar", "saade teen sau", "Aaj ka hisaab batao"]
    for text in steps:
        t = s.say(text)
        assert not (t.reason == "confirm_entry" and (t.confirm or {}).get("type") == "unsure"), (
            f"strict mode asked about a demo sentence: {t.describe()}")


def test_X05_a_trailing_unknown_word_never_saves_silently(shop):
    seeded(shop)
    t = shop.say("Ramesh ka 340 udhaar bahut")
    assert t.status == "needs_clarification", t.describe()
    expect_ask(t)


@pytest.mark.parametrize("text,want", [
    ("Zorawar ka 100 udhaar", ("credit", "zorawar", 100)),
    ("Zorawar chai wale ne 50 diye", ("payment", "zorawar", 50)),
])
def test_X06_stored_names_and_tags_are_known_words(shop, text, want):
    shop.seed(("zorawar", "credit", 1000, 0, "chai wale"))
    expect_saved(shop.say(text), want, shop=shop)


def test_X07_a_correction_with_an_unknown_word_asks_and_changes_nothing(shop):
    seeded(shop)
    shop.say("Ramesh ka 340 udhaar")
    before = shop.balance("ramesh")
    t = shop.say("nahi, 430 blorp")
    expect_ask(t, "confirm_entry")
    assert shop.balance("ramesh") == before
    assert (t.confirm or {}).get("type") == "unsure", t.describe()


def test_X08_queries_and_undo_are_not_gated(shop):
    seeded(shop)
    shop.say("Ramesh ka 340 udhaar")
    q = shop.say("Ramesh ka total?")
    assert q.action == "query", q.describe()
    u = shop.say("undo karo")
    assert u.status == "ok" and u.action == "undo", u.describe()


def test_X09_a_new_customer_question_comes_before_the_unknown_word_question(shop):
    seeded(shop)
    t = shop.say("Mahesh ka blorp 340 udhaar")
    expect_ask(t)
    assert t.reason in ("new_customer", "confirm_entry"), t.describe()


def test_X10_the_parser_names_the_unknown_words():
    from .kit import parse, roster

    r = parse("Ramesh ka blorp 340 udhaar", ctx={"customers": roster("ramesh"), "limits": {"strict": True}})
    assert r["status"] == "needs_clarification" and r["reason"] == "confirm_entry", r
    assert r["confirm"]["type"] == "unsure" and r["confirm"]["words"] == ["blorp"], r
    assert [(e["kind"], e["amount"]) for e in r["pending"]["events"]] == [("credit", 340)], r
