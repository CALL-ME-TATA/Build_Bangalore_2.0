"""While a question is pending, a complete new entry or a query replaces it, and an unrelated incomplete sentence
is a failed attempt. Nothing from the pending question is ever saved in those cases (CONTRACT 1.9, 1.13, 1.14).

Every pending reason the parser can produce is crossed with four follow-ups."""
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
D0 = "2026-11-21"
ROSTER = [
    {"id": "c1", "name": "ramesh", "tags": [], "balance": 343, "usual": 100},
    {"id": "c2", "name": "mohan", "tags": [], "balance": 1000},
    {"id": "c3", "name": "sunita", "tags": [], "balance": 341},
    {"id": "c4", "name": "rakesh", "tags": ["chai wale"]},
    {"id": "c5", "name": "rakesh", "tags": ["gali number 3"]},
]
LAST = {"kind": "credit", "customer": "ramesh", "customer_id": "c1", "amount": 340, "date": D0}
TWO_LAST = [{"id": 1, "kind": "credit", "customer": "ramesh", "amount": 340, "date": D0},
            {"id": 2, "kind": "payment", "customer": "sunita", "amount": 200, "date": D0}]


def base_ctx(**extra):
    ctx = {"customers": ROSTER, "limits": {"confirm_new_customer": True}}
    ctx.update(extra)
    return ctx


# (label, utterance that asks, ctx, expected reason, expected confirm type or mode)
PENDINGS = [
    ("plausibility", "Ramesh ka 60000 udhaar", base_ctx(), "plausibility", None),
    ("confusable", "Ramesh ka teen chaar sau udhaar", base_ctx(), "confusable_number", None),
    ("missing_amount_credit", "Ramesh ko udhaar", base_ctx(), "missing_amount", None),
    ("missing_amount_payment_half", "Sunita ne aadha de diya", base_ctx(), "missing_amount", None),
    ("missing_amount_writeoff", "round off kar do",
     base_ctx(customers=[dict(ROSTER[0], balance=1000)] + ROSTER[1:], last_event=LAST,
              last_turn={"action": "append", "age_s": 5}), "missing_amount", None),
    ("name_only", "Ramesh", base_ctx(), "missing_amount", None),
    ("missing_customer", "500 udhaar", base_ctx(), "missing_customer", None),
    ("ambiguous_direction", "Ramesh 500", base_ctx(), "ambiguous_direction", None),
    ("same_name", "Rakesh ka 200 udhaar", base_ctx(), "same_name", None),
    ("unclear_date", "Ramesh ne somvar ko 200 diye", base_ctx(), "unclear_date", None),
    ("unclear_correction", "nahi", base_ctx(last_event=LAST), "unclear_correction", None),
    ("which_entry", "nahi 430", base_ctx(last_event=TWO_LAST[1], last_events=TWO_LAST), "unclear_correction",
     "which_entry"),
    ("confirm_undo", "Sunita ki entry hata do", base_ctx(last_event=LAST), "unclear_correction", "confirm_undo"),
    ("replace", "Nahi Sunita ne 500 diye", base_ctx(last_event=LAST), "unclear_correction", "replace"),
    ("new_customer", "Geeta ne 150 diye", base_ctx(), "new_customer", None),
    ("computed", "Ramesh ka bill 450 hai, 200 diya, baaki udhaar", base_ctx(), "confirm_entry", "computed"),
    ("settle", "Ramesh ka hisaab barabar", base_ctx(), "confirm_entry", "settle"),
    ("half", "Sunita ne aadha de diya",
     base_ctx(customers=[dict(ROSTER[2], balance=340)] + ROSTER[:2]), "confirm_entry", "half"),
    ("writeoff", "Ramesh ka baaki chhod do", base_ctx(), "confirm_entry", "writeoff"),
    ("roundoff", "round off kar do",
     base_ctx(last_event=LAST, last_turn={"action": "append", "age_s": 5}), "confirm_entry", "roundoff"),
    ("overpayment", "Ramesh ne 900 diye", base_ctx(), "confirm_entry", "overpayment"),
    ("duplicate", "Ramesh ka 340 udhaar",
     base_ctx(last_event=LAST, last_events=[LAST], last_turn={"action": "append", "age_s": 5}), "confirm_entry",
     "duplicate"),
    ("hearsay", "Ramesh bol raha tha 340 udhaar", base_ctx(), "confirm_entry", "hearsay"),
    ("unsure", "Ramesh ne 50 phenk diye", base_ctx(limits={"strict": True, "confirm_new_customer": True}),
     "confirm_entry", "unsure"),
]


