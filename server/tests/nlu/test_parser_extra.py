"""Parser cases beyond the golden set: every direction row, correction form and pending answer, plus
mixed scripts, fillers, punctuation, case, rupee signs, regressions, and properties over arbitrary text."""
import time
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nlu.parser import _parse, parse

TODAY = date(2026, 11, 21)
D0, D1, D2 = "2026-11-21", "2026-11-20", "2026-11-19"
LAST = {"last_event": {"kind": "credit", "customer": "ramesh", "amount": 340, "date": D0}}
LAST_PAY = {"last_event": {"kind": "payment", "customer": "sunita", "amount": 200, "date": D1}}
TWO_RAMESH = [{"id": "c1", "name": "ramesh", "tags": ["chai wale"]},
              {"id": "c2", "name": "ramesh", "tags": ["gali number 3"]}]


def matches(expect, actual) -> bool:
    if isinstance(expect, dict):
        return isinstance(actual, dict) and all(k in actual and matches(v, actual[k]) for k, v in expect.items())
    if isinstance(expect, list):
        return isinstance(actual, list) and len(expect) == len(actual) and all(
            matches(e, a) for e, a in zip(expect, actual))
    return expect == actual


def ok(*events, action="append"):
    return {"status": "ok", "action": action, "events": [
        {"kind": k, "customer": c, "amount": a, "date": d} for k, c, a, d in events]}


def ask(reason):
    return {"status": "needs_clarification", "reason": reason}


def rej(reason):
    return {"status": "rejected", "reason": reason}


P, C = "payment", "credit"

