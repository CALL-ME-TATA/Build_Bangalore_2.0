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


@pytest.mark.parametrize("a,b,same", [
    ("rameysh", "ramesh", True),
    ("suneeta", "sunita", True),
    ("ramesh sharma", "ramesh sharma", True),
    ("sunit", "sunita", False),
    ("kamal", "kamala", False),
    ("rajan", "ranjan", False),
    ("rakesh sharma", "ramesh sharma", False),
    ("ramesh", "ramesh sharma", False),
    ("ramesh", "suresh", False),
    ("", "ramesh", False),
])
def test_same_person(a, b, same):
    from nlu.names import same_person
    assert same_person(a, b) is same
    assert same_person(b, a) is same


def test_honorific_alone_is_a_name_only_when_asked():
    from nlu.names import split_tokens
    assert split_tokens(["chacha"]) == ([], [])
    assert split_tokens(["chacha"], honorific_name=True) == (["chacha"], [])
    assert split_tokens(["lala", "ji"], honorific_name=True) == (["lala"], [])
    assert split_tokens(["sharma", "ji"], honorific_name=True) == (["sharma"], [])
