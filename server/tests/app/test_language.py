"""Reply language: every template in English and Hinglish, session language switching, TTS language."""
from __future__ import annotations

import json
from datetime import date

import websockets

from app.gnani.tts import cache_key
from app.pipeline import Pipeline, SessionState
from app.replies import Replier

from .conftest import fake_nw
from .test_session import hello, is_type, of, recv_until

HI = Replier(fake_nw)
EN = HI.with_lang("en")
TODAY = date(2026, 11, 21)


def ev(kind, name, amt, day="2026-11-21", new=False, cid=None):
    return {"kind": kind, "customer": name, "amount": amt, "date": day, "new_customer": new, "customer_id": cid}


def test_english_templates():
    assert EN.lang == "en" and HI.lang == "hi"
    assert EN.disclosure().text == "Hello! I am KhataVaani, an AI assistant."
    assert EN.saved([ev("credit", "Ramesh", 340)], TODAY).text == "Added ₹340 credit for Ramesh."
    assert EN.saved([ev("payment", "Ramesh", 200)], TODAY).text == "Received ₹200 from Ramesh."
    assert EN.saved([ev("payment", "Ramesh", 200, "2026-11-20")], TODAY).text == \
        "Received ₹200 from Ramesh, dated yesterday."
    assert EN.saved([ev("credit", "Ramesh", 200, "2026-11-19")], TODAY).text == \
        "Added ₹200 credit for Ramesh, dated the day before yesterday."
    two = EN.saved([ev("credit", "Ramesh", 340), ev("payment", "Ramesh", 200, "2026-11-20")], TODAY)
    assert two.text == "2 entries: ₹340 credit for Ramesh, and ₹200 received yesterday."
    assert EN.saved([ev("credit", "Ramesh", 5, new=True, cid="c1"), ev("credit", "Ramesh", 6, new=True, cid="c1")],
                    TODAY).text.count("New account for Ramesh.") == 1
    assert EN.amend(ev("payment", "Ramesh", 430)).text == "Corrected: Ramesh, ₹430 payment."
    assert EN.undo(ev("credit", "Ramesh", 340)).text == "Removed the last entry: Ramesh, ₹340 credit."
    assert EN.entry_not_found().text == "No previous entry found."
    assert EN.nothing_to_undo().text == "There is nothing to undo."
    assert EN.nothing_to_amend().text == "There is no earlier entry."
    assert EN.confusable(340, 740).text == "₹340 or ₹740?"
    assert EN.same_name("Ramesh", ["chai wale", ""]).text == "Which Ramesh: chai wale or the first one?"
    assert EN.missing_amount().text == "How many rupees?" and EN.missing_customer().text == "Whose account?"
    assert EN.direction("Ramesh").text == "Did Ramesh pay, or did Ramesh take credit?"
    assert EN.plausibility(60000).text == "₹60,000, are you sure?"
    assert EN.unclear_correction().text == "Say the right amount, or say remove it."
    assert EN.unclear_date().text == "Which day? Say today, yesterday or the day before."
    a, b = {"kind": "credit", "amount": 340}, {"kind": "payment", "amount": 200}
    assert EN.which_entry(a, b).text == "Which entry: ₹340 credit or ₹200 payment?"
    assert EN.undo_check("Ramesh", 340, "credit").text == \
        "I can only remove the last entry: Ramesh, ₹340 credit. Remove it?"
    assert EN.replace_check().text == "Replace the last entry with this one?"
    assert EN.cancelled().text == "Okay, nothing was saved."
    assert EN.rejected().text == "Sorry, I did not understand. Please say it again."
    assert EN.balance("Ramesh", 340).text == "Ramesh owes ₹340."
    assert EN.balance("Ramesh", 0).text == "Ramesh's account is settled."
    assert EN.balance("Ramesh", 0, has_entries=False).text == "Ramesh has no entries."
    assert EN.balance("Ramesh", -50).text == "Ramesh has paid ₹50 extra."
    assert EN.unknown_customer("Mohan").text == "No account found for Mohan."
    assert EN.credit_total(500).text == "Today ₹500 was given on credit."
    assert EN.credit_total(0).text == "No credit given today."
    assert EN.payment_total(500).text == "Today ₹500 was received."
    assert EN.payment_total(0).text == "Nothing received today."
    assert EN.credit_total(500, "yesterday").text == "Yesterday ₹500 was given on credit."
    s = EN.daily_summary({"count": 2, "credit": 340, "payment": 200, "top": ("Ramesh", 140)})
    assert s.text == "Today: ₹340 credit, ₹200 received. Highest due: Ramesh, ₹140."
    assert EN.daily_summary({"count": 0}).text == "No entries yet today."
    assert EN.top_dues([("A", 3), ("B", 2)]).text == "Highest dues: A ₹3, B ₹2."
    assert EN.top_dues([]).text == "Nobody owes anything."
    assert EN.upstream_failure().text == "Network problem, please say it again."


def test_english_speech_is_plain_english_with_number_words():
    r = EN.saved([ev("credit", "Ramesh", 340)], TODAY)
    assert r.speak == "Added <340> rupees credit for Ramesh." and "₹" not in r.speak
    assert not any("ऀ" <= ch <= "ॿ" for ch in r.speak)
    assert EN.disclosure().speak == "Hello! I am KhataVaani, an AI assistant."
    assert EN.balance("Ramesh", 340).speak == "Ramesh owes <340> rupees."


