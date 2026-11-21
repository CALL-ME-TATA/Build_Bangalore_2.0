"""Validation for hand edits on the khata screens (CONTRACT 3.6): customer names, tags and phone numbers.

Every check raises `EditError`, which carries the HTTP status and the error code the route reports.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import nlu
from nlu.numbers import parse_number
from nlu.translit import romanise


class EditError(Exception):
    """A refused edit: `status` is the HTTP status and `code` the machine-readable detail."""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


NAME_MIN, NAME_MAX, TAG_MAX, TAGS_MAX = 2, 40, 24, 3
_NAME_PUNCT = set(".'-")


@lru_cache(maxsize=1)
def _never_names() -> frozenset[str]:
    """Words the parser never takes as a name (the `nevername` keyword class)."""
    path = Path(nlu.__file__).parent / "vocab" / "keywords.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(w.lower() for w in str(data.get("nevername", "")).split())


def _clean(text: str) -> str:
    """Romanise Devanagari, lower-case and collapse spaces."""
    return " ".join(romanise(text).lower().split())


def _letters_only(text: str) -> bool:
    return all(ch.isalpha() or ch == " " or ch in _NAME_PUNCT for ch in text)


def customer_key(text: object) -> str:
    """The key (the name the parser matches) for a typed display name, or `bad_name`."""
    if not isinstance(text, str):
        raise EditError(400, "bad_name")
    key = _clean(text)
    if not NAME_MIN <= len(key) <= NAME_MAX or not _letters_only(key) or not any(c.isalpha() for c in key):
        raise EditError(400, "bad_name")
    if parse_number(key) is not None:
        raise EditError(400, "bad_name")
    if all(w in _never_names() for w in key.split()):
        raise EditError(400, "bad_name")
    return key


def tag_list(tags: object) -> list[str]:
    """Up to three distinct tags made like names, each at most 24 characters, or `bad_tag`."""
    if not isinstance(tags, list) or len(tags) > TAGS_MAX:
        raise EditError(400, "bad_tag")
    out: list[str] = []
    for raw in tags:
        if not isinstance(raw, str):
            raise EditError(400, "bad_tag")
        tag = _clean(raw)
        if not tag or len(tag) > TAG_MAX or not _letters_only(tag) or not any(c.isalpha() for c in tag):
            raise EditError(400, "bad_tag")
        if tag not in out:
            out.append(tag)
    return out


def phone_number(value: object) -> str | None:
    """Ten digits of an Indian mobile number (91, +91 and 0 prefixes accepted), None for a cleared number."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise EditError(400, "bad_phone")
    digits = re.sub(r"[\s\-()]", "", value)
    if not digits:
        return None
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isascii() or not digits.isdigit():
        raise EditError(400, "bad_phone")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise EditError(400, "bad_phone")
    return digits


def phone_hint(phone: str | None) -> str | None:
    """`"•••• 3210"` for a stored number, never the number itself."""
    digits = re.sub(r"\D", "", phone or "")
    return f"•••• {digits[-4:]}" if len(digits) >= 4 else None
