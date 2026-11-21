"""Utterance to a structured ledger result (CONTRACT section 1).

`parse(utterance, today=..., ctx=...)` is a pure function: no I/O, no clock, no state between calls. It never
raises; anything it cannot read becomes a `rejected` or `needs_clarification` result, and it never guesses an
amount, a direction, a date or a customer.

Pipeline
1. Tokenise. Roman, Devanagari and digits are all accepted; Devanagari words are romanised, and every word is
   reduced with `translit.fold` so keyword spellings vary as freely as number spellings (udhar / udhaar).
   English `X's` becomes a possessive particle.
2. Mark spans: the word before a particle becomes a name whatever else it could mean (`Chacha ne`, `Diya ko`);
   relations (`Ramesh ki biwi`, `Ramesh's wife`) become one name; tag phrases (`chai wale`, `gali number 3`);
   `N din pehle` dates (one number counts the days); number phrases (one amount each; `likh do sau` keeps both
   readings). Filler words are dropped; first-person words (`maine`, `mujhe`, `I`) and pronouns are kept as
   keywords and never become names.
3. A pending question (`ctx.pending`) is answered first when the utterance is an answer, with extra words allowed;
   two unresolved answers in a row cancel the question (`pending.attempts`).
4. Otherwise: negation, future, yes/no questions, undo, correction, query, then ledger clauses. Clauses split on
   `,` `aur` `phir` `and`, and without punctuation where a second amount brings its own date word or name.
   Corrections choose their target among `ctx.last_events` and ask which entry when that is not clear.
5. Guards, in order: missing amount / customer / direction / date, customer resolution (same name), confusable
   number (`likh do sau`, `stt_alternatives`), plausibility (`limits.confirm_above`).
6. Every result carries `lang` ("en" or "hi") when the words tell the language.

Section 1.14 adds, in the same pipeline: quantities that are never amounts ("2 kilo"), stated balances
("total 800 ho gaya"), periods ("pichle hafte"), stop words ("... ruko"), hearsay and tag questions, promises and
conditionals, out-of-scope words (suppliers, expenses, cash sales), glued tokens ("kofivehundred"), the roster-first
rule for names that are also words ("Das"), carry-over that ends after `limits.carry_s` or another kind of turn,
the `confirm_entry` family (computed bills, settle, half, write-off, round-off, overpayment, duplicate, hearsay),
the `new_customer` question, `outstanding_total` / `due_since` queries and the `reminder` action. Every rule that
needs a new ctx field (`last_turn`, `customers[i].balance`, `usual`, `limits`, `confusables`) is skipped when the
field is absent. Vocabulary lives in nlu/vocab/*.json (see `nlu.lexicon`).
"""
from __future__ import annotations

import copy
import re
from datetime import date, datetime, timedelta
from typing import Any

from . import names as nm
from .lexicon import load
from .numbers import (CURRENCY_WORDS, classify_word, digit_sequence, digits_value, expand_text, parse_number,
                      value_of_items)
from .translit import fold, is_devanagari, normalise, romanise_word

# ---------------------------------------------------------------------------------------------------------------
# Lexicon. Each canonical keyword lists spellings in Roman and Devanagari; all are folded at import.

# Keywords: canonical meaning -> spellings in Roman and Devanagari (nlu/vocab/keywords.json). The order
# matters: when two canonical keywords share a spelling, the first one listed wins.
_KEYWORDS: dict[str, str] = load("keywords")
_PV = load("parser")  # relations, language markers, out-of-scope words: nlu/vocab/parser.json


def _build_keywords() -> dict[str, str]:
    table: dict[str, str] = {}
    for canon, text in _KEYWORDS.items():
        for w in normalise(text).split():
            roman = romanise_word(w) if is_devanagari(w) else w
            table.setdefault(fold(roman), canon)
    return table


_KW = _build_keywords()

_MARKERS = {"ne", "ko", "ka", "se", "pe", "poss"}
_VERBS = {"give", "take", "gaya", "mila", "aaya", "kiya", "likh", "chukaya", "hua"}
_LEDGER_CUES = {"udhaar", "give", "take", "mila", "aaya", "payment", "jama", "chukaya", "likh", "add", "daal",
                "chadha", "kaat", "paid", "gave", "took", "owes", "received", "paymode", "wapas", "credit", "debit",
                "saaman", "naam"}
# Keywords that keep their meaning in front of a particle; any other word there is read as the customer name.
_KEEP_BEFORE_PARTICLE = {"ne", "ko", "ka", "se", "pe", "poss", "to", "maine", "mujhe", "from", "aur", "phir", "aaj",
                         "kal", "parso", "narson", "din",
                         "pehle", "khata", "kis", "kiska", "sabse", "zyada", "entry", "pichla", "kitna", "kya", "kaun",
                         "hafte", "mahine", "tarikh", "mein", "neg", "galat", "udhaar", "payment", "jama", "hisaab",
                         "total", "baaki", "pronoun", "naam", "saaman", "paisa", "credit", "debit", "tha", "hai",
                         "weekday", "kuch", "on", "undo", "nonname", "ho", "measure", "advance", "bill",
                         "reminder", "send", "kab", "kul", "sab", "discount", "stop", "ya", "minus", "period",
                         "outstanding", "naya", "wahi", "poora", "aadha", "barabar", "chhod", "maaf", "round", "off",
                         "agar", "rehne", "month_name", "nevername", "lene"}
_RELATIONS = {k: tuple(v) for k, v in _PV["relations"].items()}
_RELATION_LOOKUP = {}
for _canon, (_particle, _words) in _RELATIONS.items():
    for _w in normalise(_words).split():
        _RELATION_LOOKUP.setdefault(fold(romanise_word(_w) if is_devanagari(_w) else _w), (_canon, _particle))

# Words that mark a sentence as English or as Hindi for `lang`. Names, digits and a few shared words are neutral.
_ENGLISH_WORDS = frozenset(_PV["english_words"])
# Words used the same way in both languages carry no `lang` (1.14).
_NEUTRAL_WORDS = frozenset(_PV["neutral_words"])

# Verb stems after which "do" is the auxiliary "give/do" ("likh do"); "likh do sau" is then 200 or 100.
_AUX_STEMS = frozenset(fold(w) for w in _PV["aux_stems"])
MAX_DAYS_AGO = 60
_PAY_CUES = {"payment", "jama", "chukaya", "paymode", "received", "paid", "gave", "mila", "aaya", "kaat"}
_YES = {"yes", "ha", "ji", "ok"}

DEFAULT_CONFIRM_ABOVE = 50_000
MAX_AMOUNT = 9_999_999
CARRY_S = 60
DUPLICATE_S = 30

# A number followed by one of these is a quantity, never an amount (1.14 A16, A24, H03).
_MEASURE_FOLDS = frozenset(fold(romanise_word(w) if is_devanagari(w) else w) for w in normalise(
    _KEYWORDS["measure"] + " " + " ".join(_PV["measure_extra"])).split())
# Out of scope (1.14 I01 to I03): supplier, expense and cash-sale words.
_OOS_WORDS = frozenset(fold(w) for w in _PV["out_of_scope_words"])
_OOS_PHRASES = [tuple(fold(w) for w in p.split()) for p in _PV["out_of_scope_phrases"]]
# Glued tokens may be cut into [name] + [particle] + [number words] (1.14 F01 to F05).
_PARTICLES = tuple(_PV["particles"])
# A number directly before one of these, with no currency word, is a count of goods (1.15 B7).
_GOODS_FOLDS = frozenset(fold(romanise_word(w) if is_devanagari(w) else w) for w in _PV["goods_words"])
_MODIFIER_FOLDS = frozenset(fold(w) for w in _PV["amount_modifiers"])
_QUESTION_OPENERS = frozenset(_PV["question_openers"])
_GUESS_FOLDS = frozenset(fold(w) for w in _PV["guess_words"])
# Common harmless words of Hindi and English that strict mode accepts anywhere (1.14 strict mode).
_HARMLESS_FOLDS = frozenset(fold(w) for w in _PV["harmless_words"])


class Tok:
    """One token. cls: sep, cur, amt, num, digit, and, kw, unk, hon, tag, date, aux, fill."""

    __slots__ = ("alt", "cls", "cur", "doubt", "items", "kw", "raw", "rom", "tag_id", "val")

    def __init__(self, raw: str, cls: str, rom: str = "", kw: str = "", val: Any = None):
        self.raw = raw
        self.rom = rom or raw
        self.cls = cls
        self.kw = kw
        self.val = val
        self.items: list = []
        self.tag_id = -1
        self.alt: int | None = None
        self.cur = False
        self.doubt = False

    def copy(self) -> Tok:
        t = Tok(self.raw, self.cls, self.rom, self.kw, self.val)
        t.items = self.items
        t.tag_id = self.tag_id
        t.alt = self.alt
        t.cur = self.cur
        t.doubt = self.doubt
        return t

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Tok({self.raw!r},{self.cls},{self.kw or self.val})"


_TOKEN_RE = re.compile(r"₹|\d+(?:,\d+)*(?:\.\d+)?|[a-z]+|[ऀ-ॣ॰-ॿ]+|[,;.?!।॥|]")


def _classify(raw: str) -> Tok:
    """One word to a token (before any context is applied)."""
    rom = romanise_word(raw) if is_devanagari(raw) else raw
    f = fold(rom)
    if raw == "off":
        return Tok(raw, "kw", rom, kw="off")  # "round off", "write off" ("off" folds to the filler "of")
    if raw == "zdate":
        return Tok(raw, "date", rom, val="unclear")
    if raw == "ztime":
        return Tok(raw, "fill", rom)
    if raw == "साथ":
        return Tok(raw, "kw", rom, kw="filler")  # "with"; the number sixty is साठ (1.15 B8)
    if f in CURRENCY_WORDS:
        return Tok(raw, "cur", rom)
    item = classify_word(raw)
    if item is not None:
        t = Tok(raw, "num", rom)
        t.items = [item]
        return t
    if nm.is_tag_word(rom):
        return Tok(raw, "wale", rom)
    if nm.is_gali_word(rom):
        return Tok(raw, "gali", rom)
    if f in _KW:
        return Tok(raw, "kw", rom, kw=_KW[f])
    if nm.is_honorific(rom):
        return Tok(raw, "hon", rom)
    return Tok(raw, "unk", rom)


def _name_vocab(ctx: dict | None) -> set[str]:
    """Lower-case words of stored customer names and aliases (computed once per parse call)."""
    ctx = ctx or {}
    if "_vocab_once" in ctx:
        return ctx["_vocab_once"]
    words = _build_name_vocab(ctx)
    if ctx.get("_parse_copy"):
        ctx["_vocab_once"] = words
    return words


def _build_name_vocab(ctx: dict) -> set[str]:
    words: set[str] = set()
    for c in _customers(ctx) or []:
        names = [c["name"]] + [a for a in (c.get("aliases") or []) if isinstance(a, str)]
        for name in names:
            words.update(name.lower().split())
    aliases = ctx.get("aliases")
    if isinstance(aliases, dict):
        for a, v in aliases.items():
            if isinstance(a, str):
                words.update(a.lower().split())
            if isinstance(v, str):
                words.update(v.lower().split())
    return words


def _segment_numbers(s: str) -> list[str] | None:
    """Cut a glued string into number words ("fivehundred" -> five hundred), or None."""
    if not s:
        return []
    memo: dict[int, list[str] | None] = {}

    def go(i: int) -> list[str] | None:
        if i == len(s):
            return []
        if i in memo:
            return memo[i]
        memo[i] = None
        for j in range(len(s), i + 1, -1):  # longest piece first, at least two letters
            piece = s[i:j]
            if classify_word(piece) is not None:
                rest = go(j)
                if rest is not None:
                    memo[i] = [piece] + rest
                    break
        return memo[i]

    return go(0)


def _cut_glued(word: str, names: set[str], has_customer: bool = True) -> list[str] | str | None:
    """[name] + [particle] + [number words], cut completely, any part optional; "ambiguous" for two readings.
    A cut into particle and number with no name is made only when the sentence has a stored or carried customer
    (1.15: "Kochar" stays a name)."""
    readings: dict[tuple, list[str]] = {}
    name_ends = [0] + [k for k in range(2, len(word)) if word[:k] in names]
    for k in name_ends:
        rest = word[k:]
        for p in ("",) + _PARTICLES:
            if not rest.startswith(p):
                continue
            tail = rest[len(p):]
            seg = _segment_numbers(tail)
            if seg is None:
                continue
            parts = ([word[:k]] if k else []) + ([p] if p else []) + seg
            if len(parts) < 2:
                continue
            if p and not k and not has_customer:
                continue
            value = parse_number(" ".join(seg)) if seg else None
            if seg and value is None:
                continue
            readings.setdefault((word[:k], p, value), parts)
    if not readings:
        return None
    if len(readings) > 1:
        return "ambiguous"
    return next(iter(readings.values()))


# Keywords that may still be a customer name when they open a clause before the amount ("Diya 200 le gayi",
# "Sham 300 le gaya", "Sara 500 le gayi"). Every other word of the vocabulary is never a new customer (1.16).
_START_NAME_KW = {"give", "take", "mila", "aaya", "time", "poora"}
_ROSTER_OVERRIDE_KW = {"filler", "nonname", "measure", "time", "yes", "ha", "ok", "ji", "first", "second", "kuch",
                       "ho", "weekday", "naya", "wahi", "sab", "kul", "round", "off", "bill"}


def _tokenise(utterance: str, ctx: dict | None = None) -> list[Tok]:
    s = normalise(utterance)
    s = re.sub(r"\brs\.", "rs ", s).replace("/-", " ")
    s = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " zdate ", s)  # 21/11, 21-11-2026: a date (1.16)
    s = re.sub(r"\b\d{1,2}:\d{2}\b", " ztime ", s)  # 10:30: a time, ignored
    s = re.sub(r"\bgoogle\s*pay\b", " gpay ", s)
    s = re.sub(r"\bphone\s*pe\b", " phonepe ", s)
    s = re.sub(r"(?:(?<=\s)|^)-(?=\d)", " zminus ", s).replace("-", " ")
    s = re.sub(r"[\u2019']s\b", " zposs ", s).replace("'", "").replace("\u2019", "")
    s = re.sub(r"\bday before yesterday\b", " zparso ", s)
    s = expand_text(s)
    vocab = _name_vocab(ctx)
    carried = set()
    le = (ctx or {}).get("last_event")
    if isinstance(le, dict) and isinstance(le.get("customer"), str):
        carried = set(le["customer"].lower().split())
    toks: list[Tok] = []
    words = set(_TOKEN_RE.findall(s))
    has_customer = bool(words & (vocab | carried))
    for raw in _TOKEN_RE.findall(s):
        if raw == "₹":
            toks.append(Tok(raw, "cur"))
        elif raw[0].isdigit():
            toks.append(Tok(raw, "digit", val=digits_value(raw)))
        elif len(raw) == 1 and not raw.isalnum():
            toks.append(Tok(raw, "sep"))
        elif raw == "and":
            toks.append(Tok(raw, "and"))
        else:
            t = _classify(raw)
            if t.cls == "unk" and len(raw) >= 4 and raw not in vocab and not is_devanagari(raw):
                cut = _cut_glued(raw, vocab | carried, has_customer)
                if cut == "ambiguous":
                    toks.append(Tok(raw, "digit", val=None))  # two readings: an unreadable amount
                    continue
                if cut:
                    toks.extend(_classify(part) for part in cut)
                    continue
            toks.append(t)
    # A stored customer name wins where a name can stand, even when it is also a number word or filler ("Das").
    if vocab:
        for i, t in enumerate(toks):
            if t.raw in vocab and (t.cls in ("num", "hon") or (t.cls == "kw" and t.kw in _ROSTER_OVERRIDE_KW)):
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if t.cls == "num" and nxt is not None and (nxt.cls == "cur" or (nxt.cls == "num"
                                                                                and nxt.items[0][0] == "u")):
                    continue  # "das rupaye", "das hazaar" stay numbers
                prv = toks[i - 1] if i > 0 else None
                at_start = prv is None or prv.cls == "sep" or prv.kw in ("aur", "phir")
                before_particle = nxt is not None and nxt.kw in _MARKERS
                if t.cls == "num" and not (at_start or before_particle):
                    continue  # "teen sau das": a number word inside a number phrase stays a number (1.16)
                t.cls, t.kw, t.items = "unk", "", []
    return toks


