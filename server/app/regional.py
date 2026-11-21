"""Kannada, Marathi and Tamil sessions, through the LLM (needs LLM_API_KEY).

The rule parser understands Hinglish and English only. In a regional session:
- each utterance is translated by the LLM into the short Hinglish the parser already reads ("Ramesh ka 340
  udhaar", "haan", "doosra"), then parsed as usual; a new entry from it is always read back before it is saved;
- each reply (written in English by the templates) is translated into the session's language for screen and
  speech. A translation that loses or changes any number falls back to the English reply, so an amount is never
  spoken wrongly.
Speech uses Gnani's kn-IN / mr-IN / ta-IN.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Callable

log = logging.getLogger("khata.regional")

REGIONAL = {"kn": ("kn-IN", "Kannada"), "mr": ("mr-IN", "Marathi"), "ta": ("ta-IN", "Tamil")}
Chat = Callable[[str, str, int], str]  # (system, user, max_tokens) -> text

TO_HINGLISH = """You translate a {name} kirana shopkeeper's spoken sentence into the short Hinglish a rule-based \
udhaar ledger parser reads. Output only the Hinglish, or NONE.
- An entry: "<Name> ka <amount> udhaar" (customer took goods on credit) or "<Name> ne <amount> diye" (customer paid).
- A question: "<Name> ka total kitna hai", "aaj ka hisaab batao", "sabse zyada baaki kiska hai".
- A short answer: haan, nahi, udhaar, jama, pehla, doosra, teesra, koi aur, a name, or a number.
- Corrections and undo: "nahi, <amount>", "undo karo".
Write every amount in digits exactly as said. Keep names as said, in Latin letters. Never invent an amount or a
name. Chit-chat or anything unclear: NONE."""

FROM_ENGLISH = """Translate this shop assistant reply into natural spoken {name}, in {name} script. Keep every number \
exactly as written, in the same digits, with the ₹ sign where it appears. Keep personal names as they are. Output \
only the translation."""


def is_regional(lang: str | None) -> bool:
    return lang in REGIONAL


# Marathi often writes amounts in Devanagari digits (६००), Kannada and Tamil sometimes in their own.
_NATIVE_DIGITS = str.maketrans("०१२३४५६७८९೦೧೨೩೪೫೬೭೮೯௦௧௨௩௪௫௬௭௮௯", "0123456789" * 3)


def ascii_digits(text: str) -> str:
    return text.translate(_NATIVE_DIGITS)


def numbers(text: str) -> list[str]:
    return sorted(re.findall(r"\d+", ascii_digits(text).replace(",", "")))


class Regional:
    def __init__(self, chat: Chat):
        self.chat = chat

    def to_hinglish(self, text: str, lang: str) -> str | None:
        try:
            out = self.chat(TO_HINGLISH.format(name=REGIONAL[lang][1]), text, 60).strip().splitlines()[0].strip()
        except Exception as exc:
            log.warning("regional input failed: %s", type(exc).__name__)
            return None
        return None if not out or out.upper().startswith("NONE") else out.strip('"')

    def reply(self, text: str, lang: str) -> str | None:
        """The reply in `lang`, or None (keep English) when translation fails or a number changed."""
        if not text.strip():
            return None
        return _translate(self, text, lang)


@lru_cache(maxsize=512)
def _cached(chat_id: int, text: str, lang: str) -> str | None:  # keyed by the Regional instance id
    inst = _INSTANCES.get(chat_id)
    if inst is None:
        return None
    try:
        # Native digits become 0-9, so "६००" is checked (and shown) as 600.
        out = ascii_digits(inst.chat(FROM_ENGLISH.format(name=REGIONAL[lang][1]), text, 300).strip())
    except Exception as exc:
        log.warning("regional reply failed: %s", type(exc).__name__)
        return None
    if not out or numbers(out) != numbers(text):
        return None  # a number was lost or changed: the English reply is spoken instead
    return out


_INSTANCES: dict[int, Regional] = {}


def _translate(inst: Regional, text: str, lang: str) -> str | None:
    _INSTANCES[id(inst)] = inst
    return _cached(id(inst), text, lang)
