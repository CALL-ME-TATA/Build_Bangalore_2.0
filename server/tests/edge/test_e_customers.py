"""E. Customers and names (docs/EDGE_CASES.md section E, CONTRACT 1.8, 1.12 and 1.14)."""
from __future__ import annotations

import itertools
import time

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_reject, expect_saved, parse, roster


def two_ramesh(shop):
    shop.seed(("ramesh", "credit", 100, 0, "chai wale"), ("ramesh", "credit", 100, 0, "gali wale"))


def test_E01_two_customers_named_ramesh_asks_which(shop):
    two_ramesh(shop)
    t = shop.say("Ramesh ka 50 udhaar")
    expect_ask(t, "same_name")
    ids = {c["id"] for c in (t.candidates or [])}
    assert ids == {shop.cid("ramesh", "chai wale"), shop.cid("ramesh", "gali wale")}, t.describe()


@pytest.mark.parametrize("answer,tag", [("chai wale", "chai wale"), ("pehla wala", "chai wale"),
                                         ("doosra wala", "gali wale")])
def test_E02_answer_resolves_by_tag_or_order(shop, answer, tag):
    two_ramesh(shop)
    expect_ask(shop.say("Ramesh ka 50 udhaar"), "same_name")
    t = shop.say(answer)
    assert t.status == "ok" and [r["customer_id"] for r in t.saved] == [shop.cid("ramesh", tag)], t.describe()
    assert [(r["kind"], r["amount"]) for r in t.saved] == [("credit", 50)]


def test_E02_silence_drops_the_question_after_60_seconds(shop):
    two_ramesh(shop)
    expect_ask(shop.say("Ramesh ka 50 udhaar"), "same_name")
    shop.wait(61)
    t = shop.say("chai wale")
    expect_nothing_saved(t, "an expired question must not be answered")


@pytest.mark.parametrize("spoken", ["Suneeta", "Sunitha"])
def test_E03_spelling_drift_is_the_same_customer(shop, spoken):
    shop.seed(("sunita", "credit", 100))
    t = shop.say(f"{spoken} ka 50 udhaar")
    expect_saved(t, ("credit", "sunita", 50), shop=shop)
    assert [c["name"] for c in shop.customers()] == ["sunita"], "no second customer may be created"


def test_E04_a_name_close_to_nobody_is_asked(rs):
    t = rs.say("Zubair ka 340 udhaar")
    expect_ask(t, "new_customer")
    assert not any(c["name"] == "zubair" for c in rs.customers())


@pytest.mark.parametrize("spoken", ["Ramesh", "Rakes"])
def test_E05_close_names_are_asked(shop, spoken):
    shop.seed(("rakesh", "credit", 100))
    t = shop.say(f"{spoken} ka 50 udhaar")
    expect_ask(t, "new_customer")
    assert shop.cid("rakesh") in {c["id"] for c in (t.candidates or [])}, t.describe()


def test_E05_phonetic_spelling_of_rakesh_is_the_same_customer(shop):
    shop.seed(("rakesh", "credit", 100))
    expect_saved(shop.say("Raakesh ka 50 udhaar"), ("credit", "rakesh", 50), shop=shop)


@pytest.mark.parametrize("text,want", [
    ("Kiran ne 50 diye", ("payment", "kiran", 50)), ("Ganga ko 20 udhaar", ("credit", "ganga", 20)),
    ("Raja ka 30 udhaar", ("credit", "raja", 30)), ("Sagar ne 10 diye", ("payment", "sagar", 10)),
])
def test_E06_common_word_names_are_the_stored_customer(shop, text, want):
    shop.seed(("kiran", "credit", 100), ("ganga", "credit", 100), ("raja", "credit", 100), ("sagar", "credit", 100))
    expect_saved(shop.say(text), want, shop=shop)


@pytest.mark.parametrize("text,want", [
    ("Das ko 500 udhaar", ("credit", "das", 500)), ("Das ne 50 diye", ("payment", "das", 50)),
    ("Tina ka 340 udhaar", ("credit", "tina", 340)), ("Lakhan ne 20 diye", ("payment", "lakhan", 20)),
])
def test_E07_number_word_names_are_not_broken_up(shop, text, want):
    shop.seed(("das", "credit", 100), ("tina", "credit", 100), ("lakhan", "credit", 100))
    expect_saved(shop.say(text), want, shop=shop)


