"""Text helpers shared by the number, name and sentence parsers.

- `normalise(text)`: Unicode NFC, lower case, Devanagari digits to ASCII, zero-width characters removed.
- `romanise_word(word, long_vowels=True)`: Devanagari word to lowercase Roman with Hindi schwa deletion.
  With `long_vowels=True` long vowels are written double (aa, ee, oo), which keeps keyword and number lookups
  close to common Hinglish typing. With `long_vowels=False` they are written single (रमेश -> ramesh,
  सुनीता -> sunita), which is the customer-key convention.
- `fold(word)`: collapses the spelling variation seen in Roman Hinglish (vowel length, doubled consonants,
  chh/ch, w/v, z/j, nasalisation, a trailing h after a vowel, the r-flap written d) into one lookup form.
  It deliberately keeps `th` distinct from `t`, `ei` distinct from `i`, and a trailing `i`, so that
  saath/saat, teis/tees and pachaas/pachaasi stay apart.
"""
from __future__ import annotations

import re
import unicodedata

_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)

_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "ऩ": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ऱ": "r", "ल": "l", "ळ": "l", "ऴ": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
# Consonant + nukta. NFC decomposes the precomposed forms (U+0958..U+095F), so only the combining form is seen.
_NUKTA_FORMS = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f", "य": "y"}
_INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ॠ": "ri", "ऌ": "li",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e", "ऎ": "e", "ऒ": "o",
}
_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "ॄ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e", "ॆ": "e", "ॊ": "o",
}
_SHORT = {"aa": "a", "ee": "i", "oo": "u"}
_VIRAMA, _ANUSVARA, _CANDRABINDU, _VISARGA, _NUKTA = "्", "ं", "ँ", "ः", "़"

DEVANAGARI_RUN = re.compile(r"[ऀ-ॣ॰-ॿ]+")


def normalise(text: str) -> str:
    """NFC, lower case, ASCII digits, no zero-width characters."""
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    return text.translate(_DEVA_DIGITS).lower()


def is_devanagari(word: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in word)


class _Unit:
    """One written syllable: a consonant cluster (possibly empty) and its vowel."""

    __slots__ = ("cons", "ncons", "vowel", "inherent", "nasal", "coda", "base")

    def __init__(self, cons: str, vowel: str | None, inherent: bool, base: str = ""):
        self.cons = cons
        self.ncons = 1 if cons else 0
        self.vowel = vowel
        self.inherent = inherent
        self.nasal = False
        self.coda = ""
        self.base = base  # last Devanagari consonant, for a following nukta


def romanise_word(word: str, long_vowels: bool = True) -> str:
    """Romanise one Devanagari word. Non-Devanagari characters pass through unchanged."""
    units: list[_Unit] = []
    virama_open = False
    out_prefix = []
    for ch in word:
        if ch in _CONSONANTS:
            roman = _CONSONANTS[ch]
            if units and virama_open:
                unit = units[-1]
                unit.cons += roman
                unit.ncons += 1
                unit.vowel, unit.inherent, unit.base = "a", True, ch
            else:
                units.append(_Unit(roman, "a", True, ch))
            virama_open = False
            continue
        virama_open = False if ch != _VIRAMA else virama_open
        if ch == _NUKTA:
            if units and units[-1].base in _NUKTA_FORMS:
                unit = units[-1]
                plain = _CONSONANTS[unit.base]
                if unit.cons.endswith(plain):
                    unit.cons = unit.cons[: len(unit.cons) - len(plain)] + _NUKTA_FORMS[unit.base]
                unit.base = ""
        elif ch in _MATRAS:
            if units and units[-1].cons:
                units[-1].vowel, units[-1].inherent = _MATRAS[ch], False
            else:
                units.append(_Unit("", _MATRAS[ch], False))
        elif ch == _VIRAMA:
            if units and units[-1].cons:
                units[-1].vowel, units[-1].inherent = None, False
                virama_open = True
        elif ch in _INDEPENDENT_VOWELS:
            units.append(_Unit("", _INDEPENDENT_VOWELS[ch], False))
        elif ch in (_ANUSVARA, _CANDRABINDU):
            if units:
                units[-1].nasal = True
            else:
                out_prefix.append("n")
        elif ch == _VISARGA:
            if units:
                units[-1].coda = "h"
        elif ch == "ॐ":
            units.append(_Unit("", "om", False))
        elif "ऀ" <= ch <= "ॿ":
            continue  # avagraha, danda, signs without a sound
        else:
            units.append(_Unit("", ch, False))

    _delete_schwas(units)

    parts = list(out_prefix)
    for i, unit in enumerate(units):
        vowel = unit.vowel or ""
        if not long_vowels and vowel in _SHORT:
            vowel = _SHORT[vowel]
        nasal = ""
        if unit.nasal:
            nxt = units[i + 1].cons if i + 1 < len(units) else ""
            nasal = "m" if nxt[:1] in ("p", "b", "m") and nxt[:2] != "ph" else "n"
            if unit.cons and unit.vowel is None:
                nasal = "n"
        parts.append(unit.cons + vowel + nasal + unit.coda)
    return "".join(parts)


def _delete_schwas(units: list[_Unit]) -> None:
    """Hindi schwa deletion: drop the final inherent 'a', then medial ones in the context V C(a) C V."""
    n = len(units)
    if n == 0:
        return
    last = units[-1]
    if n > 1 and last.inherent and not last.nasal and not last.coda and last.ncons == 1:
        last.vowel, last.inherent = None, False
    for i in range(n - 2, 0, -1):
        unit = units[i]
        if not unit.inherent or unit.nasal or unit.coda or unit.ncons != 1:
            continue
        prev, nxt = units[i - 1], units[i + 1]
        if prev.vowel is None:
            continue
        if nxt.ncons != 1 or nxt.vowel is None:
            continue
        unit.vowel, unit.inherent = None, False


def romanise(text: str, long_vowels: bool = True) -> str:
    """Romanise every Devanagari run in `text`; everything else is unchanged."""
    return DEVANAGARI_RUN.sub(lambda m: romanise_word(m.group(0), long_vowels), text)


_NASAL_BEFORE_CONSONANT = re.compile(r"n(?=[bcdfgjklmpqrstvxz])")
_FLAP = re.compile(r"d(?=[ts])")
_DOUBLE = re.compile(r"(.)\1+")
_TRAILING_H = re.compile(r"(?<=[aeiou])h$")


def fold(word: str) -> str:
    """Spelling-variant fold for a single lowercase Roman word (see the module docstring)."""
    w = word.replace("chh", "ch").replace("cch", "ch").replace("chch", "ch")
    w = w.replace("w", "v").replace("z", "j").replace("q", "k")
    w = _FLAP.sub("r", w)
    w = w.replace("ee", "i").replace("ii", "i").replace("oo", "u").replace("uu", "u").replace("aa", "a")
    w = _NASAL_BEFORE_CONSONANT.sub("", w)
    w = _DOUBLE.sub(r"\1", w)
    w = _TRAILING_H.sub("", w)
    return w
