"""Logging helpers that keep customer data out of log lines (CONTRACT 3.3, P05).

Exception messages can hold names, amounts or transcripts, so only the exception type and the code location of
the innermost frame are ever logged. Uvicorn's access records carry the request line, whose query string can hold
the access code (`?code=`); `StripQuery` removes it.
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path


def describe(exc: BaseException) -> str:
    """`TypeName at file.py:123`: the exception type and where it was raised, never its message."""
    frames = traceback.extract_tb(exc.__traceback__)
    where = f"{Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else "?"
    return f"{type(exc).__name__} at {where}"


class StripQuery(logging.Filter):
    """Removes the query string from the path of uvicorn access records."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            record.args = args[:2] + (args[2].split("?", 1)[0],) + args[3:]
        return True


class NoDebug(logging.Filter):
    """Drops DEBUG records: at that level websockets logs frames and upgrade headers verbatim."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno > logging.DEBUG
