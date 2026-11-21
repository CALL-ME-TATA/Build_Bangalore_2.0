"""Customer names: lowercase Roman keys, tags and the phonetic form used for matching (CONTRACT 1.8).

- `name_key("Sharma ji")` -> "sharma"; `name_key("रमेश")` -> "ramesh"; `name_key("Ramesh chai wale")` -> "ramesh".
- `split_name("Ramesh chai wale")` -> ("ramesh", ["chai wale"]); `gali ...` phrases are tags too.
- `phonetic_key("suneeta")` -> "sunita". It is only for matching and is never stored as a name.
"""
from __future__ import annotations

import re

from .lexicon import load
from .numbers import parse_number
from .translit import fold, is_devanagari, normalise, romanise_word

_V = load("names")  # honorifics and tag words: nlu/vocab/names.json
HONORIFICS = frozenset(_V["honorifics"])
TAG_WORDS = frozenset(_V["tag_words"])
GALI_WORDS = frozenset(_V["gali_words"])
TAG_FILLERS = frozenset(_V["tag_fillers"])

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


def split_tokens(tokens: list[str], honorific_name: bool = False) -> tuple[list[str], list[str]]:
    """Split Roman tokens into (name tokens, tags). Honorifics are dropped next to a name.

    With `honorific_name=True` (the words directly before a particle, or an answer to "Kiska khata?") a phrase made
    only of kinship words and honorifics is itself the name: "Chacha" -> chacha, "Lala ji" -> lala.
    """
    name: list[str] = []
    honorifics: list[str] = []
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
        else:
            honorifics.append(tok)
        i += 1
    if not name and honorific_name and honorifics:
        kept = [h for h in honorifics if fold(h) not in (fold("ji"), fold("jee"))]
        name = kept or honorifics
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


_VOWELS = "aeiou"


def _skeleton(word: str) -> tuple[str, str]:
    """(consonants in order, ending) of one phonetic word. y counts as a vowel; the ending is the final folded vowel
    or "C" for a consonant."""
    consonants = "".join(ch for ch in word if ch not in _VOWELS and ch != "y")
    consonants = _PHONETIC_DOUBLE.sub(r"", consonants)
    last = word[-1:] if word else ""
    return consonants, (last if last in _VOWELS else "C")


def same_person(a: str, b: str) -> bool:
    """Fuzzy name match (CONTRACT 1.12): equal phonetic keys, or the same number of words and, word by word, the
    same consonants in the same order and the same ending. rameysh = ramesh; sunit != sunita; rajan != ranjan."""
    pa, pb = phonetic_key(a).replace("th", "t"), phonetic_key(b).replace("th", "t")  # Sunitha = Sunita (1.14)
    if not pa or not pb:
        return False
    if pa == pb:
        return True
    wa, wb = pa.split(), pb.split()
    if len(wa) != len(wb):
        return False
    return all(_skeleton(x) == _skeleton(y) for x, y in zip(wa, wb))


def _edit1(a: str, b: str) -> bool:
    """True when a and b differ by exactly one substitution, insertion or deletion."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(b)):
        if b[:i] + b[i + 1:] == a:
            return True
    return False


def close_name(spoken: str, stored: str) -> bool:
    """Not the same person, but close enough to ask about (1.14 E05): one consonant differs or is missing
    ("rakes" / "rakesh", "ramesh" / "rakesh"), or the spoken word is the end of the stored name and has three
    letters or more ("esh" for "ramesh")."""
    if not spoken or not stored or same_person(spoken, stored):
        return False
    pa = phonetic_key(spoken).replace("th", "t")
    pb = phonetic_key(stored).replace("th", "t")
    wa, wb = pa.split(), pb.split()
    if len(wa) == 1 and len(pa) >= 3 and pb.endswith(pa) and pb != pa:
        return True
    if len(wa) != len(wb):
        return False
    diffs = 0
    for x, y in zip(wa, wb):
        if x == y:
            continue
        cx, ex = _skeleton(x)
        cy, ey = _skeleton(y)
        if ex == ey and _edit1(cx, cy):
            diffs += 1
        elif cx == cy and _edit1(x, y):
            diffs += 1
        else:
            return False
    return diffs == 1


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
