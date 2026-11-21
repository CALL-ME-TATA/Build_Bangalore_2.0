"""Spoken and written amounts to whole rupees.

`parse_number(text)` accepts one number phrase in any of these forms (CONTRACT 1.3):

- digits: 340, 1,500, 1,25,000, ₹340, Rs 340, Rs. 340, 340/-, 340 rupaye, ३४०
- Hindi words in Roman or Devanagari script, 1 to 99,99,999, with the unit words sau / hazaar / lakh and
  the usual Hinglish spelling variation (vowel length, doubled consonants, chh/ch, v/w, nasalisation,
  trailing h, the r-flap written d or r)
- fractions: sawa (+1/4), saade (+1/2, needs a number of 3 or more), paune (-1/4), dedh (1.5), dhai (2.5),
  each followed by a unit word
- English: three hundred (and) forty, three forty, two fifty, fifteen hundred, one thousand five hundred

It returns None when the text is anything other than exactly one whole-rupee number phrase.

Word lookup: every spelling of a number word is reduced with `translit.fold` and stored in one dictionary.
The dictionary is built from the canonical spellings, the listed variants, a few generation rules and the
romanised Devanagari forms; building it raises if any folded spelling would map to two different values.
"""
from __future__ import annotations

import re
from fractions import Fraction
from functools import lru_cache

from .lexicon import load
from .translit import fold, is_devanagari, normalise, romanise_word

_V = load("numbers")  # number words, units, fractions, currency words: nlu/vocab/numbers.json

# Roman spellings of 1..99. The first entry is the canonical spelling (used by nlu.speak); the rest are
# variants. Older or alternative transcriptions are listed explicitly; the fold covers the rest.
_ROMAN_1_99 = {int(k): v for k, v in _V["roman_1_99"].items()}

# Standard Devanagari spellings (the first is used by nlu.speak), then alternatives.
DEVA_1_99 = {int(k): v for k, v in _V["deva_1_99"].items()}

_UNITS = {int(k): v for k, v in _V["units"].items()}
DEVA_UNITS = {int(k): v for k, v in _V["deva_units"].items()}

_FRACTIONS = _V["fractions"]

ENGLISH_UNITS = _V["english_units"]
ENGLISH_TENS = _V["english_tens"]
ENGLISH_SCALES = _V["english_scales"]

CURRENCY_WORDS = frozenset(fold(romanise_word(w) if is_devanagari(w) else w) for w in _V["currency"])
ZERO_WORDS = frozenset(_V["zero"])


def _spellings(text: str) -> list[str]:
    """Lowercase Roman spellings for a space-separated list that may mix Roman and Devanagari."""
    out = []
    for w in normalise(text).split():
        out.append(romanise_word(w) if is_devanagari(w) else w)
    return out


def _generated(word: str) -> list[str]:
    """Rule-generated spellings that the fold does not already cover."""
    out = [word]
    if word.startswith("chau"):
        out += ["cho" + word[4:], "chou" + word[4:], "chow" + word[4:]]
    if word.endswith("aanave"):
        out.append(word[: -len("aanave")] + "aanve")
        out.append(word[: -len("aanave")] + "anve")
    if word.endswith("ees"):
        out.append(word[:-3] + "is")
    if "ai" in word:
        out += [w.replace("ai", "e") for w in list(out)]
    return out


def _build_lookup() -> dict[str, tuple[str, object]]:
    """fold(spelling) -> ("n", 1..99) | ("u", 100|1000|100000) | ("f", fraction name). Raises on a collision."""
    table: dict[str, tuple[str, object]] = {}
    sources: dict[str, str] = {}

    def add(spelling: str, entry: tuple[str, object]) -> None:
        key = fold(spelling)
        if not key:
            return
        if key in table and table[key] != entry:
            raise RuntimeError(
                f"number spelling collision: {spelling!r} -> {entry} but {sources[key]!r} -> {table[key]}"
            )
        table[key] = entry
        sources.setdefault(key, spelling)

    for n, text in _ROMAN_1_99.items():
        for w in _spellings(text):
            for g in _generated(w):
                add(g, ("n", n))
    for n, text in DEVA_1_99.items():
        for w in _spellings(text):
            for g in _generated(w):
                add(g, ("n", n))
    for value, text in _UNITS.items():
        for w in _spellings(text):
            add(w, ("u", value))
    for name, text in _FRACTIONS.items():
        for w in _spellings(text):
            add(w, ("f", name))
    return table


