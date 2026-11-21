"""Run the parser over eval/golden.jsonl and eval/golden.seed.jsonl and write docs/SCOREBOARD.md.

    cd server
    ../.venv/Scripts/python ../eval/scoreboard.py

Metrics (each over the cases that state the field in `expect`):
  exact amount   every expected event amount equals the parsed one, in order
  direction      every expected event kind equals the parsed one
  customer       every expected event customer equals the parsed one
  status         the status equals the expected status
A silent wrong save is a case where the parser wrote (or would write) something it should not have:
  - the case expects a question or a rejection, and the parser answered `ok` with action append, amend or undo
  - the case expects `ok`, and the parser answered `ok` with a different amount, kind or customer, or a different
    saving action
Exit code 1 when there is at least one silent wrong save.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

TODAY = date(2026, 11, 21)
FILES = ("golden.seed.jsonl", "golden.jsonl")
REPORT = ROOT / "docs" / "SCOREBOARD.md"
SAVING = ("append", "amend", "undo")


def load_cases(directory: Path) -> list[dict]:
    cases = []
    for name in FILES:
        path = directory / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    case = json.loads(line)
                    case["file"] = name
                    cases.append(case)
    return cases


def _events(result: dict | None) -> list[dict]:
    events = (result or {}).get("events")
    return events if isinstance(events, list) else []


def _field_matches(expect_events: list[dict], actual_events: list[dict], field: str) -> bool | None:
    """None when the case does not state the field, else whether every expected value matches in order."""
    wanted = [e[field] for e in expect_events if field in e]
    if not wanted or len(wanted) != len(expect_events):
        return None
    got = [e.get(field) for e in actual_events]
    return got[: len(wanted)] == wanted and len(got) >= len(wanted)


def score_case(case: dict, result: dict | None) -> dict:
    """Score one case. `result` is the parser output, or None when the parser raised."""
    expect = case["expect"]
    exp_events = expect.get("events") if isinstance(expect.get("events"), list) else []
    actual_events = _events(result)
    out = {
        "id": case["id"],
        "amount": _field_matches(exp_events, actual_events, "amount"),
        "kind": _field_matches(exp_events, actual_events, "kind"),
        "customer": _field_matches(exp_events, actual_events, "customer"),
        "status": None,
        "silent_wrong_save": False,
        "why": "",
    }
    if "status" in expect:
        out["status"] = bool(result) and result.get("status") == expect["status"]
    saved = bool(result) and result.get("status") == "ok" and result.get("action") in SAVING
    if expect.get("status") in ("needs_clarification", "rejected") and saved:
        out["silent_wrong_save"] = True
        out["why"] = f"expected {expect['status']}, parser saved ({result.get('action')})"
    elif expect.get("status") == "ok" and saved:
        wrong = [f for f in ("amount", "kind", "customer") if out[f] is False]
        if "action" in expect and result.get("action") != expect["action"]:
            wrong.append("action")
        if wrong:
            out["silent_wrong_save"] = True
            out["why"] = "wrong " + ", ".join(wrong)
    return out


def _rate(rows: list[dict], key: str) -> tuple[int, int]:
    stated = [r[key] for r in rows if r[key] is not None]
    return sum(1 for v in stated if v), len(stated)


def summarise(rows: list[dict]) -> dict:
    summary = {"cases": len(rows), "silent_wrong_saves": [r for r in rows if r["silent_wrong_save"]]}
    for key in ("amount", "kind", "customer", "status"):
        summary[key] = _rate(rows, key)
    return summary


def format_rate(pair: tuple[int, int]) -> str:
    good, total = pair
    return f"{good}/{total} ({100 * good / total:.1f}%)" if total else "n/a"


def render(summary: dict, cases_by_id: dict[str, dict]) -> str:
    lines = [
        "# Parser scoreboard", "",
        "Written by `eval/scoreboard.py` from `eval/golden.seed.jsonl` and `eval/golden.jsonl`.", "",
        "| Metric | Result |", "|---|---|",
        f"| Cases | {summary['cases']} |",
        f"| Exact amount | {format_rate(summary['amount'])} |",
        f"| Direction | {format_rate(summary['kind'])} |",
        f"| Customer | {format_rate(summary['customer'])} |",
        f"| Status | {format_rate(summary['status'])} |",
        f"| Silent wrong saves | {len(summary['silent_wrong_saves'])} |", "",
    ]
    if summary["silent_wrong_saves"]:
        lines += ["## Silent wrong saves", "", "| Case | Utterance | Why |", "|---|---|---|"]
        for r in summary["silent_wrong_saves"]:
            utt = cases_by_id[r["id"]]["utterance"].replace("|", "\\|")
            lines.append(f"| {r['id']} | {utt} | {r['why']} |")
        lines.append("")
    return "\n".join(lines)


def run(directory: Path) -> tuple[dict, dict[str, dict]]:
    from nlu.parser import parse

    cases = load_cases(directory)
    rows = []
    for case in cases:
        try:
            result = parse(case["utterance"], today=TODAY, ctx=case.get("ctx"))
        except Exception:  # noqa: BLE001 - a crash is scored as a wrong answer
            result = None
        rows.append(score_case(case, result))
    return summarise(rows), {c["id"]: c for c in cases}


def main() -> int:
    summary, cases_by_id = run(Path(__file__).resolve().parent)
    report = render(summary, cases_by_id)
    REPORT.write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(report)
    return 1 if summary["silent_wrong_saves"] else 0


if __name__ == "__main__":
    sys.exit(main())
