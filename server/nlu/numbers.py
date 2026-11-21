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

from .translit import fold, is_devanagari, normalise, romanise_word

# Roman spellings of 1..99. The first entry is the canonical spelling (used by nlu.speak); the rest are
# variants. Older or alternative transcriptions are listed explicitly; the fold covers the rest.
_ROMAN_1_99 = {
    1: "ek aik", 2: "do doh", 3: "teen tin theen", 4: "chaar", 5: "paanch paach pach",
    6: "chhah chhe chah che chheh", 7: "saat", 8: "aath", 9: "nau nao",
    10: "das dus", 11: "gyarah gyaarah giyarah gyarha igyarah", 12: "baarah barha",
    13: "terah terha", 14: "chaudah chaudha", 15: "pandrah pandarah pandrha", 16: "solah solha",
    17: "satrah satrha", 18: "athaarah atharah athara", 19: "unnees",
    20: "bees", 21: "ikkees ekkis", 22: "baaees baais", 23: "teis teees tais teyis",
    24: "chaubees", 25: "pachchees pacchis", 26: "chhabbees", 27: "sattaees sattais",
    28: "atthaees athaais", 29: "untees unatees unatis",
    30: "tees", 31: "ikattees ikatees iktees ekatis", 32: "battees", 33: "taintees", 34: "chauntees",
    35: "paintees", 36: "chhattees", 37: "saintees", 38: "adtees", 39: "untaalees unataalees unataalis",
    40: "chaalis chaalees", 41: "iktaalees ektalis", 42: "bayaalees byalis", 43: "taintaalees",
    44: "chavaalees chauvaalees", 45: "paintaalees", 46: "chhiyaalees chhyalis", 47: "saintaalees",
    48: "adtaalees", 49: "unchaas unanchas", 50: "pachaas pachaash",
    51: "ikyaavan ikkyavan ikavan", 52: "baavan", 53: "tirpan tirepan tirapan trepan", 54: "chauvan chavan",
    55: "pachpan pachapan", 56: "chhappan", 57: "sattaavan", 58: "atthaavan", 59: "unsath unasath unsaath",
    60: "saath", 61: "iksath ikasath eksath", 62: "baasath", 63: "tirsath tiresath", 64: "chaunsath",
    65: "painsath", 66: "chhiyaasath", 67: "sadsath", 68: "adsath", 69: "unhattar unahattar",
    70: "sattar", 71: "ikahattar ikhattar ekhattar", 72: "bahattar", 73: "tihattar tehattar",
    74: "chauhattar", 75: "pachahattar pachattar pachhattar", 76: "chhihattar",
    77: "satahattar satattar sathattar", 78: "athahattar athattar athhattar",
    79: "unyaasi unnyaasi unaasi", 80: "assi aasi", 81: "ikyaasi ikaasi", 82: "bayaasi byaasi",
    83: "tiraasi", 84: "chauraasi", 85: "pachaasi", 86: "chhiyaasi", 87: "sattaasi sataasi",
    88: "atthaasi athaasi", 89: "navaasi nawaasi",
    90: "nabbe navve nabbay nabe", 91: "ikyaanave ikyanbe ikaanave", 92: "baanave banbe",
    93: "tiraanave tiranbe", 94: "chauraanave", 95: "pachaanave pachanbe", 96: "chhiyaanave",
    97: "sattaanave", 98: "atthaanave", 99: "ninyaanave ninanve",
}