WORD_LOOKUP = _build_lookup()
CANONICAL_ROMAN = {n: text.split()[0] for n, text in _ROMAN_1_99.items()}
CANONICAL_DEVA = {n: text.split()[0] for n, text in DEVA_1_99.items()}


@lru_cache(maxsize=65536)
def classify_word(word: str) -> tuple[str, object, str] | None:
    """Classify one lowercase Roman or Devanagari word as a number item, or None.

    Items: ("n", value 0..99, source) for a number word, ("u", 100|1000|100000, source) for a unit word,
    ("f", name, source) for a fraction word. source is "en" for English words, else "hi".
    """
    if word in ENGLISH_UNITS:
        return ("n", ENGLISH_UNITS[word], "en")
    if word in ENGLISH_TENS:
        return ("n", ENGLISH_TENS[word], "en")
    if word in ("hundred", "thousand"):
        return ("u", ENGLISH_SCALES[word], "en")
    roman = romanise_word(word) if is_devanagari(word) else word
    if roman in ZERO_WORDS:
        return ("n", 0, "hi")
    hit = WORD_LOOKUP.get(fold(roman))
    if hit is None:
        return None
    return (hit[0], hit[1], "hi")


_DIGITS_RE = re.compile(r"^\d+(?:,\d+)*(?:\.\d+)?$")
_K_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?k\b")
_LETTER_DIGIT_RE = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")


def expand_text(s: str) -> str:
    """Rewrite digit forms before tokenising: "2k" / "2.5k" -> thousands, commas between digits dropped whatever
    the grouping ("3,40" -> 340), and a letters-digits boundary split ("ko500" -> "ko 500")."""
    s = re.sub(r"(?<=\d),(?=\d)", "", s)

    def thousands(m: re.Match) -> str:
        v = Fraction(m.group(1)) * 1000
        return str(v.numerator) if v.denominator == 1 else str(float(v))

    s = _K_RE.sub(thousands, s)
    return _LETTER_DIGIT_RE.sub(" ", s)


def digit_sequence(items: list) -> int | None:
    """Three or more single-digit words in a row with no unit word are the digits joined ("four three zero")."""
    if len(items) >= 3 and all(k == "n" and isinstance(v, int) and 0 <= v <= 9 for k, v, _ in items):
        if items[0][1] == 0:
            return None
        return int("".join(str(v) for _, v, _ in items))
    return None


def digits_value(token: str) -> Fraction | None:
    """Value of a digit token such as 340, 1,25,000, 3,40 or 1.5 (commas are dropped), or None if malformed."""
    if not _DIGITS_RE.match(token):
        return None
    try:
        return Fraction(token.replace(",", ""))
    except (ValueError, ZeroDivisionError):
        return None