@pytest.mark.parametrize("text,want", [
    ("Sharma ji ka 50 udhaar", ("credit", "sharma", 50)), ("Ramesh bhaiya ne 20 diye", ("payment", "ramesh", 20)),
    ("Sunita aunty ko 30 udhaar", ("credit", "sunita", 30)),
])
def test_E08_honorific_is_dropped(shop, text, want):
    shop.seed(("sharma", "credit", 100), ("ramesh", "credit", 100), ("sunita", "credit", 100))
    expect_saved(shop.say(text), want, shop=shop)


def test_E09_unknown_name_is_asked_before_creating(rs):
    t = rs.say("Mahesh ka 340 udhaar")
    expect_ask(t, "new_customer")
    assert not any(c["name"] == "mahesh" for c in rs.customers()), "the customer must not exist before the answer"
    t2 = rs.say("haan")
    expect_saved(t2, ("credit", "mahesh", 340), shop=rs)
    assert any(c["name"] == "mahesh" for c in rs.customers())


def test_E09_no_answer_keeps_the_customer_out(rs):
    expect_ask(rs.say("Mahesh ka 340 udhaar"), "new_customer")
    t = rs.say("nahi")
    expect_reject(t, "cancelled")
    assert not any(c["name"] == "mahesh" for c in rs.customers())


def test_E10_alias_resolves_to_the_customer():
    ctx = {"customers": [{"id": "c1", "name": "shiva", "tags": [], "aliases": ["shivu"]}]}
    r = parse("Shivu ka 100 udhaar", ctx=ctx)
    assert r["status"] == "ok", r
    ev = r["events"][0]
    assert (ev["customer"], ev.get("customer_id"), ev["amount"], ev["kind"]) == ("shiva", "c1", 100, "credit"), r


def test_E10_alias_map_resolves_to_the_customer():
    ctx = {"customers": [{"id": "c1", "name": "shiva", "tags": []}], "aliases": {"shivu": "shiva"}}
    r = parse("Shivu ka 100 udhaar", ctx=ctx)
    assert r["status"] == "ok" and r["events"][0]["customer"] == "shiva", r


def test_E11_tag_picks_the_customer(shop):
    two_ramesh(shop)
    t = shop.say("Ramesh chai wale ka 50 udhaar")
    assert t.status == "ok" and [r["customer_id"] for r in t.saved] == [shop.cid("ramesh", "chai wale")], t.describe()


def test_E12_name_alone_asks_what_to_write(rs):
    t = rs.say("Ramesh")
    expect_ask(t, "missing_amount")
    expect_saved(rs.say("340 udhaar"), ("credit", "ramesh", 340), shop=rs)


def test_E12_unknown_word_alone_is_not_a_command(rs):
    expect_reject(rs.say("Zzyzx"), "not_ledger")


def test_E14_customer_with_no_entries(shop):
    shop.customer("ramesh")
    t = shop.say("Ramesh ka total?")
    assert t.status == "ok" and t.action == "query", t.describe()
    assert t.reply_text == "Ramesh ka koi hisaab nahi hai.", t.describe()
    expect_nothing_saved(t)


@pytest.mark.parametrize("probe", ["exact", "fuzzy"])
def test_E15_thousand_customers_parse_under_10_ms(shop, probe):
    syl = ["ra", "me", "su", "ni", "ka", "vi", "mo", "ha", "ge", "ta", "la", "pu", "di", "sha", "ro"]
    names = ["".join(p) for p in itertools.product(syl, repeat=3)][:1000]
    for n in names:
        shop.ledger.create_customer(n)
    ctx = {"customers": shop.ledger.customers_for_parser()}
    assert len(ctx["customers"]) == 1000
    spoken = names[517] if probe == "exact" else names[517] + "h"
    best = min(_timed(lambda: parse(f"{spoken.title()} ka 340 udhaar", ctx=ctx)) for _ in range(7))
    assert best < 0.010, f"best of 7 parses took {best * 1000:.1f} ms with 1000 customers ({probe})"


def _timed(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0