def _mark(toks: list[Tok], keep_fillers: bool = False) -> list[Tok]:
    """Mark tag phrases, N-din-pehle dates and number phrases; drop fillers. Returns a new token list."""
    out = [t.copy() for t in toks]
    # A word or name said twice back to back is said once ("Ramesh Ramesh ka").
    out = [t for i, t in enumerate(out)
           if not (i > 0 and t.cls in ("unk", "hon") and out[i - 1].cls == t.cls and out[i - 1].raw == t.raw)]
    # A full stop right before a particle is not a boundary ("Ramesh ki bevi. Ka khata?").
    out = [t for i, t in enumerate(out)
           if not (t.cls == "sep" and t.raw in ".," and i + 1 < len(out) and out[i + 1].kw in _MARKERS)]
    # "wo na" is a filler pair.
    for i in range(len(out) - 1):
        if out[i].kw == "pronoun" and out[i].rom in ("wo", "woh") and out[i + 1].rom == "na":
            out[i].cls = "fill"
    # Punctuation inside a number phrase does not split it ("teen sau, chalis", "three. Forty") (1.16).
    out = [t for i, t in enumerate(out)
           if not (t.cls == "sep" and t.raw in ".," and 0 < i < len(out) - 1 and out[i - 1].cls == "num"
                   and out[i + 1].cls == "num" and not out[i - 1].raw.isdigit() and not out[i + 1].raw.isdigit()
                   and (out[i - 1].items[0][0] == "u" or (out[i - 1].items[0][2] == "en"
                                                         and out[i + 1].items[0][2] == "en")))]
    # "aa gaya / aa gaye" (came) is the verb aaya, not the filler "aa".
    for i in range(len(out) - 1):
        if out[i].rom in ("aa", "aaa") and out[i + 1].kw == "gaya":
            out[i].cls, out[i].kw = "kw", "aaya"
    # Dates, times and years are never amounts: "21 November", "2026 mein", "10 baje" (1.16).
    i = 0
    while i < len(out):
        t = out[i]
        nxt = out[i + 1] if i + 1 < len(out) else None
        if t.cls in ("num", "digit") and nxt is not None and (nxt.kw == "month_name" or nxt.rom == "may"):
            out[i:i + 2] = [Tok("date", "date", val="unclear")]
        elif t.kw == "month_name":
            out[i] = Tok("date", "date", val="unclear")
        elif (t.cls == "digit" and len(t.raw) == 4 and t.val is not None and 1900 <= t.val <= 2099
              and nxt is not None and nxt.rom in ("mein", "me", "men", "main", "in", "ko")):
            out[i:i + 2] = [Tok("date", "date", val="unclear")]
        elif t.cls in ("num", "digit") and nxt is not None and fold(nxt.rom) == fold("baje"):
            out[i:i + 2] = [Tok(t.raw + " baje", "fill")]  # a time of day is ignored
        i += 1
    # "do hazaar mein se paanch sau": the first number is the total, not an amount (1.16).
    for i in range(len(out) - 2):
        if out[i].cls in ("num", "digit") and out[i + 1].rom in ("mein", "me", "men") and out[i + 2].kw == "se":
            j = i
            while j >= 0 and out[j].cls in ("num", "digit"):
                out[j].cls = "stated"
                j -= 1
    # A balance stated beside an entry ("300 baaki hai", "baaki 300") is never an entry (1.16).
    n_numbers = sum(1 for t in out if t.cls in ("num", "digit"))
    if n_numbers >= 2:
        for i, t in enumerate(out):
            if t.kw == "baaki":
                k = i - 1
                while k >= 0 and out[k].cls in ("num", "digit"):
                    out[k].cls = "stated"
                    k -= 1
                if k == i - 1:
                    k = i + 1
                    while k < len(out) and out[k].cls in ("num", "digit"):
                        out[k].cls = "stated"
                        k += 1
                    if k == i + 1:
                        continue
                t.cls = "fill"
    # A stated balance ("total 800 ho gaya", "kul 800", "ab 800 baaki") is never an amount (H10).
    for i, t in enumerate(out):
        if t.kw in ("total", "kul") or (t.rom == "ab" and t.kw == "filler"):
            j = i + 1
            while j < len(out) and out[j].cls in ("num", "digit"):
                j += 1
            stated = j > i + 1 and (t.rom != "ab" or (j < len(out) and out[j].kw == "baaki"))
            if stated:
                for k in range(i + 1, j):
                    out[k].cls = "stated"
                t.cls = "fill"  # the whole statement is set aside, not only the number
                if j < len(out) and out[j].kw == "baaki":
                    out[j].cls = "fill"
    # Periods: "is hafte", "pichle mahine", "this week", "last month"; "pichle saal" is not resolved.
    i = 0
    while i + 1 < len(out):
        a, b = out[i], out[i + 1]
        this = a.rom in ("is", "this")
        last = a.kw == "pichla"
        unit = "week" if b.kw == "hafte" else "month" if b.kw == "mahine" else \
            "year" if fold(b.rom) in (fold("saal"), "sal", "year") else None
        if (this or last) and unit:
            val = "unclear" if unit == "year" else ("this_" if this else "last_") + unit
            out[i:i + 2] = [Tok(a.raw + " " + b.raw, "kw", kw="period", val=val)]
        i += 1
    out = _merge_relations(out)
    # The word directly before a particle is the customer name, whatever else it could mean
    # ("Chacha ne", "Abhi ko", "Diya ko", "Sham ne").
    for i in range(1, len(out)):
        if out[i].cls == "kw" and out[i].kw in _MARKERS:
            prev = out[i - 1]
            if prev.kw == "time" and out[i].kw == "ko":
                continue  # "raat ko", "shaam ko": a time of day, never a name (1.15)
            if prev.cls == "kw" and prev.kw not in _KEEP_BEFORE_PARTICLE:
                prev.cls = "unk"
            elif (prev.cls == "num" and prev.items and prev.items[0][0] == "n" and not prev.raw.isdigit()
                  and (i == 1 or out[i - 2].cls == "sep")):
                prev.cls, prev.items = "unk", []  # "Sattar ko 500", "Das ne 200": a name at the clause start
    # "Ramesh ka 500 ka note": a note of money, not the action word.
    for i in range(1, len(out)):
        if out[i].rom == "note" and out[i - 1].kw == "ka":
            out[i].cls, out[i].kw = "unk", ""
    # Leading "theek hai" / "haan" before more words are fillers.
    if not keep_fillers:
        sig = [t for t in out if t.cls != "sep"]
        if (len(sig) > 2 and sig[0].cls == "kw" and sig[0].kw == "yes" and sig[0].rom in ("theek", "thik")
                and sig[1].kw == "hai"):
            out.remove(sig[0])
            out.remove(sig[1])
        sig = [t for t in out if t.cls != "sep"]
        while (len(sig) > 1 and sig[0].cls == "kw" and sig[0].kw in ("yes", "ha", "ok", "ji")
               and sig[0].rom not in ("pakka", "sahi")):
            out.remove(sig[0])
            sig = sig[1:]
        out = [t for t in out if not (t.cls == "kw" and t.kw == "filler")]
        for t in out:
            if t.cls == "kw" and t.kw == "ji":
                t.cls = "hon"  # "Sharma ji": part of the name run, dropped from the key
    # A single word at the start of a clause, directly before the amount, is the customer name, even when it is a
    # kinship word, an honorific or also a common word ("Chacha 200 le gaye", "Diya 200 le gayi") (1.15).
    for i, t in enumerate(out):
        start = i == 0 or out[i - 1].cls == "sep" or out[i - 1].kw in ("aur", "phir")
        nxt = out[i + 1] if i + 1 < len(out) else None
        if (start and nxt is not None and nxt.cls in ("num", "digit")
                and (t.cls == "hon" or (t.cls == "kw" and t.kw in _START_NAME_KW))
                and not (i + 2 < len(out) and fold(out[i + 2].rom) in _MEASURE_FOLDS)):
            t.cls, t.kw = "unk", "startname"

    # Tag phrases.
    tag_id = 0
    i = 0
    while i < len(out):
        t = out[i]
        if t.cls == "gali":
            t.cls, t.tag_id = "tag", tag_id
            j = i + 1
            while j < len(out) and out[j].rom in nm.TAG_FILLERS:
                out[j].cls, out[j].tag_id = "tag", tag_id
                j += 1
            if j < len(out) and out[j].cls in ("num", "digit", "unk"):
                out[j].cls, out[j].tag_id = "tag", tag_id
                j += 1
            tag_id += 1
            i = j
            continue
        if t.cls == "wale":
            prev = out[i - 1] if i > 0 else None
            if prev is not None and (prev.cls in ("unk", "hon") or (prev.cls == "num" and not prev.raw.isdigit())
                                     or (prev.cls == "kw" and prev.kw in ("time", "second", "first", "pehle",
                                                                          "kal", "aaj", "parso", "saaman"))):
                prev.cls, prev.tag_id = "tag", tag_id
                t.cls, t.tag_id = "tag", tag_id
                tag_id += 1
            else:
                t.cls = "fill"
        i += 1

    # "N din pehle" dates.
    i = 0
    while i < len(out):
        t = out[i]
        if (t.kw in ("hafte", "mahine") or fold(t.rom) in _LONG_AGO) and i + 1 < len(out) \
                and out[i + 1].kw == "pehle":
            j = i - 1 if i > 0 and out[i - 1].cls in ("num", "digit", "aux") else i
            out[j:i + 2] = [Tok("date", "date", val="unclear")]  # weeks, months or years ago (1.15)
            i = j + 1
            continue
        if t.kw == "din" and i + 1 < len(out) and out[i + 1].kw == "pehle":
            # Only the single number directly before "din" counts the days ("teen sau do din pehle" = 300, 2 days).
            j = i
            if i > 0 and out[i - 1].cls in ("num", "digit"):
                j = i - 1
                if (j > 0 and out[j].cls == "num" and out[j].items[0][2] == "en" and out[j - 1].cls == "num"
                        and out[j - 1].items[0][2] == "en" and out[j - 1].items[0][1] in range(20, 100, 10)
                        and 1 <= out[j].items[0][1] <= 9):
                    j -= 1  # "twenty five days ago"
            elif i > 0 and out[i - 1].kw == "kuch":
                j = i - 1
            span = [x for x in out[j:i] if x.cls in ("num", "digit")]
            value = _run_value(span) if span else None
            ok_days = value is not None and 0 <= value <= MAX_DAYS_AGO
            d = Tok("date", "date", val=value if ok_days else "unclear")
            out[j:i + 2] = [d]
            i = j + 1
            continue
        i += 1

    # "15 tarikh": a day of the month is not an amount and is not resolved (unclear date).
    i = 0
    while i < len(out):
        if out[i].kw == "tarikh":
            j = i
            while j > 0 and out[j - 1].cls in ("num", "digit"):
                j -= 1
            out[j:i + 1] = [Tok("date", "date", val="unclear")]
            i = j + 1
            continue
        i += 1

    # "paanch sa": "sa" right after a number is "sau".
    for i in range(1, len(out)):
        if out[i].cls == "unk" and out[i].rom == "sa" and out[i - 1].cls in ("num", "digit"):
            out[i].cls = "num"
            out[i].items = [("u", 100, "hi")]
    # A word right before a unit word that is not a number is a misheard number ("saadh sau"), never a name.
    i = 1
    while i < len(out):
        t = out[i]
        if (t.cls == "num" and t.items[0][0] == "u" and out[i - 1].cls == "unk"
                and not (i > 1 and out[i - 2].cls in ("num", "digit"))):
            bad = out[i - 1]
            bad.cls = "digit"
            bad.val = None  # an unreadable amount: the run containing it has no value
            i += 1
            continue
        i += 1

    # Number phrases.
    res: list[Tok] = []
    i = 0
    n = len(out)
    while i < n:
        t = out[i]
        if t.cls in ("num", "digit"):
            j = i + 1
            while j < n:
                c = out[j]
                if c.cls in ("num", "digit") or (c.cls == "and" and j + 1 < n and out[j + 1].cls in ("num", "digit")
                                                 and out[j - 1].cls == "num" and out[j - 1].items[0][0] == "u"):
                    j += 1
                else:
                    break
            span = _dedupe_span(out[i:j])
            nxt = out[j] if j < n else None
            prev_tok = out[i - 1] if i > 0 else None
            near_cur = (prev_tok is not None and prev_tok.cls == "cur") or (nxt is not None and nxt.cls == "cur")
            if nxt is not None and (fold(nxt.rom) in _MEASURE_FOLDS or (fold(nxt.rom) in _GOODS_FOLDS
                                                                        and not near_cur)):
                # "2 kilo", "teen customer", "12 ande": a quantity or a count of goods, never an amount
                res.append(Tok(" ".join(x.raw for x in span) + " " + nxt.raw, "qty"))
                i = j
                continue
            if (len(span) == 1 and t.cls == "num" and fold(t.raw) == "sath"
                    and not (nxt is not None and nxt.cls == "cur")):
                if prev_tok is not None and prev_tok.kw in _MARKERS and prev_tok.rom not in ("ke", "ki"):
                    amt = Tok(t.raw, "amt", val=60)
                    amt.doubt = True  # a bare "saath" where an amount stands: confirmed (1.15 B8)
                    res.append(amt)
                else:
                    res.append(Tok(t.raw, "fill", t.rom))  # "saath" / "sath" means "with" here
                i = j
                continue
            if (len(span) == 1 and t.cls == "num" and t.items[0][0] == "n"
                    and not (nxt is not None and nxt.cls == "cur")
                    and ((t.items[0][2] == "hi" and t.items[0][1] in (1, 2))
                         or (t.items[0] == ("n", 1, "en") and prev_tok is not None and prev_tok.kw == "pichla"))):
                res.append(Tok(t.raw, "aux", t.rom))  # "do" in "likh do", "ek" as an article
                i = j
                continue
            amt = Tok(" ".join(x.raw for x in span), "amt", val=_run_value(span))
            if (amt.val is None and len(span) == 3 and all(x.cls == "num" for x in span)
                    and all(x.items[0][0] == "n" and 1 <= x.items[0][1] <= 9 for x in span[:2])
                    and span[2].items[0] == ("u", 100, span[2].items[0][2])):
                d1, d2 = span[0].items[0][1], span[1].items[0][1]
                amt.val, amt.alt = d1 * 100 + d2 * 10, d2 * 100  # "teen chaar sau": 340 or 400 (A11)
            if (len(span) > 1 and t.cls == "num" and t.items[0] == ("n", 2, "hi") and span[1].cls == "num"
                    and span[1].items[0][0] == "u" and prev_tok is not None and fold(prev_tok.rom) in _AUX_STEMS):
                amt.alt = _run_value(span[1:])  # "likh do sau": "do" may be the auxiliary
            amt.cur = (prev_tok is not None and prev_tok.cls == "cur") or (nxt is not None and nxt.cls == "cur")
            if prev_tok is not None and prev_tok.kw == "minus":
                amt.cls = "negamt"
            res.append(amt)
            i = j
            continue
        res.append(t)
        i += 1
    # "de do", "de dena", "de dijiye": an instruction to give (1.16).
    for i in range(len(res) - 1):
        if res[i].kw == "give" and res[i].rom == "de" and res[i + 1].rom in ("do", "dena", "dijiye", "dijie", "dedo"):
            res[i].kw = "deinstr"
    # "340 rupaye 50 paise": not a whole-rupee amount (1.16).
    i = 0
    while i + 3 < len(res):
        a, b, c, d2 = res[i], res[i + 1], res[i + 2], res[i + 3]
        if (a.cls == "amt" and b.cls == "cur" and c.cls == "amt" and d2.cls == "cur"
                and fold(d2.rom) in (fold("paise"), fold("paisa"))):
            a.val, a.alt = None, None
            del res[i + 2:i + 4]
            continue
        i += 1
    # "200 ya 300": two candidates (A12).
    i = 0
    while i + 2 < len(res):
        a, b, c = res[i], res[i + 1], res[i + 2]
        if a.cls == "amt" and b.kw == "ya" and c.cls == "amt" and a.val and c.val and a.val != c.val:
            a.alt = c.val
            del res[i + 1:i + 3]
            continue
        i += 1
    return res


def _dedupe_span(span: list[Tok]) -> list[Tok]:
    """A number phrase said twice is said once ("340 340"); a restart keeps the longer phrase
    ("teen sau teen sau chaalis" = 340). A single repeated unit word ("sau sau") is not a restart."""
    raws = [x.raw.lower() for x in span]
    n = len(raws)
    for p in range(1, n // 2 + 1):
        if raws[:p] == raws[p:2 * p]:
            if 2 * p == n:
                return span[:p]
            if p >= 2:
                return span[p:]
    return span


def _merge_relations(out: list[Tok]) -> list[Tok]:
    """"Ramesh ki biwi", "Ramesh ka beta", "Ramesh's wife" -> one name token "ramesh ki biwi" (another person)."""
    i = 1
    while i + 1 < len(out):
        t = out[i]
        rel = _RELATION_LOOKUP.get(fold(out[i + 1].rom)) if t.cls == "kw" and t.kw in ("ka", "poss") else None
        if rel is not None and out[i - 1].cls in ("unk", "hon", "tag", "wale"):
            j = i - 1
            while j > 0 and out[j - 1].cls in ("unk", "hon", "tag", "wale"):
                j -= 1
            words = [romanise_word(x.raw, long_vowels=False) if is_devanagari(x.raw) else x.raw for x in out[j:i]]
            name_words, _tags = nm.split_tokens(words, True)
            name_words = [w for w in name_words if not nm.is_tag_word(w)]
            if name_words:
                key = f"{' '.join(name_words)} {rel[1]} {rel[0]}"
                out[j:i + 2] = [Tok(key, "unk", key)]
                i = j + 1
                continue
        i += 1
    return out


def _lang(toks: list[Tok]) -> str | None:
    """"en" for an English sentence, "hi" for Hindi / Hinglish / Devanagari, None when it cannot tell."""
    words = [t for t in toks if t.cls not in ("sep", "cur", "digit")]
    if not words or all(t.cls == "num" for t in words):
        return None
    hindi = english = False
    for t in words:
        if is_devanagari(t.raw):
            hindi = True
        elif t.raw in _NEUTRAL_WORDS or t.cls in ("unk", "hon"):
            continue
        elif t.raw in _ENGLISH_WORDS:
            english = True
        elif t.cls in ("kw", "num", "wale", "gali", "and"):
            hindi = True
    if hindi:
        return "hi"
    return "en" if english else None


def _run_value(span: list[Tok]) -> int | None:
    items = []
    for t in span:
        if t.cls == "digit":
            if t.val is None:
                return None
            items.append(("d", t.val, "dig"))
        elif t.cls == "and":
            items.append(("and", None, "en"))
        else:
            items.extend(t.items)
    if len(items) == 1 and items[0][0] == "n" and items[0][1] == 0:
        return 0
    if len(items) == 1 and items[0][0] == "d" and items[0][1] == 0:
        return 0
    seq = digit_sequence(items)
    if seq is not None:
        return seq  # "four three zero" = 430 (A18)
    if any(k == "n" and v == 0 for k, v, _ in items):
        return None
    return value_of_items(items)


# ---------------------------------------------------------------------------------------------------------------
# Small helpers


def _sig(toks: list[Tok]) -> list[Tok]:
    return [t for t in toks if t.cls not in ("sep", "cur", "fill", "aux")]


def _kws(toks: list[Tok]) -> set[str]:
    return {t.kw for t in toks if t.cls == "kw"}


def _display(key: str) -> str:
    return " ".join(w.capitalize() for w in (key or "").split())


def _rupees(n: int) -> str:
    s = str(int(n))
    if len(s) <= 3:
        return "₹" + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])


def _rejected(reason: str) -> dict[str, Any]:
    return {"status": "rejected", "reason": reason}


def _limit(ctx: dict) -> int:
    limits = ctx.get("limits")
    if isinstance(limits, dict):
        v = limits.get("confirm_above")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return DEFAULT_CONFIRM_ABOVE


def _last_event(ctx: dict) -> dict | None:
    le = ctx.get("last_event")
    if isinstance(le, dict) and le.get("customer") and le.get("kind") in ("credit", "payment", "writeoff"):
        return le
    return None


def _entry_turn(ctx: dict) -> bool:
    """True when the previous turn saved an entry (or the server did not say): only then may a correction or a bare
    cancel change the last event (1.15)."""
    lt = ctx.get("last_turn")
    return not isinstance(lt, dict) or lt.get("action") in ("append", "amend")


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _lim(ctx: dict, key: str, default: Any) -> Any:
    limits = ctx.get("limits")
    if isinstance(limits, dict):
        v = limits.get(key)
        if isinstance(default, bool):
            return v if isinstance(v, bool) else default
        if _num(v):
            return v
    return default


def _carry(ctx: dict) -> tuple[str, dict] | None:
    """Where a carried-over customer comes from (1.14 L01 to L06): ("event", last_event) after a recent entry,
    ("query", {"customer", "customer_id"}) after a recent query about one customer, else None."""
    le = _last_event(ctx)
    carry_s = _lim(ctx, "carry_s", CARRY_S)
    lt = ctx.get("last_turn")
    if isinstance(lt, dict):
        age = lt.get("age_s")
        fresh = not _num(age) or age <= carry_s
        action = lt.get("action")
        if action in ("append", "amend") and fresh and le is not None:
            return "event", le
        if action == "query" and fresh and isinstance(lt.get("customer"), str) and lt["customer"]:
            return "query", {"customer": lt["customer"], "customer_id": lt.get("customer_id")}
        return None
    if le is None:
        return None
    age = le.get("age_s")
    if _num(age) and age > carry_s:
        return None
    return "event", le


def _carry_ok(le: dict | None, ctx: dict | None = None) -> bool:
    """True when the last event's customer may carry over (see `_carry`)."""
    if le is None:
        return False
    c = _carry(ctx if ctx is not None else {"last_event": le})
    return c is not None and c[0] == "event"


def _clean_event(e: dict) -> dict:
    out = {}
    for k in ("kind", "customer", "amount", "date", "customer_id", "new_customer", "tags"):
        if k in e and e[k] is not None:
            out[k] = e[k]
    return out


_QUESTIONS = {
    "missing_amount": "Kitne rupaye?",
    "missing_customer": "Kiska khata?",
    "unclear_correction": "Sahi amount boliye, ya hata do boliye.",
    "unclear_date": "Kaunsa din? Aaj, kal ya parso boliye.",
}


def _question(reason: str, events: list[dict], candidates: Any, index: int | None) -> str:
    if reason in _QUESTIONS:
        return _QUESTIONS[reason]
    ev = events[index] if index is not None and 0 <= index < len(events) else (events[0] if events else {})
    if reason == "ambiguous_direction":
        target = next((e for e in events if "kind" not in e), ev)
        name = _display(target.get("customer", ""))
        return f"{name} ne diye, ya {name} ko udhaar?" if name else "Diye, ya udhaar?"
    if reason == "plausibility" and isinstance(ev.get("amount"), int):
        return f"{_rupees(ev['amount'])}, pakka?"
    if (reason == "confusable_number" and isinstance(candidates, list) and len(candidates) >= 2
            and all(isinstance(c, int) for c in candidates[:2])):
        return f"{_rupees(candidates[0])} ya {_rupees(candidates[1])}?"
    if reason == "new_customer":
        name = _display(ev.get("customer", ""))
        if isinstance(candidates, list) and candidates and all(isinstance(c, dict) for c in candidates):
            others = " ya ".join(_display(str(c.get("name") or "")) for c in candidates)
            return f"{name} naya customer hai, ya {others}?"
        return f"{name} naya customer hai?"
    if (reason == "same_name" and isinstance(candidates, list) and candidates
            and all(isinstance(c, dict) for c in candidates)):
        name = _display(str(candidates[0].get("name") or ""))
        labels = [", ".join(str(t) for t in (c.get("tags") or [])) or "pehle wale" for c in candidates]
        if len(labels) > 2:
            joined = ", ".join(labels[:-1]) + " ya " + labels[-1]
        else:
            joined = " ya ".join(labels)
        return f"Kaunse {name}: {joined}?"
    return "Maaf kijiye, samajh nahi aaya. Dobara boliye."


def _clarify(reason: str, action: str, events: list[dict], *, candidates: Any = None, index: int | None = None,
             confirmed: set[str] | None = None, query: dict | None = None, question: str | None = None,
             extra: dict | None = None) -> dict[str, Any]:
    """A needs_clarification result. `extra` adds keys to pending (mode, change, target, attempts)."""
    events = [_clean_event(e) for e in events]
    pending: dict[str, Any] = {"reason": reason, "action": action}
    if action == "query":
        pending["query"] = query or {}
    else:
        pending["events"] = events
    if candidates is not None:
        pending["candidates"] = candidates
    if index is not None:
        pending["index"] = index
    if confirmed:
        pending["confirmed"] = sorted(confirmed)
    for k, v in (extra or {}).items():
        if v is not None:
            pending[k] = v
    result: dict[str, Any] = {
        "status": "needs_clarification",
        "reason": reason,
        "question": question or _question(reason, events, candidates, index),
        "pending": pending,
    }
    if candidates is not None:
        result["candidates"] = candidates
    if isinstance(pending.get("confirm"), dict):
        result["confirm"] = pending["confirm"]
    return result