def value_of_items(items: list[tuple[str, object, str]]) -> int | None:
    """Combine number items (see `classify_word`; digits are ("d", Fraction, "dig")) into whole rupees."""
    items = _merge_english(items)
    if items is None or not items:
        return None
    n = len(items)
    # English "three forty", "seven fifty", "twelve fifty": hundreds then a two-digit number.
    if n == 2 and all(k == "n" and s == "en" for k, _, s in items):
        a, b = items[0][1], items[1][1]
        if 1 <= a <= 19 and 10 <= b <= 99:
            return a * 100 + b
        return None
    if n == 1 and items[0][0] == "d":
        v = items[0][1]
        return int(v) if v.denominator == 1 else None

    total = Fraction(0)
    last_unit: int | None = None
    frac_unit: int | None = None  # unit of a fraction group; what follows must stay below a quarter of it
    after_frac = Fraction(0)
    i = 0
    while i < n:
        kind, value, _src = items[i]
        group: Fraction | None = None
        if kind == "f":
            j = i + 1
            mult = None
            if j < n and items[j][0] in ("n", "d"):
                if value in ("dedh", "dhai"):
                    return None
                mult = Fraction(items[j][1])
                if mult.denominator != 1 or not 1 <= mult <= 99:
                    return None
                j += 1
            if j >= n or items[j][0] != "u":
                return None
            unit = items[j][1]
            if value == "saade":
                if mult is None or mult < 3:
                    return None
                group = (mult + Fraction(1, 2)) * unit
            elif value == "sawa":
                group = ((mult or 1) + Fraction(1, 4)) * unit
            elif value == "paune":
                group = ((mult or 1) - Fraction(1, 4)) * unit
            elif value == "dedh":
                group = Fraction(3, 2) * unit
            else:
                group = Fraction(5, 2) * unit
            if not _unit_allowed(unit, mult, last_unit):
                return None
            next_i = j + 1
        elif kind in ("n", "d"):
            mult = Fraction(value)
            if i + 1 < n and items[i + 1][0] == "u":
                unit = items[i + 1][1]
                if kind == "n" and mult < 1:
                    return None
                if not 0 < mult <= 99 or not _unit_allowed(unit, mult, last_unit):
                    return None
                group = mult * unit
                next_i = i + 2
            else:
                if i != n - 1 or mult.denominator != 1 or mult < 1:
                    return None
                if last_unit is not None and mult >= last_unit:
                    return None
                if kind == "d" and last_unit is None:
                    return None
                total += mult
                if frac_unit is not None:
                    after_frac += mult
                i += 1
                continue
        elif kind == "u":
            if last_unit is not None:
                return None
            unit = value
            group = Fraction(unit)
            next_i = i + 1
        else:
            return None
        if frac_unit is not None:
            after_frac += group
        total += group
        last_unit = unit
        if kind == "f":
            frac_unit, after_frac = unit, Fraction(0)
        i = next_i
    if frac_unit is not None and after_frac * 4 >= frac_unit:
        return None
    if total.denominator != 1:
        return None
    return int(total)


def _unit_allowed(unit: int, mult: Fraction | None, last_unit: int | None) -> bool:
    """Groups go in descending order; "pandrah sau" style multipliers of 10..99 only lead the phrase."""
    if last_unit is not None and unit >= last_unit:
        return False
    if unit == 100 and mult is not None and mult >= 10 and last_unit is not None:
        return False
    return True


def _merge_english(items):
    """Drop an English "and" after a scale word and merge "twenty five" into 25."""
    out = []
    i = 0
    n = len(items)
    while i < n:
        kind, value, src = items[i]
        if kind == "and":
            if not out or out[-1][0] != "u" or i + 1 >= n or items[i + 1][0] not in ("n", "d"):
                return None
            i += 1
            continue
        if (kind == "n" and src == "en" and value in (20, 30, 40, 50, 60, 70, 80, 90) and i + 1 < n
                and items[i + 1][0] == "n" and items[i + 1][2] == "en" and 1 <= items[i + 1][1] <= 9):
            out.append(("n", value + items[i + 1][1], "en"))
            i += 2
            continue
        out.append(items[i])
        i += 1
    return out


_SPLIT_RE = re.compile(r"₹|\d+(?:,\d+)*(?:\.\d+)?|[a-z]+|[ऀ-ॣ॰-ॿ]+")


def parse_number(text: str) -> int | None:
    """Return the whole-rupee value of `text`, or None if it is not exactly one number phrase."""
    if not isinstance(text, str):
        return None
    s = normalise(text)
    s = re.sub(r"\brs\.", "rs ", s).replace("/-", " ").replace("-", " ")
    s = expand_text(s)
    items = []
    for tok in _SPLIT_RE.findall(s):
        if tok == "₹":
            continue
        if tok[0].isdigit():
            v = digits_value(tok)
            if v is None:
                return None
            items.append(("d", v, "dig"))
            continue
        if tok == "and":
            items.append(("and", None, "en"))
            continue
        item = classify_word(tok)
        if item is not None:
            items.append(item)
            continue
        roman = romanise_word(tok) if is_devanagari(tok) else tok
        if fold(roman) in CURRENCY_WORDS:
            continue
        return None
    if not items:
        return None
    if len(items) == 1 and items[0][0] == "n" and items[0][1] == 0:
        return 0
    seq = digit_sequence(items)
    if seq is not None:
        return seq
    if any(k == "n" and v == 0 for k, v, _ in items):
        return None
    return value_of_items(items)
