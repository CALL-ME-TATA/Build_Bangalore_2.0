"""Maintenance commands: `python -m app.admin purge|seed|init-key`.

purge     delete the database files and the cached TTS audio (the ledger is never edited row by row)
seed      add a few synthetic customers and entries for demos
init-key  create data/ledger.key when neither LEDGER_KEY nor the key file exists
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Settings, get_settings
from .crypto import Crypto, load_key
from .ledger import Ledger


def purge(settings: Settings) -> list[str]:
    """Delete the SQLite database (with its WAL files) and the TTS audio cache. Returns what was removed."""
    removed = []
    base = settings.db_path
    for suffix in ("", "-wal", "-shm"):
        path = base.parent / (base.name + suffix)
        if path.exists():
            path.unlink()
            removed.append(path.name)
    if settings.tts_cache_dir.exists():
        shutil.rmtree(settings.tts_cache_dir, ignore_errors=True)
        removed.append(settings.tts_cache_dir.name + "/")
    users = settings.data_dir / "users"  # one ledger per signed-in Google account
    if users.exists():
        shutil.rmtree(users, ignore_errors=True)
        removed.append("users/")
    return removed


SEED_CUSTOMERS = [
    ("ramesh", ["chai wale"], 340),
    ("ramesh", ["gali wale"], 150),
    ("sunita", [], 500),
    ("mohan", ["doodh wale"], 1200),
    ("geeta", [], 0),
]


def seed(ledger: Ledger, settings: Settings) -> int:
    """Add synthetic customers with a few credit and payment entries. Returns the number of customers added."""
    now = datetime.now(ZoneInfo(settings.shop_tz))
    session = "seed"
    for key, tags, owed in SEED_CUSTOMERS:
        c = ledger.create_customer(key, tags=tags, now=now)
        if owed:
            res = {"action": "append", "events": [{"kind": "credit", "customer": key, "customer_id": c["id"],
                                                  "amount": owed, "date": (now - timedelta(days=2)).date().isoformat()}]}
            ledger.apply(res, now=now, session_id=session)
    return len(SEED_CUSTOMERS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin")
    parser.add_argument("command", choices=["purge", "seed", "init-key"])
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.command == "purge":
        try:
            removed = purge(settings)
        except OSError as exc:
            print(f"Could not delete the database ({type(exc).__name__}): another process, probably the running "
                  "server, is holding it. Stop the server, or call POST /api/admin/purge with the admin token "
                  "while it runs, then try again.")
            return 1
        print("removed: " + (", ".join(removed) if removed else "nothing"))
    elif args.command == "init-key":
        load_key(settings.ledger_key, settings.key_path)
        print(f"key ready ({'LEDGER_KEY' if settings.ledger_key else settings.key_path})")
    else:
        ledger = Ledger(settings.db_path, Crypto(load_key(settings.ledger_key, settings.key_path)))
        n = seed(ledger, settings)
        ledger.close()
        print(f"seeded {n} synthetic customers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
