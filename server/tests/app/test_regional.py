"""Kannada / Marathi / Tamil sessions (app/regional.py) with a fake LLM."""
from __future__ import annotations

from app.pipeline import Pipeline, SessionState, default_parse
from app.regional import Regional, numbers

from .conftest import fake_nw


def make(ledger, settings, parser, replies):
    def chat(system, user, max_tokens):
        if "translate a" in system:  # input to Hinglish
            return {"ರಮೇಶ್ 340 ಸಾಲ": "ramesh ka 340 udhaar", "ಹೌದು": "haan"}.get(user, "NONE")
        return replies(user)
    p = Pipeline(ledger, settings, parse=default_parse, number_to_words=fake_nw)  # the real rules
    p.regional = Regional(chat)
    s = SessionState(session_id="sesskn001")
    s.lang, s.disclosed = "kn", True
    return p, s


def test_kannada_turn_is_translated_read_back_and_answered_in_kannada(ledger, settings, parser):
    p, s = make(ledger, settings, parser, lambda text: "ಕನ್ನಡ: " + text)
    t = p.run_turn(s, "ರಮೇಶ್ 340 ಸಾಲ")
    assert t.status == "needs_clarification" and t.reply_text.startswith("ಕನ್ನಡ:")  # read back before saving
    assert t.lang == "kn" and t.message(0)["lang"] == "en" and s.lang == "kn"
    t = p.run_turn(s, "ಹೌದು")
    assert t.status == "ok" and t.entries and t.entries[0]["amount"] == 340


def test_a_translation_that_changes_a_number_is_not_spoken(ledger, settings, parser):
    p, s = make(ledger, settings, parser, lambda text: text.replace("340", "430"))
    p.run_turn(s, "ರಮೇಶ್ 340 ಸಾಲ")  # new customer question (no number)
    t = p.run_turn(s, "ಹೌದು")  # saved: the reply states ₹340
    assert "340" in t.reply_text and "430" not in t.reply_text  # the English reply, not the wrong number


def test_numbers_helper():
    assert numbers("₹1,250 aur 340") == numbers("340 ... ₹1250")


def test_native_digits_count_as_the_same_number():
    from app.regional import ascii_digits
    assert numbers("रमेशसाठी ६०० रुपयांचा क्रेडिट") == numbers("Added ₹600 credit")
    assert ascii_digits("₹೧,೨೫೦ · ௩௪௦") == "₹1,250 · 340"


def test_marathi_reply_with_devanagari_digits_is_spoken_in_marathi(ledger, settings, parser):
    p, s = make(ledger, settings, parser, lambda text: text.replace("340", "३४०").replace("Ramesh", "रमेश"))
    p.run_turn(s, "ರಮೇಶ್ 340 ಸಾಲ")
    t = p.run_turn(s, "ಹೌದು")
    assert "रमेश" in t.reply_text and "340" in t.reply_text, t.reply_text  # translated, digits shown as 340
