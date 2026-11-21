"""Whole-rupee amounts as spoken words, for the speech synthesiser and for on-screen Roman text.

`number_to_words(n, "deva")` uses standard Devanagari spellings (340 -> "तीन सौ चालीस",
1500 -> "एक हज़ार पाँच सौ", 125000 -> "एक लाख पच्चीस हज़ार"). `number_to_words(n, "roman")` uses the
canonical Roman Hinglish spellings ("teen sau chaalis"). `number_to_words(n, "en")` is Indian English
("one thousand five hundred", "one lakh twenty five thousand"). All three read back through `parse_number`.
"""
from __future__ import annotations

import unicodedata

from .numbers import CANONICAL_DEVA, CANONICAL_ROMAN, DEVA_UNITS, ENGLISH_TENS, ENGLISH_UNITS

MAX_SPOKEN = 9_999_999

_ROMAN_UNITS = {100: "sau", 1000: "hazaar", 100000: "lakh"}
_ENGLISH_UNITS = {100: "hundred", 1000: "thousand", 100000: "lakh"}
_ZERO = {"deva": "शून्य", "roman": "shunya", "en": "zero"}
_EN_SMALL = {v: k for k, v in ENGLISH_UNITS.items() if v}
_EN_TENS = {v: k for k, v in ENGLISH_TENS.items() if k != "fourty"}


def _english_below_100(n: int) -> str:
    if n < 20:
        return _EN_SMALL[n]
    tens, unit = divmod(n, 10)
    return _EN_TENS[tens * 10] + (f" {_EN_SMALL[unit]}" if unit else "")


_EN_BELOW_100 = {k: _english_below_100(k) for k in range(1, 100)}


def number_to_words(n: int, script: str = "deva") -> str:
    """Spell `n` (0..9,999,999) in Indian grouping: lakh, thousand, hundred, then 1..99."""
    if script not in ("deva", "roman", "en"):
        raise ValueError("script must be 'deva', 'roman' or 'en'")
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= MAX_SPOKEN:
        raise ValueError(f"n must be an int in 0..{MAX_SPOKEN}")
    if n == 0:
        return _ZERO[script]
    if script == "en":
        below = _EN_BELOW_100
        units = _ENGLISH_UNITS
    else:
        below = CANONICAL_DEVA if script == "deva" else CANONICAL_ROMAN
        units = DEVA_UNITS if script == "deva" else _ROMAN_UNITS
    parts: list[str] = []
    lakh, rest = divmod(n, 100_000)
    hazaar, rest = divmod(rest, 1000)
    sau, tail = divmod(rest, 100)
    for count, unit in ((lakh, 100_000), (hazaar, 1000), (sau, 100)):
        if count:
            parts.append(f"{below[count]} {units[unit]}")
    if tail:
        parts.append(below[tail])
    return unicodedata.normalize("NFC", " ".join(parts))