def _confirm_question(confirm: dict, events: list[dict], index: int | None = None) -> str:
    """The question for a confirmation. `index` is the event it is about when the utterance has several (1.17)."""
    many = isinstance(index, int) and 0 <= index < len(events) and len(events) >= 2
    ev = events[index] if many else (events[0] if events else {})
    name = _display(ev.get("customer", ""))
    amt = _rupees(ev.get("amount", 0))
    t = confirm.get("type")
    bal = confirm.get("balance")
    if t == "computed":
        return f"{_rupees(confirm.get('bill', 0))} mein {_rupees(confirm.get('paid', 0))} diye, {amt} udhaar likhun?"
    if t == "settle":
        return f"{name} ke poore {amt} jama karun?"
    if t == "half":
        return f"Aadha, yaani {amt} jama karun?"
    if t == "writeoff":
        return f"{name} ke {amt} maaf karun?"
    if t == "roundoff":
        return f"{amt} chhod dun?"
    if t == "overpayment":
        if many and not bal:
            return f"{name} ka kuch baaki nahi. {amt} advance likhun?"
        if many:
            return f"{name} ke sirf {_rupees(bal or 0)} baaki hain. {amt} hi likhun?"
        return f"Sirf {_rupees(bal or 0)} baaki hain, {amt} hi?"
    if t == "duplicate":
        return f"Yeh entry abhi likhi thi: {name}, {amt}. Phir se likhun?"
    if t == "review":
        parts = []
        for e in events:
            who = _display(e.get("customer", ""))
            amt_e = _rupees(e.get("amount", 0))
            parts.append(f"{who} se {amt_e} jama" if e.get("kind") == "payment" else
                         f"{who} ke {amt_e} maaf" if e.get("kind") == "writeoff" else f"{who} ke {amt_e} udhaar")
        return f"{len(events)} entry likhun: " + ", ".join(parts) + "?"
    if t == "amend":
        return (f"{name} ki {_rupees(confirm.get('old', 0))} {_KIND_WORD.get(ev.get('kind'), '')} entry "
                f"{_rupees(confirm.get('new', 0))} kar doon?")
    if t == "unsure":
        words = " ".join(str(w) for w in confirm.get("words") or [])
        return f"'{words}' samajh nahi aaya. {name}, {amt} {_KIND_WORD.get(ev.get('kind'), '')} likhun?"
    kind = _KIND_WORD.get(ev.get("kind"), "")
    return f"{name} ke {amt} {kind} likhun?".replace("  ", " ")


# ---------------------------------------------------------------------------------------------------------------
# Customers


def _customers(ctx: dict) -> list[dict] | None:
    if "_customers_once" in ctx:
        return ctx["_customers_once"]
    cs = ctx.get("customers")
    out = None if not isinstance(cs, list) else [
        c for c in cs if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("id") is not None]
    if ctx.get("_parse_copy"):
        ctx["_customers_once"] = out  # computed once per parse call, on the parser's own copy of ctx
    return out


def _alias(key: str, ctx: dict) -> str:
    aliases = ctx.get("aliases")
    if isinstance(aliases, dict) and key in aliases and isinstance(aliases[key], str):
        return nm.name_key(aliases[key]) or aliases[key].lower()
    return key


def _cand(c: dict) -> dict:
    return {"id": c.get("id"), "name": c.get("name"), "tags": list(c.get("tags") or [])}


def _resolve(key: str, tags: list[str], ctx: dict) -> tuple[str, Any]:
    """("ok", fields) or ("same_name", candidates). fields replace customer / customer_id / new_customer / tags."""
    key = _alias(key, ctx) if key else key
    customers = _customers(ctx)
    if customers is None:
        if not key:
            return "unknown", None
        fields: dict[str, Any] = {"customer": key}
        if tags:
            fields["tags"] = tags
        return "ok", fields
    cands: list[dict] = []
    if key:
        cands = [c for c in customers if key in [str(a).lower() for a in (c.get("aliases") or [])]]
        if not cands:
            cands = [c for c in customers if c["name"] == key]
        if not cands:
            # Fuzzy match on a small set: names can only match when their first letters agree, or one starts with
            # a vowel (the 1.12 consonant rule ignores vowels).
            cands = [c for c in _same_head(customers, key) if nm.same_person(c["name"], key)]
        if not cands:
            cands = _repeated_or_split(key, customers)
    elif tags:
        cands = [c for c in customers if any(nm.tag_matches(t, ct) for t in tags for ct in (c.get("tags") or []))]
        if not cands:
            return "unknown", None
    if not cands:
        fields = {"customer": key, "new_customer": True}
        if tags:
            fields["tags"] = tags
        return "ok", fields
    if tags:
        tagged = [c for c in cands if any(nm.tag_matches(t, ct) for t in tags for ct in (c.get("tags") or []))]
        if len(tagged) == 1:
            return "ok", {"customer": tagged[0]["name"], "customer_id": tagged[0]["id"]}
        if len(tagged) > 1:
            return "same_name", [_cand(c) for c in tagged]
        untagged = [c for c in cands if not c.get("tags")]
        if len(cands) == 1 and untagged:
            return "ok", {"customer": cands[0]["name"], "customer_id": cands[0]["id"], "tags": tags}
        if untagged:
            return "same_name", [_cand(c) for c in cands]
        fields = {"customer": key or cands[0]["name"], "new_customer": True, "tags": tags}
        return "ok", fields
    if len(cands) == 1:
        return "ok", {"customer": cands[0]["name"], "customer_id": cands[0]["id"]}
    return "same_name", [_cand(c) for c in cands]


def _close_customers(key: str, ctx: dict, limit: int = 2) -> list[dict]:
    """Stored customers whose names are close to an unknown key (1.14 E05): candidates for the question."""
    out = []
    for c in _customers(ctx) or []:
        if nm.close_name(key, c["name"]):
            out.append(_cand(c))
            if len(out) >= limit:
                break
    return out


def _same_head(customers: list[dict], key: str) -> list[dict]:
    """Customers whose name could match `key` by the 1.12 rule: the first letters agree, or one starts with a vowel
    (the consonant rule ignores vowels). Keeps the fuzzy scan small on a large roster."""
    head = nm.phonetic_key(key)[:1]
    if not head:
        return []
    vowel = head in "aeiou"
    return [c for c in customers
            if vowel or c["name"][:1].lower() in (head, "a", "e", "i", "o", "u", "w" if head == "v" else head)]


def _repeated_or_split(key: str, customers: list[dict]) -> list[dict]:
    """Two name-recovery rules for speech-to-text slips, each only when exactly one stored customer fits:
    - a name said twice in two spellings ("Ramish Ramesh"): every spoken word is the same person as one and the
      same stored customer; a real two-word name ("Ramesh Chopra") or two different customers never collapse;
    - a name split or joined ("Diwa Kar" for stored "divakar", or "Divakar" for stored "diwa kar"): the spoken
      words joined are the same person as the stored name joined."""
    words = key.split()
    if len(words) >= 2:
        common: set | None = None
        for w in words:
            ids = {c["id"] for c in _same_head(customers, w) if nm.same_person(c["name"], w)}
            common = ids if common is None else common & ids
            if not common:
                break
        if common and len(common) == 1:
            cid = next(iter(common))
            return [c for c in customers if c["id"] == cid]
    joined = key.replace(" ", "")
    hits = [c for c in _same_head(customers, joined)
            if c["name"].replace(" ", "") != c["name"] or " " in key
            if nm.same_person(c["name"].replace(" ", ""), joined)]
    return hits if len(hits) == 1 else []


def _apply_fields(event: dict, fields: dict) -> None:
    for k in ("customer_id", "new_customer", "tags"):
        event.pop(k, None)
    event.update(fields)


# ---------------------------------------------------------------------------------------------------------------
# Finalisation: guards in order, then the ok result.


# Marker kept in pending.confirmed once a field question was asked or an answer changed a field (1.16 review).
_FIELDS_ASKED = "fields_asked"
_FIELD_REASONS = {"missing_amount", "missing_customer", "ambiguous_direction", "unclear_date", "same_name",
                  "confusable_number"}


def _finalize(events: list[dict], action: str, ctx: dict, *, confirmed: set[str] | None = None,
              confusable: Any = None, target: Any = "last", confirm: dict | None = None,
              carry_form: bool = False, unsure: list[str] | None = None, asked: bool = False) -> dict[str, Any]:
    confirmed = set(confirmed or ())
    events = [dict(e) for e in events]
    extra: dict[str, Any] = {"target": target} if action == "amend" and target != "last" else {}
    if unsure:
        extra["unsure_words"] = list(unsure)  # strict mode: confirmed at the end, whatever is asked first
    if any(_num(e.get("amount")) and e["amount"] > _lim(ctx, "max_amount", MAX_AMOUNT) for e in events):
        return _rejected("too_large")  # above limits.max_amount (A22)
    if "confusable_number" not in confirmed:
        # Two amounts in one clause ("340 ya 740", "teen chaar sau") are asked first, whatever else is missing (A12).
        for i, e in enumerate(events):
            if _num(e.get("amount")) and isinstance(e.get("_alt"), int) and e["_alt"] > 0 and e["_alt"] != e["amount"]:
                return _clarify("confusable_number", action, events, candidates=[e["amount"], e["_alt"]],
                                index=i, confirmed=confirmed, extra=dict(extra, confirm=confirm))
    for reason, field in (("missing_amount", "amount"), ("missing_customer", "customer"),
                          ("ambiguous_direction", "kind"), ("unclear_date", "date")):
        missing = [i for i, e in enumerate(events) if field not in e]
        if missing:
            # pending.index: the event this question is about (1.16)
            return _clarify(reason, action, events, confirmed=confirmed, index=missing[0],
                            extra=dict(extra, confirm=confirm))
    for i, e in enumerate(events):
        if e.get("customer_id") is not None or e.get("new_customer"):
            continue
        status, data = _resolve(e.get("customer", ""), list(e.get("tags") or []), ctx)
        if status == "same_name":
            return _clarify("same_name", action, events, candidates=data, index=i, confirmed=confirmed,
                            extra=dict(extra, confirm=confirm))
        if status == "unknown":
            e.pop("customer", None)
            return _clarify("missing_customer", action, events, confirmed=confirmed,
                            extra=dict(extra, confirm=confirm))
        if status == "ok":
            if (data.get("new_customer") and _lim(ctx, "confirm_new_customer", False)
                    and "new_customer" not in confirmed and _customers(ctx) is not None):
                return _clarify("new_customer", action, events, candidates=_close_customers(data["customer"], ctx),
                                index=i, confirmed=confirmed, extra=dict(extra, confirm=confirm))
            _apply_fields(e, data)
    if "confusable_number" not in confirmed:
        for i, e in enumerate(events):
            if isinstance(e.get("_alt"), int) and e["_alt"] > 0 and e["_alt"] != e["amount"]:
                return _clarify("confusable_number", action, events, candidates=[e["amount"], e["_alt"]],
                                index=i, confirmed=confirmed, extra=dict(extra, confirm=confirm))
        shop = ctx.get("confusables")
        if isinstance(shop, dict):
            for i, e in enumerate(events):
                meant = shop.get(str(e["amount"]))
                if isinstance(meant, list) and meant and _num(meant[0]) and int(meant[0]) != e["amount"]:
                    return _clarify("confusable_number", action, events, candidates=[e["amount"], int(meant[0])],
                                    index=i, confirmed=confirmed, extra=dict(extra, confirm=confirm))
    if confusable is not None and "confusable_number" not in confirmed:
        hit = confusable(events)
        if hit is not None:
            index, cands = hit
            return _clarify("confusable_number", action, events, candidates=cands, index=index,
                            confirmed=confirmed, extra=dict(extra, confirm=confirm))
    many = len(events) >= 2
    c_index = _confirm_index(confirm, events) if confirm and many else None
    if confirm and "confirm_entry" not in confirmed:
        return _clarify("confirm_entry", action, events, confirmed=confirmed, extra=dict(extra, confirm=confirm),
                        index=c_index, question=_confirm_question(confirm, events, c_index))
    if confirm and confirm.get("type") in ("settle", "half", "writeoff", "roundoff", "computed"):
        # the amount itself was just confirmed; with several events only that event's amount (1.17)
        confirmed.add(f"plausibility@{c_index}" if c_index is not None else "plausibility")
    if "plausibility" not in confirmed:
        limit = _limit(ctx)
        below = _lim(ctx, "confirm_below", None)
        for i, e in enumerate(events):
            if f"plausibility@{i}" in confirmed:
                continue  # this event's amount was confirmed already (1.17)
            if e["amount"] > limit or e.get("_doubt"):
                return _clarify("plausibility", action, events, index=i, confirmed=confirmed, extra=extra or None)
            usual = _usual(e, ctx)
            if usual and e["amount"] >= 1000 and e["amount"] >= 10 * usual:
                res = _clarify("plausibility", action, events, index=i, confirmed=confirmed, extra=extra or None)
                res["usual"] = usual  # ten times what this customer usually takes (A21)
                return res
            if below is not None and e["amount"] < below and not e.get("_cur") and e.get("kind") != "writeoff":
                return _clarify("plausibility", action, events, index=i, confirmed=confirmed, extra=extra or None)
    if many and ("confirm_entry" not in confirmed or any(c.startswith("confirm_entry@") for c in confirmed)):
        # Several events: each over-payment is asked about on its own, for its own event (1.17). A yes to a
        # confirmation of the whole utterance (hearsay, unsure, review) still covers them all.
        done_at = {i for i in range(len(events)) if f"confirm_entry@{i}" in confirmed}
        hit = _overpayment_at(events, ctx, _last_event(ctx) if action == "amend" else None, done_at)
        if hit is not None:
            i, over = hit
            return _clarify("confirm_entry", action, events, confirmed=confirmed, index=i,
                            extra=dict(extra, confirm=over), question=_confirm_question(over, events, i))
    if "confirm_entry" not in confirmed:
        over = None if many else _overpayment(events, ctx, _last_event(ctx) if action == "amend" else None)
        if over is not None:
            return _clarify("confirm_entry", action, events, confirmed=confirmed,
                            extra=dict(extra, confirm=over), question=_confirm_question(over, events))
        if action == "append" and not carry_form and _is_duplicate(events, ctx):
            dup = {"type": "duplicate"}
            return _clarify("confirm_entry", action, events, confirmed=confirmed,
                            extra=dict(extra, confirm=dup), question=_confirm_question(dup, events))
        if unsure:
            sure = {"type": "unsure", "words": list(unsure)}
            return _clarify("confirm_entry", action, events, confirmed=confirmed,
                            extra=dict(extra, confirm=sure), question=_confirm_question(sure, events))
    if asked and len(events) >= 2 and "review" not in confirmed and _FIELDS_ASKED in confirmed:
        # Two or more entries after a question about a missing or ambiguous field, or after an answer that changed a
        # field: one review question lists every entry before saving (1.16). New-customer questions alone save on
        # the yes, since every entry was complete in the utterance.
        review = {"type": "review"}
        return _clarify("confirm_entry", action, events, confirmed=confirmed, extra=dict(extra, confirm=review),
                        question=_confirm_question(review, events))
    result: dict[str, Any] = {"status": "ok", "action": action, "events": [_clean_event(e) for e in events]}
    if action == "amend":
        result["target"] = target
    return result


def _stored(e: dict, ctx: dict) -> dict | None:
    if e.get("customer_id") is None:
        return None
    for c in _customers(ctx) or []:
        if c.get("id") == e["customer_id"]:
            return c
    return None


def _usual(e: dict, ctx: dict) -> int | None:
    c = _stored(e, ctx)
    u = c.get("usual") if c else None
    return int(u) if _num(u) and u > 0 else None


def _confirm_index(confirm: dict, events: list[dict]) -> int | None:
    """The event a confirmation of one entry is about, in an utterance with several (1.17)."""
    t = confirm.get("type")
    if t in ("writeoff", "roundoff"):
        return next((i for i, e in enumerate(events) if e.get("kind") == "writeoff" and "amount" in e), None)
    if t in ("settle", "half"):
        return next((i for i, e in enumerate(events) if e.get("kind") == "payment" and "amount" in e), None)
    return None


def _overpayment(events: list[dict], ctx: dict, replaced: dict | None = None) -> dict | None:
    hit = _overpayment_at(events, ctx, replaced)
    return hit[1] if hit is not None else None


def _overpayment_at(events: list[dict], ctx: dict, replaced: dict | None = None,
                    skip: set[int] | None = None) -> tuple[int, dict] | None:
    """The first payment above the customer's balance plus this utterance's credits for them (H08), with its index.
    On an amend the entry being replaced is left out (1.16). Events in `skip` were confirmed already (1.17)."""
    for i, e in enumerate(events):
        if skip and i in skip:
            continue
        if e.get("kind") != "payment" or e.get("new_customer") or e.get("_advance") or "amount" not in e:
            continue
        c = _stored(e, ctx)
        bal = _balance_of(c)
        if bal is None:
            continue
        credits = sum(x["amount"] for x in events if x.get("kind") == "credit"
                      and x.get("customer_id") == e.get("customer_id"))
        if replaced and replaced.get("kind") == "payment" and nm.same_person(str(replaced.get("customer") or ""),
                                                                             e.get("customer", "")):
            bal += int(replaced.get("amount") or 0)
        if e["amount"] > bal + credits:
            return i, {"type": "overpayment", "balance": bal}
    return None


def _is_duplicate(events: list[dict], ctx: dict) -> bool:
    """The same complete entry as one of last_events within limits.duplicate_s (K01)."""
    lt = ctx.get("last_turn")
    if not isinstance(lt, dict) or lt.get("action") not in ("append", "amend") or not _num(lt.get("age_s")):
        return False
    if lt["age_s"] > _lim(ctx, "duplicate_s", DUPLICATE_S):
        return False
    previous = ctx.get("last_events")
    if not isinstance(previous, list):
        le = _last_event(ctx)
        previous = [le] if le else []
    def same(a: dict, b: dict) -> bool:
        return isinstance(b, dict) and all(a.get(k) == b.get(k) for k in ("kind", "amount", "date")) \
            and (a.get("customer") == b.get("customer") or nm.same_person(a.get("customer", ""), b.get("customer", "")))
    return bool(events) and all(any(same(e, p) for p in previous) for e in events)


def _finalize_query(query: dict, ctx: dict) -> dict[str, Any]:
    if query.get("customer") and query.get("customer_id") is None:
        status, data = _resolve(query["customer"], [], ctx)
        if status == "same_name":
            return _clarify("same_name", "query", [], candidates=data, query=query)
        if status == "ok":
            query = dict(query)
            query["customer"] = data.get("customer", query["customer"])
            if data.get("customer_id") is not None:
                query["customer_id"] = data["customer_id"]
            if data.get("new_customer") and query.get("type") in ("balance", "due_since"):
                query["unknown_customer"] = True
    return {"status": "ok", "action": "query", "query": query}


# ---------------------------------------------------------------------------------------------------------------
# Clause analysis


class _Name:
    __slots__ = ("end", "key", "start", "tags", "words")

    def __init__(self, start: int, end: int, key: str, tags: list[str], words: list[str]):
        self.start, self.end, self.key, self.tags, self.words = start, end, key, tags, words


def _name_runs(toks: list[Tok], honorific_name: bool = False) -> list[_Name]:
    """Runs of name words. A run of only kinship words or honorifics is a name when it stands directly before a
    particle (or `honorific_name` is set, as in an answer to "Kiska khata?")."""
    runs: list[_Name] = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i].cls in ("unk", "hon", "tag"):
            j = i
            while j < n and toks[j].cls in ("unk", "hon", "tag"):
                j += 1
            words = []
            for t in toks[i:j]:
                words.append(romanise_word(t.raw, long_vowels=False) if is_devanagari(t.raw) else t.raw)
            before_particle = j < n and toks[j].kw in _MARKERS
            start_name = all(t.kw == "startname" for t in toks[i:j])
            name_words, tags = nm.split_tokens(words, honorific_name or before_particle or start_name)
            if name_words or tags:
                runs.append(_Name(i, j, " ".join(name_words), tags, name_words))
            i = j
        else:
            i += 1
    return runs


def _pick_names(toks: list[Tok], ctx: dict) -> tuple[list[_Name], int]:
    """Significant name runs (before a marker, at the clause start, after 'from') and the count of distinct names."""
    runs = _name_runs(toks)
    sig = []
    for r in runs:
        nxt = toks[r.end] if r.end < len(toks) else None
        prev = toks[r.start - 1] if r.start > 0 else None
        if (nxt is not None and nxt.kw in _MARKERS) or r.start == 0 or \
                (prev is not None and (prev.kw in ("from", "to", "give_en", "pay_en", "gave", "send")
                                       or prev.cls == "brk")):
            sig.append(r)
    if not sig and runs:
        sig = [runs[0]]
    keyed = [r for r in sig if r.key]
    if keyed:
        for r in sig:
            if not r.key and r.tags:
                owner = max((k for k in keyed if k.start < r.start), key=lambda k: k.start, default=keyed[0])
                owner.tags = owner.tags + [t for t in r.tags if t not in owner.tags]
        sig = keyed
    count = 0
    keys = set()
    for r in sig:
        if r.key in keys:
            continue
        keys.add(r.key)
        count += _names_in_run(r, ctx)
    return sig, count


def _names_in_run(r: _Name, ctx: dict) -> int:
    """Name words in a row are one name ("Ramesh Chopra" -> "ramesh chopra")."""
    return 1


def _date_of(toks: list[Tok], today: date) -> tuple[str | None, str | None]:
    """(iso date, issue). issue is 'unclear' when the date words cannot be resolved to one day."""
    offsets = set()
    unclear = False
    for t in toks:
        if t.cls == "date":
            if t.val == "unclear":
                unclear = True
            else:
                offsets.add(int(t.val))
        elif t.kw == "aaj":
            offsets.add(0)
        elif t.kw == "kal":
            offsets.add(1)
        elif t.kw == "parso":
            offsets.add(2)
        elif t.kw in ("narson", "weekday", "hafte", "mahine", "tarikh", "period"):
            unclear = True
    if unclear or len(offsets) > 1:
        return None, "unclear"
    off = offsets.pop() if offsets else 0
    if off > 3660:
        return None, "unclear"
    return (today - timedelta(days=off)).isoformat(), None