def test_english_falls_back_to_digits_when_words_unsupported():
    def only_hindi(n, script="deva"):
        if script == "en":
            raise ValueError("unsupported")
        return "x"

    assert Replier(only_hindi).with_lang("en").balance("Ramesh", 340).speak == "Ramesh owes 340 rupees."


def test_new_questions_in_hinglish():
    a, b = {"kind": "credit", "amount": 340}, {"kind": "payment", "amount": 200}
    assert HI.which_entry(a, b).text == "Kaunsi entry: ₹340 udhaar ya ₹200 jama?"
    assert HI.undo_check("Ramesh", 340, "credit").text == \
        "Sirf pichli entry hata sakta hoon: Ramesh, ₹340 udhaar. Hata doon?"
    assert HI.replace_check().text == "Pichli entry hata kar yeh likhoon?"


def test_clarification_dispatch_new_questions_both_languages():
    cands = {"reason": "unclear_correction", "candidates": [{"kind": "credit", "amount": 340},
                                                            {"kind": "payment", "amount": 200}]}
    assert HI.clarification(cands).text == "Kaunsi entry: ₹340 udhaar ya ₹200 jama?"
    assert EN.clarification(cands).text == "Which entry: ₹340 credit or ₹200 payment?"
    undo = {"reason": "unclear_correction", "pending": {"action": "undo", "events": [
        {"kind": "credit", "customer": "ramesh", "amount": 340}]}}
    assert EN.clarification(undo).text.startswith("I can only remove the last entry: Ramesh")
    assert HI.clarification(undo).text.startswith("Sirf pichli entry hata sakta hoon: Ramesh")
    replace = {"reason": "unclear_correction", "pending": {"action": "amend", "events": [
        {"kind": "payment", "customer": "sunita", "amount": 100}]}}
    last = {"kind": "credit", "customer": "ramesh", "amount": 340}
    assert EN.clarification(replace, last=last).text == "Replace the last entry with this one?"
    # Only a whole new entry (customer, amount and kind all different) gets the replace wording (1.16).
    assert EN.clarification(replace).text == "Say the right amount, or say remove it."
    same_amount = dict(last, amount=100)
    assert EN.clarification(replace, last=same_amount).text == "Say the right amount, or say remove it."
    plain = {"reason": "unclear_correction", "pending": {"action": "amend", "events": []}}
    assert EN.clarification(plain).text == "Say the right amount, or say remove it."


def test_session_language_switches_with_result_lang_and_is_kept_otherwise(pipeline, state):
    pipeline.mark_spoken(state, pipeline.greeting(state))
    t = pipeline.run_turn(state, "ramesh ka 340 udhaar")
    assert t.lang == "hi" and t.reply_text.endswith("₹340 udhaar likh diya.")
    t = pipeline.run_turn(state, "sunita paid 150")
    assert t.lang == "en" and t.reply_text == "New account for Sunita. Received ₹150 from Sunita."
    assert state.lang == "en"
    t = pipeline.run_turn(state, "yes")  # no `lang` in the result: the session keeps English
    assert t.lang == "en" and t.reply_text == "Sorry, I did not understand. Please say it again."
    assert t.message(3)["lang"] == "en"
    t = pipeline.run_turn(state, "ramesh ka 340 udhaar")
    assert t.lang == "hi" and state.lang == "hi"


def test_english_greeting_and_disclosure_prefix(pipeline):
    state = SessionState(session_id="s1", lang="en")
    g = pipeline.greeting(state)
    assert g.reply_text == "Hello! I am KhataVaani, an AI assistant." and g.lang == "en"
    t = pipeline.run_turn(state, "sunita paid 150")  # greeting was not marked as spoken: prefix again, in English
    assert t.reply_text.startswith("Hello! I am KhataVaani, an AI assistant. ")


def test_cache_key_includes_tts_language(settings):
    assert cache_key(settings, "x", "hi") != cache_key(settings, "x", "en")
    assert cache_key(settings, "x", "hi") == cache_key(settings, "x")


async def test_english_hello_greets_in_english_with_en_in(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        msgs = await hello(ws, lang="en")
        result = of(msgs, "result")[0]
        assert result["reply_text"] == "Hello! I am KhataVaani, an AI assistant." and result["lang"] == "en"
        assert fake_gnani.tts_requests[0]["language"] == "en-IN"
        await ws.send(json.dumps({"type": "text", "text": "sunita paid 150"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=1))
        r = of(msgs, "result")[0]
        assert r["lang"] == "en" and r["reply_text"] == "New account for Sunita. Received ₹150 from Sunita."
        assert fake_gnani.tts_requests[-1]["language"] == "en-IN"
        assert "<150> rupees" in fake_gnani.tts_requests[-1]["text"]
        await ws.send(json.dumps({"type": "text", "text": "ramesh ka 340 udhaar"}))
        msgs = await recv_until(ws, is_type("audio_end", turn_id=2))
        assert of(msgs, "result")[0]["lang"] == "hi"
        assert fake_gnani.tts_requests[-1]["language"] == "hi-IN"


async def test_hindi_hello_is_default(server, fake_gnani):
    async with websockets.connect(server.url) as ws:
        msgs = await hello(ws)
        assert of(msgs, "result")[0]["lang"] == "hi"
        assert fake_gnani.tts_requests[0]["language"] == "hi-IN"