CASES = [
    # --- Direction table (CONTRACT 1.4), one or more per row ---
    ("dir-ne-de-diya", "Ramesh ne 200 de diya", None, ok((P, "ramesh", 200, D0))),
    ("dir-de-gaya", "Ramesh 200 de gaya", None, ok((P, "ramesh", 200, D0))),
    ("dir-se-aaya", "Ramesh se 200 aaya", None, ok((P, "ramesh", 200, D0))),
    ("dir-ka-aaya", "Ramesh ka 200 aaya", None, ok((P, "ramesh", 200, D0))),
    ("dir-payment-aaya-asks-since-1-15", "300 payment aaya", LAST, ask("missing_customer")),
    ("dir-ne-jama-karaya", "Ramesh ne 300 jama karaya", None, ok((P, "ramesh", 300, D0))),
    ("dir-ke-jama-likh", "Ramesh ke jama 300 likh do", None, ok((P, "ramesh", 300, D0))),
    ("dir-chuka-diya", "Ramesh ne 200 chuka diya", None, ok((P, "ramesh", 200, D0))),
    ("dir-wapas-kiya", "Ramesh ne 100 wapas kiya", None, ok((P, "ramesh", 100, D0))),
    ("dir-cash-kiya", "Ramesh ne 500 cash kiya", None, ok((P, "ramesh", 500, D0))),
    ("dir-khate-se-kaat", "Ramesh ke khate se 100 kaat do", None, ok((P, "ramesh", 100, D0))),
    ("dir-english-paid", "Ramesh paid 200", None, ok((P, "ramesh", 200, D0))),
    ("dir-english-received", "received 200 from Ramesh", None, ok((P, "ramesh", 200, D0))),
    ("dir-bare-diya-asks-since-1-15", "200 diye", LAST, ask("missing_customer")),
    ("dir-pe-udhaar", "Ramesh pe 200 udhaar", None, ok((C, "ramesh", 200, D0))),
    ("dir-ko-diye", "Ramesh ko 200 diye", None, ok((C, "ramesh", 200, D0))),
    ("dir-le-liya", "Ramesh 200 le liya", None, ok((C, "ramesh", 200, D0))),
    ("dir-ne-saaman-liya", "Ramesh ne 200 ka saaman liya", None, ok((C, "ramesh", 200, D0))),
    ("dir-khate-mein-daal", "Ramesh ke khate mein 200 daal do", None, ok((C, "ramesh", 200, D0))),
    ("dir-likh-do", "Ramesh 200 likh do", None, ok((C, "ramesh", 200, D0))),
    ("dir-english-owes", "Ramesh owes 200", None, ok((C, "ramesh", 200, D0))),
    ("dir-english-took", "Ramesh took 200 on credit", None, ok((C, "ramesh", 200, D0))),
    ("dir-ask-ko-wapas", "Ramesh ko 100 wapas diya", None, ask("ambiguous_direction")),
    ("dir-ask-ko-payment", "Ramesh ko 100 payment kiya", None, ask("ambiguous_direction")),
    ("dir-ask-credit-word", "Ramesh ko 200 credit kar do", None, ask("ambiguous_direction")),
    ("dir-future-dene-hain", "Ramesh ko 200 dene hain", None, rej("future")),
    ("dir-ask-baaki", "Ramesh ke 500 rupaye baaki hain", None, ask("ambiguous_direction")),
    ("dir-ask-se-udhaar-liya", "Ramesh se 200 udhaar liya", None, ask("ambiguous_direction")),
    ("dir-ask-name-amount", "Ramesh 200", None, ask("ambiguous_direction")),
    ("dir-negated-aaya", "Ramesh ka 200 abhi tak nahi aaya", None, rej("negated")),
    ("dir-negated-after", "Ramesh ne diya nahi", None, rej("negated")),
    ("dir-future-aayega", "Ramesh ka 200 aayega", None, rej("future")),
    ("dir-future-dunga", "main 200 dunga", None, rej("future")),
    ("dir-kind-not-carried", "Ramesh ka 200 udhaar aur 100", None, ask("ambiguous_direction")),

    # --- Corrections, undo and carry-over (1.6) ---
    ("cor-galat-amount", "galat, 430", LAST, ok((C, "ramesh", 430, D0), action="amend")),
    ("cor-old-nahi-new", "340 nahi, 430", LAST, ok((C, "ramesh", 430, D0), action="amend")),
    ("cor-old-mismatch", "740 nahi, 430", LAST, ask("unclear_correction")),
    ("cor-customer", "Ramesh nahi, Suresh ko", LAST, ok((C, "suresh", 340, D0), action="amend")),
    ("cor-customer-mismatch", "Mahesh nahi, Suresh", LAST, ask("unclear_correction")),
    ("cor-kind", "nahi, payment tha", LAST, ok((P, "ramesh", 340, D0), action="amend")),
    ("cor-date", "nahi, kal ka tha", LAST, ok((C, "ramesh", 340, D1), action="amend")),
    ("cor-keeps-old-date", "nahi, 450", LAST_PAY, ok((P, "sunita", 450, D1), action="amend")),
    ("cor-amend-plausibility", "nahi, 70000", LAST, ask("plausibility")),
    ("cor-nahi-nahi", "nahi nahi", LAST, ask("unclear_correction")),
    ("cor-galat-hai", "galat hai", LAST, ask("unclear_correction")),
    ("cor-no-last", "galat, 430", None, rej("no_last_event")),
    ("undo-mita-do", "mita do", LAST, {"status": "ok", "action": "undo", "target": "last"}),
    ("undo-delete", "delete karo", LAST, {"status": "ok", "action": "undo", "target": "last"}),
    ("undo-pichla", "pichla entry hatao", LAST, {"status": "ok", "action": "undo", "target": "last"}),
    ("undo-old-event", "hata do", {"last_event": dict(LAST["last_event"], age_s=900)},
     {"status": "ok", "action": "undo", "target": "last"}),
    ("undo-no-last", "mita do", None, rej("no_last_event")),
    ("carry-aur-same-kind", "aur 200", LAST_PAY, ok((P, "sunita", 200, D0))),
    ("carry-aur-new-kind", "aur 200 udhaar", LAST_PAY, ok((C, "sunita", 200, D0))),
    ("carry-aur-date", "aur kal 200", LAST, ok((C, "ramesh", 200, D1))),
    ("carry-stale", "kal 200 diya tha", {"last_event": dict(LAST["last_event"], age_s=121)}, ask("missing_customer")),
    ("carry-within-sentence", "Ramesh ka 100 udhaar aur parso 50 diye", None,
     ok((C, "ramesh", 100, D0), (P, "ramesh", 50, D2))),
    ("carry-customer-id", "aur 200", {"last_event": dict(LAST["last_event"], customer_id="c9")},
     {"status": "ok", "events": [{"customer": "ramesh", "customer_id": "c9", "amount": 200}]}),

    # --- Answers to a pending question (1.9) ---
    ("pend-plaus-theek-hai", "theek hai", {"pending": {"reason": "plausibility", "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "amount": 60000, "date": D0}]}}, ok((C, "ramesh", 60000, D0))),
    ("pend-plaus-haan-ji", "haan ji", {"pending": {"reason": "plausibility", "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "amount": 60000, "date": D0}]}}, ok((C, "ramesh", 60000, D0))),
    ("pend-plaus-number-big", "sattar hazaar", {"pending": {"reason": "plausibility", "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "amount": 60000, "date": D0}]}}, ok((C, "ramesh", 70000, D0))),
    ("pend-plaus-amend", "haan", {"pending": {"reason": "plausibility", "action": "amend", "events": [
        {"kind": C, "customer": "ramesh", "amount": 70000, "date": D0}]}},
     {"status": "ok", "action": "amend", "target": "last"}),
    ("pend-plaus-cancel-word", "rehne do", {"pending": {"reason": "plausibility", "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "amount": 60000, "date": D0}]}}, rej("cancelled")),
    ("pend-conf-doosra-deva", "दूसरा", {"pending": {"reason": "confusable_number", "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "amount": 340, "date": D0}], "candidates": [340, 740]}},
     ok((C, "ramesh", 740, D0))),
    ("pend-conf-number-not-replausible", "saath hazaar", {"pending": {"reason": "confusable_number",
                                                                      "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "amount": 6000, "date": D0}], "candidates": [6000, 60000]}},
     ok((C, "ramesh", 60000, D0))),
    ("pend-amount-plausibility-still-applies", "saath hazaar", {"pending": {"reason": "missing_amount",
                                                                            "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "date": D0}]}}, ask("plausibility")),
    ("pend-amount-zero", "0", {"pending": {"reason": "missing_amount", "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "date": D0}]}}, rej("invalid_number")),
    ("pend-same-name-tag-loose", "chai wala", {"customers": TWO_RAMESH, "pending": {
        "reason": "same_name", "action": "append", "events": [{"kind": P, "customer": "ramesh", "amount": 200,
                                                               "date": D0}], "candidates": TWO_RAMESH}},
     {"status": "ok", "events": [{"customer_id": "c1"}]}),
    ("pend-same-name-gali", "gali 3 wale", {"customers": TWO_RAMESH, "pending": {
        "reason": "same_name", "action": "append", "events": [{"kind": P, "customer": "ramesh", "amount": 200,
                                                               "date": D0}], "candidates": TWO_RAMESH}},
     {"status": "ok", "events": [{"customer_id": "c2"}]}),
    ("pend-same-name-query-doosra", "doosra", {"customers": TWO_RAMESH, "pending": {
        "reason": "same_name", "action": "query", "query": {"type": "balance", "customer": "ramesh"},
        "candidates": TWO_RAMESH}},
     {"status": "ok", "action": "query", "query": {"type": "balance", "customer_id": "c2"}}),
    ("pend-customer-then-same-name", "Ramesh", {"customers": TWO_RAMESH, "pending": {
        "reason": "missing_customer", "action": "append", "events": [{"kind": C, "amount": 300, "date": D0}]}},
     ask("same_name")),
    ("pend-customer-with-ka", "Ramesh ka", {"pending": {"reason": "missing_customer", "action": "append",
                                                        "events": [{"kind": C, "amount": 300, "date": D0}]}},
     ok((C, "ramesh", 300, D0))),
    ("pend-customer-then-direction", "Ramesh", {"pending": {"reason": "missing_customer", "action": "append",
                                                            "events": [{"amount": 300, "date": D0}]}},
     ask("ambiguous_direction")),
    ("pend-direction-jama", "जमा", {"pending": {"reason": "ambiguous_direction", "action": "append", "events": [
        {"customer": "ramesh", "amount": 500, "date": D0}]}}, ok((P, "ramesh", 500, D0))),
    ("pend-direction-ko-udhaar", "ko udhaar", {"pending": {"reason": "ambiguous_direction", "action": "append",
                                                           "events": [{"customer": "ramesh", "amount": 500,
                                                                       "date": D0}]}},
     ok((C, "ramesh", 500, D0))),
    ("pend-direction-second-event", "udhaar", {"pending": {"reason": "ambiguous_direction", "action": "append",
                                                           "events": [
        {"kind": C, "customer": "ramesh", "amount": 100, "date": D0},
        {"customer": "sunita", "amount": 200, "date": D0}]}},
     ok((C, "ramesh", 100, D0), (C, "sunita", 200, D0))),
    ("pend-correction-number", "430", dict(LAST, pending={"reason": "unclear_correction", "action": "amend",
                                                          "events": []}),
     ok((C, "ramesh", 430, D0), action="amend")),
    ("pend-correction-undo", "mita do", dict(LAST, pending={"reason": "unclear_correction", "action": "amend",
                                                            "events": []}),
     {"status": "ok", "action": "undo", "target": "last"}),
    ("pend-date-kal", "kal", {"pending": {"reason": "unclear_date", "action": "append", "events": [
        {"kind": P, "customer": "ramesh", "amount": 200}]}}, ok((P, "ramesh", 200, D1))),
    ("pend-fresh-sentence-wins", "Sunita ne 300 diye", {"pending": {"reason": "plausibility", "action": "append",
                                                                    "events": [{"kind": C, "customer": "ramesh",
                                                                                "amount": 60000, "date": D0}]}},
     ok((P, "sunita", 300, D0))),
    ("pend-unrelated-reasks", "mausam kaisa hai", {"pending": {"reason": "missing_amount", "action": "append",
                                                               "events": [{"kind": C, "customer": "ramesh",
                                                                           "date": D0}]}},
     ask("missing_amount")),
    ("pend-cancel-any", "cancel karo", {"pending": {"reason": "missing_amount", "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "date": D0}]}}, rej("cancelled")),

    # --- Scripts, fillers, punctuation, case, rupee signs ---
    ("mix-deva-name-roman-rest", "रमेश ne 200 diye", None, ok((P, "ramesh", 200, D0))),
    ("mix-deva-digits", "सुनीता को ५०० उधार", None, ok((C, "sunita", 500, D0))),
    ("mix-deva-compound", "रमेश का ३४० उधार और सुनीता ने २०० दिए", None,
     ok((C, "ramesh", 340, D0), (P, "sunita", 200, D0))),
    ("mix-deva-correction", "नहीं, साढ़े तीन सौ", LAST, ok((C, "ramesh", 350, D0), action="amend")),
    ("mix-deva-undo", "पिछली एंट्री हटाओ", LAST, {"status": "ok", "action": "undo", "target": "last"}),
    ("fill-bhaiya-zara", "bhaiya zara Ramesh ka 100 udhaar likh do", None, ok((C, "ramesh", 100, D0))),
    ("fill-accha-ji", "accha ji Sunita ne 200 diye", None, ok((P, "sunita", 200, D0))),
    ("fill-please-end", "Ramesh ko 100 udhaar please", None, ok((C, "ramesh", 100, D0))),
    ("fill-to-middle", "Ramesh ne to 200 diye", None, ok((P, "ramesh", 200, D0))),
    ("fill-haan-start", "haan Ramesh ka 100 udhaar", None, ok((C, "ramesh", 100, D0))),
    ("fill-suno-deva", "सुनो रमेश का 100 उधार", None, ok((C, "ramesh", 100, D0))),
    ("punct-question-confirms-since-1-15", "Ramesh ne 200 diye?", None, ask("confirm_entry")),
    ("punct-semicolon", "Ramesh ka 100 udhaar; Sunita ne 50 diye", None,
     ok((C, "ramesh", 100, D0), (P, "sunita", 50, D0))),
    ("punct-danda-split", "रमेश का 100 उधार। सुनीता ने 50 दिए।", None,
     ok((C, "ramesh", 100, D0), (P, "sunita", 50, D0))),
    ("upper-deedh", "SUNITA NE DEEDH SAU DIYE.", None, ok((P, "sunita", 150, D0))),
    ("rupee-sign-space", "Ramesh ka ₹ 1,500 udhaar", None, ok((C, "ramesh", 1500, D0))),
    ("rupee-rs-after", "Ramesh ne 500 rs diye", None, ok((P, "ramesh", 500, D0))),
    ("rupee-indian-commas", "Ramesh ne ₹12,500/- diye", None, ok((P, "ramesh", 12500, D0))),
    ("spell-udhar-chalis", "ramesh ka teen sau chalis udhar", None, ok((C, "ramesh", 340, D0))),
    ("spell-diyaa", "Sunita ne paanch sau diyaa", None, ok((P, "sunita", 500, D0))),
    ("no-comma-two-names", "Ramesh ka 100 udhaar Sunita ne 50 diye", None,
     ok((C, "ramesh", 100, D0), (P, "sunita", 50, D0))),
    ("no-comma-dates", "Ramesh ka 200 udhaar kal 100 diye parso 50 diye", None,
     ok((C, "ramesh", 200, D0), (P, "ramesh", 100, D1), (P, "ramesh", 50, D2))),
    ("english-numbers-sentence", "Ramesh ne two thousand five hundred diye", None, ok((P, "ramesh", 2500, D0))),

    # --- Dates (1.5) ---
    ("date-din-pehle-deva", "रमेश ने तीन दिन पहले 100 दिए", None, ok((P, "ramesh", 100, "2026-11-18"))),
    ("date-tarikh", "Ramesh ne 15 tarikh ko 200 diye", None, ask("unclear_date")),
    ("date-kuch-din", "Ramesh ne kuch din pehle 200 diye", None, ask("unclear_date")),
    ("date-pichle-mahine", "pichle mahine Ramesh ne 200 diye", None, ask("unclear_date")),
    ("date-two-words", "aaj kal Ramesh ne 200 diye", None, ask("unclear_date")),

    # --- Customers and guards ---
    ("cust-multiword", "Ramesh Kumar ka 200 udhaar", None, ok((C, "ramesh kumar", 200, D0))),
    ("cust-two-names-missing-amount", "Ramesh, Suresh ko 200 diya", None, ask("missing_amount")),
    ("cust-tag-only-roster", "chai wale ka 200 udhaar", {"customers": TWO_RAMESH},
     {"status": "ok", "events": [{"customer": "ramesh", "customer_id": "c1"}]}),
    ("cust-tag-only-no-roster", "chai wale ka 200 udhaar", None, ask("missing_customer")),
    ("cust-alias-map", "Pappu ne 100 diye", {"aliases": {"pappu": "prakash"}}, ok((P, "prakash", 100, D0))),
    ("cust-fuzzy-not-merged", "Suresh ka 100 udhaar", {"customers": [{"id": "c1", "name": "ramesh", "tags": []}]},
     {"status": "ok", "events": [{"customer": "suresh", "new_customer": True}]}),
    ("guard-zero-deva", "रमेश का शून्य उधार", None, rej("invalid_number")),
    ("guard-decimal", "Ramesh ka 340.50 udhaar", None, ask("missing_amount")),
    ("guard-confusable-other-name-ignored", "Ramesh ka 340 udhaar",
     {"stt_alternatives": ["Suresh ka 740 udhaar"]}, ok((C, "ramesh", 340, D0))),
    ("guard-plausibility-compound", "Ramesh ka 100 udhaar aur Sunita ne 60000 diye", None, ask("plausibility")),
    ("query-balance-deva-baaki", "रमेश का कितना बाकी है", None,
     {"status": "ok", "action": "query", "query": {"type": "balance", "customer": "ramesh"}}),
    ("query-not-ledger-question", "kitne baje hain", None, rej("not_ledger")),

    # --- Regressions for bugs fixed during development ---
    ("reg-ji-is-honorific", "Sharma ji ne 400 diye", None, ok((P, "sharma", 400, D0))),
    ("reg-chai-is-not-six", "Ramesh chai wale ne 200 diye", None,
     {"status": "ok", "events": [{"customer": "ramesh", "amount": 200, "tags": ["chai wale"]}]}),
    ("reg-nahi-comma-kind", "nahi, jama tha", LAST, ok((P, "ramesh", 340, D0), action="amend")),
    ("reg-likh-do-not-two", "Ramesh ke naam 300 likh do", None, ok((C, "ramesh", 300, D0))),
]


@pytest.mark.parametrize("utterance,ctx,expect", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_case(utterance, ctx, expect):
    result = parse(utterance, today=TODAY, ctx=ctx)
    assert matches(expect, result), f"\n{utterance!r}\nexpected {expect}\nactual   {result}"


def test_case_ids_are_unique():
    ids = [c[0] for c in CASES]
    assert len(ids) == len(set(ids))


def test_clarification_shape():
    r = parse("Ramesh ka 100 udhaar, Sunita 200", today=TODAY)
    assert r["status"] == "needs_clarification" and r["reason"] == "ambiguous_direction"
    assert r["question"] == "Sunita ne diye, ya Sunita ko udhaar?"
    assert r["pending"]["action"] == "append"
    assert r["pending"]["events"][1] == {"customer": "sunita", "amount": 200, "date": D0}


def test_same_name_question_names_the_tags():
    r = parse("Ramesh ne 200 diye", today=TODAY, ctx={"customers": TWO_RAMESH})
    assert r["question"] == "Kaunse Ramesh: chai wale ya gali number 3?"
    assert r["candidates"] == TWO_RAMESH


def test_plausibility_question_uses_indian_grouping():
    r = parse("Ramesh ka 1,25,000 udhaar", today=TODAY)
    assert r["question"] == "₹1,25,000, pakka?"


def test_pending_round_trip_through_answers():
    first = parse("Ramesh ka 60000 udhaar", today=TODAY, ctx={"customers": TWO_RAMESH})
    assert first["reason"] == "same_name"
    second = parse("gali number 3", today=TODAY, ctx={"customers": TWO_RAMESH, "pending": first["pending"]})
    assert second["reason"] == "plausibility"
    third = parse("haan", today=TODAY, ctx={"customers": TWO_RAMESH, "pending": second["pending"]})
    assert third["status"] == "ok"
    assert third["events"] == [{"kind": C, "customer": "ramesh", "amount": 60000, "date": D0, "customer_id": "c2"}]


def test_input_ctx_is_not_mutated():
    ctx = {"customers": TWO_RAMESH, "pending": {"reason": "same_name", "action": "append", "events": [
        {"kind": P, "customer": "ramesh", "amount": 200, "date": D0}], "candidates": TWO_RAMESH}}
    before = repr(ctx)
    parse("chai wale", today=TODAY, ctx=ctx)
    assert repr(ctx) == before


def test_datetime_today_is_accepted():
    from datetime import datetime
    r = parse("Ramesh ne kal 200 diye", today=datetime(2026, 11, 21, 23, 59), ctx=None)
    assert r["events"][0]["date"] == D1


def test_parse_is_fast():
    utterances = [c[1] for c in CASES]
    start = time.perf_counter()
    for u in utterances * 5:
        parse(u, today=TODAY, ctx=None)
    per_call_ms = (time.perf_counter() - start) * 1000 / (len(utterances) * 5)
    assert per_call_ms < 5


WORDS = st.sampled_from([
    "Ramesh", "ka", "ko", "ne", "se", "udhaar", "diya", "diye", "nahi", "galat", "aur", "phir", "kal", "parso",
    "sau", "hazaar", "lakh", "saade", "dedh", "sawa", "paune", "dhai", "teen", "do", "340", "1,500", "₹", "rs.",
    "chai", "wale", "gali", "number", "3", "haan", "ji", "undo", "hata", "pehle", "din", "kitna", "total", ",",
    ".", "?", "रमेश", "का", "उधार", "दिए", "सौ", "साढ़े", "three", "forty", "and", "hundred", "0", "", "-", "/-",
])
CTXS = st.sampled_from([
    None, {}, LAST, LAST_PAY, {"customers": TWO_RAMESH}, {"stt_alternatives": ["Ramesh ka 740 udhaar"]},
    {"pending": {"reason": "plausibility", "action": "append", "events": [
        {"kind": C, "customer": "ramesh", "amount": 60000, "date": D0}]}},
    {"pending": {"reason": "same_name", "action": "query", "query": {"type": "balance"}, "candidates": TWO_RAMESH}},
    {"pending": {"reason": "missing_customer", "action": "append", "events": [{"amount": 5}]}},
    {"pending": {"reason": "confusable_number", "action": "append", "events": [], "candidates": [1]}},
    {"pending": {"reason": "bogus"}}, {"pending": "x"}, {"customers": "x", "limits": {"confirm_above": "x"}},
    {"last_event": {"kind": "credit"}}, {"aliases": {"ramesh": 5}},
])


@settings(max_examples=400, deadline=None)
@given(st.text(max_size=80), CTXS)
def test_never_raises_on_arbitrary_text(text, ctx):
    result = _parse(text, TODAY, ctx)  # the unguarded core: no exception may be hidden by the safety net
    assert result["status"] in ("ok", "needs_clarification", "rejected")


@settings(max_examples=600, deadline=None)
@given(st.lists(WORDS, max_size=14).map(" ".join), CTXS)
def test_never_raises_on_ledger_like_text(text, ctx):
    result = _parse(text, TODAY, ctx)
    assert result["status"] in ("ok", "needs_clarification", "rejected")
    if result["status"] == "ok" and result["action"] in ("append", "amend"):
        for e in result["events"]:
            assert e["kind"] in ("credit", "payment")
            assert isinstance(e["amount"], int) and e["amount"] > 0
            assert e["customer"]
            assert len(e["date"]) == 10
    if result["status"] == "needs_clarification":
        assert result["question"]
        assert result["pending"]["reason"] == result["reason"]
