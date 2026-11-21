"""Scores, distances and identifiers are never amounts: "250 run bane", "4 wicket liye", "phone number 98"."""
from __future__ import annotations

from datetime import date

import pytest

from nlu.parser import parse

TODAY = date(2026, 11, 21)
CTX = {"customers": [{"id": 1, "key": "ramesh", "name": "Ramesh", "tags": [], "aliases": []}],
       "limits": {"strict": True, "confirm_new_customer": True}}


@pytest.mark.parametrize("sentence", [
    "kal match mein 250 run bane", "India ne 300 run banaye", "Ramesh ne 4 wicket liye", "Ramesh 5 over khela",
    "Ramesh 10 km chala", "Ramesh ka phone number 98 hai", "Ramesh class 8 mein hai",
])
def test_not_a_khata_sentence(sentence):
    r = parse(sentence, today=TODAY, ctx=CTX)
    assert (r["status"], r.get("reason")) == ("rejected", "not_ledger"), r


@pytest.mark.parametrize("sentence", ["Ramesh ne 4 wicket liye aur 200 udhaar liya", "flat 302 wale Ramesh ka 340 udhaar"])
def test_a_score_or_identifier_is_never_offered_as_the_amount(sentence):
    r = parse(sentence, today=TODAY, ctx=CTX)
    pending = r.get("pending") or {}
    amounts = {e.get("amount") for e in (r.get("events") or []) + (pending.get("events") or [])}
    assert not amounts & {4, 302}, r  # before this rule: "Ramesh, ₹4 udhaar likhun?"


def test_ordinary_entries_are_unchanged():
    assert parse("Ramesh ka 340 udhaar", today=TODAY, ctx=CTX)["events"][0]["amount"] == 340
    assert parse("5 din pehle Ramesh ne 200 diye", today=TODAY, ctx=CTX)["events"][0]["kind"] == "payment"
    assert parse("Ramesh ne 2 kilo chawal liye", today=TODAY, ctx=CTX)["question"] == "Kitne ka?"


def test_phone_number_in_words_with_a_full_stop():  # Gnani's transcript of the screenshot case
    r = parse("Ramesh ka phone number ninety eight hai.", today=TODAY, ctx=CTX)
    assert (r["status"], r.get("reason")) == ("rejected", "not_ledger"), r