def _direction(toks: list[Tok], marker: str | None, has_name: bool) -> str | None:
    """'credit' | 'payment' | 'ambiguous' | None (no direction word at all)."""
    cues = _kws(toks)
    seq = [t.kw for t in toks if t.cls == "kw"]
    if "credit" in cues:
        for i, k in enumerate(seq):
            if k == "credit" and ((i > 0 and seq[i - 1] == "on") or (i + 1 < len(seq) and seq[i + 1] in ("pe", "give",
                                                                                                    "deinstr"))):
                cues.add("udhaar")  # "on credit", "credit pe diya", "credit de do": given on credit
    give, take, gaya = "give" in cues, "take" in cues, "gaya" in cues
    dene = any(t.kw == "dene" and not (i > 0 and fold(toks[i - 1].rom) in _AUX_STEMS) for i, t in enumerate(toks))
    pay = cues & _PAY_CUES
    if "baaki" in cues or dene or "debit" in cues or "pay_en" in cues:
        return "ambiguous"
    if "saaman" in cues and (cues & {"wapas", "chukaya"} or marker == "se"):
        return "ambiguous"  # goods returned, or goods bought from the customer (1.15)
    if "took" in cues and "from" in cues:
        return "payment"  # "took 500 from Ramesh" = "Ramesh se 500 liye" (1.15)
    if "advance" in cues:
        # "advance 500 diya": paid ahead (B15); "X ko N advance diya" (given to X) asks (1.16)
        return "ambiguous" if marker == "ko" else "payment"
    if any(t.cls == "stated" for t in toks) and (give or cues & {"aaya", "mila"}):
        return "payment"  # "X ke 540 mein se 200 diye": a part of the total was paid (1.16)
    if marker == "ne" and "send" in cues:
        return "payment"  # "Sunita ne 250 online bheje"
    if "udhaar" in cues and cues & {"wapas", "chukaya"}:
        return "payment"  # "udhaar chuka diya", "udhaar wapas aaya" (B11)
    if marker == "to":  # English "... to X": the shop hands something to X
        if cues & {"paid"}:
            return "ambiguous"
        if cues & {"give_en", "credit", "lent", "add", "gave", "udhaar"}:
            return "credit"
        return "ambiguous"
    if "lent" in cues:
        return "credit"
    if "give_en" in cues and cues & {"credit", "saaman"}:
        return "credit"
    if "mujhe" in cues and (give or cues & {"mila", "aaya", "gave"}) and marker != "ko":
        return "payment"  # "mujhe Ramesh ne 300 diye", "mujhe 200 mile"
    if "maine" in cues:
        if marker == "se" and (take or "mila" in cues):
            return "payment"  # "maine Ramesh se 200 liye"
        if (give or "gave" in cues) and marker != "ne" and "udhaar" not in cues:
            return "credit"  # "maine 455 diye": the shop gave
    if "wapas" in cues:
        return "payment" if marker == "ne" else "ambiguous"
    if "udhaar" in cues:
        if marker == "ne":
            return "credit" if take else "ambiguous"
        if marker == "se" or pay:
            return "ambiguous"
        return "credit"
    if "credit" in cues:
        return "ambiguous"
    if cues & {"took", "owes"}:
        return "credit"
    if cues & {"paid", "gave", "received"}:
        return "payment"
    if marker == "ne":
        if take or "saaman" in cues:
            return "credit"
        if give or pay:
            return "payment"
        return "ambiguous"
    if marker == "ko":
        if pay:
            return "ambiguous"
        if _give_instruction(toks):
            return "ambiguous"  # "Ramesh ko 200 de do": an instruction to give, not a record (1.16)
        if give:
            return "credit"
        if cues & _ACTION_WORDS and not cues & {"take", "mila", "aaya"}:
            return "credit"  # "Ramesh ko 200 likh do" (L04)
        return "ambiguous"
    if marker == "se":
        if pay or take or give:
            return "payment"
        return "ambiguous"
    if marker == "ka":
        if "naam" in cues:
            return "credit"
        if "jama" in cues or "kaat" in cues:
            return "payment"
        if "khata" in cues and cues & {"likh", "add", "daal", "chadha"}:
            return "credit"
        if cues & {"aaya", "mila", "payment"}:
            return "payment"
        if "saaman" in cues and take:
            return "credit"
        if cues & _ACTION_WORDS and not cues & {"give", "take", "mila", "aaya"}:
            return "credit"  # "Ramesh ka 100 likh do" (L04)
        return "ambiguous"
    if marker == "pe":
        return "ambiguous"
    if _give_instruction(toks) and "udhaar" not in cues:
        return "ambiguous"  # "aur 200 de do", "de dena" (1.16)
    if give and gaya and not take:
        return "payment"
    if take:
        return "credit"
    if "jama" in cues or pay:
        return "payment"
    if cues & {"likh", "add", "daal", "chadha"}:
        return "credit"
    if give:
        return None if has_name else "payment"
    if has_name:
        return "ambiguous"
    return None


def _give_instruction(toks: list[Tok]) -> bool:
    """"de do", "de dena", "de dijiye": an instruction to give, which says nothing about who owes whom (marked as
    `deinstr` while marking)."""
    return any(t.kw == "deinstr" for t in toks)


class _Clause:
    __slots__ = (
        "amount",
        "amount_alt",
        "amount_bad",
        "cues",
        "date",
        "date_issue",
        "extra_names",
        "kind",
        "marker",
        "name_count",
        "names",
        "action_only",
        "giver_receiver",
        "no_carry",
        "no_dir",
        "orphan",
        "pronoun",
        "toks",
    )


def _pronoun_marker(sig: list[Tok], i: int) -> str | None:
    nxt = sig[i + 1] if i + 1 < len(sig) else None
    if nxt is not None and nxt.kw in _MARKERS:
        return nxt.kw
    r = fold(sig[i].rom)
    if r.endswith(("ka", "ki", "ke")):
        return "ka"
    if r.endswith("ko") or r in ("unhe", "inhe"):
        return "ko"
    if r.endswith("ne"):
        return "ne"
    return None


_NAME_LIKE = ("unk", "hon", "tag", "amt", "date")
_BEFORE_PARTICLE_OK = {"aaj", "kal", "parso", "khata", "pronoun", "naam", "jama", "udhaar", "payment", "saaman",
                       "mujhe", "maine"}


def _analyse_clause(toks: list[Tok], ctx: dict, today: date) -> _Clause:
    c = _Clause()
    c.toks = toks
    amts = [t for t in toks if t.cls == "amt"]
    c.amount = amts[0].val if amts else None
    c.amount_bad = bool(amts) and amts[0].val is None
    c.amount_alt = amts[0].alt if amts else None
    sig = _sig(toks)
    c.names, c.name_count = _pick_names(sig, ctx)
    c.marker = None
    c.pronoun = False
    if c.names:
        r = c.names[0]
        nxt = sig[r.end] if r.end < len(sig) else None
        prev = sig[r.start - 1] if r.start > 0 else None
        if nxt is not None and nxt.kw in _MARKERS:
            c.marker = "ka" if nxt.kw == "poss" else nxt.kw
        elif prev is not None and prev.kw in ("to", "give_en", "pay_en", "gave"):
            c.marker = "to"  # "give Ramesh 500" = "give 500 to Ramesh"; "gave Sunita 500 on credit"
    else:
        for i, t in enumerate(sig):
            if t.kw == "pronoun":
                c.pronoun = True
                c.marker = _pronoun_marker(sig, i)
                break
    # A particle with no name before it ("ne 200 diye") never borrows an earlier customer.
    c.orphan = False
    for i, t in enumerate(sig):
        if t.cls == "kw" and t.kw in _MARKERS:
            prev = sig[i - 1] if i > 0 else None
            if prev is None or (prev.cls not in _NAME_LIKE and prev.kw not in _BEFORE_PARTICLE_OK):
                c.orphan = True
            break
    # A name after the verb with no amount of its own ("Ramesh ne 500 diye Sunita bhi").
    c.extra_names = []
    runs = _name_runs(sig)
    picked = {(r.start, r.end) for r in c.names}
    amt_idx = max((i for i, t in enumerate(sig) if t.cls == "amt"), default=-1)
    cue_idx = max((i for i, t in enumerate(sig) if t.kw in _LEDGER_CUES or t.kw == "tha"), default=-1)
    strict_vocab = _name_vocab(ctx) if _lim(ctx, "strict", False) else None
    for r in runs:
        if (r.start, r.end) not in picked and r.key and r.start > max(amt_idx, cue_idx) and amt_idx >= 0:
            if strict_vocab is not None and not all(w in strict_vocab for w in r.words):
                continue  # strict mode: an unlisted trailing word is left to the "unsure" question, not a 2nd name
            c.extra_names.append(r)
    c.date, c.date_issue = _date_of(toks, today)
    c.cues = _kws(toks)
    c.kind = _direction(sig, c.marker, bool(c.names) or c.pronoun)
    if c.kind == "credit" and any(t.cls == "conflict" for t in toks):
        c.kind = "ambiguous"  # "500 udhaar diya, usne de diye": a credit and a payment cue with no amount (1.16)
    # One customer giving (ne) and another receiving (ko) in one clause (B14); one name with both (B12).
    markers = {}
    for r in c.names:
        nxt = sig[r.end] if r.end < len(sig) else None
        if nxt is not None and nxt.kw in ("ne", "ko"):
            markers.setdefault(nxt.kw, set()).add(r.key)
    c.giver_receiver = bool(markers.get("ne")) and bool(markers.get("ko")) and markers["ne"] != markers["ko"]
    ka_names = {r.key for r in c.names if r.end < len(sig) and sig[r.end].kw == "ka"}
    if markers.get("ne") and ka_names and ka_names - markers["ne"] and any(r.key for r in c.names):
        c.giver_receiver = True  # "Sunita ne Ramesh ke 200 diye": one customer paying for another
    # "ne" and "ko" both said for one name ("Sunita ko ne 500 diya"); a "ko" after a day word ("somvar ko") is
    # part of the date, not a particle for the name.
    day_words = {"weekday", "aaj", "kal", "parso", "time", "period", "tarikh"}
    particles = {t.kw for i, t in enumerate(sig) if t.kw in ("ne", "ko")
                 and not (i > 0 and (sig[i - 1].kw in day_words or sig[i - 1].cls == "date"))}
    if not c.giver_receiver and len({r.key for r in c.names}) == 1 and particles == {"ne", "ko"}:
        c.kind = "ambiguous"
    direction_words = c.cues & (_LEDGER_CUES | {"advance", "maine", "mujhe", "udhaar"})
    c.action_only = bool(c.cues & _ACTION_WORDS) and not (direction_words - _ACTION_WORDS)
    c.no_dir = not direction_words
    # "wapas kiya" with no "ne" and no name: ask whose account first, never carry over (B16).
    c.no_carry = "wapas" in c.cues and c.marker != "ne" and "udhaar" not in c.cues
    return c


_ACTION_WORDS = {"likh", "add", "daal", "chadha"}
_KIND_WORDS = {"udhaar", "credit", "payment", "jama"}


def _split_segments(toks: list[Tok]) -> list[list[Tok]]:
    segs: list[list[Tok]] = [[]]
    for t in toks:
        if t.cls == "sep" or t.cls == "and" or (t.cls == "kw" and t.kw in ("aur", "phir")):
            if segs[-1]:
                segs.append([])
            continue
        segs[-1].append(t)
    return [s for s in segs if s]


def _has_cue(toks: list[Tok]) -> bool:
    return bool(_kws(toks) & _LEDGER_CUES)


def _split_on_amounts(seg: list[Tok]) -> list[list[Tok]]:
    """Split a segment holding several amounts: the second amount starts a clause at its date word or name."""
    idx = [i for i, t in enumerate(seg) if t.cls == "amt"]
    if len(idx) < 2:
        return [seg]
    cuts = []
    for a, b in zip(idx, idx[1:]):
        cut = b
        for k in range(a + 1, b):
            t = seg[k]
            if t.cls == "date" or t.kw in ("aaj", "kal", "parso", "narson", "weekday") or t.cls in ("unk", "tag"):
                cut = k
                break
        cuts.append(cut)
    parts = []
    start = 0
    for cut in cuts:
        parts.append(seg[start:cut])
        start = cut
    parts.append(seg[start:])
    return [p for p in parts if p]


def _clauses(toks: list[Tok]) -> list[list[Tok]]:
    segs = _split_segments(toks)
    merged: list[list[Tok]] = []
    for seg in segs:
        has_amt = any(t.cls == "amt" for t in seg)
        if has_amt:
            merged.append(seg)
            continue
        if _name_runs(_sig(seg)) and _has_cue(seg):
            merged.append(seg)  # a name with a ledger word but no amount: its own clause (missing amount)
            continue
        if merged:
            seg_kws = _kws(seg)
            paycue = bool(seg_kws & (_PAY_CUES | {"paymode"})) or ("give" in seg_kws and (
                "ne" in seg_kws or any(t.kw == "pronoun" and fold(t.rom).endswith("ne") for t in seg)))
            conflict = [Tok("paycue", "conflict")] if paycue and not seg_kws & {"udhaar", "credit", "took"} else []
            merged[-1] = merged[-1] + [Tok("|", "brk")] + seg + conflict
        else:
            merged.append(seg)
    # A leading segment without an amount was kept alone; fold it into the next one.
    out: list[list[Tok]] = []
    carry: list[Tok] = []
    for seg in merged:
        has_amt = any(t.cls == "amt" for t in seg)
        if not has_amt and not (_name_runs(_sig(seg)) and _has_cue(seg)):
            carry += seg
            continue
        out.append(carry + ([Tok("|", "brk")] if carry else []) + seg)
        carry = []
    if carry:
        if out:
            out[-1] = out[-1] + [Tok("|", "brk")] + carry
        else:
            out.append(carry)
    result = []
    for seg in out:
        result.extend(_split_on_amounts(seg))
    return result


# ---------------------------------------------------------------------------------------------------------------
# Fresh parse


_HEARSAY_VERBS = frozenset(fold(w) for w in _PV["hearsay_verbs"])
_KEHTA = frozenset(fold(w) for w in ("kehta", "kehti", "kahta"))
_HEARSAY_PROG = frozenset(fold(w) for w in _PV["hearsay_progressive"])
_PAST = frozenset(fold(w) for w in _PV["past_markers"])


class _Flags:
    __slots__ = ("conditional", "hearsay", "modifiers", "negated", "oos")

    def __init__(self):
        self.hearsay = False
        self.conditional = False
        self.oos = False
        self.negated = False
        self.modifiers: list[str] = []


_NA_VERBS = {"give", "take", "likh", "kiya", "mila", "aaya", "chukaya", "jama", "dene", "payment"}
_EN_VERBS = frozenset("paid pay pays gave give took take owe owes borrowed received collected lent".split())
_NOT_START_NAMES = (_MARKERS | _LEDGER_CUES | _KEEP_BEFORE_PARTICLE | {
    "aur", "phir", "ya", "pronoun", "maine", "mujhe", "neg", "mat", "galat", "makeit", "undo", "kya", "kitna",
    "kab", "yes", "ha", "ok", "ji", "advance", "bill", "discount", "minus", "pay_en", "give_en", "lent", "to",
    "from", "on", "reminder", "send", "measure", "stop", "rehne", "agar", "future", "filler", "nonname", "hua",
    "gaya", "dene", "hai", "tha", "ho", "first", "second", "kul", "sab", "outstanding", "round", "off", "period"}) \
    - {"give", "take", "mila", "aaya", "time", "poora", "wahi"}
_BINA, _HONE = fold("bina"), fold("hone")
_STOP_PAIRS = frozenset((fold(a), fold(b)) for a, b in (("ruk", "jao"), ("rehne", "do"), ("rahne", "do"),
                                                       ("jaane", "do"), ("ek", "minute")))
_CANCEL_FOLD = fold("cancel")
_LONG_AGO = frozenset(fold(w) for w in "saal sal year years week weeks month months".split())


def _scan_questions(out: list[Tok], flags: _Flags) -> None:
    """Questions, guesses, negations and amount modifiers read on the raw words (1.15)."""
    sig = [t for t in out if t.cls != "sep"]
    words = [fold(t.rom) for t in sig]
    raws = [t.raw for t in sig]
    if not sig:
        return
    ends_q = out[-1].raw == "?" if out else False
    last = words[-1]
    if ends_q or (last in ("kya", "kyaa", "right", "na", "naa") and len(sig) > 1) or raws[0] in _QUESTION_OPENERS:
        flags.hearsay = True  # a question about an entry is confirmed, never saved directly
    for i, w in enumerate(words):
        nxt = sig[i + 1] if i + 1 < len(sig) else None
        prv = raws[i - 1] if i > 0 else ""
        if w in ("na", "naa") and nxt is not None and nxt.cls == "kw" and nxt.kw in _NA_VERBS:
            flags.negated = True  # "500 na diye", "na likhna"
        if raws[i] in ("never", "didnt", "didn", "doesnt", "hasnt", "havent", "wasnt", "dont", "didnot"):
            flags.negated = True
        if raws[i] == "not" and (prv in ("did", "does", "do", "has", "have", "was", "is", "were")
                                 or (nxt is not None and nxt.raw in _EN_VERBS)):
            flags.negated = True  # "did not pay", "not paid": a negation, never a correction
        if w == _BINA:
            flags.negated = True  # "bina 500 diye" (without paying)
        if w in _GUESS_FOLDS:
            flags.hearsay = True  # "hoga", "shayad", "maybe"
        if w == _HONE and nxt is not None and nm.is_tag_word(nxt.rom):
            flags.conditional = True  # "hone wala tha": it had not happened
        if w in _MODIFIER_FOLDS or (sig[i].kw in ("aadha", "zyada")):
            flags.modifiers.append(raws[i])
        if sig[i].kw == "neg" and nxt is not None and nxt.raw == "to":
            flags.modifiers.append(raws[i] + " to")  # "500 nahi to 600"


def _shop_pays(out: list[Tok]) -> bool:
    """English sentences where the shop pays or owes the customer (1.15): out of scope."""
    sig = [t for t in out if t.cls != "sep"]
    raws = [t.raw for t in sig]
    me = bool({"i", "we"} & set(raws))
    for i, r in enumerate(raws):
        nxt = sig[i + 1] if i + 1 < len(sig) else None
        if r == "paid" and (me or (i == 0 and nxt is not None and nxt.cls == "unk")):
            return True  # "I paid Ramesh 500", "paid Ramesh 500" (a customer before "paid" is the payer)
        if r == "paid" and i > 0 and raws[i - 1] in ("was", "were"):
            return True  # "Ramesh was paid 500"
        if r in ("got", "received", "collected") and i > 0 and sig[i - 1].cls == "unk" and "from" not in raws[i:]:
            return True  # "Ramesh got 500"
        if r == "from" and nxt is not None and nxt.raw in ("me", "us"):
            return True  # "Ramesh received 500 from me"
        if r in ("owe", "owes", "borrowed") and me:
            return True  # "I owe Ramesh 500", "I borrowed 500 from Ramesh"
        if r == "lent" and nxt is not None and nxt.raw in ("me", "us"):
            return True  # "Ramesh lent me 500"
    return False


def _scan(toks: list[Tok], ctx: dict) -> tuple[list[Tok], _Flags]:
    """Sentence-level cues read before marking: hearsay and tag questions (removed, flagged), conditionals and
    out-of-scope words (flagged)."""
    flags = _Flags()
    out = list(toks)
    words = [fold(t.rom) for t in out]
    keep = [True] * len(out)
    for i, w in enumerate(words):
        if w in _HEARSAY_VERBS and i + 1 < len(out) and words[i + 1] in _HEARSAY_PROG:
            flags.hearsay = True
            keep[i] = keep[i + 1] = False
            if i + 2 < len(out) and words[i + 2] in _PAST:
                keep[i + 2] = False
        elif w in _KEHTA and i + 1 < len(out) and words[i + 1] in _PAST:
            flags.hearsay = True
            keep[i] = keep[i + 1] = False
        elif w == "said" or (w == "was" and i + 1 < len(out) and words[i + 1] == "saying"):
            flags.hearsay = True
            keep[i] = False
            if w == "was":
                keep[i + 1] = False
    sig = [i for i, t in enumerate(out) if t.cls != "sep" and keep[i]]
    if len(sig) >= 3 and words[sig[-1]] in ("na", "naa") and words[sig[-2]] in _PAST:
        flags.hearsay = True  # "... diya tha na?" asks back about the past
        keep[sig[-1]] = False
    out = [t for i, t in enumerate(out) if keep[i]]
    _scan_questions(out, flags)
    if _shop_pays(out):
        flags.oos = True
    words = [fold(t.rom) for t in out]
    if any(t.kw == "agar" for t in out) or any(
            out[i].kw == "give" and out[i].rom == "de" and i + 1 < len(out) and out[i + 1].rom == "to"
            for i in range(len(out))):
        flags.conditional = True
    vocab = _name_vocab(ctx)
    for i, w in enumerate(words):
        if out[i].raw in vocab:
            continue
        if w in _OOS_WORDS:
            flags.oos = True
        for phrase in _OOS_PHRASES:
            if tuple(words[i:i + len(phrase)]) == phrase:
                flags.oos = True
    return out, flags


