"""Unit tests for the scoring rules of eval/scoreboard.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "eval" / "scoreboard.py"
spec = importlib.util.spec_from_file_location("scoreboard", SCRIPT)
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)


def ev(kind="credit", customer="ramesh", amount=340):
    return {"kind": kind, "customer": customer, "amount": amount, "date": "2026-11-21"}


def case(expect, cid="g1"):
    return {"id": cid, "utterance": "x", "expect": expect}


def ok(*events, action="append"):
    return {"status": "ok", "action": action, "events": list(events)}


def test_a_correct_save_scores_everything_and_is_not_silent():
    row = sb.score_case(case({"status": "ok", "events": [ev()]}), ok(ev()))
    assert (row["amount"], row["kind"], row["customer"], row["status"], row["silent_wrong_save"]) == (
        True, True, True, True, False)


@pytest.mark.parametrize("change,field", [({"amount": 430}, "amount"), ({"kind": "payment"}, "kind"),
                                          ({"customer": "suresh"}, "customer")])
def test_a_wrong_field_in_a_save_is_a_silent_wrong_save(change, field):
    row = sb.score_case(case({"status": "ok", "events": [ev()]}), ok({**ev(), **change}))
    assert row[field] is False and row["silent_wrong_save"] is True and field in row["why"]


@pytest.mark.parametrize("expected", ["needs_clarification", "rejected"])
def test_saving_when_a_question_or_rejection_was_expected_is_silent_wrong(expected):
    row = sb.score_case(case({"status": expected}), ok(ev()))
    assert row["silent_wrong_save"] is True and row["status"] is False


def test_a_query_answer_is_not_a_save():
    row = sb.score_case(case({"status": "rejected"}), {"status": "ok", "action": "query", "query": {}})
    assert row["silent_wrong_save"] is False and row["status"] is False


def test_asking_when_a_save_was_expected_is_a_miss_but_not_silent():
    row = sb.score_case(case({"status": "ok", "events": [ev()]}), {"status": "needs_clarification"})
    assert row["silent_wrong_save"] is False and row["status"] is False and row["amount"] is False


def test_wrong_action_in_a_save_is_silent_wrong():
    row = sb.score_case(case({"status": "ok", "action": "undo", "target": "last"}), ok(ev(), action="append"))
    assert row["silent_wrong_save"] is True


def test_a_parser_crash_is_scored_as_a_miss():
    row = sb.score_case(case({"status": "ok", "events": [ev()]}), None)
    assert row["status"] is False and row["amount"] is False and row["silent_wrong_save"] is False


def test_fields_not_stated_are_not_scored():
    row = sb.score_case(case({"status": "needs_clarification", "reason": "same_name"}),
                        {"status": "needs_clarification"})
    assert row["amount"] is None and row["kind"] is None and row["customer"] is None and row["status"] is True


def test_events_compared_in_order_and_count():
    exp = {"status": "ok", "events": [ev(amount=340), ev("payment", amount=200)]}
    assert sb.score_case(case(exp), ok(ev(amount=340), ev("payment", amount=200)))["amount"] is True
    assert sb.score_case(case(exp), ok(ev(amount=200), ev("payment", amount=340)))["amount"] is False
    assert sb.score_case(case(exp), ok(ev(amount=340)))["amount"] is False


def test_summarise_counts_and_renders():
    rows = [sb.score_case(case({"status": "ok", "events": [ev()]}, "g1"), ok(ev())),
            sb.score_case(case({"status": "ok", "events": [ev()]}, "g2"), ok(ev(amount=1))),
            sb.score_case(case({"status": "rejected"}, "g3"), {"status": "rejected"})]
    s = sb.summarise(rows)
    assert s["cases"] == 3 and s["amount"] == (1, 2) and s["status"] == (3, 3)
    assert [r["id"] for r in s["silent_wrong_saves"]] == ["g2"]
    text = sb.render(s, {"g2": {"utterance": "a|b"}})
    assert "| Cases | 3 |" in text and "| Silent wrong saves | 1 |" in text and "a\\|b" in text


def test_load_cases_reads_both_files_in_order(tmp_path):
    (tmp_path / "golden.seed.jsonl").write_text(json.dumps(case({"status": "ok"}, "s1")) + "\n", encoding="utf-8")
    (tmp_path / "golden.jsonl").write_text(json.dumps(case({"status": "ok"}, "g1")) + "\n\n", encoding="utf-8")
    assert [c["id"] for c in sb.load_cases(tmp_path)] == ["s1", "g1"]
