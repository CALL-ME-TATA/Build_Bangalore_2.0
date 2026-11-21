"""Further number cases: lookup integrity, regressions and the corners of the fraction rules."""
import pytest

from nlu import numbers
from nlu.numbers import WORD_LOOKUP, _build_lookup, parse_number
from nlu.translit import fold, romanise


def test_lookup_builds_without_collisions():
    # _build_lookup raises RuntimeError if any folded spelling maps to two values.
    assert _build_lookup() == WORD_LOOKUP


def test_every_value_1_to_99_has_a_word():
    values = {v for kind, v in WORD_LOOKUP.values() if kind == "n"}
    assert values == set(range(1, 100))


def test_devanagari_table_round_trips_through_the_romaniser():
    for n, text in numbers.DEVA_1_99.items():
        for word in text.split():
            assert parse_number(word) == n, word


@pytest.mark.parametrize("text,value", [
    # older and alternative spellings
    ("unaasi", 79), ("ikhattar", 71), ("pentis", 35), ("tentees", 33), ("sentalis", 47), ("pensath", 65),
    ("chobis", 24), ("chowdah", 14), ("ikyanve", 91), ("ninyanve", 99), ("artees", 38), ("sarsath", 67),
    ("teees", 23), ("baais", 22), ("chalis", 40), ("chaalees", 40),
    # units and bare units
    ("lakh", 100000), ("do lakh pachaas hazaar", 250000), ("ninyaanave lakh", 9900000),
    ("hazar", 1000), ("so", 100),
    # fractions, more forms
    ("paune ek sau", 75), ("sawa ek sau", 125), ("dhai lakh", 250000), ("saade das sau", 1050),
    ("ek hazaar sawa sau", 1125), ("साढ़े पाँच हज़ार", 5500), ("अढ़ाई सौ", 250), ("deedh hazaar", 1500),
    # digits with units, mixed scripts
    ("2 hazaar", 2000), ("1.5 lakh", 150000), ("2.5 hazaar", 2500), ("do hazaar 500", 2500),
    ("teen sau 40", 340), ("दो हज़ार पाँच सौ", 2500), ("तीन सौ chaalis", 340), ("₹ 1,25,000", 125000),
    ("rs 500", 500), ("500 rs", 500), ("पाँच सौ रुपये", 500), ("३,४०", 340), ("1,2,3", 123), ("ek crore", 10000000),
    ("2k", 2000), ("2.5k", 2500), ("four three zero", 430), ("char teen shunya", 430), ("rs500", 500),
    # English
    ("twelve fifty", 1250), ("one hundred", 100), ("ninety nine", 99), ("two thousand three hundred and ten", 2310),
    # zero
    ("0", 0), ("zero", 0), ("shunya", 0),
])
def test_more_forms(text, value):
    assert parse_number(text) == value


@pytest.mark.parametrize("text", [
    "chai",  # "chai wale" is a tag, not 6
    "saade sau", "dedh", "sawa", "paune", "dhai paanch", "saade dhai sau", "dedh sau pachaas",
    "teen chaalis",  # Hindi has no "three forty" shortcut
    "do teen sau", "sau sau", "hazaar sau", "lakh hazaar sau", "do hazaar pandrah sau",
    "340.5", "three five", "saade 300", "2.0005k", "teen chaar",
    "Ramesh 340", "340 udhaar", None, 340,
])
def test_not_one_whole_amount(text):
    assert parse_number(text) is None


def test_fold_keeps_the_distinctions_the_contract_names():
    assert fold("saath") != fold("saat")
    assert fold("teis") != fold("tees")
    assert fold("pachaasi") != fold("pachaas")


def test_romaniser_schwa_deletion():
    assert romanise("रमेश") == "ramesh"
    assert romanise("कितना") == "kitnaa"
    assert romanise("बहत्तर") == "bahattar"
    assert romanise("परसों") == "parson"
    assert romanise("सुनीता", long_vowels=False) == "sunita"
