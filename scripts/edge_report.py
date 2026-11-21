"""Run the edge-case tests and write docs/EDGE_REPORT.md.

    cd server
    ../.venv/Scripts/python ../scripts/edge_report.py [--no-run] [--junit path.xml]

The tests in server/tests/edge/ carry the case id in their name (test_A13_...). Results are grouped by case id and
written as one table per section of docs/EDGE_CASES.md. A case with at least one failing test is `fail`. Cases that
cannot be automated are listed in MANUAL with the reason. The script exits 0 when tests fail; it exits 1 only when
the tests could not be run at all.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
CASES_DOC = ROOT / "docs" / "EDGE_CASES.md"
REPORT = ROOT / "docs" / "EDGE_REPORT.md"

MANUAL = {
    "E13": "merge is not built; honorific stripping and the new-customer question (E03, E08, E09) prevent the duplicate",
    "E16": "not built: one database file is one shop",
    "M04": "browser pre-buffer (300 ms before the press); needs a microphone",
    "M05": "browser 300 ms tail after release; needs a microphone",
    "M12": "Gnani returns no confidence score, so there is nothing to test",
    "M13": "a background speaker is a recording case; push-to-talk, readback and undo are the guard (D08, N08)",
    "M14": "needs recordings: run scripts/replay_audio.py with a noisy manifest",
    "M15": "needs recordings (whisper, shouting, clipping, far microphone)",
    "M16": "needs recordings of other accents and voices",
    "N02": "the optional per-customer `say` field is not in the contract; check by ear",
    "N05": "browser behaviour: pressing the button stops playback and mutes the microphone",
    "O01": "browser behaviour: the offline message and the typed-sentence queue",
    "O04": "browser queue order; the server only sees the entries in the order they arrive",
    "Q02": "an opt-in confirmation done with the customer present; there is no code check to test",
    "R01": "browser: microphone permission denied message",
    "R02": "browser: Offline status at start",
    "R03": "visual: contrast and text size in sunlight",
    "R05": "see M03 (recordings under 0.5 s are ignored)",
    "R06": "UI: visible Undo button",
    "R07": "wording of the tagline in the web app",
    "R08": "venue plan: hotspot, recorded backup video, text input",
    "R09": "cached phrases are tested in N07; Gnani limits are checked by hand against the live account",
    "R10": "browser: reconnect on focus",
    "R11": "server restart during a session; check by hand",
    "S02": "not built: Kannada and Marathi number words are optional",
    "P02b": "PIN entry screen and wording (the access-code check is automated)",
}


# Section X is not in docs/EDGE_CASES.md; it is listed here until the document has it.
EXTRA_SECTIONS = [("X", "Sentences nobody listed", [
    ("X01", "unknown word: ask first, yes saves"), ("X02", "unknown word: no saves nothing"),
    ("X03", "flag off: the same sentences save directly"), ("X04", "demo script sentences do not ask"),
    ("X05", "trailing unknown word never saves silently"), ("X06", "stored names and tags are known words"),
    ("X07", "correction with an unknown word asks"), ("X08", "queries and undo are not gated"),
    ("X09", "new-customer question and unknown word"), ("X10", "parser names the unknown words")])]


def parse_cases_doc() -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Sections of docs/EDGE_CASES.md: (letter, title, [(id, short description)])."""
    sections: list[tuple[str, str, list[tuple[str, str]]]] = []
    for line in CASES_DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## ([A-SX])\. (.+)$", line)
        if m:
            sections.append((m.group(1), m.group(2), []))
            continue
        m = re.match(r"^\| ([A-SX]\d\d) \| (.*?) \|", line)
        if m and sections:
            sections[-1][2].append((m.group(1), m.group(2).strip()))
    have = {letter for letter, _, _ in sections}
    return sections + [sec for sec in EXTRA_SECTIONS if sec[0] not in have]


def run_pytest(junit: Path) -> int:
    cmd = [sys.executable, "-m", "pytest", "tests/edge", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
    return subprocess.run(cmd, cwd=SERVER).returncode


def first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def read_results(junit: Path) -> dict[str, dict]:
    """Case id -> {"tests": n, "failed": n, "detail": first failing line}."""
    results: dict[str, dict] = defaultdict(lambda: {"tests": 0, "failed": 0, "detail": ""})
    for case in ET.parse(junit).getroot().iter("testcase"):
        m = re.match(r"test_([A-SX]\d\d)_", case.get("name", ""))
        if not m:
            continue
        entry = results[m.group(1)]
        entry["tests"] += 1
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        if bad is not None:
            entry["failed"] += 1
            if not entry["detail"]:
                msg = first_line(bad.get("message")) or first_line(bad.text)
                param = re.search(r"\[(.*)\]$", case.get("name", ""))
                entry["detail"] = (f"[{param.group(1)}] " if param else "") + msg
    return results


def cell(text: str, limit: int = 220) -> str:
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_report(sections, results) -> str:
    counts = {"pass": 0, "fail": 0, "manual": 0, "no test": 0}
    tables = []
    for letter, title, cases in sections:
        rows = []
        for cid, desc in cases:
            r = results.get(cid)
            if r:
                status = "fail" if r["failed"] else "pass"
                detail = r["detail"] if r["failed"] else ""
                if r["failed"]:
                    detail = f"{r['failed']}/{r['tests']} tests: {detail}"
            elif cid in MANUAL:
                status, detail = "manual", MANUAL[cid]
            else:
                status, detail = "no test", ""
            counts[status] += 1
            rows.append(f"| {cid} | {cell(desc, 60)} | {status} | {cell(detail)} |")
        tables.append(f"## {letter}. {title}\n\n| ID | Case | Result | First failing assertion |\n|---|---|---|---|\n"
                      + "\n".join(rows) + "\n")
    total = sum(counts.values())
    tests_run = sum(r["tests"] for r in results.values())
    summary = (f"{total} cases: {counts['pass']} pass, {counts['fail']} fail, {counts['manual']} manual, "
               f"{counts['no test']} without a test ({tests_run} tests run).")
    manual = "\n".join(f"- {cid}: {why}" for cid, why in sorted(MANUAL.items()))
    return (f"# Edge-case report\n\nWritten by `scripts/edge_report.py` from the tests in `server/tests/edge/`.\n\n"
            f"{summary}\n\n" + "\n".join(tables) + f"\n## Manual cases\n\n{manual}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-run", action="store_true", help="read an existing --junit file instead of running pytest")
    ap.add_argument("--junit", type=Path, help="JUnit XML path (default: a temporary directory)")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        junit = args.junit or Path(tmp) / "edge.xml"
        if not args.no_run:
            run_pytest(junit)
        if not junit.exists():
            print("pytest produced no JUnit file; the tests could not be run", file=sys.stderr)
            return 1
        results = read_results(junit)
    report = build_report(parse_cases_doc(), results)
    REPORT.write_text(report, encoding="utf-8")
    print(report.split("\n\n")[2])
    print(f"written {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
