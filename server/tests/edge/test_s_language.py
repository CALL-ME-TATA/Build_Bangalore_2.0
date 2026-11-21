"""S. Language support (docs/EDGE_CASES.md section S, CONTRACT 1.8 and 1.13)."""
from __future__ import annotations

from pathlib import Path

import pytest

from .kit import expect_saved

NLU = Path(__file__).resolve().parents[2] / "nlu"
DATA_SUFFIXES = {".json", ".csv", ".tsv", ".toml", ".yaml", ".yml", ".txt"}


def test_S01_vocabulary_is_kept_in_data_files():
    """A language is added by adding a data file, not by editing code: number words must live in one."""
    holders = []
    for p in NLU.rglob("*"):
        if p.is_file() and p.suffix in DATA_SUFFIXES:
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
            if "hazaar" in text and "sau" in text:
                holders.append(p.name)
    assert holders, "no data file under server/nlu holds the number words (sau, hazaar)"


@pytest.mark.parametrize("text,want", [
    ("Ramesh ji ne 20 diye", ("payment", "ramesh", 20)), ("Ramesh sahab ka 10 udhaar", ("credit", "ramesh", 10)),
    ("Ramesh saab ka 30 udhaar", ("credit", "ramesh", 30)), ("Sharma ji ka 50 udhaar", ("credit", "sharma", 50)),
])
def test_S03_ji_and_sahab_are_dropped_before_matching(shop, text, want):
    shop.seed(("ramesh", "credit", 100), ("sharma", "credit", 100))
    expect_saved(shop.say(text), want, shop=shop)


@pytest.mark.parametrize("text,want", [
    ("Ramesh ka three forty udhaar likh do", ("credit", "ramesh", 340)),
    ("Ramesh ne five hundred rupaye diye", ("payment", "ramesh", 500)),
    ("Sunita ko do sau fifty udhaar", ("credit", "sunita", 250)),
    ("Sunita ne paanch sau rupees diye", ("payment", "sunita", 500)),
])
def test_S04_mixed_language_sentence_is_one_parser(rs, text, want):
    expect_saved(rs.say(text), want, shop=rs)
