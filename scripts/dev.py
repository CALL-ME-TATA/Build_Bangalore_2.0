"""Run KhataVaani locally.

By default the server talks to the built-in mock of the Gnani APIs, so no API key and no credits are needed:
the page, the session protocol and typed input all work, and spoken replies are a test tone.
With --live the server uses the real Gnani API Platform and the key from .env.

Usage, from the repository root:
    .venv/Scripts/python scripts/dev.py            # mock Gnani, http://127.0.0.1:8000
    .venv/Scripts/python scripts/dev.py --live     # real Prisma v3.0 and Timbre v3.0
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))


async def run(args: argparse.Namespace) -> None:
    import uvicorn

    stop_mock = None
    if not args.live:
        from mock_gnani.testing import start_mock

        base_url, stop_mock = await start_mock()
        # Set before the app reads its settings, so the real key in .env is never sent to the mock.
        os.environ["GNANI_BASE_URL"] = base_url
        os.environ["GNANI_API_KEY"] = "mock"
        os.environ.setdefault("LEDGER_DB", "data/mock/khata.db")  # mock data and audio cache stay apart from real data
        print(f"Mock Gnani running at {base_url}")

    from app.main import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(), host=args.host, port=args.port, log_level="info"))
    try:
        await server.serve()
    finally:
        if stop_mock is not None:
            await stop_mock()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the KhataVaani server for local development.")
    parser.add_argument("--live", action="store_true", help="use the real Gnani API Platform (key from .env)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", help="ledger database file for this run (overrides LEDGER_DB), e.g. data/demo/khata.db")
    parser.add_argument("--web", help="folder to serve as the web app (overrides WEB_DIR), e.g. web or frontend/dist")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                        help="set a configuration variable for this run, e.g. --set CONFIRM_NEW_CUSTOMER=0 (repeatable)")
    args = parser.parse_args()
    os.chdir(ROOT)
    # Values given here win over .env, because .env never overrides a variable that is already set.
    if args.db:
        os.environ["LEDGER_DB"] = args.db
    if args.web:
        os.environ["WEB_DIR"] = args.web
    for pair in args.set:
        name, sep, value = pair.partition("=")
        if not sep or not name.strip():
            parser.error(f"--set needs NAME=VALUE, got {pair!r}")
        os.environ[name.strip()] = value
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