# Standard Devanagari spellings (the first is used by nlu.speak), then alternatives.
DEVA_1_99 = {
    1: "एक", 2: "दो", 3: "तीन", 4: "चार", 5: "पाँच पांच", 6: "छह छः छे", 7: "सात", 8: "आठ", 9: "नौ",
    10: "दस", 11: "ग्यारह", 12: "बारह", 13: "तेरह", 14: "चौदह", 15: "पंद्रह पन्द्रह", 16: "सोलह",
    17: "सत्रह", 18: "अठारह", 19: "उन्नीस", 20: "बीस",
    21: "इक्कीस", 22: "बाईस", 23: "तेईस", 24: "चौबीस", 25: "पच्चीस", 26: "छब्बीस", 27: "सत्ताईस",
    28: "अट्ठाईस", 29: "उनतीस", 30: "तीस",
    31: "इकतीस", 32: "बत्तीस", 33: "तैंतीस", 34: "चौंतीस", 35: "पैंतीस", 36: "छत्तीस", 37: "सैंतीस",
    38: "अड़तीस", 39: "उनतालीस", 40: "चालीस",
    41: "इकतालीस", 42: "बयालीस", 43: "तैंतालीस", 44: "चवालीस चौवालीस", 45: "पैंतालीस", 46: "छियालीस",
    47: "सैंतालीस", 48: "अड़तालीस", 49: "उनचास", 50: "पचास",
    51: "इक्यावन", 52: "बावन", 53: "तिरपन तिरेपन", 54: "चौवन", 55: "पचपन", 56: "छप्पन", 57: "सत्तावन",
    58: "अट्ठावन", 59: "उनसठ", 60: "साठ",
    61: "इकसठ", 62: "बासठ", 63: "तिरसठ तिरेसठ", 64: "चौंसठ", 65: "पैंसठ", 66: "छियासठ", 67: "सड़सठ",
    68: "अड़सठ", 69: "उनहत्तर", 70: "सत्तर",
    71: "इकहत्तर", 72: "बहत्तर", 73: "तिहत्तर", 74: "चौहत्तर", 75: "पचहत्तर", 76: "छिहत्तर",
    77: "सतहत्तर", 78: "अठहत्तर", 79: "उन्यासी उनासी उनयासी", 80: "अस्सी",
    81: "इक्यासी", 82: "बयासी", 83: "तिरासी", 84: "चौरासी", 85: "पचासी", 86: "छियासी", 87: "सत्तासी",
    88: "अट्ठासी", 89: "नवासी", 90: "नब्बे",
    91: "इक्यानवे", 92: "बानवे", 93: "तिरानवे", 94: "चौरानवे", 95: "पचानवे", 96: "छियानवे",
    97: "सत्तानवे", 98: "अट्ठानवे", 99: "निन्यानवे",
}

_UNITS = {
    100: "sau so sao sow sou सौ",
    1000: "hazaar hazar hajar hajaar hazzar hazaaar हज़ार हजार",
    100000: "lakh laakh lac lacs lakhs laakhs लाख",
}
DEVA_UNITS = {100: "सौ", 1000: "हज़ार", 100000: "लाख"}

_FRACTIONS = {
    "sawa": "sawa sava savaa sawaa सवा",
    "saade": "saade sade saadhe sadhe saarhe sarhe saadey sadey साढ़े साढे",
    "paune": "paune paun poune pone paone पौने",
    "dedh": "dedh derh deedh deerh dairh daidh deidh डेढ़ डेढ",
    "dhai": "dhai dhaai adhai dhayi dhaee arhai arhaai ढाई अढ़ाई अढाई",
}

ENGLISH_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
ENGLISH_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
ENGLISH_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000}

CURRENCY_WORDS = frozenset(fold(w) for w in (
    "rs rupaye rupay rupaya rupye rupae rupaiye rupaiya rupiya rupiye rupee rupees inr ru "
    "रुपये रुपए रुपया रुपैया रु"
).split() if not is_devanagari(w)) | frozenset(
    fold(romanise_word(w)) for w in "रुपये रुपए रुपया रुपैया रु".split()
)
ZERO_WORDS = frozenset({"shunya", "sunya", "sifar", "zero", "shoonya"})


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


_DIGITS_RE = re.compile(r"^\d+(?:,\d{2,3})*(?:\.\d+)?$")


def digits_value(token: str) -> Fraction | None:
    """Value of a digit token such as 340, 1,25,000 or 1.5, or None if malformed."""
    if not _DIGITS_RE.match(token):
        return None
    if "," in token:
        groups = token.split(".")[0].split(",")
        # Indian (1,25,000) or Western (125,000) grouping only.
        if len(groups[-1]) != 3 or len(groups[0]) > 3:
            return None
        middle = groups[1:-1]
        if middle and not (all(len(g) == 2 for g in middle) or all(len(g) == 3 for g in middle)):
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
    if any(k == "n" and v == 0 for k, v, _ in items):
        return None
    return value_of_items(items)
