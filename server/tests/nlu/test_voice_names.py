"""Names that speech-to-text repeated, split or misheard (seen in a live voice session)."""
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
ROSTER = [{"id": "c1", "name": "ramesh", "tags": []}, {"id": "c2", "name": "divakar", "tags": []},
          {"id": "c3", "name": "tanishk", "tags": []}, {"id": "c4", "name": "sunita", "tags": []},
          {"id": "c5", "name": "diwa kar", "tags": []} if False else {"id": "c5", "name": "mohan lal", "tags": []}]


def run(utterance, customers=ROSTER, confirm_new=False):
    return parse(utterance, today=T, ctx={"customers": customers, "limits": {"confirm_new_customer": confirm_new}})


def customer_of(r):
    events = r.get("events") or (r.get("pending") or {}).get("events") or [{}]
    return events[0].get("customer"), events[0].get("customer_id")


# 1. A name said twice in slightly different spellings is one name -------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramish Ramesh ne 5 diye", "Ramesh Ramish ne 5 diye", "Rameysh Ramesh ka 20 udhaar",
                                       "Sunitha Sunita ne 100 diye"])
def test_repeated_name_in_two_spellings_is_the_stored_customer(utterance):
    r = run(utterance, confirm_new=True)
    assert r["status"] == "ok", r
    assert customer_of(r)[1] in ("c1", "c4")


def test_real_two_word_name_is_not_collapsed():
    r = run("Ramesh Chopra ka 50 udhaar")
    assert customer_of(r) == ("ramesh chopra", None) and r["events"][0]["new_customer"] is True


def test_two_different_stored_customers_are_not_collapsed():
    roster = ROSTER + [{"id": "c9", "name": "ramish", "tags": []}]
    r = run("Ramish Ramesh ne 5 diye", customers=roster, confirm_new=True)
    assert customer_of(r)[1] is None  # neither customer is picked silently


def test_stored_two_word_name_still_matches_exactly():
    assert customer_of(run("Mohan Lal ne 30 diye")) == ("mohan lal", "c5")


# 2. A name split or joined by speech-to-text --------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Diwa Kar ka 50 udhaar", "Diva Kar ne 50 diye", "Divakar ka 50 udhaar"])
def test_split_name_matches_the_stored_name(utterance):
    assert customer_of(run(utterance, confirm_new=True)) == ("divakar", "c2")


@pytest.mark.parametrize("utterance", ["Mohanlal ne 30 diye", "Mohanlaal ka 30 udhaar"])
def test_joined_name_matches_a_stored_two_word_name(utterance):
    assert customer_of(run(utterance, confirm_new=True)) == ("mohan lal", "c5")


def test_split_name_matching_two_customers_is_left_to_the_question():
    roster = ROSTER + [{"id": "c8", "name": "diwakar", "tags": []}]
    r = run("Diwa Kar ka 50 udhaar", customers=roster, confirm_new=True)
    assert r["status"] == "needs_clarification"


# 3. A differing consonant makes a close candidate ----------------------------------------------------------------

@pytest.mark.parametrize("spoken,stored", [
    ("Jamesh", "ramesh"),     # first consonant
    ("Ravesh", "ramesh"),     # middle consonant
    ("Ramek", "ramesh"),      # last consonant
    ("Sunil", "sunit"),       # last consonant
    ("Mohin", "mohan"),       # a vowel differs: not close by the consonant rule, but same skeleton -> same person
])
def test_one_consonant_differs_offers_the_close_customer(spoken, stored):
    roster = [{"id": "s1", "name": stored, "tags": []}]
    r = run(f"{spoken} ka 50 udhaar", customers=roster, confirm_new=True)
    if spoken == "Mohin":
        assert customer_of(r) == (stored, "s1")  # same consonants and ending: the same person (1.12)
        return
    assert r["reason"] == "new_customer", r
    assert [c["id"] for c in r["candidates"]] == ["s1"]
    assert r["question"] == f"{spoken} naya customer hai, ya {stored.capitalize()}?"


def test_jamesh_question_text():
    r = run("Jamesh ka 50 udhaar", confirm_new=True)
    assert r["question"] == "Jamesh naya customer hai, ya Ramesh?"


def test_tanishke_offers_tanishk():
    r = run("Tanishke ne 20 diye", confirm_new=True)
    assert r["reason"] == "new_customer" and r["candidates"][0]["id"] == "c3"
