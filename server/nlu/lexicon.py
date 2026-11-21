"""Vocabulary tables, kept as JSON data files in nlu/vocab/ so that words can be added without a code change.

- numbers.json: number words 1..99 (Roman and Devanagari, canonical spelling first), unit words, fractions,
  English number words, currency words.
- keywords.json: every keyword the parser knows, as canonical meaning -> spellings (direction, particles, dates,
  actions, fillers, measure words, first person, pronouns ...). Spellings are folded with `translit.fold`.
- parser.json: relation words, the words that mark English or neither language, auxiliary verb stems, extra
  measure words, out-of-scope words and phrases, hearsay markers, particles.
- names.json: honorifics and kinship words, tag words (wale, gali).

The files are read once at import. Adding a spelling or a language is a data change; the folded lookups are built
from these tables, and the number table raises at import if a new spelling would map to two values.
"""
from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).resolve().with_name("vocab")


def load(name: str) -> dict:
    """The parsed contents of nlu/vocab/<name>.json."""
    with open(_DIR / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)