def _trailing_stop(toks: list[Tok]) -> tuple[int, bool] | None:
    """A stop phrase at the end ("ruko", "rehne do", "ek minute", "cancel"): (words in it, is it "cancel")."""
    sig = [t for t in toks if t.cls != "sep"]
    if not sig:
        return None
    w = [fold(t.rom) for t in sig]
    if len(w) >= 2 and (w[-2], w[-1]) in _STOP_PAIRS:
        return 2, False
    if sig[-1].kw == "stop":
        return 1, False
    if w[-1] == _CANCEL_FOLD:
        return 1, True
    return None


class _Draft:
    """Outcome of analysing an utterance without a pending question."""

    __slots__ = ("action", "carry_form", "complete", "confirm", "events", "marked", "query", "result", "spoken")

    def __init__(self):
        self.marked: list[Tok] = []
        self.spoken: set[str] = set()  # words used as the customer name or tag
        self.confirm: dict | None = None
        self.carry_form = False
        self.result: dict | None = None
        self.events: list[dict] | None = None
        self.action = "append"
        self.query: dict | None = None
        self.complete = False


def _negated(marked: list[Tok]) -> bool:
    """"nahi diya", "abhi tak nahi aaya", "diya nahi": a negated verb. "nahi, 430" is a correction instead."""
    sig = [t for t in marked if t.cls not in ("cur", "fill", "aux")]
    for i, t in enumerate(sig):
        if t.kw in ("neg", "mat"):
            nxt = sig[i + 1] if i + 1 < len(sig) else None
            if nxt is not None and nxt.cls == "kw" and (nxt.kw in _VERBS or nxt.kw == "dene"):
                return True
            prev = sig[i - 1] if i > 0 else None
            if (prev is not None and prev.cls == "kw" and prev.kw in ("give", "aaya", "mila")
                    and (nxt is None or nxt.cls == "sep" or nxt.kw in ("hai", "tha"))):
                return True
    return False


def _draft(toks: list[Tok], today: date, ctx: dict) -> _Draft:
    d = _Draft()
    toks, flags = _scan(toks, ctx)
    marked = _mark(toks)
    d.marked = marked
    sig = _sig(marked)
    if not sig:
        d.result = _rejected("not_ledger")
        return d
    kws = _kws(sig)
    amts = [t for t in sig if t.cls == "amt"]
    if flags.oos:
        d.result = _rejected("out_of_scope")  # supplier, expense or cash sale (I01 to I03)
        return d
    if flags.negated:
        d.result = _rejected("negated")
        return d
    if _negated(marked):
        d.result = _rejected("negated")
        return d
    seq = [t.kw for t in sig]
    dena_future = any(k == "dene" and i + 1 < len(seq) and (seq[i + 1] == "hai" or sig[i + 1].rom in
                                                            ("padega", "padegi", "pdega"))
                      for i, k in enumerate(seq))
    if "kitna" in kws and kws & {"dene", "lene"} and not amts:
        runs, _c = _pick_names(sig, ctx)
        if runs and runs[0].key:  # "Lakshmi ko kitna dena hai": the balance (1.16)
            d.result = _query_result({"type": "balance", "customer": _alias(runs[0].key, ctx)}, ctx, d)
            return d
    if "future" in kws or flags.conditional or dena_future:
        d.result = _rejected("future")
        return d
    if any(t.cls == "negamt" for t in sig):
        d.result = _rejected("invalid_number")  # "minus 50" (A15)
        return d
    if sig[0].kw == "kya":
        # "Kya Ramesh ne 500 diye the?" asks, it does not instruct. Only a query is answered.
        q = _detect_query(sig, ctx)
        d.result = _query_result(q, ctx, d) if q else _rejected("not_ledger")
        return d
    words = [t for t in sig if not (t.cls == "kw" and t.kw == "filler")]
    if words and all(t.cls == "kw" and t.kw in ("yes", "ha", "ok", "ji") for t in words):
        d.result = _rejected("no_question")  # "haan" with nothing asked (G06)
        return d
    if words and all(t.cls == "kw" and t.kw in ("neg", "galat") for t in words) and not _last_events(ctx):
        d.result = _rejected("no_question")
        return d
    if "reminder" in kws:
        return _reminder(sig, ctx, d)
    computed_shape = (len(amts) == 2 and bool(kws & {"bill", "discount"})) or (
        len(amts) == 3 and all(isinstance(a.val, int) for a in amts) and amts[0].val - amts[1].val == amts[2].val > 0)
    inst = None if computed_shape else _clause_instructions(marked, today, ctx, d)
    if inst is not None:
        return inst
    if len(amts) == 1 and _reduction(sig):
        return _writeoff_amount(sig, amts[0], today, ctx, d)
    if len(amts) == 1 and _is_amend_instruction(sig, toks):
        return _amend_instruction(sig, amts[0], today, ctx, d)
    if len(amts) == 3 and all(isinstance(a.val, int) for a in amts) \
            and amts[0].val - amts[1].val == amts[2].val > 0:
        return _computed(marked, sig, amts, today, ctx, d)
    if "undo" in kws and (amts or kws & _LEDGER_CUES):
        if "ho" not in kws:
            return _delete_request(sig, ctx, d)
    if "undo" in kws and not amts:
        return _undo(sig, ctx, d)
    if kws & {"neg", "galat", "makeit"}:
        d = _correction(marked, sig, today, ctx, d)
        if d.result is None and flags.modifiers and d.action == "append":
            d.confirm = {"type": "unsure", "words": flags.modifiers}  # "500 nahi to 600"
        return d
    if amts and kws & {"kitna", "kab"} and kws & (_ACTION_VERBS | {"udhaar"}):
        # An entry and a query in one sentence ("Ramesh ne 200 diye ab kitna baaki hai"): the entry is confirmed,
        # never dropped (1.16); the query words are set aside.
        flags.hearsay = True
        marked = [t for t in marked if t.kw not in ("kitna", "kab", "baaki")]
        d.marked = marked
        sig = _sig(marked)
        kws = _kws(sig)
    elif amts and kws & {"kitna", "kab"}:
        # A question word wins over an amount: "Ramesh ka 340 kitna hua?" is a balance question (G09).
        runs, _c = _pick_names(sig, ctx)
        if runs and runs[0].key:
            d.result = _query_result({"type": "balance", "customer": _alias(runs[0].key, ctx)}, ctx, d)
            return d
        q = _detect_query([t for t in sig if t.cls != "amt"], ctx)
        d.result = _query_result(q, ctx, d) if q else _rejected("not_ledger")
        return d
    if not amts:
        qtys = [t for t in sig if t.cls == "qty"]
        settle = _settle_type(sig)
        if settle:
            return _settle(marked, sig, settle, today, ctx, d)
        if qtys:
            clause = _analyse_clause(marked, ctx, today)
            if clause.names and clause.names[0].key and clause.kind == "credit":
                ev = {"kind": "credit", "customer": clause.names[0].key}
                if clause.date:
                    ev["date"] = clause.date
                d.events = [ev]
                d.result = _clarify("missing_amount", "append", [ev], question="Kitne ka?",
                                    extra={"quantity": True})  # a price is never invented (H03)
                d.result["quantity"] = True
                return d
            d.result = _rejected("not_ledger")  # "teen customer aaye the"
            return d
        return _no_amount(marked, sig, today, ctx, d)
    if len(amts) == 2 and kws & {"bill", "discount"}:
        return _computed(marked, sig, amts, today, ctx, d)
    d = _entries(marked, today, ctx, d)
    if d.result is None:
        qtys = [t.raw for t in sig if t.cls == "qty"]
        last = sig[-1] if sig else None
        stative = last is not None and last.kw in ("hai", "tha") and not kws & _ACTION_VERBS
        if flags.hearsay or stative:
            d.confirm = {"type": "hearsay"}  # a question, a guess or a statement of a balance is confirmed
        elif qtys:
            d.confirm = {"type": "unsure", "words": qtys}  # a count beside an amount ("2 baar 100") (1.15 B7)
        elif flags.modifiers:
            d.confirm = {"type": "unsure", "words": flags.modifiers}  # "500 se zyada", "lagbhag 500"
    return d


_ACTION_VERBS = {"give", "take", "mila", "aaya", "kiya", "likh", "add", "daal", "chadha", "chukaya", "paid", "gave",
                 "took", "received", "gaya", "jama", "payment", "wapas", "lent", "paymode", "kaat", "advance",
                 "owes"}


_BALANCE_CUES = {"total", "hisaab", "balance", "baaki", "khata", "udhaar", "kitna"}
_ENTRY_VERBS = {"give", "take", "mila", "aaya", "payment", "jama", "likh", "add", "daal", "chadha"}


def _detect_query(sig: list[Tok], ctx: dict) -> dict | None:
    """The query an amount-free utterance asks, or None. A pronoun asks about the carried-over customer.
    A total for a period the parser cannot resolve has `period: None` (the caller asks which day)."""
    if any(t.cls == "amt" for t in sig):
        return None
    kws = _kws(sig)
    runs, _count = _pick_names(sig, ctx)
    name = runs[0] if runs else None
    seq = [t.kw for t in sig if t.cls == "kw"]
    periods = [t.val for t in sig if t.kw == "period"]
    if periods:
        period = periods[0] if periods[0] != "unclear" else None
    elif kws & {"weekday", "narson", "tarikh"} or any(t.cls == "date" for t in sig):
        period = None
    elif "kal" in kws:
        period = "yesterday"
    else:
        period = "today"
    day_word = bool(periods) or bool(kws & {"aaj", "kal", "weekday", "narson", "tarikh", "parso"}) \
        or any(t.cls == "date" for t in sig)
    if ("sabse" in kws and kws & {"zyada", "baaki", "udhaar"}) or seq.count("kis") >= 2 \
            or ("kiska" in kws and kws & {"baaki", "udhaar"}) or (kws & {"kaun", "kiska"} and "zyada" in kws):
        return {"type": "top_dues"}
    if name is not None and name.key:
        nxt = sig[name.end] if name.end < len(sig) else None
        if "kab" in kws and kws & {"baaki", "udhaar", "se"}:
            return {"type": "due_since", "customer": _alias(name.key, ctx)}  # "kab se baaki hai" (J07)
        if nxt is not None and nxt.kw in ("ka", "pe", "poss") and kws & _BALANCE_CUES and not kws & _ENTRY_VERBS:
            return {"type": "balance", "customer": _alias(name.key, ctx)}
        if "kitna" in kws and kws & {"owes", "baaki"} and not kws & _ENTRY_VERBS:
            return {"type": "balance", "customer": _alias(name.key, ctx)}  # "how much does Ramesh owe"
        return None
    if "pronoun" in kws and kws & _BALANCE_CUES and not kws & _ENTRY_VERBS:
        carry = _carry(ctx)
        if carry is not None:
            src = carry[1]
            q = {"type": "balance", "customer": src["customer"]}
            if src.get("customer_id") is not None:
                q["customer_id"] = src["customer_id"]
            return q
        return {"type": "balance"}
    if not day_word and (("outstanding" in kws) or (kws & {"total", "kul"} and kws & {"udhaar", "baaki"})
                         or ("sab" in kws and kws & {"total", "baaki"}) or ("kul" in kws)
                         or ("baaki" in kws and "kitna" in kws)):
        return {"type": "outstanding_total"}  # "Total udhaar kitna hai", "kul baaki" (J09)
    if kws & {"aaj", "kal", "kitna", "batao", "kya", "period"}:
        qtype = None
        if kws & {"udhaar", "credit"} and not kws & _PAY_CUES:
            qtype = "credit_total"
        elif kws & {"aaya", "jama", "mila", "payment", "received"}:
            qtype = "payment_total"
        elif kws & {"hisaab", "total", "summary", "khata"}:
            qtype = "daily_summary"
        if qtype:
            return {"type": qtype, "period": period}
    return None


def _query_result(q: dict, ctx: dict, d: _Draft) -> dict:
    d.action = "query"
    d.query = q
    d.complete = True
    if q.get("type") == "balance" and not q.get("customer"):
        return _clarify("missing_customer", "query", [], query=q)
    if "period" in q and q["period"] is None:
        q = {k: v for k, v in q.items() if k != "period"}
        return _clarify("unclear_date", "query", [], query=q)  # a query never falls back to today
    return _finalize_query(q, ctx)


def _undo(sig: list[Tok], ctx: dict, d: _Draft) -> _Draft:
    """Undo only the last event: a generic phrase, or one naming that event's customer. Otherwise confirm first."""
    d.action = "undo"
    kws = _kws(sig)
    if "ho" in kws or ("gaya" in kws and "kiya" not in kws):
        d.result = _rejected("not_ledger")  # "order cancel ho gaya" reports, it does not instruct
        return d
    le = _last_event(ctx)
    if le is None:
        d.result = dict(_rejected("no_last_event"), action="undo")  # the server words D09 apart from D03
        return d
    if not _entry_turn(ctx):
        # After a question, a query, a rejection or an undo, "cancel" never reverses an entry silently (1.15).
        d.result = _undo_check(le)
        return d
    rest = [t for t in sig if not (t.cls == "kw" and t.kw in ("undo", "kiya", "hai", "entry", "pichla", "yes", "ok",
                                                              "ji", "filler", "tha", "to"))]
    generic = not rest
    if not generic:
        names_only = [t for t in rest if not (t.cls == "kw" and t.kw in _MARKERS)]
        runs = _name_runs(rest)
        if (names_only and all(t.cls in ("unk", "hon") for t in names_only) and len(runs) == 1
                and not runs[0].tags and nm.same_person(runs[0].key, le["customer"])):
            generic = True
    if generic:
        d.result = {"status": "ok", "action": "undo", "target": "last"}
        return d
    d.result = _undo_check(le)
    return d


def _undo_check(le: dict) -> dict:
    """The undo-check question naming the last event: "Sirf pichli entry hata sakta hoon: ... Hata doon?"."""
    base = _clean_event(le)
    question = (f"Sirf pichli entry hata sakta hoon: {_display(base['customer'])}, {_rupees(base.get('amount', 0))} "
                f"{_KIND_WORD.get(base.get('kind'), '')}. Hata doon?").replace(" .", ".")
    return _clarify("unclear_correction", "undo", [base], question=question, extra={"mode": "confirm_undo"})


def _delete_request(sig: list[Tok], ctx: dict, d: _Draft) -> _Draft:
    """An undo word with an amount or an entry ("Ramesh ka 340 udhaar hata do") is never an append (1.15): it asks
    the undo-check question for the last event, whether or not the words match it."""
    d.action = "undo"
    le = _last_event(ctx)
    if le is None:
        d.result = dict(_rejected("no_last_event"), action="undo")
        return d
    d.result = _undo_check(le)
    return d


_KIND_WORD = {"credit": "udhaar", "payment": "jama", "writeoff": "maaf"}


_AMEND_MARKERS = frozenset(fold(w) for w in "sorry arre arey theek thik karke badal badlo change galat".split())


def _is_amend_instruction(sig: list[Tok], toks: list[Tok]) -> bool:
    """"usko 430 kar do", "wo galat tha, 430 likho", "sorry 430 likho", "430 likhna tha", "change karke 430 kar do":
    one amount, no name, no direction word, and a correction marker or a pronoun with an action verb (1.16)."""
    kws = _kws(sig)
    if [r for r in _name_runs(sig) if r.key or r.tags]:
        return False
    if kws & (_LEDGER_CUES - {"likh", "add", "daal", "chadha"}) or kws & {"advance", "maine", "mujhe"}:
        return False
    raws = [fold(t.rom) for t in toks if t.cls != "sep"]
    marker = bool(set(raws) & _AMEND_MARKERS) or bool(kws & {"galat", "makeit"})
    verb = bool(kws & {"kiya", "likh"}) or (raws and raws[-1] in (fold("tha"), fold("thi")))
    pronoun = "pronoun" in kws
    likhna_tha = fold("likhna") in raws and raws[-1] in (fold("tha"), fold("thi"))
    return (marker and verb) or (pronoun and verb) or likhna_tha  # "galat, 430" stays a direct correction (1.6)


def _amend_instruction(sig: list[Tok], amt: Tok, today: date, ctx: dict, d: _Draft) -> _Draft:
    """A correction said as an instruction: the amend confirmation naming the entry, never a second entry."""
    d.action = "amend"
    targets = _last_events(ctx)
    lt = ctx.get("last_turn")
    if not targets or (isinstance(lt, dict) and lt.get("action") == "undo"):
        d.result = dict(_rejected("no_last_event"), action="amend")
        return d
    if amt.val is None:
        d.result = _clarify("unclear_correction", "amend", [_clean_event(targets[-1])])
        return d
    target_ev = targets[-1]
    new = _apply_change(target_ev, {"amount": amt.val})
    d.result = _amend_confirm(target_ev, new, targets, ctx)
    return d


def _amend_confirm(target_ev: dict, new: dict, targets: list[dict], ctx: dict) -> dict:
    """The `amend` confirmation: "Ramesh ki ₹340 udhaar entry ₹430 kar doon?" (1.16)."""
    base = _clean_event(target_ev)
    if all(new.get(k) == base.get(k) for k in ("kind", "customer", "amount", "date")):
        return _clarify("unclear_correction", "amend", [base])
    confirm = {"type": "amend", "old": base.get("amount"), "new": new.get("amount")}
    extra: dict[str, Any] = {"confirm": confirm}
    target = _amend_target(targets, target_ev)
    if target != "last":
        extra["target"] = target
    return _clarify("confirm_entry", "amend", [new], extra=extra, question=_confirm_question(confirm, [new]))


def _reduction(sig: list[Tok]) -> bool:
    """"write off", "maaf", "chhod do", "discount", "chhoot", "kam kar do" (1.16)."""
    kws = _kws(sig)
    raws = [fold(t.rom) for t in sig]
    if "chhod" in kws or "discount" in kws or ("maaf" in kws and (kws & {"kiya"} or any(t.cls == "aux" for t in sig))):
        return True
    if "likh" in kws and "off" in kws:
        return True
    return fold("kam") in raws and bool(kws & {"kiya"})


def _clause_instructions(marked: list[Tok], today: date, ctx: dict, d: _Draft) -> _Draft | None:
    """Balance instructions and reductions in an utterance with other entries (1.17). Each stays in its own clause:
    `poora` / `aadha` is a payment and `maaf` / `chhod do` / `round off` a write-off for that clause's customer,
    with no amount (it is never worked out from the balance here, and never taken from another clause); a
    reduction with its own amount is a write-off of that amount, confirmed. The other entries are kept as spoken.
    None when the utterance is not of that shape."""
    segs = _split_segments(marked)
    if len(segs) < 2:
        return None
    kinds: list[str | None] = []
    for seg in segs:
        ssig = _sig(seg)
        n_amt = sum(1 for t in ssig if t.cls == "amt")
        if n_amt == 0:
            st = _settle_type([t for t in ssig if t.kw != "balance"])  # "write off Mohan's balance"
            kinds.append(("payment" if st in ("settle", "half") else "writeoff") if st else None)
        elif n_amt == 1 and _reduction(ssig):
            kinds.append("cut")
        else:
            kinds.append(None)
    if not any(kinds) or not any(k is None and any(t.cls == "amt" for t in seg) for k, seg in zip(kinds, segs)):
        return None
    events: list[dict] = []
    rest: list[list[Tok]] = []
    complete = False
    cut_confirm: dict | None = None

    def flush() -> _Draft | None:
        nonlocal rest, complete
        if not rest:
            return None
        joined: list[Tok] = []
        for k, seg in enumerate(rest):
            if k:
                joined.append(Tok(",", "sep"))
            joined.extend(seg)
        rest = []
        sub = _entries(joined, today, ctx, d)
        if sub.result is not None:
            return sub
        events.extend(sub.events or [])
        complete = complete or sub.complete
        return None

    for kind, seg in zip(kinds, segs):
        if kind is None:
            rest.append(seg)
            continue
        stop = flush()
        if stop is not None:
            return stop
        toks = [t for t in seg if t.cls not in ("fill", "aux", "cur")]
        c = _analyse_clause(toks, ctx, today)
        ev: dict[str, Any] = {"date": c.date or today.isoformat()}
        if c.names and (c.names[0].key or c.names[0].tags):
            ev["customer"] = c.names[0].key
            if c.names[0].tags:
                ev["tags"] = c.names[0].tags
            for r in c.names:
                d.spoken.update(_run_words(r))
        elif events and events[-1].get("customer"):
            # "..., uska baaki maaf kar do": the customer of the clause just spoken
            ev["customer"] = events[-1]["customer"]
            for key in ("customer_id", "tags"):
                if events[-1].get(key) is not None:
                    ev[key] = events[-1][key]
        if kind == "cut":
            ev["kind"] = "writeoff"
            amt = next(t for t in _sig(seg) if t.cls == "amt")
            if isinstance(amt.val, int) and amt.val > 0:
                ev["amount"] = amt.val
                if cut_confirm is None:
                    cut_confirm = {"type": "writeoff", "amount": amt.val}
                else:
                    ev["_doubt"] = True  # a second reduction is confirmed on its own
        else:
            ev["kind"] = kind
        events.append(ev)
    stop = flush()
    if stop is not None:
        return stop
    d.events = events
    d.complete = complete
    d.confirm = cut_confirm
    d.result = None
    return d


