"""Sanity checks for the oracle itself. These must pass BEFORE any parser exists."""
from tests.oracle.hindi_numbers import BELOW_100, MAX_N, render, variants


def test_table_covers_1_to_99_with_distinct_words():
    assert sorted(BELOW_100) == list(range(1, 100))
    assert len(set(BELOW_100.values())) == 99


def test_known_renderings():
    assert render(340) == "teen sau chaalees"
    assert render(430) == "chaar sau tees"
    assert render(100) == "ek sau"
    assert render(1500) == "ek hazaar paanch sau"
    assert render(125_000) == "ek lakh pachchees hazaar"
    assert render(MAX_N) == "nau lakh ninyaanave hazaar nau sau ninyaanave"


def test_render_is_injective_on_a_large_sample():
    seen = {render(n): n for n in range(1, 20_000)}
    assert len(seen) == 19_999


def test_variants_include_deck_spelling():
    assert "teen sau chaalis" in variants(render(340))
