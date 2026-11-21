"""Runs every case in eval/golden.seed.jsonl (and eval/golden.jsonl if present) through nlu.parser.parse.

`expect` is matched as a SUBSET of the actual result: every key given must match;
lists must have equal length and match element-wise.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from nlu.parser import parse

TODAY = date(2026, 11, 21)  # fixed so relative dates (kal, parso) are deterministic
EVAL = Path(__file__).resolve().parents[2] / "eval"


def _load():
    cases = []
    for name in ("golden.seed.jsonl", "golden.jsonl"):
        path = EVAL / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    cases.append(json.loads(line))
    return cases


def matches(expect, actual) -> bool:
    if isinstance(expect, dict):
        return isinstance(actual, dict) and all(k in actual and matches(v, actual[k]) for k, v in expect.items())
    if isinstance(expect, list):
        return isinstance(actual, list) and len(expect) == len(actual) and all(matches(e, a) for e, a in zip(expect, actual))
    return expect == actual


@pytest.mark.parametrize("case", _load(), ids=lambda c: c["id"])
def test_golden_case(case):
    result = parse(case["utterance"], today=TODAY, ctx=case.get("ctx"))
    assert matches(case["expect"], result), f"\nutterance: {case['utterance']}\nexpected: {case['expect']}\nactual:   {result}"
