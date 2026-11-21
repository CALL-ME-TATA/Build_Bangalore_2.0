# KhataVaani

A voice ledger (khata) for kirana stores. The shopkeeper holds one button and speaks, for example
"Ramesh ka 340 udhaar, kal 200 diya tha". KhataVaani records the credit and the payment and confirms by voice.

Built for the Gnani Voice Hackathon, problem statement 2 (Voice Khata for kirana stores), by team Not IITians.

**Status:** in development. Full setup and demo instructions replace this page before submission.

## Design in one paragraph

A browser app streams push-to-talk audio over a WebSocket to a FastAPI server. The server relays it to Gnani Prisma v3.0
(streaming speech-to-text), parses the transcript with a rule-based parser (no LLM decides an amount or a direction),
appends the result to an encrypted, append-only SQLite ledger, and speaks a short confirmation through Gnani Timbre v3.0
(text-to-speech). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/CONTRACT.md](docs/CONTRACT.md).

## Repository

| Path | Contents |
|---|---|
| `server/nlu/` | Parser: numbers, direction, dates, corrections |
| `server/app/` | FastAPI server, ledger, Gnani clients |
| `server/mock_gnani/` | Mock of the Gnani WebSocket APIs, used by the tests |
| `web/` | Static push-to-talk web app |
| `eval/` | Acceptance cases for the parser |
| `docs/` | Architecture and interface specification |

## Setup

- Windows: `powershell -ExecutionPolicy Bypass -File setup.ps1`
- macOS or Linux: `bash setup.sh`

Then put your Gnani API key in `.env` (see `.env.example`). Run the tests from `server/` with
`../.venv/Scripts/python -m pytest`.
