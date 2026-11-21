"""Test oracle: render integers as Roman-script Hindi number words.

Used for round-trip property tests: parse_number(render(n)) must equal n.
The 1..99 table was checked on 2026-11-21 against the romanisation in the Wikipedia article "Hindi numerals"
(see docs/research/hinglish-ledger-language.md, section 2); eight spellings were corrected. The older spellings
must still parse and are covered in tests/nlu/test_number_forms.py.
"""
from __future__ import annotations

import re

BELOW_100 = {
    1: "ek", 2: "do", 3: "teen", 4: "chaar", 5: "paanch", 6: "chhe", 7: "saat", 8: "aath", 9: "nau",
    10: "das", 11: "gyarah", 12: "barah", 13: "terah", 14: "chaudah", 15: "pandrah", 16: "solah",
    17: "satrah", 18: "atharah", 19: "unnees",
    20: "bees", 21: "ikkees", 22: "baees", 23: "teis", 24: "chaubees", 25: "pachchees",
    26: "chhabbees", 27: "sattaees", 28: "atthaees", 29: "untees",
    30: "tees", 31: "ikatees", 32: "battees", 33: "taintees", 34: "chauntees", 35: "paintees",
    36: "chhattees", 37: "saintees", 38: "adtees", 39: "untaalees",
    40: "chaalees", 41: "iktaalees", 42: "bayaalees", 43: "taintaalees", 44: "chauvaalees",
    45: "paintaalees", 46: "chhiyaalees", 47: "saintaalees", 48: "adtaalees", 49: "unchaas",
    50: "pachaas", 51: "ikyaavan", 52: "baavan", 53: "tirpan", 54: "chauvan", 55: "pachpan",
    56: "chhappan", 57: "sattaavan", 58: "atthaavan", 59: "unsath",
    60: "saath", 61: "iksath", 62: "baasath", 63: "tirsath", 64: "chausath", 65: "painsath",
    66: "chhiyaasath", 67: "sadsath", 68: "adsath", 69: "unhattar",
    70: "sattar", 71: "ikahattar", 72: "bahattar", 73: "tihattar", 74: "chauhattar", 75: "pachahattar",
    76: "chhihattar", 77: "satahattar", 78: "athahattar", 79: "unyaasi",
    80: "assi", 81: "ikyaasi", 82: "bayaasi", 83: "tiraasi", 84: "chauraasi", 85: "pachaasi",
    86: "chhiyaasi", 87: "sataasi", 88: "atthaasi", 89: "navaasi",
    90: "nabbe", 91: "ikyaanave", 92: "baanave", 93: "tiraanave", 94: "chauraanave", 95: "pachaanave",
    96: "chhiyaanave", 97: "sattaanave", 98: "atthaanave", 99: "ninyaanave",
}

MAX_N = 999_999


def render(n: int) -> str:
    """Canonical Roman Hinglish words for 1..999,999, e.g. 340 -> 'teen sau chaalees'."""
    if not 1 <= n <= MAX_N:
        raise ValueError(f"n must be in 1..{MAX_N}")
    parts: list[str] = []
    lakh, rest = divmod(n, 100_000)
    if lakh:
        parts.append(f"{BELOW_100[lakh]} lakh")
    hazaar, rest = divmod(rest, 1000)
    if hazaar:
        parts.append(f"{BELOW_100[hazaar]} hazaar")
    sau, tail = divmod(rest, 100)
    if sau:
        parts.append(f"{BELOW_100[sau]} sau")
    if tail:
        parts.append(BELOW_100[tail])
    return " ".join(parts)


def variants(words: str) -> list[str]:
    """Common romanization variants of the canonical form (STT output is not consistent).

    - word-final "ees" -> "is" (chaalees -> chaalis, bees -> bis; the pitch deck spells it chaalis)
    - "aa" -> "a" (paanch -> panch)
    - every "ee" -> "i" (teen -> tin)
    - all of the above together
    """
    ees_to_is = " ".join(re.sub(r"ees$", "is", w) for w in words.split())
    aa_to_a = words.replace("aa", "a")
    ee_to_i = words.replace("ee", "i")
    combined = " ".join(re.sub(r"ees$", "is", w) for w in words.replace("aa", "a").split())
    out: list[str] = []
    for v in (words, ees_to_is, aa_to_a, ee_to_i, combined):
        if v not in out:
            out.append(v)
    return out