def make_pending(utterance, ctx, reason, kind):
    first = parse(utterance, today=T, ctx=ctx)
    assert first["status"] == "needs_clarification" and first["reason"] == reason, first
    pending = first["pending"]
    if kind is not None:
        got = (pending.get("confirm") or {}).get("type") or pending.get("mode")
        assert got == kind, first
    return pending


def follow(pending, ctx, utterance):
    c = dict(ctx)
    c["pending"] = pending
    return parse(utterance, today=T, ctx=c)


def pending_amounts(pending):
    return {e.get("amount") for e in pending.get("events") or [] if e.get("amount")}


@pytest.mark.parametrize("label,utterance,ctx,reason,kind", PENDINGS, ids=[p[0] for p in PENDINGS])
def test_complete_entry_for_the_same_customer_replaces_the_question(label, utterance, ctx, reason, kind):
    pending = make_pending(utterance, ctx, reason, kind)
    r = follow(pending, ctx, "Ramesh ka 77 udhaar")
    assert r["status"] == "ok" and r["action"] == "append", r
    assert [(e["kind"], e["customer"], e["amount"]) for e in r["events"]] == [("credit", "ramesh", 77)]


@pytest.mark.parametrize("label,utterance,ctx,reason,kind", PENDINGS, ids=[p[0] for p in PENDINGS])
def test_complete_entry_for_another_customer_replaces_the_question(label, utterance, ctx, reason, kind):
    pending = make_pending(utterance, ctx, reason, kind)
    r = follow(pending, ctx, "Mohan ne 33 diye")
    assert r["status"] == "ok" and r["action"] == "append", r
    assert [(e["kind"], e["customer"], e["amount"]) for e in r["events"]] == [("payment", "mohan", 33)]


@pytest.mark.parametrize("label,utterance,ctx,reason,kind", PENDINGS, ids=[p[0] for p in PENDINGS])
def test_query_replaces_the_question(label, utterance, ctx, reason, kind):
    pending = make_pending(utterance, ctx, reason, kind)
    r = follow(pending, ctx, "Sunita ka total")
    assert r["status"] == "ok" and r["action"] == "query", r
    assert r["query"]["type"] == "balance" and r["query"]["customer"] == "sunita"


@pytest.mark.parametrize("label,utterance,ctx,reason,kind", PENDINGS, ids=[p[0] for p in PENDINGS])
@pytest.mark.parametrize("other", ["chai pe kitne log aaye the", "Kamla ne kal kuch kaha", "dobara boliye"])
def test_unrelated_incomplete_sentence_saves_nothing(label, utterance, ctx, reason, kind, other):
    pending = make_pending(utterance, ctx, reason, kind)
    r = follow(pending, ctx, other)
    assert r["status"] != "ok", r


@pytest.mark.parametrize("label,utterance,ctx,reason,kind",
                         [p for p in PENDINGS if p[0] in ("overpayment", "plausibility", "half",
                                                         "missing_amount_payment_half", "missing_amount_writeoff",
                                                         "settle")],
                         ids=lambda v: v if isinstance(v, str) and " " not in v else None)
def test_number_answer_with_a_disagreeing_direction_is_not_an_answer(label, utterance, ctx, reason, kind):
    pending = make_pending(utterance, ctx, reason, kind)
    word = "udhaar" if any(e.get("kind") != "credit" for e in pending["events"]) else "jama"
    r = follow(pending, ctx, f"60 {word}")
    assert r["status"] != "ok", r