def _writeoff_amount(sig: list[Tok], amt: Tok, today: date, ctx: dict, d: _Draft) -> _Draft:
    """A reduction with one amount: a write-off of that amount, confirmed first; never a credit (1.16)."""
    if amt.val is None:
        d.result = _clarify("missing_amount", "append", [{"kind": "writeoff", "date": today.isoformat()}])
        return d
    ev: dict[str, Any] = {"kind": "writeoff", "amount": amt.val, "date": today.isoformat()}
    runs, _c = _pick_names(sig, ctx)
    if runs and runs[0].key:
        ev["customer"] = _alias(runs[0].key, ctx)
        d.spoken.update(_run_words(runs[0]))
    else:
        carry = _carry(ctx)
        if carry is not None and "pronoun" in _kws(sig):
            ev["customer"] = carry[1]["customer"]
            if carry[1].get("customer_id") is not None:
                ev["customer_id"] = carry[1]["customer_id"]
    return _confirmed_draft(d, ev, {"type": "writeoff", "amount": amt.val})


def _settle_type(sig: list[Tok]) -> str | None:
    """Amount-free settlement phrases (H04 to H09)."""
    kws = _kws(sig)
    if kws & {"batao", "kitna", "kya", "total", "balance", "kab"}:
        return None  # "poora hisaab batao" asks; it does not settle
    if "round" in kws and "off" in kws:
        return "roundoff"
    if "chhod" in kws or ("maaf" in kws and kws & {"kiya"} or "maaf" in kws and any(t.cls == "aux" for t in sig)) \
            or ("likh" in kws and "off" in kws):
        return "writeoff"
    if "aadha" in kws:
        return "half"
    if "poora" in kws or "barabar" in kws or ("chukaya" in kws and kws & {"udhaar", "hisaab"}):
        return "settle"
    return None


def _roster_customer(key: str | None, ctx: dict, customer_id: Any = None) -> dict | None:
    """The one stored customer a key (or id) names, or None."""
    customers = _customers(ctx)
    if not customers:
        return None
    if customer_id is not None:
        hits = [c for c in customers if c.get("id") == customer_id]
        return hits[0] if len(hits) == 1 else None
    if not key:
        return None
    key = _alias(key, ctx)
    hits = [c for c in customers if c["name"] == key or key in [str(a).lower() for a in (c.get("aliases") or [])]]
    if not hits:
        hits = [c for c in customers if nm.same_person(c["name"], key)]
    return hits[0] if len(hits) == 1 else None


def _balance_of(c: dict | None) -> int | None:
    if c is None:
        return None
    b = c.get("balance")
    return int(b) if _num(b) and int(b) == b else None


