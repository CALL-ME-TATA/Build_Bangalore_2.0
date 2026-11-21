# Testing plan

Counts below are from a run on 2026-11-21 at 21:28 IST. Automated tests use the mock Gnani server and never call the
real API.

## Suites

Run the Python suites from `server/` with `../.venv/Scripts/python` (Windows) or `../.venv/bin/python`.

| Suite | Tests | What it proves | Run |
|---|---|---|---|
| Parser and golden: `tests/nlu`, `tests/oracle`, `tests/test_numbers_roundtrip.py`, `tests/test_fractions.py`, `tests/test_golden.py` | 4,855 | Every amount from 1 to 9,99,999 parses back from words, spelling variants and digits; fractions, English, Devanagari and digit forms; the parser rules of CONTRACT section 1; `eval/golden.seed.jsonl` and `eval/golden.jsonl` | `python -m pytest` |
| Server: `tests/app` | 287 | Ledger rules, session protocol, replies, pipeline, and the Responsible AI tests of CONTRACT section 7 | `python -m pytest tests/app` |
| Edge cases: `tests/edge` | 944 | One or more tests per case id of docs/EDGE_CASES.md (test names start with the id, for example `test_A11_...`). They cover 255 of the 280 listed cases; 25 are manual checks (below) | `python -m pytest tests/edge` |
| End-to-end and scoreboard: `tests/e2e`, `tests/test_scoreboard.py` | 108 | Whole turns over `/ws/session` against the mock Gnani server, the audio replay script, and the scoreboard script | see below |
| Web app: `frontend/` | 288 | Pure logic of the web app (Vitest, no browser): money and dates, doubt-sheet answers, mic states, session reducer and protocol, audio conversion, the offline cache and typed queue, settings, insights, the demo script | `npm test` in `frontend/` |
| Earlier client: `web/tests` | see `node --test web/tests` | Audio conversion and protocol handling of the no-build client | `node --test web/tests` from the repository root |

`tests/e2e` has its own fixtures file and must be run on its own: `python -m pytest tests/e2e`. Run
`tests/test_scoreboard.py` with the rest of the server suite. Do not add a shared `conftest.py` at `server/tests/`;
each test directory keeps its fixtures inside itself.

Other checks in `frontend/`: `npm run lint` (eslint with accessibility rules) and `npm run typecheck`.

## Reports and scripts

| Script | What it does |
|---|---|
| `scripts/edge_report.py` | Runs `tests/edge` and writes docs/EDGE_REPORT.md: one table per section of docs/EDGE_CASES.md, each case `pass`, `fail` or `manual`, with the manual reasons. Run from `server/`: `../.venv/Scripts/python ../scripts/edge_report.py` (`--no-run` rebuilds the report without running the tests; `--junit path.xml` uses an existing result file). The report is generated; do not edit it |
| `eval/scoreboard.py` | Runs the parser over the golden files and writes docs/SCOREBOARD.md: exact amount, direction, customer and status accuracy, and the count of silent wrong saves (a case that should have asked or refused, or should have saved something else, but saved). It exits 1 when that count is above zero. The scoreboard is generated; do not edit it |
| `scripts/latency_harness.py` | p50 and p95 per hop against the mock |
| `scripts/fix_log_replay.py` | Replays every case of docs/FIX_LOG.md through the real parser and pipeline on a temporary ledger and prints what each turn does; `python scripts/fix_log_replay.py 9.` replays one round |
| `scripts/replay_audio.py` | Replays recorded WAV files through a running server exactly as the browser sends them and reports exact-amount, direction and customer accuracy, silent wrong saves, how many turns asked a question, and the median and p95 of each timing stage. `--make-noisy DIR` writes noisy copies (white, pink and babble noise at 20, 10 and 5 dB). It needs a manifest of recordings and the expected entries; see the script's header. It is a live tool: tests never run it, apart from its own unit tests in `tests/e2e/test_replay_audio.py` |
| `scripts/live_smoke.py` | One real Prisma v3.0 and Timbre v3.0 round trip. Uses real credits |

## Manual checks

These are the cases that docs/EDGE_REPORT.md lists as manual (25 cases; P02b is one part of case P02), because they need a microphone, a browser, recordings,
a venue, or the feature is not built.

Not built
- E13: customer merge. Honorific stripping and the new-customer question reduce duplicates.
- E16: two shops on one device. One database file is one shop.
- S02: Kannada or Marathi number words.

Need recordings (use `scripts/replay_audio.py`, with `--make-noisy` for noise)
- M12: very low confidence. Gnani returns no confidence score, so there is nothing to test.
- M13: a background speaker says a number. Push-to-talk, the readback and undo are the guard, and a turn whose
  speaker is barely above the background is read back before it is saved (CONTRACT 3.5).
- M14: noise such as traffic, a pressure cooker, a mixer, a crowd. Measured with a synthetic voice and generated
  white, pink and babble noise (README, "Noise handling and noise test": 120 turns run with noise handling off and
  on, none saved wrongly in either run); real shop noise still needs recordings.
- M15: whisper, shouting, clipping, a far microphone.
- M16: accents, an older speaker, different voices.

Need a browser, a microphone or a phone
- M04: first word clipped (`esh ka 340`); the page keeps 300 ms from before the press.
- M05: last digit clipped on early release; the page sends 300 ms after the release.
- N02: a customer name that is mispronounced; check by ear.
- N05: the microphone is muted and playback stops when the button is pressed.
- O01: voice with no connection; check the offline message and the typed-sentence queue.
- O04: an undo sent before its entry; check the browser queue order.
- P02b: the access-code entry screen and its wording (the check itself is automated).
- R01: microphone permission denied message.
- R02: offline status at start.
- R03: contrast and text size on a small screen in sunlight.
- R05: an accidental press (recordings under 0.5 s are ignored, case M03).
- R06: a visible Undo button.
- R07: the wording of the tagline.
- R10: a tab sent to the background reconnects on focus.

Need a person, the venue or the live account
- Q02: a wrong or unverified phone number; opt-in is confirmed with the customer present, and there is no code check.
- R08: poor Wi-Fi at the venue. Plan: a hotspot, a recorded backup video, the text input.
- R09: performance; cached phrases are tested (N07), Gnani limits are checked by hand against the live account.
- R11: a server restart during a session.

Also, before the demo
1. `scripts/live_smoke.py` against the real key.
2. Real voices on a low-end Android phone in a noisy room; the new web app's microphone handling has not been
   verified on one.
3. A demo rehearsal over HTTPS on the real network (docs/DEMO_SCRIPT.md).
4. After judging: `python -m app.admin purge` from `server/`.
