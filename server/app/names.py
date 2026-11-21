"""Display form of a customer key."""
from __future__ import annotations

# Connecting words of relation keys.
CONNECTORS = {"ki", "ka", "ke"}


def display_name(key: str) -> str:
    """Capitalise the name words of a lowercase key.

    In a relation key the connecting word (ki / ka / ke) and the relation word after it stay lower case:
    "ramesh ki biwi" becomes "Ramesh ki biwi".
    """
    words = key.split()
    out = []
    relation = False
    for i, w in enumerate(words):
        if i > 0 and w.lower() in CONNECTORS:
            relation = True
        out.append(w.lower() if relation else w[:1].upper() + w[1:])
    return " ".join(out)


class SpokenName(str):
    """A display name that is spoken differently (the customer's optional `say` spelling).

    It formats as the display name; `spoken(name)` returns the pronunciation for text-to-speech.
    """

    say: str

    def __new__(cls, text: str, say: str) -> "SpokenName":
        obj = super().__new__(cls, text)
        obj.say = say
        return obj


def spoken(name: str) -> str:
    """The text-to-speech form of a name: its `say` spelling when it has one, else the name itself."""
    return getattr(name, "say", None) or str(name)
