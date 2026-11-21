"""Customer names: lowercase Roman keys, tags and the phonetic form used for matching (CONTRACT 1.8).

- `name_key("Sharma ji")` -> "sharma"; `name_key("रमेश")` -> "ramesh"; `name_key("Ramesh chai wale")` -> "ramesh".
- `split_name("Ramesh chai wale")` -> ("ramesh", ["chai wale"]); `gali ...` phrases are tags too.
- `phonetic_key("suneeta")` -> "sunita". It is only for matching and is never stored as a name.
"""
from __future__ import annotations

import re

from .numbers import parse_number
from .translit import fold, is_devanagari, normalise, romanise_word

HONORIFICS = frozenset({
    "ji", "jee", "bhai", "bhaiya", "bhaiyya", "bhaiyaa", "bhaisaab", "bhaisahab", "saab", "sahab", "saheb", "sahib",
    "didi", "di", "behen", "behenji", "bhabhi", "uncle", "aunty", "auntie", "anti", "seth", "sethji", "sir", "madam",
    "chacha", "chachi", "mama", "mami", "dada", "dadi", "kaka", "kaki", "amma", "anna", "lala", "babu", "mr", "mrs",
    "shri", "shrimati", "smt",
})
TAG_WORDS = frozenset({"wale", "wala", "wali", "vale", "vala", "vali", "waale", "waala", "waali", "vaale", "vaala"})
GALI_WORDS = frozenset({"gali", "galli", "gully"})
TAG_FILLERS = frozenset({"number", "no", "nambar", "numbar", "num", "nmbr"})

_HONORIFIC_FOLDS = frozenset(fold(w) for w in HONORIFICS)
_TAG_FOLDS = frozenset(fold(w) for w in TAG_WORDS)
_GALI_FOLDS = frozenset(fold(w) for w in GALI_WORDS)

_WORD_RE = re.compile(r"\d+|[a-z]+|[ऀ-ॣ॰-ॿ]+")


def roman_tokens(text: str) -> list[str]:
    """Lowercase Roman word tokens; Devanagari words are romanised with single long vowels."""
    out = []
    for tok in _WORD_RE.findall(normalise(text)):
        out.append(romanise_word(tok, long_vowels=False) if is_devanagari(tok) else tok)
    return out


def is_honorific(word: str) -> bool:
    return fold(word) in _HONORIFIC_FOLDS


def is_tag_word(word: str) -> bool:
    return fold(word) in _TAG_FOLDS


def is_gali_word(word: str) -> bool:
    return fold(word) in _GALI_FOLDS


def split_tokens(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Split Roman tokens into (name tokens, tags). Honorifics are dropped."""
    name: list[str] = []
    tags: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        if is_gali_word(tok):
            j = i + 1
            parts = ["gali"]
            while j < n and tokens[j] in TAG_FILLERS:
                parts.append("number")
                j += 1
            if j < n:
                value = parse_number(tokens[j])
                parts.append(str(value) if value is not None else tokens[j])
                j += 1
            tags.append(" ".join(parts))
            i = j
            continue
        if i + 1 < n and is_tag_word(tokens[i + 1]) and not is_honorific(tok):
            tags.append(f"{tok} wale")
            i += 2
            continue
        if is_tag_word(tok):
            i += 1
            continue
        if not is_honorific(tok):
            name.append(tok)
        i += 1
    return name, tags


def split_name(text: str) -> tuple[str, list[str]]:
    """(key, tags) for a spoken name phrase such as "Ramesh chai wale" or "Sharma ji"."""
    name, tags = split_tokens(roman_tokens(text))
    return " ".join(name), tags


def name_key(text: str) -> str:
    """Lowercase Roman customer key from Roman or Devanagari input (honorifics and tags removed)."""
    if not isinstance(text, str):
        return ""
    name, _tags = split_tokens(roman_tokens(text))
    return " ".join(name)


_PHONETIC_DOUBLE = re.compile(r"([a-z])\1+")


def phonetic_key(key: str) -> str:
    """Matching form of a key: ee/ii->i, oo/uu->u, aa->a, w->v, doubled letters collapsed; th/dh/sh kept."""
    if not isinstance(key, str):
        return ""
    k = key.lower()
    k = k.replace("ee", "i").replace("ii", "i").replace("oo", "u").replace("uu", "u").replace("aa", "a")
    k = k.replace("w", "v")
    k = _PHONETIC_DOUBLE.sub(r"\1", k)
    return " ".join(k.split())


def tag_words(tag: str) -> list[str]:
    """Content words of a tag for loose matching: wala/wale/wali and "number" dropped, phonetic, ay -> ai.

    In a gali tag a number word is compared as digits ("gali number teen" matches "gali number 3").
    """
    out = []
    words = roman_tokens(tag)
    gali = any(is_gali_word(w) for w in words)
    for w in words:
        if is_tag_word(w) or w in TAG_FILLERS:
            continue
        if gali and not w.isdigit() and not is_gali_word(w):
            value = parse_number(w)
            if value is not None and value > 0:
                w = str(value)
        p = phonetic_key(w)
        if p.endswith("ay"):
            p = p[:-2] + "ai"
        if is_gali_word(p):
            p = "gali"
        out.append(p)
    return out


def tag_matches(spoken: str, stored: str) -> bool:
    """True when every content word of the spoken tag appears in the stored tag ("chai" matches "chai wale")."""
    sw, tw = tag_words(spoken), set(tag_words(stored))
    return bool(sw) and all(w in tw for w in sw)