def _settle(marked: list[Tok], sig: list[Tok], kind: str, today: date, ctx: dict, d: _Draft,
            customer: dict | None = None) -> _Draft:
    """poora / hisaab barabar (settle), aadha (half), chhod do / maaf (writeoff), round off (roundoff)."""
    if customer is None:
        runs, _c = _pick_names(sig, ctx)
        if runs and runs[0].key:
            customer = {"customer": _alias(runs[0].key, ctx)}
            d.spoken.update(_run_words(runs[0]))
        else:
            carry = _carry(ctx)
            if carry is not None and ("pronoun" in _kws(sig) or carry[0] == "event"):
                customer = {"customer": carry[1]["customer"], "customer_id": carry[1].get("customer_id")}
    if customer is None:
        d.result = _clarify("missing_customer", "append", [{"date": today.isoformat()}], extra={"settle": kind})
        return d
    c = _roster_customer(customer["customer"], ctx, customer.get("customer_id"))
    bal = _balance_of(c)
    name = c["name"] if c else customer["customer"]
    ev: dict[str, Any] = {"customer": name, "date": today.isoformat()}
    if c is not None:
        ev["customer_id"] = c["id"]
    query = {"type": "balance", "customer": name}
    if c is not None:
        query["customer_id"] = c["id"]
    if kind == "settle":
        if bal is not None and bal > 0:
            ev.update(kind="payment", amount=bal)
            return _confirmed_draft(d, ev, {"type": "settle", "balance": bal})
        d.result = _query_result(query, ctx, d)
        return d
    if kind == "half":
        if bal is not None and bal > 0 and bal % 2 == 0:
            ev.update(kind="payment", amount=bal // 2)
            return _confirmed_draft(d, ev, {"type": "half", "balance": bal})
        ev["kind"] = "payment"
        d.result = _clarify("missing_amount", "append", [ev])
        return d
    if kind == "writeoff":
        if bal is not None and bal > 0:
            ev.update(kind="writeoff", amount=bal)
            return _confirmed_draft(d, ev, {"type": "writeoff", "balance": bal})
        d.result = _query_result(query, ctx, d)
        return d
    if bal is not None and bal > 0 and bal % 10:
        ev.update(kind="writeoff", amount=bal % 10)
        return _confirmed_draft(d, ev, {"type": "roundoff", "balance": bal})
    ev["kind"] = "writeoff"
    d.result = _clarify("missing_amount", "append", [ev])
    return d


def _confirmed_draft(d: _Draft, ev: dict, confirm: dict) -> _Draft:
    d.events = [ev]
    d.confirm = confirm
    d.result = None
    return d


def _computed(marked: list[Tok], sig: list[Tok], amts: list[Tok], today: date, ctx: dict, d: _Draft) -> _Draft:
    """"Bill 450, 200 diya, baaki udhaar" and "500 udhaar, 100 discount": one credit of the difference (H01, H02)."""
    first, second = amts[0].val, amts[1].val
    if first is None or second is None:
        d.result = _clarify("missing_amount", "append", [{}])
        return d
    if second >= first:
        d.result = _rejected("out_of_scope")
        return d
    names = [r for r in _name_runs(sig) if r.key]
    for r in names:
        d.spoken.update(_run_words(r))
    ev: dict[str, Any] = {"kind": "credit", "amount": first - second, "date": today.isoformat()}
    if names:
        ev["customer"] = _alias(names[0].key, ctx)
    else:
        carry = _carry(ctx)
        if carry is not None and carry[0] == "event":
            ev["customer"] = carry[1]["customer"]
            if carry[1].get("customer_id") is not None:
                ev["customer_id"] = carry[1]["customer_id"]
    return _confirmed_draft(d, ev, {"type": "computed", "bill": first, "paid": second})


def _reminder(sig: list[Tok], ctx: dict, d: _Draft) -> _Draft:
    """"Ramesh ko reminder bhejo", "send Ramesh a reminder for 850", "remind Ramesh" (Q08)."""
    d.action = "reminder"
    d.complete = True
    runs = [r for r in _name_runs(sig) if r.key]
    amts = [t.val for t in sig if t.cls == "amt" and t.val]
    rem: dict[str, Any] = {"status": "ok", "action": "reminder"}
    if amts:
        rem["amount"] = amts[0]
    if runs:
        rem["customer"] = _alias(runs[0].key, ctx)
    else:
        carry = _carry(ctx)
        if carry is not None:
            rem["customer"] = carry[1]["customer"]
            if carry[1].get("customer_id") is not None:
                rem["customer_id"] = carry[1]["customer_id"]
    if "customer" not in rem:
        d.result = _clarify("missing_customer", "reminder", [], extra={"reminder": rem})
        return d
    d.result = _finalize_reminder(rem, ctx)
    return d


def _finalize_reminder(rem: dict, ctx: dict) -> dict:
    if rem.get("customer_id") is None:
        status, data = _resolve(rem["customer"], [], ctx)
        if status == "same_name":
            return _clarify("same_name", "reminder", [], candidates=data, extra={"reminder": rem})
        if status == "ok":
            rem = dict(rem, customer=data.get("customer", rem["customer"]))
            if data.get("customer_id") is not None:
                rem["customer_id"] = data["customer_id"]
    return rem


def _no_amount(marked: list[Tok], sig: list[Tok], today: date, ctx: dict, d: _Draft) -> _Draft:
    runs, _count = _pick_names(sig, ctx)
    name = runs[0] if runs else None
    q = _detect_query(sig, ctx)
    if q is not None:
        d.result = _query_result(q, ctx, d)
        return d
    if not _has_cue(sig):
        # A stored customer's name alone: ask what to write (E12). Any other word alone is not an entry.
        rest = [t for t in sig if not (t.cls == "kw" and t.kw in _MARKERS)]
        if name is not None and name.key and all(t.cls in ("unk", "hon") for t in rest):
            c = _roster_customer(name.key, ctx)
            if c is not None:
                ev = {"customer": c["name"], "customer_id": c["id"], "date": today.isoformat()}
                d.result = _clarify("missing_amount", "append", [ev],
                                    question=f"{_display(c['name'])} ka kya likhun?", extra={"name_only": True})
                return d
        d.result = _rejected("not_ledger")
        return d
    # A ledger sentence without an amount.
    clause = _analyse_clause(marked, ctx, today)
    ev: dict[str, Any] = {}
    if clause.kind in ("credit", "payment"):
        ev["kind"] = clause.kind
    if name is not None and name.key or (name is not None and name.tags):
        ev["customer"] = name.key
        if name.tags:
            ev["tags"] = name.tags
    if clause.date:
        ev["date"] = clause.date
    d.events = [ev]
    d.result = _clarify("missing_amount", "append", [ev])
    return d


def _entries(marked: list[Tok], today: date, ctx: dict, d: _Draft) -> _Draft:
    sig_all = _sig(marked)
    leading_aur = bool(sig_all) and sig_all[0].kw == "aur"
    trailing_aur = bool(sig_all) and sig_all[-1].kw == "aur"
    clause_toks = _clauses([t for t in marked if t.cls not in ("fill", "aux", "cur")])
    carry = _carry(ctx)
    events: list[dict] = []
    prev_customer: dict | None = None
    explicit_any = False
    zero = False
    two_names = False
    out_scope = False
    for ci, toks in enumerate(clause_toks):
        c = _analyse_clause(toks, ctx, today)
        ev: dict[str, Any] = {}
        if c.amount is not None and c.amount > 0:
            ev["amount"] = c.amount
            if c.amount_alt:
                ev["_alt"] = c.amount_alt
            amt_tok = next((t for t in toks if t.cls == "amt"), None)
            if amt_tok is not None and amt_tok.cur:
                ev["_cur"] = True
            if amt_tok is not None and amt_tok.doubt:
                ev["_doubt"] = True
        elif c.amount == 0 and not c.amount_bad:
            zero = True
        if c.giver_receiver:
            out_scope = True
        elif c.name_count > 1:
            two_names = True
        carried = None
        if c.names and (c.names[0].key or c.names[0].tags):
            r = c.names[0]
            ev["customer"] = r.key
            if r.tags:
                ev["tags"] = r.tags
            prev_customer = {"customer": r.key, "tags": r.tags}
            for nr in c.names:
                d.spoken.update(_run_words(nr))
        elif c.pronoun:
            # "uska", "wo", "usne": the customer just spoken about, never a new customer.
            if prev_customer is not None:
                ev["customer"] = prev_customer["customer"]
                if prev_customer.get("customer_id") is not None:
                    ev["customer_id"] = prev_customer["customer_id"]
            elif carry is not None:
                carried = carry[0]
                ev["customer"] = carry[1]["customer"]
                if carry[1].get("customer_id") is not None:
                    ev["customer_id"] = carry[1]["customer_id"]
                prev_customer = {"customer": ev["customer"], "customer_id": ev.get("customer_id")}
        elif c.orphan or c.no_carry:
            pass  # a particle with no name before it, or "wapas kiya" with no name: ask whose account
        elif prev_customer is not None:
            ev["customer"] = prev_customer["customer"]
            if prev_customer.get("tags"):
                ev["tags"] = prev_customer["tags"]
        elif carry is not None and (leading_aur or trailing_aur or c.action_only):
            # Across turns only an explicit continuation takes the last customer ("aur 200", "200 aur",
            # "200 add kar do", pronouns); any other turn without a name asks whose account (1.15).
            carried = carry[0]
            ev["customer"] = carry[1]["customer"]
            if carry[1].get("customer_id") is not None:
                ev["customer_id"] = carry[1]["customer_id"]
            prev_customer = {"customer": ev["customer"], "customer_id": ev.get("customer_id")}
        if carried:
            d.carry_form = True
        explicit = bool(c.names and (c.names[0].key or c.names[0].tags))
        kind = c.kind
        if carried == "event":
            le = carry[1]
            # A carried form with no direction word takes the kind of the last event ("aur 200", "50 add kar do").
            if c.action_only or (kind is None and ci == 0 and (leading_aur or trailing_aur)) \
                    or (c.pronoun and c.no_dir):
                kind = le["kind"]
        elif carried == "query":
            # After a query the customer carries over, the direction does not (L06).
            if c.action_only or c.no_dir or kind is None:
                kind = "ambiguous"
        if "advance" in c.cues:
            ev["_advance"] = True
        if kind in ("credit", "payment"):
            ev["kind"] = kind
            if explicit and "amount" in ev:
                explicit_any = True  # a complete entry: customer, amount and direction
        if c.date:
            ev["date"] = c.date
        if prev_customer is not None and prev_customer.get("customer_id") is not None \
                and ev.get("customer") == prev_customer["customer"] and "customer_id" not in ev and not c.names:
            ev["customer_id"] = prev_customer["customer_id"]
        events.append(ev)
        for r in c.extra_names:
            d.spoken.update(_run_words(r))
            extra_ev: dict[str, Any] = {"customer": r.key}
            if r.tags:
                extra_ev["tags"] = r.tags
            if c.date:
                extra_ev["date"] = c.date
            events.append(extra_ev)
    d.events = events
    d.complete = explicit_any
    if out_scope:
        d.result = _rejected("out_of_scope")  # one customer paying another (B14)
        return d
    if zero:
        d.result = _rejected("invalid_number")
        return d
    if two_names:
        with_amount = [e for e in events if "amount" in e]
        if len(with_amount) == 1:
            # One amount and two names it cannot be given to ("Ramesh ka khata, Sunita ko 1500 udhaar"): what was
            # said is kept and only the customer is asked (1.17).
            ev = {k: v for k, v in with_amount[0].items() if k not in ("customer", "customer_id", "tags")}
            ev.setdefault("date", today.isoformat())
            d.events = [ev]
            d.result = _clarify("missing_customer", "append", [ev])
            return d
        for e in events:
            e.pop("customer", None)
            e.pop("customer_id", None)
            e.pop("amount", None)
        d.result = _clarify("missing_amount", "append", events)
        return d
    d.result = None  # finalised by the caller (needs the confusable check)
    return d


def _last_events(ctx: dict) -> list[dict]:
    """The events saved by the previous saving utterance (ctx.last_events), else [ctx.last_event]."""
    evs = ctx.get("last_events")
    if isinstance(evs, list):
        good = [e for e in evs if isinstance(e, dict) and e.get("customer")
                and e.get("kind") in ("credit", "payment", "writeoff") and isinstance(e.get("amount"), int)]
        if good:
            return good
    le = _last_event(ctx)
    return [le] if le is not None else []


def _event_label(e: dict) -> str:
    return f"{_rupees(e.get('amount', 0))} {_KIND_WORD.get(e.get('kind'), '')}".strip()


def _which_entry(targets: list[dict], change: dict) -> dict:
    labels = [_event_label(e) for e in targets]
    joined = ", ".join(labels[:-1]) + " ya " + labels[-1] if len(labels) > 1 else labels[0]
    cands = [dict(e) for e in targets]
    return _clarify("unclear_correction", "amend", [], candidates=cands, question=f"Kaunsi entry: {joined}?",
                    extra={"mode": "which_entry", "change": change})


def _amend_target(targets: list[dict], ev: dict) -> Any:
    if len(targets) > 1 and ev.get("id") is not None:
        return {"event_id": ev["id"]}
    return "last"


def _apply_change(base: dict, change: dict) -> dict:
    new = _clean_event(base)
    if "customer" in change:
        for key in ("customer_id", "new_customer", "tags"):
            new.pop(key, None)
    new.update(change)
    return new


def _correction_change(suffix: list[Tok], today: date, ctx: dict) -> tuple[dict | None, str | None]:
    """Fields that the words after "nahi" replace: (change, problem). problem is unclear_correction / unclear_date."""
    change: dict[str, Any] = {}
    s_amts = [t for t in suffix if t.cls == "amt"]
    if len(s_amts) > 1:
        return None, "unclear_correction"
    if s_amts:
        v = s_amts[0].val
        if v is None:
            return None, "missing_amount"  # "nahi nahi, saadh sau": a misheard amount
        if v == 0:
            return None, "invalid_number"
        change["amount"] = v
    clause = _analyse_clause(suffix, ctx, today)
    ssig = _sig(suffix)
    named = [r for r in clause.names if r.key and (r.start == 0 or (r.end < len(ssig) and ssig[r.end].kw in _MARKERS))]
    if named:
        # A replacement name stands where a name can: first after "nahi", or before a particle ("nahi, Suresh ko").
        r = named[0]
        change["customer"] = r.key
        if r.tags:
            change["tags"] = r.tags
    if _kws(suffix) & _LEDGER_CUES and clause.kind in ("credit", "payment"):
        change["kind"] = clause.kind
    elif _kws(suffix) & _KIND_WORDS:
        kind = _answer_kind([t for t in suffix if t.cls == "kw"], None)
        if kind is not None:
            change["kind"] = kind  # a correction that names a kind changes the kind
    if any(t.cls == "date" or t.kw in ("aaj", "kal", "parso", "narson", "weekday", "hafte", "tarikh")
           for t in suffix):
        if clause.date_issue:
            return None, "unclear_date"
        change["date"] = clause.date
    return change, None


def _correction(marked: list[Tok], sig: list[Tok], today: date, ctx: dict, d: _Draft) -> _Draft:
    # The words after the last "nahi" replace those before it ("nahi, Ramesh ka nahi, Sunita ka 200").
    k = max(i for i, t in enumerate(sig) if t.kw in ("neg", "galat", "makeit"))
    prefix = [t for t in sig[:k] if t.kw not in ("neg", "galat", "makeit")]
    suffix = [t for t in sig[k + 1:] if t.kw not in ("neg", "galat", "hai", "tha", "to", "makeit")]
    kind_toks = [t for t in prefix if t.cls == "kw" and t.kw in _KIND_WORDS]
    if not suffix and len(kind_toks) >= 2:
        # "jama tha udhaar nahi": the kind right before "nahi" is denied, the earlier one is meant.
        denied = kind_toks[-1]
        suffix = [t for t in prefix if t is not denied and t.kw not in ("hai", "tha")]
        prefix = [denied]
    elif sig[k].rom == "not" and prefix and suffix:
        prefix, suffix = suffix, prefix  # English "credit not payment": the word before "not" is meant
    if not suffix and k > 0 and any(t.kw in ("neg", "galat") for t in sig[:k]) and prefix:
        # "nahi, 430 nahi": the replacement came before the last "nahi"
        first = min(i for i, t in enumerate(sig) if t.kw in ("neg", "galat", "makeit"))
        prefix = [t for t in sig[:first]]
        suffix = [t for t in sig[first + 1:k] if t.kw not in ("neg", "galat", "hai", "tha", "to", "makeit")]
    if not prefix and len([t for t in suffix if t.cls == "amt"]) == 2 and suffix[0].cls == "amt":
        prefix, suffix = suffix[:1], suffix[1:]  # "not 340, 430"
    prefix = [t for t in prefix if not (t.cls == "kw" and t.kw in ("nevername", "pronoun", "tha", "hai"))]
    p_amts = [t for t in prefix if t.cls == "amt"]
    p_names = _name_runs(prefix)
    p_fields = (1 if p_amts else 0) + (1 if p_names else 0) + (1 if _kws(prefix) & _LEDGER_CUES else 0)
    other = [t for t in prefix if t.cls not in ("amt", "unk", "hon", "tag") and t.kw not in _MARKERS
             and t.kw not in _LEDGER_CUES]
    s_amts = [t for t in suffix if t.cls == "amt"]
    s_names = _name_runs(suffix)
    for r in p_names:
        d.spoken.update(_run_words(r))  # the name being corrected
    if not prefix and suffix and not s_amts:
        q = _detect_query(suffix, ctx)
        if q is not None:  # "Nahi, Sunita ka total batao": the query is what was meant
            d.result = _query_result(q, ctx, d)
            return d
    if p_fields > 1 or other:
        s_dates = any(t.cls == "date" or t.kw in ("aaj", "kal", "parso") for t in suffix)
        if not (s_amts or s_names or s_dates or _kws(suffix) & _LEDGER_CUES):
            d.result = _rejected("negated")  # "... udhaar nahi hai": nothing replaces what was denied
            return d
        # A self-correction inside a new sentence: the words after "nahi" replace those before it.
        keep = []
        for t in prefix:
            if s_amts and t.cls == "amt":
                continue
            if s_names and t.cls in ("unk", "hon", "tag"):
                continue
            keep.append(t)
        rebuilt = keep + suffix
        for r in s_names:
            d.spoken.update(_run_words(r))
        if not any(t.cls == "amt" for t in rebuilt):
            return _no_amount(rebuilt, _sig(rebuilt), today, ctx, d)
        return _entries(rebuilt, today, ctx, d)
    targets = _last_events(ctx)
    d.action = "amend"
    lt = ctx.get("last_turn")
    if not targets or (isinstance(lt, dict) and lt.get("action") == "undo"):
        d.result = dict(_rejected("no_last_event"), action="amend")  # never an undone entry (D11)
        return d
    confirm_first = not _entry_turn(ctx)  # after a question, a query or a silence: confirm the change (1.16)
    last = targets[-1]
    if not suffix:
        d.result = _clarify("unclear_correction", "amend", [_clean_event(last)])
        return d
    change, problem = _correction_change(suffix, today, ctx)
    if change:
        d.spoken.update(str(change.get("customer") or "").split())
        for tag in change.get("tags") or []:
            d.spoken.update(tag.split())
    if problem == "missing_amount":
        d.result = _clarify("missing_amount", "amend", [{k2: v2 for k2, v2 in _clean_event(last).items()
                                                         if k2 != "amount"}],
                            extra={"target": _amend_target(targets, last)} if len(targets) > 1 else None)
        return d
    if problem == "invalid_number":
        d.result = _rejected("invalid_number")
        return d
    if problem == "unclear_date":
        d.result = _clarify("unclear_date", "amend", [{k2: v2 for k2, v2 in _clean_event(last).items()
                                                       if k2 != "date"}])
        return d
    if problem or not change:
        d.result = _clarify("unclear_correction", "amend", [_clean_event(last)])
        return d
    # Which saved event is being corrected?
    pool = targets
    if p_amts:
        pool = [e for e in pool if e.get("amount") == p_amts[0].val]
    if p_names:
        pool = [e for e in pool if nm.same_person(p_names[0].key, e.get("customer", ""))]
    if not pool:
        d.result = _which_entry(targets, change) if len(targets) > 1 else \
            _clarify("unclear_correction", "amend", [_clean_event(last)])
        return d
    if len(pool) > 1:
        d.result = _which_entry(pool, change)
        return d
    target_ev = pool[0]
    base = _clean_event(target_ev)
    new = _apply_change(target_ev, change)
    if all(new.get(k2) == base.get(k2) for k2 in ("kind", "customer", "amount", "date")):
        d.result = _clarify("unclear_correction", "amend", [base])  # "nahi 340" on a 340 entry changes nothing
        return d
    if not prefix and all(k2 in change for k2 in ("customer", "amount", "kind")) \
            and not nm.same_person(change["customer"], base.get("customer", "")) \
            and change["amount"] != base.get("amount") and change["kind"] != base.get("kind"):
        # "Nahi, Sunita ne 500 diye" after "Ramesh ka 340 udhaar": replace the last entry, or add this one?
        fresh = {"kind": change["kind"], "customer": change["customer"], "amount": change["amount"],
                 "date": change.get("date", today.isoformat())}
        if change.get("tags"):
            fresh["tags"] = change["tags"]
        d.result = _clarify("unclear_correction", "amend", [fresh], question="Pichli entry hata kar yeh likhoon?",
                            extra={"mode": "replace", "target": _amend_target(targets, target_ev)})
        return d
    d.events = [new]
    if confirm_first:
        d.result = _amend_confirm(target_ev, new, targets, ctx)
        return d
    d.result = _finalize([new], "amend", ctx, target=_amend_target(targets, target_ev))
    return d


def _confusable_checker(utterance: str, events: list[dict], today: date, ctx: dict):
    alts = ctx.get("stt_alternatives")
    if not isinstance(alts, list) or not alts:
        return None
    sub_ctx = {k: v for k, v in ctx.items() if k not in ("stt_alternatives", "pending")}
    base_norm = " ".join(normalise(utterance).split())
    alt_events = []
    for alt in alts:
        if not isinstance(alt, str) or " ".join(normalise(alt).split()) == base_norm:
            continue
        ad = _draft(_tokenise(alt, sub_ctx), today, sub_ctx)
        if ad.result is None and ad.events:
            alt_events.append(ad.events)

    def check(final_events: list[dict]):
        for other in alt_events:
            if len(other) != len(events):
                continue
            for i, (a, b) in enumerate(zip(events, other)):
                if a.get("kind") != b.get("kind") or a.get("customer") != b.get("customer") \
                        or a.get("date") != b.get("date"):
                    break
            else:
                for i, (a, b) in enumerate(zip(events, other)):
                    if "amount" in b and a.get("amount") != b["amount"]:
                        return i, [final_events[i]["amount"], b["amount"]]
        return None

    return check


def _run_words(r: _Name) -> set[str]:
    words = set(r.words)
    for tag in r.tags:
        words.update(tag.split())
    return words


def _unknown_words(d: _Draft, events: list[dict], ctx: dict) -> list[str]:
    """Words of the utterance the parser cannot account for: not a keyword, number, currency, filler or harmless
    word, not used as the customer name or tag, and not a stored name, alias or tag (1.14 strict mode)."""
    known = set(d.spoken) | _name_vocab(ctx)
    for c in _customers(ctx) or []:
        for tag in c.get("tags") or []:
            if isinstance(tag, str):
                known.update(tag.lower().split())
    for e in events:
        known.update(str(e.get("customer") or "").split())
        for tag in e.get("tags") or []:
            known.update(str(tag).split())
    out: list[str] = []
    for t in d.marked:
        if t.cls != "unk":
            continue
        roman = romanise_word(t.raw, long_vowels=False) if is_devanagari(t.raw) else t.raw
        for w in roman.split():
            if w in known or t.raw in known or fold(w) in _HARMLESS_FOLDS or nm.is_honorific(w) or w in out:
                continue
            out.append(w)
    return out


def _strict_gate(result: dict, d: _Draft, ctx: dict) -> dict:
    """With limits.strict, a save that holds a word nobody listed becomes a yes/no question (1.14)."""
    if not _lim(ctx, "strict", False) or result.get("status") != "ok" \
            or result.get("action") not in ("append", "amend"):
        return result
    events = result.get("events") or []
    unknown = _unknown_words(d, events, ctx)
    if not unknown:
        return result
    confirm = {"type": "unsure", "words": unknown}
    extra: dict[str, Any] = {"confirm": confirm}
    if result.get("action") == "amend" and result.get("target") not in (None, "last"):
        extra["target"] = result["target"]
    return _clarify("confirm_entry", result["action"], events, extra=extra,
                    question=_confirm_question(confirm, events))


def _fresh(toks: list[Tok], utterance: str, today: date, ctx: dict) -> tuple[dict, _Draft]:
    d = _draft(toks, today, ctx)
    if d.result is not None:
        return _carry_unsure(_strict_gate(d.result, d, ctx), d, ctx), d
    events = d.events or []
    checker = _confusable_checker(utterance, events, today, ctx)
    result = _finalize(events, "append", ctx, confusable=checker, confirm=d.confirm, carry_form=d.carry_form)
    return _carry_unsure(_strict_gate(result, d, ctx), d, ctx), d


def _carry_unsure(result: dict, d: _Draft, ctx: dict) -> dict:
    """Strict mode: when another question comes first, the unknown words ride along in pending.unsure_words, and
    the entry is confirmed with an `unsure` question before it is saved (1.15)."""
    if not _lim(ctx, "strict", False) or result.get("status") != "needs_clarification":
        return result
    pending = result.get("pending")
    if not isinstance(pending, dict) or pending.get("action") not in ("append", "amend"):
        return result
    if (pending.get("confirm") or {}).get("type") == "unsure":
        return result
    unknown = _unknown_words(d, pending.get("events") or [], ctx)
    if unknown:
        pending["unsure_words"] = unknown
    return result


# ---------------------------------------------------------------------------------------------------------------
# Answers to a pending question


def _answer_tokens(toks: list[Tok]) -> list[Tok]:
    return [t for t in _mark(toks, keep_fillers=True) if t.cls not in ("sep", "cur")]


_SOFT = {"filler", "hai", "tha", "ji", "ok", "kiya", "likh", "to"}


def _name_matches(toks: list[Tok], customer: str | None) -> bool:
    """Name words in an answer are allowed only when they name the customer already in the question."""
    runs = _name_runs(toks)
    if not runs:
        return True
    if not customer or not customer.split():
        return False
    first = customer.split()[0]
    return all(not r.key.split() or nm.same_person(r.key, customer) or nm.same_person(r.key.split()[0], first)
               for r in runs)


def _only_number(sig: list[Tok], customer: str | None = None, allow_neg: bool = False) -> int | None | str:
    """The one amount in an answer ("200", "200 rupaye udhaar", "nahi 7500"), "bad" if unreadable, else None."""
    amts = [t for t in sig if t.cls == "amt"]
    if len(amts) > 1 or (amts and amts[0].alt):
        return None  # two readings ("300 ya 400", "teen chaar sau"): not one number
    others = [t for t in sig if t.cls not in ("amt", "aux")]
    for t in others:
        if t.cls == "kw":
            if t.kw in _SOFT or t.kw in _LEDGER_CUES or t.kw in _MARKERS:
                continue
            if allow_neg and t.kw in ("neg", "galat"):
                continue
            return None
        elif t.cls not in ("unk", "hon", "tag"):
            return None
    if not _name_matches(others, customer):
        return None
    if amts:
        return amts[0].val if amts[0].val is not None else "bad"
    rest = [t for t in sig if t.cls == "aux"]
    if len(rest) == 1 and len(sig) == 1:  # a lone "do" or "ek" as an answer
        v = classify_word(rest[0].raw)
        return v[1] if v else None
    return None


def _is_yes(sig: list[Tok]) -> bool:
    kws = [t.kw if t.cls == "kw" else t.cls for t in sig]
    allowed = _YES | {"hai", "filler", "likh", "kiya", "aux", "to"}
    return bool(kws) and all(k in allowed for k in kws) and any(k in _YES for k in kws)


def _is_no(sig: list[Tok]) -> bool:
    kws = [t.kw if t.cls == "kw" else t.cls for t in sig]
    return bool(kws) and all(k in ("neg", "galat", "hai", "filler", "undo") for k in kws) \
        and any(k in ("neg", "galat", "undo") for k in kws)


def _is_plain_no(sig: list[Tok]) -> bool:
    kws = [t.kw if t.cls == "kw" else t.cls for t in sig]
    return bool(kws) and all(k in ("neg", "galat", "hai", "filler", "ji") for k in kws) \
        and any(k in ("neg", "galat") for k in kws)


def _is_cancel(sig: list[Tok]) -> bool:
    kws = [t.kw if t.cls == "kw" else t.cls for t in sig]
    if not kws:
        return False
    if "rehne" in kws or ("mat" in kws and "likh" in kws):
        return True
    return all(k in ("undo", "kiya", "aux", "hai", "filler", "entry", "pichla") for k in kws) and "undo" in kws


def _ordinal(sig: list[Tok]) -> int | None:
    """pehla / pehli / first -> 0, doosra / second -> 1, with or without "wala" and fillers."""
    kws = [t.kw for t in sig if not (nm.is_tag_word(t.rom) or (t.cls == "kw" and t.kw in ("filler", "hai", "ji")))]
    if kws in (["first"], ["pehle"]):
        return 0
    if kws == ["second"]:
        return 1
    return None


def _pehle_wale(sig: list[Tok]) -> bool:
    raws = [t.rom for t in sig]
    return len(raws) == 2 and fold(raws[0]) == fold("pehle") or (
        len(raws) == 2 and fold(raws[0]) == fold("pahle")) and nm.is_tag_word(raws[1])


def _has_stop(sig: list[Tok]) -> bool:
    kws = _kws(sig)
    return bool(kws & {"undo", "stop", "rehne"}) or ("mat" in kws and bool(kws & {"likh", "kiya"}))


def _two_amounts(sig: list[Tok]) -> list[int] | None:
    """The two candidates of an answer such as "300 ya 400", "teen chaar sau" or "likh do sau", else None."""
    amts = [t for t in sig if t.cls == "amt" and isinstance(t.val, int) and t.val > 0]
    if len(amts) >= 2 and amts[0].val != amts[1].val:
        return [amts[0].val, amts[1].val]
    if len(amts) == 1 and isinstance(amts[0].alt, int) and amts[0].alt > 0 and amts[0].alt != amts[0].val:
        return [amts[0].val, amts[0].alt]
    return None


def _answer_names(sig: list[Tok]) -> list[_Name] | None:
    """The one name (or tag) an answer gives. After "nahi" only the words that follow count ("X nahi Y" -> Y);
    a denied name alone ("X nahi"), two names ("X ya Y", "X aur Y") or nothing give None (1.15)."""
    negs = [i for i, t in enumerate(sig) if t.cls == "kw" and t.kw in ("neg", "galat")]
    part = sig[negs[-1] + 1:] if negs else sig
    part = [t for t in part if not (t.cls == "kw" and t.kw in ("filler", "hai", "ji", "ok", "yes", "tha"))]
    runs = [r for r in _name_runs(part, honorific_name=True) if r.key or r.tags]
    if not runs:
        return None
    if len(runs) > 1 or any(t.kw in ("ya", "aur") for t in part):
        return None
    return runs


def _foreign_amount(sig: list[Tok], events: list[dict]) -> bool:
    """An answer carrying an amount different from the pending one, where no amount was asked for."""
    pending_amts = {e.get("amount") for e in events if e.get("amount")}
    return any(t.cls == "amt" and t.val not in pending_amts for t in sig)


def _bare_name(sig: list[Tok]) -> bool:
    """Only name words (and tags), with fillers and an optional leading "nahi": a name answer."""
    words = [t for t in sig if not (t.cls == "kw" and t.kw in ("filler", "hai", "ji", "ok", "yes", "neg"))
             and t.cls not in ("sep", "cur")]
    return bool(words) and all(t.cls in ("unk", "hon", "tag") for t in words)


def _kind_conflict(sig: list[Tok], events: list[dict]) -> bool:
    """An answer whose own direction word disagrees with the pending event is not an answer ("60 udhaar" when a
    payment is pending)."""
    words = [t for t in sig if t.cls not in ("amt", "sep", "cur", "aux")
             and not (t.cls == "kw" and t.kw in (_MARKERS | {"neg", "galat", "to", "tha", "hai"}))]
    kind = _answer_kind([t for t in words if t.cls == "kw"], None) if words else None
    if kind is None:
        return False
    return any(e.get("kind") and e["kind"] != kind for e in events)


def _target_index(events: list[dict], pending: dict, field: str | None = None, value: Any = None) -> int:
    idx = pending.get("index")
    if isinstance(idx, int) and 0 <= idx < len(events):
        return idx
    for i, e in enumerate(events):
        if field is not None and value is not None and e.get(field) == value:
            return i
        if field is not None and value is None and field not in e:
            return i
    return 0


MAX_UNRESOLVED_ANSWERS = 2


def _reask(pending: dict, ctx: dict) -> dict[str, Any]:
    """Ask the same question again; the second unresolved answer in a row cancels it."""
    attempts = pending.get("attempts") if isinstance(pending.get("attempts"), int) else 0
    attempts += 1
    if attempts >= MAX_UNRESOLVED_ANSWERS:
        return _rejected("cancelled")
    reason = pending.get("reason")
    action = pending.get("action") or "append"
    events = [e for e in (pending.get("events") or []) if isinstance(e, dict)]
    extra = {k: pending.get(k) for k in ("mode", "change", "target", "confirm", "settle", "reminder", "name_only",
                                         "quantity", "unsure_words") if k in pending}
    extra["attempts"] = attempts
    question = None
    mode = pending.get("mode")
    if mode == "replace":
        question = "Pichli entry hata kar yeh likhoon?"
    elif mode in ("which_entry", "confirm_undo"):
        cands = [c for c in (pending.get("candidates") or events) if isinstance(c, dict)]
        if mode == "which_entry" and cands:
            labels = [_event_label(e) for e in cands]
            question = "Kaunsi entry: " + (", ".join(labels[:-1]) + " ya " + labels[-1] if len(labels) > 1
                                           else labels[0]) + "?"
        elif mode == "confirm_undo" and events:
            question = (f"Sirf pichli entry hata sakta hoon: {_display(events[0].get('customer', ''))}, "
                        f"{_event_label(events[0])}. Hata doon?")
    elif reason == "confirm_entry" and isinstance(pending.get("confirm"), dict):
        question = _confirm_question(pending["confirm"], events, pending.get("index")
                                     if isinstance(pending.get("index"), int) else None)
    elif pending.get("name_only") and events:
        question = f"{_display(events[0].get('customer', ''))} ka kya likhun?"
    elif pending.get("quantity"):
        question = "Kitne ka?"
    result = _clarify(reason, action, events, candidates=pending.get("candidates"), index=pending.get("index")
                      if isinstance(pending.get("index"), int) else None,
                      confirmed=set(c for c in (pending.get("confirmed") or []) if isinstance(c, str)),
                      query=pending.get("query"), question=question, extra=extra)
    if pending.get("quantity"):
        result["quantity"] = True
    return result


def _pending_target(pending: dict) -> Any:
    t = pending.get("target")
    if isinstance(t, dict) and "event_id" in t:
        return {"event_id": t["event_id"]}
    return "last"


def _answer_correction(sig, toks, utterance, today, ctx, pending, events) -> dict | None:
    mode = pending.get("mode")
    le = _last_event(ctx)
    kws = _kws(sig)
    if mode == "confirm_undo":
        plain = [t for t in sig
                 if not (t.cls == "kw" and t.kw in ("undo", "entry", "pichla", "kiya") or t.cls == "aux")]
        if (_is_yes(plain) if plain else False) or (_is_cancel(sig) and "undo" in kws):
            return {"status": "ok", "action": "undo", "target": "last"} if (le or events) else \
                _rejected("no_last_event")
        if _is_plain_no(sig):
            return _rejected("cancelled")
        return None
    if mode in ("replace", "which_entry") and _has_stop(sig):
        return _rejected("cancelled")
    if mode == "replace":
        if _is_yes(sig):
            return _finalize(events, "amend", ctx, target=_pending_target(pending))
        if _is_plain_no(sig):
            return _finalize(events, "append", ctx)  # keep the old entry and add this one
        return None
    if mode == "which_entry":
        cands = [c for c in (pending.get("candidates") or []) if isinstance(c, dict)]
        change = pending.get("change") if isinstance(pending.get("change"), dict) else {}
        pick = None
        num = _only_number(sig)
        o = _ordinal(sig)
        if isinstance(num, int):
            hits = [c for c in cands if c.get("amount") == num]
            pick = hits[0] if len(hits) == 1 else None
        elif o is not None and o < len(cands):
            pick = cands[o]
        else:
            kind = _answer_kind(sig, None)
            if kind is not None:
                hits = [c for c in cands if c.get("kind") == kind]
                pick = hits[0] if len(hits) == 1 else None
        if pick is None or not change:
            return None
        new = _apply_change(pick, change)
        target = {"event_id": pick["id"]} if pick.get("id") is not None else "last"
        return _finalize([new], "amend", ctx, target=target)
    base = le or (events[0] if events else None)
    if "undo" in kws and not any(t.cls == "amt" for t in sig):
        return {"status": "ok", "action": "undo", "target": "last"} if base else _rejected("no_last_event")
    two = _two_amounts(sig)
    if two and base is not None:
        new = _clean_event(base)
        new["amount"] = two[0]
        return _clarify("confusable_number", "amend", [new], candidates=two, index=0)  # which of the two (1.15)
    num = _only_number(sig)
    if isinstance(num, int):
        if base is None:
            return _rejected("no_last_event")
        if num <= 0:
            return _rejected("invalid_number")
        new = _clean_event(base)
        new["amount"] = num
        return _finalize([new], "amend", ctx)
    if _is_no(sig) or _is_cancel(sig):
        return _rejected("cancelled")
    return None


_ONE_EVENT_CONFIRMS = {"overpayment", "settle", "half", "writeoff", "roundoff"}


def _event_index(pending: dict, events: list[dict]) -> int | None:
    """pending.index when the pending result holds several events, else None."""
    idx = pending.get("index")
    if len(events) >= 2 and isinstance(idx, int) and 0 <= idx < len(events):
        return idx
    return None


def _one_event_index(pending: dict, events: list[dict], ctype: Any) -> int | None:
    """The event a confirmation is about when it concerns one entry of several (1.17), else None."""
    return _event_index(pending, events) if ctype in _ONE_EVENT_CONFIRMS else None


def _answer_pending(toks: list[Tok], utterance: str, today: date, ctx: dict, pending: dict) -> dict | None:
    reason = pending.get("reason")
    action = pending.get("action") or "append"
    events = [dict(e) for e in (pending.get("events") or []) if isinstance(e, dict)]
    confirmed = set(c for c in (pending.get("confirmed") or []) if isinstance(c, str))
    candidates = pending.get("candidates")
    target = _pending_target(pending)
    sig = _answer_tokens(toks)
    if not sig:
        return _reask(pending, ctx)
    # A complete entry (customer, amount and direction) or a query is a new utterance, never an answer: it is
    # parsed fresh and the pending question is dropped (1.9, 1.13). This holds for every pending reason.
    fresh_result, fresh_d = _fresh(toks, utterance, today, ctx)
    if fresh_d.complete:
        return fresh_result

    confirm = pending.get("confirm") if isinstance(pending.get("confirm"), dict) else None
    unsure = [w for w in (pending.get("unsure_words") or []) if isinstance(w, str)]
    if reason in _FIELD_REASONS:
        confirmed.add(_FIELDS_ASKED)  # a multi-entry save after this answer is read back first (1.16)

    def done(evs: list[dict], keep_confirm: bool = True) -> dict:
        return _finalize(evs, action, ctx, confirmed=confirmed, target=target,
                         confirm=confirm if keep_confirm else None, unsure=unsure, asked=True)

    # "pakka?" said back is a question, not a yes.
    if utterance.strip().endswith("?") and _is_yes(sig):
        return _reask(pending, ctx)
    # An undo or stop word in an answer is no, whatever else it holds ("ok cancel karo", "haan hata do"); only the
    # undo-check question reads "hata do" as yes (1.15).
    if reason != "unclear_correction" and _has_stop(sig):
        return _rejected("cancelled")
    # Two amounts in an answer are asked about, as in a fresh sentence (1.15).
    two = _two_amounts(sig)
    if two and reason in ("missing_amount", "plausibility", "confusable_number", "confirm_entry") and events:
        i = _target_index(events, pending, "amount", None) if reason == "missing_amount" else \
            (pending["index"] if isinstance(pending.get("index"), int) and 0 <= pending["index"] < len(events) else 0)
        events[i]["amount"] = two[0]
        keep = {k: pending.get(k) for k in ("confirm", "target", "unsure_words") if pending.get(k) is not None}
        return _clarify("confusable_number", action, events, candidates=two, index=i,
                        confirmed=confirmed - {"confusable_number"}, extra=keep)

    if reason == "unclear_correction":
        res = _answer_correction(sig, toks, utterance, today, ctx, pending, events)
        if res is not None:
            return res
        result, d = _fresh(toks, utterance, today, ctx)
        if d.complete or d.action in ("amend", "undo"):
            return result
        return _reask(pending, ctx)

    if _is_cancel(sig):
        return _rejected("cancelled")

    first_customer = next((e.get("customer") for e in events if e.get("customer")), None)
    if reason == "confirm_entry" and confirm is not None and confirm.get("type") == "reminder":
        # Yes to "send a reminder?" returns the reminder action for the pending customer, without an amount.
        plain = [t for t in sig if not (t.cls == "kw" and t.kw in ("send", "reminder"))]
        if plain and len(plain) < len(sig) and _is_yes(plain) or _is_yes(sig):
            src = pending.get("reminder") if isinstance(pending.get("reminder"), dict) else \
                (events[0] if events else pending)
            if isinstance(src.get("customer"), str) and src["customer"]:
                rem: dict[str, Any] = {"status": "ok", "action": "reminder", "customer": src["customer"]}
                if src.get("customer_id") is not None:
                    rem["customer_id"] = src["customer_id"]
                return rem
        if _is_plain_no(sig) or _is_no(sig):
            return _rejected("cancelled")
        return _reask(pending, ctx)
    if reason == "confirm_entry":
        # Answers as for plausibility: yes saves, no cancels, a number replaces the amount (1.14).
        ctype = (confirm or {}).get("type")
        likh_yes = bool(sig) and "likh" in _kws(sig) and all(
            t.cls == "aux" or t.kw in ("likh", "kiya", "yes", "ok", "filler", "hai") for t in sig)
        one = _one_event_index(pending, events, ctype)
        if _is_yes(sig) or likh_yes:
            if one is not None:
                # One entry of several: the yes covers that entry only; the others, and any words still to be
                # confirmed, are checked after it (1.17).
                confirmed |= {f"confirm_entry@{one}", f"plausibility@{one}"}
                if ctype != "overpayment":
                    confirmed.add("confirm_entry")  # the utterance's own confirmation was answered
                return done(events, keep_confirm=ctype != "overpayment")
            confirmed |= {"confirm_entry", "plausibility"}
            if ctype == "review" or len(events) < 2:
                confirmed.add("review")
            return done(events)
        if _is_plain_no(sig) or _is_no(sig):
            return _rejected("cancelled")
        num = _only_number(sig, first_customer, allow_neg=True)
        if ctype in ("duplicate", "review", "amend"):
            num = None  # these questions take only yes or no (1.16)
        if isinstance(num, int) and len(events) == 1 and not _kind_conflict(sig, events):
            if num <= 0:
                return _rejected("invalid_number")
            events[0]["amount"] = num
            confirmed |= {"confirm_entry", "plausibility", _FIELDS_ASKED}
            return done(events)
        if isinstance(num, int) and one is not None and not _kind_conflict(sig, [events[one]]):
            if num <= 0:
                return _rejected("invalid_number")
            events[one]["amount"] = num  # the replacement is not asked about again
            confirmed |= {f"confirm_entry@{one}", f"plausibility@{one}", _FIELDS_ASKED}
            if ctype != "overpayment":
                confirmed.add("confirm_entry")
            return done(events, keep_confirm=ctype != "overpayment")

    elif reason == "new_customer":
        # Answers (1.14): "naya" / "haan" make the new customer; "pehla" / "doosra" pick a candidate by position;
        # the close name, "wahi" or "purana" pick the only candidate; a tag picks among same-name candidates.
        cands = [c for c in (candidates or []) if isinstance(c, dict)]
        i = _target_index(events, pending, "customer_id", None) if events else 0
        kws = _kws(sig)
        plain = [t for t in sig if not (t.cls == "kw" and t.kw in ("filler", "hai", "ji"))]
        if events and (_is_yes(sig) or ("naya" in kws and all(
                t.kw in ("naya", "yes", "ok", "kiya", "measure", "khata") or t.cls == "aux" for t in plain))):
            # One question per distinct unknown name (1.16): the yes covers every event naming the same person, under
            # one key, so one account is opened; another unknown name gets its own question.
            key = events[i].get("customer")
            for j, e in enumerate(events):
                if j == i or (isinstance(key, str) and key and e.get("customer_id") is None
                              and not e.get("new_customer") and isinstance(e.get("customer"), str)
                              and nm.same_person(key, e["customer"])):
                    e["new_customer"] = True
                    if j != i:
                        e["customer"] = key
            return done(events)
        if _is_plain_no(sig) or (kws & {"neg", "mat"} and "naya" in kws):
            return _rejected("cancelled")  # "nahi", "mat banao", "nahi banana"
        pick = None
        order = _ordinal(sig)
        if order is not None and order < len(cands):
            pick = cands[order]
        elif "wahi" in kws and len(cands) == 1:
            pick = cands[0]
        elif _bare_name(sig) and not _foreign_amount(sig, events) and _answer_names(sig) is not None:
            runs = _answer_names(sig) or []
            tags = [tg for r in runs for tg in r.tags]
            keyed = [r for r in runs if r.key]
            if tags:
                hits = [c for c in cands if any(nm.tag_matches(tg, ct) for tg in tags for ct in (c.get("tags") or []))]
                pick = hits[0] if len(hits) == 1 else None
            elif keyed:
                hits = [c for c in cands if nm.same_person(keyed[0].key, c.get("name", ""))]
                if len(hits) == 1:
                    pick = hits[0]
                elif not hits and events:
                    events[i]["customer"] = keyed[0].key  # another name: resolve it again (1.8)
                    for key in ("customer_id", "new_customer", "tags"):
                        events[i].pop(key, None)
                    confirmed.add(_FIELDS_ASKED)  # a name nobody offered changes the customer: reviewed
                    return done(events)
        if pick is not None and events:
            # Picking a customer the question offered answers the question itself: no review (1.16, Z01).
            _apply_fields(events[i], {"customer": pick.get("name"), "customer_id": pick.get("id")})
            return done(events)

    elif reason == "plausibility":
        p_index = _event_index(pending, events)
        if _is_yes(sig):
            # With several events the yes covers the amount that was asked about only (1.17).
            confirmed.add(f"plausibility@{p_index}" if p_index is not None else "plausibility")
            return done(events)
        if _is_plain_no(sig) or _is_no(sig):
            return _rejected("cancelled")
        num = _only_number(sig, first_customer, allow_neg=True)
        if isinstance(num, int) and events and not _kind_conflict(sig, events):
            if num <= 0:
                return _rejected("invalid_number")
            limit = _limit(ctx)
            i = pending.get("index") if isinstance(pending.get("index"), int) and \
                0 <= pending["index"] < len(events) else next(
                (j for j, e in enumerate(events) if e.get("amount", 0) > limit), 0)
            events[i]["amount"] = num
            confirmed |= {f"plausibility@{i}" if p_index is not None else "plausibility", _FIELDS_ASKED}
            return done(events)

    elif reason == "confusable_number":
        cands = candidates if isinstance(candidates, list) and len(candidates) >= 2 else None
        choice = None
        num = _only_number(sig, first_customer)
        if isinstance(num, int) and not _kind_conflict(sig, events):
            choice = num
        elif cands is not None:
            o = _ordinal(sig)
            if o is not None:
                choice = cands[o]
            elif _is_yes(sig):
                choice = cands[0]
        if choice is not None and events:
            if not isinstance(choice, int) or choice <= 0:
                return _rejected("invalid_number")
            i = _target_index(events, pending, "amount", cands[0] if cands else None)
            events[i]["amount"] = choice
            confirmed |= {"confusable_number", "plausibility"}
            return done(events)
        if _is_no(sig):
            return _rejected("cancelled")

    elif reason == "missing_amount":
        i = _target_index(events, pending, "amount", None) if events else 0
        customer = events[i].get("customer") if events else None
        if pending.get("name_only") and events and _kws(sig) & {"total", "hisaab", "balance", "baaki"} \
                and not any(t.cls == "amt" for t in sig):
            q = {"type": "balance", "customer": customer}
            if events[i].get("customer_id") is not None:
                q["customer_id"] = events[i]["customer_id"]
            return _finalize_query(q, ctx)  # "Ramesh" then "hisaab": the balance
        num = _only_number(sig, customer)
        if num == 0:
            return _rejected("invalid_number")
        if isinstance(num, int) and events and not _kind_conflict(sig, events[i:i + 1]):
            events[i]["amount"] = num
            if "kind" not in events[i]:
                kind = _answer_kind([t for t in sig if t.cls != "amt"], customer)
                if kind is not None:
                    events[i]["kind"] = kind
            return done(events)

    elif reason == "same_name":
        cands = [c for c in (candidates or []) if isinstance(c, dict)]
        pick = None
        if cands:
            o = _ordinal(sig)
            if _pehle_wale(sig):
                untagged = [c for c in cands if not c.get("tags")]
                pick = untagged[0] if len(untagged) == 1 else cands[0]
            elif o is not None and o < len(cands):
                pick = cands[o]
            elif not _foreign_amount(sig, events) and not _kind_conflict(sig, events) \
                    and not (_kws(sig) & {"neg", "galat", "ya", "aur"} and _answer_names(sig) is None):
                content = [t for t in sig if not (t.cls == "kw" and t.kw in ("filler", "hai", "ji", "ok", "yes"))]
                negs = [k for k, t in enumerate(content) if t.cls == "kw" and t.kw in ("neg", "galat")]
                if negs:
                    content = content[negs[-1] + 1:]
                runs = _name_runs(content)
                tags = [tg for r in runs for tg in r.tags]
                keys = [r.key for r in runs if r.key]
                name_ok = all(any(nm.same_person(k2, c.get("name", "")) for c in cands) for k2 in keys)
                if tags and name_ok:
                    hits = [c for c in cands if any(nm.tag_matches(tg, ct) for tg in tags
                                                    for ct in (c.get("tags") or []))]
                else:
                    spoken = " ".join(romanise_word(t.raw, False) if is_devanagari(t.raw) else t.raw for t in content)
                    hits = [c for c in cands if any(nm.tag_matches(spoken, ct) for ct in (c.get("tags") or []))]
                if len(hits) == 1:
                    pick = hits[0]
        if pick is not None:
            if action == "query":
                q = dict(pending.get("query") or {})
                q["customer"] = pick.get("name", q.get("customer"))
                q["customer_id"] = pick.get("id")
                return {"status": "ok", "action": "query", "query": q}
            if action == "reminder" and isinstance(pending.get("reminder"), dict):
                return dict(pending["reminder"], customer=pick.get("name"), customer_id=pick.get("id"))
            i = _target_index(events, pending, "customer", pick.get("name"))
            if events:
                _apply_fields(events[i], {"customer": pick.get("name"), "customer_id": pick.get("id")})
            return done(events)

    elif reason == "missing_customer":
        rest = [t for t in sig if not (t.cls == "kw" and t.kw in ("filler", "hai", "ji", "ok", "yes")
                                       or t.kw in _MARKERS)]
        runs: list[_Name] = []
        le = _last_event(ctx)
        if rest and all(t.cls == "kw" and t.kw == "wahi" for t in rest) and le is not None and events:
            i = _target_index(events, pending, "customer", None)
            events[i]["customer"] = le["customer"]  # "wahi", "usi ka", "same": the customer of the last event
            if le.get("customer_id") is not None:
                events[i]["customer_id"] = le["customer_id"]
            return done(events)
        if _foreign_amount(sig, events):
            pass
        elif _kws(sig) & {"neg", "galat", "ya", "aur"} or len(_name_runs(rest)) > 1:
            runs = _answer_names(sig) or []
        elif rest and all(t.cls in ("unk", "hon", "tag") for t in rest):
            runs = _name_runs(rest, honorific_name=True)
        else:
            # The name may come with other words ("Ramesh ko 100 wapas kiya"); the first name in front is the answer.
            picked, _c = _pick_names([t for t in sig if t.cls != "sep"], ctx)
            amts = [t.val for t in sig if t.cls == "amt"]
            pending_amt = next((e.get("amount") for e in events if e.get("amount")), None)
            if picked and picked[0].key and (not amts or amts == [pending_amt]) and not _kind_conflict(sig, events):
                runs = picked
        if runs and (runs[0].key or runs[0].tags):
            key = runs[0].key
            if action == "query":
                q = dict(pending.get("query") or {"type": "balance"})
                q["customer"] = _alias(key, ctx)
                return _query_result(q, ctx, _Draft())
            if action == "reminder" and isinstance(pending.get("reminder"), dict):
                return _finalize_reminder(dict(pending["reminder"], customer=_alias(key, ctx)), ctx)
            if isinstance(pending.get("settle"), str):
                dd = _settle([], [], pending["settle"], today, ctx, _Draft(), customer={"customer": key})
                if dd.result is not None:
                    return dd.result
                return _finalize(dd.events or [], "append", ctx, confirm=dd.confirm)
            if events:
                i = _target_index(events, pending, "customer", None)
                events[i]["customer"] = key
                for k2 in ("customer_id", "new_customer", "tags"):
                    events[i].pop(k2, None)
                if runs[0].tags:
                    events[i]["tags"] = runs[0].tags
                if "kind" not in events[i]:
                    clause = _analyse_clause([t for t in sig], ctx, today)
                    if clause.kind in ("credit", "payment"):
                        events[i]["kind"] = clause.kind
                iso, issue = _date_of(sig, today)
                if iso and not issue and any(t.kw in ("aaj", "kal", "parso") or t.cls == "date" for t in sig):
                    events[i]["date"] = iso  # "Ramesh ka kal ka": the date said with the name is kept (1.16)
                return done(events)

    elif reason == "ambiguous_direction":
        i = _target_index(events, pending, "kind", None) if events else 0
        kind = None if _foreign_amount(sig, events) else \
            _answer_kind([t for t in sig if t.cls != "amt"], events[i].get("customer") if events else None)
        if kind is not None and events:
            events[i]["kind"] = kind
            return done(events)

    elif reason == "unclear_date":
        only_date = all(t.cls == "date" or t.kw in ("aaj", "kal", "parso", "time", "filler", "hai", "tha", "period",
                                                     "ka", "nevername", "yes")
                        for t in sig) and any(t.cls == "date" or t.kw in ("aaj", "kal", "parso", "period") for t in sig)
        if only_date and action == "query":
            q = dict(pending.get("query") or {})
            periods = [t.val for t in sig if t.kw == "period" and t.val != "unclear"]
            kws = _kws(sig)
            period = periods[0] if periods else "yesterday" if "kal" in kws else "today" if "aaj" in kws else None
            if period:
                q["period"] = period
                return _finalize_query(q, ctx)
        elif only_date:
            iso, issue = _date_of(sig, today)
            if iso and events:
                i = _target_index(events, pending, "date", None)
                events[i]["date"] = iso
                return done(events)

    result, d = _fresh(toks, utterance, today, ctx)
    if d.complete:
        return result
    if reason in ("plausibility", "confusable_number") and _is_no(sig):
        return _rejected("cancelled")
    return _reask(pending, ctx)


def _answer_kind(sig: list[Tok], customer: str | None) -> str | None:
    """udhaar / credit / ko (diya) -> credit; payment / jama / mila / ne (diye) -> payment. A name in the answer
    must be the customer the question is about ("Ramesh ne diye")."""
    negs = [i for i, t in enumerate(sig) if t.cls == "kw" and t.kw in ("neg", "galat")]
    if negs and negs[-1] + 1 < len(sig):
        sig = sig[negs[-1] + 1:]  # "jama nahi udhaar": the word after "nahi" wins
    names = [t for t in sig if t.cls in ("unk", "hon", "tag")]
    if names and not _name_matches(names, customer):
        return None
    if any(t.cls not in ("kw", "aux", "unk", "hon", "tag") for t in sig):
        return None
    kws = []
    for t in sig:
        if t.cls != "kw":
            continue
        if t.kw == "pronoun":
            m = _pronoun_marker([t], 0)
            if m in ("ko", "ne"):
                kws.append(m)  # "usko diye" = ko diye; "usne diye" = ne diye
            continue
        if t.kw not in ("filler", "hai", "tha", "kiya", "likh", "yes", "ok", "ji", "to"):
            kws.append(t.kw)
    s = set(kws)
    if not s:
        return None
    if s <= {"udhaar", "credit", "ko", "give", "on", "took", "owes", "take", "gaya"} and \
            s & {"udhaar", "credit", "ko", "took", "owes", "take"}:
        return "credit"  # "haan udhaar", "le gayi", "liye", "usko diye"
    if s <= {"payment", "jama", "mila", "ne", "give", "paymode", "aaya", "paid", "gave", "received", "gaya"} and s:
        return "payment"
    return None  # "pehla" / "doosra" answer only questions with ordered candidates


# ---------------------------------------------------------------------------------------------------------------


_WARM_UP = (
    ("Ramesh ka teen sau chaalis udhaar, kal 200 diya tha", None),
    ("रमेश ने ढाई सौ दिए", None),
    ("Sunita paid five hundred rupees yesterday", None),
    ("nahi, 430", {"last_event": {"kind": "credit", "customer": "ramesh", "amount": 340, "date": "2026-01-01"}}),
    ("Rameysh ka 2k udhaar", {"customers": [{"id": "c1", "name": "ramesh", "tags": ["chai wale"], "balance": 10}],
                              "limits": {"strict": True, "confirm_new_customer": True}}),
    ("pichle hafte kitna udhaar gaya", None),
)


def warm() -> None:
    """Load the vocabulary and run each stage once, so the first live parse is as fast as later ones."""
    today = date(2026, 1, 1)
    for utterance, ctx in _WARM_UP:
        parse(utterance, today=today, ctx=ctx)


def parse(utterance: str, *, today: date, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse one utterance. See the module docstring and CONTRACT section 1 for the result shape."""
    try:
        return _parse(utterance, today, ctx)
    except Exception:  # never raise on the latency path; an unreadable input is simply not understood
        result = _rejected("not_ledger")
        try:
            lang = _lang(_tokenise(utterance)) if isinstance(utterance, str) else None
            if lang is not None:
                result["lang"] = lang
        except Exception:
            pass
        return result


def _parse(utterance: Any, today: date, ctx: Any) -> dict[str, Any]:
    """`parse` without the safety net, so tests can see any exception the net would hide."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(utterance, str):
        utterance = ""
    ctx = dict(ctx) if isinstance(ctx, dict) else {}
    ctx["_parse_copy"] = True  # the parser's own shallow copy: per-call caches live here, the caller's ctx is untouched
    toks = _tokenise(utterance, ctx)
    result = None
    pending = ctx.get("pending")
    has_pending = isinstance(pending, dict) and isinstance(pending.get("reason"), str)
    stop = _trailing_stop(toks)
    if stop is not None:
        # "... ruko", "rehne do", "cancel": stop; nothing is saved (D12, D13).
        n_stop, is_cancel = stop
        before = [t for t in toks if t.cls != "sep"][:-n_stop]
        before = [t for t in before if not (t.cls == "kw" and t.kw == "filler")]
        undo_words = all(t.kw in ("pichla", "entry", "tha", "kiya", "undo") or t.cls == "aux" for t in before)
        if before and not (is_cancel and undo_words):
            result = _rejected("cancelled")
        elif not before and (has_pending or not is_cancel):
            result = _rejected("cancelled")
    if result is None and has_pending:
        result = _answer_pending(toks, utterance, today, ctx, copy.deepcopy(pending))
    if result is None:
        result, _d = _fresh(toks, utterance, today, ctx)
    lang = _lang(toks)
    if lang is not None:
        result["lang"] = lang
    return result
