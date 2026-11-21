# Testing plan

Run from `server/`: `../.venv/Scripts/python -m pytest`

| Suite | What it proves | Owner |
|---|---|---|
| `tests/oracle` | The number oracle itself is sound | qa |
| `tests/test_numbers_roundtrip.py` | Every amount from 1 to 9,99,999 parses back from words, spelling variants and digits | qa (spec), nlu (code) |
| `tests/test_fractions.py`, `tests/nlu/test_number_forms.py` | Fractions, English, Devanagari and digit forms | nlu |
| `tests/test_golden.py` | `eval/golden.seed.jsonl` (88 contract cases) and `eval/golden.jsonl` (generated cases) | qa |
| `tests/app` | Ledger rules, session protocol, replies, and the Responsible AI tests of CONTRACT section 7 | backend |
| `tests/e2e` | Whole turns over `/ws/session` against the mock Gnani server | qa |
| `scripts/latency_harness.py` | p50 and p95 per hop against the mock | qa |
| `node --test web/tests` | Audio conversion and protocol handling in the web app | web |

## Manual tests (real API key, credits and real audio)
1. `scripts/live_smoke.py`: a real Prisma v3.0 and Timbre v3.0 round trip. Prints the transcript for each output format
   and the measured latencies.
2. Real voices on a low-end Android phone in a noisy room: check amounts and direction.
3. Demo rehearsal over HTTPS on the real network.
4. After judging: `python -m app.admin purge`.
