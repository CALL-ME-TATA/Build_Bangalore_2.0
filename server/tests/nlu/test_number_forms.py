"""Number forms the hackathon brief names: "teen sau chaalis", "340" or "three-forty", in any script.

Specification for nlu.numbers.parse_number (docs/CONTRACT.md section 1.3). Add cases; never weaken them.
"""
import pytest

from nlu.numbers import parse_number

DIGITS = {
    "340": 340,
    "1,500": 1500,
    "1,25,000": 125000,
    "₹340": 340,
    "Rs 340": 340,
    "Rs. 340": 340,
    "340/-": 340,
    "340 rupaye": 340,
    "३४०": 340,
}

HINDI_ROMAN = {
    "teen sau chaalis": 340,
    "teen sau chalis": 340,
    "tin sau chalis": 340,
    "chaar sau tees": 430,
    "panch sau": 500,
    "chhah sau": 600,
    "che sau": 600,
    "aath sau": 800,
    "nau sau": 900,
    "ek sau": 100,
    "hazaar": 1000,
    "ek hazaar": 1000,
    "hajar": 1000,
    "do hazaar paanch sau": 2500,
    "do sau pachaas": 250,
    "ek lakh": 100000,
    "pandrah sau": 1500,
    "gyarah sau": 1100,
    "teen sau rupaye": 300,
}

OLD_ORACLE_SPELLINGS = {
    "unatees": 29,
    "unataalees": 39,
    "pachhattar": 75,
    "satattar": 77,
    "athattar": 78,
    "unnyaasi": 79,
    "athaasi": 88,
    "nawaasi": 89,
}

FRACTIONS = {
    "sava sau": 125,
    "derh sau": 150,
    "deedh sau": 150,
    "dhaai sau": 250,
    "saadhe teen sau": 350,
    "sadhe teen sau": 350,
    "paune hazaar": 750,
    "saade paanch hazaar": 5500,
    "sawa lakh": 125000,
    "dedh lakh": 150000,
    "do hazaar saade teen sau": 2350,
}

DEVANAGARI = {
    "तीन सौ चालीस": 340,
    "दो सौ": 200,
    "पचास": 50,
    "डेढ़ सौ": 150,
    "ढाई सौ": 250,
    "साढ़े तीन सौ": 350,
    "सवा दो सौ": 225,
    "पौने दो सौ": 175,
    "एक हज़ार पाँच सौ": 1500,
    "एक हजार पांच सौ": 1500,
}

ENGLISH = {
    "three hundred forty": 340,
    "three hundred and forty": 340,
    "three forty": 340,
    "three-forty": 340,
    "three forty five": 345,
    "two fifty": 250,
    "seven fifty": 750,
    "five hundred": 500,
    "fifteen hundred": 1500,
    "one thousand five hundred": 1500,
    "two thousand": 2000,
    "twenty five": 25,
    "one lakh": 100000,
}

NOT_A_WHOLE_AMOUNT = [
    "saade ek sau",
    "saade do sau",
    "dedh teen sau",
    "sawa dedh sau",
    "saade teen",
    "dhai",
    "do sau hazaar",
    "namaste",
    "udhaar",
    "",
]


def _cases(*tables):
    return [(text, value) for table in tables for text, value in table.items()]


@pytest.mark.parametrize("text,expected", _cases(DIGITS, HINDI_ROMAN, OLD_ORACLE_SPELLINGS, FRACTIONS, DEVANAGARI, ENGLISH))
def test_number_form(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", NOT_A_WHOLE_AMOUNT)
def test_not_a_whole_amount(text):
    assert parse_number(text) is None


def test_confusable_words_stay_distinct():
    assert parse_number("saat") == 7
    assert parse_number("saath") == 60
    assert parse_number("tees") == 30
    assert parse_number("teis") == 23
    assert parse_number("pachaas") == 50
    assert parse_number("pachaasi") == 85
    assert parse_number("satrah") == 17
    assert parse_number("sattar") == 70
