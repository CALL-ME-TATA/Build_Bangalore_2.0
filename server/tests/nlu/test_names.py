"""nlu.names: customer keys, tags and phonetic matching keys (CONTRACT 1.8)."""
import pytest

from nlu.names import name_key, phonetic_key, split_name, tag_matches


@pytest.mark.parametrize("text,key", [
    ("Ramesh", "ramesh"),
    ("RAMESH", "ramesh"),
    ("  Ramesh  ", "ramesh"),
    ("Sharma ji", "sharma"),
    ("Ramesh bhai", "ramesh"),
    ("Sunita didi", "sunita"),
    ("Mohan uncle", "mohan"),
    ("Gupta saab", "gupta"),
    ("Seth Mohan", "mohan"),
    ("Ramesh chai wale", "ramesh"),
    ("Ramesh gali number 3", "ramesh"),
    ("Ramesh Kumar", "ramesh kumar"),
    ("Bhaiyalal", "bhaiyalal"),  # honorifics are only dropped as separate words
    ("रमेश", "ramesh"),
    ("सुनीता", "sunita"),
    ("मोहन", "mohan"),
    ("गीता", "gita"),
    ("कमला", "kamla"),
    ("लक्ष्मी", "lakshmi"),
    ("शर्मा जी", "sharma"),
    ("रमेश चाय वाले", "ramesh"),
    ("", ""),
])
def test_name_key(text, key):
    assert name_key(text) == key


@pytest.mark.parametrize("text,key,tags", [
    ("Ramesh chai wale", "ramesh", ["chai wale"]),
    ("Ramesh chai wala", "ramesh", ["chai wale"]),
    ("doodh wale Ramesh", "ramesh", ["doodh wale"]),
    ("Ramesh gali number 3", "ramesh", ["gali number 3"]),
    ("Ramesh gali number teen", "ramesh", ["gali number 3"]),
    ("Ramesh gali 3", "ramesh", ["gali 3"]),
    ("Sharma ji", "sharma", []),
])
def test_split_name(text, key, tags):
    assert split_name(text) == (key, tags)


@pytest.mark.parametrize("a,b", [
    ("suneeta", "sunita"),
    ("sunitaa", "sunita"),
    ("geeta", "gita"),
    ("shivkumaar", "shivkumar"),
    ("noor", "nur"),
    ("pappu", "papu"),
    ("rawi", "ravi"),
])
def test_phonetic_key_folds_variants(a, b):
    assert phonetic_key(a) == phonetic_key(b)


@pytest.mark.parametrize("a,b", [
    ("ramesh", "suresh"),
    ("ramesh", "mahesh"),
    ("satish", "sathish"),  # th is kept
    ("sadhna", "sadna"),  # dh is kept
    ("shanti", "santi"),  # sh is kept
])
def test_phonetic_key_keeps_distinct_names(a, b):
    assert phonetic_key(a) != phonetic_key(b)


@pytest.mark.parametrize("spoken,stored,ok", [
    ("chai wale", "chai wale", True),
    ("chai wala", "chai wale", True),
    ("chai", "chai wale", True),
    ("chay wale", "chai wale", True),
    ("gali 3", "gali number 3", True),
    ("gali number teen", "gali number 3", True),
    ("doodh wale", "chai wale", False),
    ("gali number 4", "gali number 3", False),
    ("", "chai wale", False),
])
def test_tag_matches(spoken, stored, ok):
    assert tag_matches(spoken, stored) is ok


def test_non_string_inputs_are_safe():
    assert name_key(None) == ""  # type: ignore[arg-type]
    assert phonetic_key(None) == ""  # type: ignore[arg-type]