def test_live_case_new_customer_then_a_full_sentence():
    ctx = base_ctx()
    pending = make_pending("Geeta ne 150 diye", ctx, "new_customer", None)
    r = follow(pending, ctx, "Ramesh ka 50 udhaar")
    assert r["events"] == [{"kind": "credit", "customer": "ramesh", "amount": 50, "date": D0, "customer_id": "c1"}]
    pending = make_pending("Sunita2 ne dedh sau rupaye diye", ctx, "new_customer", None) \
        if False else make_pending("Geetu ne dedh sau rupaye diye", ctx, "new_customer", None)
    r = follow(pending, ctx, "Ramesh ka three forty udhaar likh do.")
    assert [(e["kind"], e["customer"], e["amount"]) for e in r["events"]] == [("credit", "ramesh", 340)]


def test_live_case_overpayment_then_a_full_sentence():
    ctx = base_ctx(customers=[{"id": "c1", "name": "ramesh", "tags": [], "balance": 70}] + ROSTER[1:])
    pending = make_pending("Ramesh ne 5000 diye", ctx, "confirm_entry", "overpayment")
    r = follow(pending, ctx, "Ramesh ka 60 udhaar")
    assert [(e["kind"], e["customer"], e["amount"]) for e in r["events"]] == [("credit", "ramesh", 60)]
    assert follow(pending, ctx, "60")["events"][0]["amount"] == 60  # a bare amount is still an answer


@pytest.mark.parametrize("label,utterance,ctx,reason,kind", PENDINGS, ids=[p[0] for p in PENDINGS])
def test_nothing_from_the_pending_question_leaks_into_a_fresh_save(label, utterance, ctx, reason, kind):
    pending = make_pending(utterance, ctx, reason, kind)
    for other in ("Ramesh ka 77 udhaar", "Mohan ne 33 diye"):
        r = follow(pending, ctx, other)
        amounts = {e["amount"] for e in r.get("events") or []}
        assert amounts <= {77, 33}, (label, other, r)
        assert not (pending_amounts(pending) - {77, 33}) & amounts


# --- 1.15: yes plus an undo word, negated or two-name answers, two amounts in an answer --------------------------

@pytest.mark.parametrize("label,utterance,ctx,reason,kind", PENDINGS, ids=[p[0] for p in PENDINGS])
@pytest.mark.parametrize("reply", ["haan hata do", "ok cancel karo", "theek hai mita do", "yes delete", "haan rehne do"])
def test_yes_plus_undo_word_never_saves(label, utterance, ctx, reason, kind, reply):
    pending = make_pending(utterance, ctx, reason, kind)
    r = follow(pending, ctx, reply)
    assert not (r["status"] == "ok" and r.get("action") in ("append", "amend")), r


@pytest.mark.parametrize("label,utterance,ctx,reason,kind", PENDINGS, ids=[p[0] for p in PENDINGS])
@pytest.mark.parametrize("reply", ["Ramesh nahi", "Sunita nahi hai", "chai wale nahi", "Ramesh ya Sunita",
                                   "Ramesh aur Sunita", "Rakesh nahi"])
def test_negated_or_two_name_answers_never_save(label, utterance, ctx, reason, kind, reply):
    pending = make_pending(utterance, ctx, reason, kind)
    r = follow(pending, ctx, reply)
    assert not (r["status"] == "ok" and r.get("action") in ("append", "amend")), r


@pytest.mark.parametrize("label,utterance,ctx,reason,kind", PENDINGS, ids=[p[0] for p in PENDINGS])
@pytest.mark.parametrize("reply", ["300 ya 400", "teen chaar sau", "likh do sau"])
def test_two_amounts_in_an_answer_never_save(label, utterance, ctx, reason, kind, reply):
    pending = make_pending(utterance, ctx, reason, kind)
    r = follow(pending, ctx, reply)
    assert not (r["status"] == "ok" and r.get("action") in ("append", "amend")), r
    if reason in ("missing_amount", "plausibility", "confusable_number", "confirm_entry") and r["status"] == \
            "needs_clarification":
        assert r["reason"] in ("confusable_number", reason, "missing_amount"), r
