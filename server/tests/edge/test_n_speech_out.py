"""N. Text-to-speech and readback (docs/EDGE_CASES.md section N, CONTRACT 3.1, 3.3, 5 and 5.1)."""
from __future__ import annotations

import re
import time

import pytest

from nlu.speak import number_to_words

from .kit import expect_ask, expect_saved
from .scenarios import SCENARIOS

DISCLOSURE_HI = "Namaste! Main KhataVaani hoon, ek AI sahayak."


def words(text: str) -> int:
    return len(text.replace(DISCLOSURE_HI, "").split())


@pytest.mark.parametrize("amount", [430, 1250])
def test_N01_amounts_are_spoken_as_words(rs, amount):
    t = rs.say(f"Ramesh ka {amount} udhaar")
    assert not re.search(r"[0-9]", t.speak_text), f"digits in the text sent to speech: {t.speak_text!r}"
    assert number_to_words(amount, "deva") in t.speak_text, t.describe()


def test_N01_five_lakh_is_spoken_as_words_in_the_question_and_in_the_readback(rs):
    q = rs.say("Ramesh ka 5,00,000 udhaar")
    expect_ask(q, "plausibility")
    spoken = number_to_words(500000, "deva")
    assert not re.search(r"[0-9]", q.speak_text) and spoken in q.speak_text, q.describe()
    done = rs.say("haan")
    assert not re.search(r"[0-9]", done.speak_text) and spoken in done.speak_text, done.describe()


@pytest.mark.parametrize("amount,expected", [
    (430, "four hundred thirty"), (1250, "one thousand two hundred fifty"), (500000, "five lakh")])
def test_N01_english_words(amount, expected):
    assert number_to_words(amount, "en") == expected


@pytest.mark.parametrize("name,before,sentence", SCENARIOS, ids=[s[0].replace(" ", "_") for s in SCENARIOS])
def test_N03_every_reply_is_about_twelve_words_or_fewer(rs, name, before, sentence):
    for s in before:
        rs.say(s)
    t = rs.say(sentence)
    assert words(t.reply_text) <= 12, f"{words(t.reply_text)} words: {t.describe()}"


def test_N03_same_name_question_is_short(shop):
    shop.seed(("ramesh", "credit", 100, 0, "chai wale"), ("ramesh", "credit", 100, 0, "gali wale"))
    t = shop.say("Ramesh ka 50 udhaar")
    assert words(t.reply_text) <= 12, t.describe()


def test_N06_reply_language_follows_the_last_utterance(rs):
    english = rs.say("Sunita paid 50")
    assert english.msg.get("lang") == "en" and "Received" in english.reply_text, english.describe()
    hindi = rs.say("Ramesh ka 100 udhaar")
    assert hindi.msg.get("lang") == "hi" and "udhaar" in hindi.reply_text, hindi.describe()
    again = rs.say("Sunita paid 50")
    assert again.msg.get("lang") == "en", again.describe()


def test_N08_the_readback_of_a_save_has_no_balance(rs):
    t = rs.say("Ramesh ka 340 udhaar")
    expect_saved(t, ("credit", "ramesh", 340), shop=rs)
    assert "1340" not in t.reply_text.replace(",", "") and "baaki" not in t.reply_text.lower(), t.describe()
    assert number_to_words(1340, "deva") not in t.speak_text, t.describe()


def test_N08_the_balance_goes_to_the_screen_in_the_result(rs):
    t = rs.say("Ramesh ka 340 udhaar")
    balances = t.msg.get("balances")
    assert balances, "the result message carries no `balances` for the customers the turn touched"
    assert balances[0]["balance"] == 1340 and balances[0]["display"] == "Ramesh", balances


def test_N08_private_mode_keeps_the_answer_off_the_voice(live_stack):
    live_stack.seed_customer("ramesh", credit=440)
    c = live_stack.session(private=True)
    turn = c.text("Ramesh ka total?")
    assert "440" in turn.result["reply_text"], turn.result
    assert turn["frames"] > 0, "the fixed private reply is spoken"
    spoken = " ".join(str(r.get("text")) for r in live_stack.mock_log()["tts_requests"])
    assert number_to_words(440, "deva") not in spoken and "440" not in spoken, spoken


def test_N09_first_reply_of_an_undisclosed_session_carries_the_disclosure(make_shop):
    s = make_shop(disclosed=False)
    s.seed(("ramesh", "credit", 100))
    t = s.say("Ramesh ka 340 udhaar")
    assert "AI" in t.reply_text, t.describe()
    assert t.speak_text.startswith(s.pipeline.greeting(s.state).speak_text), "the spoken text must carry it too"
    s.pipeline.mark_spoken(s.state, t.result)
    t2 = s.say("Ramesh ka 10 udhaar")
    assert "AI" not in t2.reply_text, "the disclosure is spoken once the first reply has been fully sent"


def test_N09_english_session_discloses_in_english(make_shop):
    s = make_shop(disclosed=False)
    s.seed(("ramesh", "credit", 100))
    t = s.say("Ramesh took 50 on credit")
    assert "AI" in t.reply_text and "assistant" in t.reply_text.lower(), t.describe()


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_N09_every_session_greeting_discloses(live_stack, lang):
    for _ in range(2):
        c = live_stack.session(lang=lang, greet=False)
        greeting = c.collect(min_turn=0, timeout=15)
        assert greeting.result["action"] == "greeting" and "AI" in greeting.result["reply_text"], greeting.result
        c.close()


def test_N04_a_failed_speech_request_still_delivers_the_result_and_the_entry(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    c = live_stack.session()
    live_stack.mock_script(tts_fail=1, tts_fail_mode="error")
    turn = c.text("Ramesh ne 40 diye")
    assert turn.result["status"] == "ok" and turn.result["reply_text"], turn.result
    assert turn["errors"] and turn["errors"][0]["code"] == "tts_upstream", turn["msgs"]
    assert live_stack.balance("ramesh") == 60
    after = c.text("Ramesh ne 10 diye")
    assert after["frames"] > 0, "the next turn must be spoken again"


def test_N04_a_socket_that_dies_before_start_is_retried_once(live_stack):
    live_stack.seed_customer("ramesh", credit=100)
    c = live_stack.session()
    live_stack.mock_script(tts_fail=1, tts_fail_mode="close")
    turn = c.text("Ramesh ne 40 diye")
    assert turn["frames"] > 0 and not turn["errors"], (turn["errors"], turn["types"])


def _clear_tts_memory_cache() -> None:
    from app.gnani.tts import _memory_cache

    _memory_cache.clear()


def test_N07_a_fixed_reply_is_synthesised_once(live_stack):
    _clear_tts_memory_cache()
    live_stack.seed_customer("ramesh", credit=100)
    c = live_stack.session()
    first = c.text("asdf qwer zxcv")
    second = c.text("qwer asdf zxcv")
    assert first["frames"] > 0 and second["frames"] > 0
    requests = [r["text"] for r in live_stack.mock_log()["tts_requests"]]
    rejected = [t for t in requests if requests.count(t) > 1]
    assert not rejected, f"fixed reply requested more than once: {rejected[:1]}"


def test_N07_fixed_phrases_are_generated_ahead(make_live_stack):
    _clear_tts_memory_cache()
    stack = make_live_stack(env={"TTS_PREWARM": "1"})
    deadline, last, stable_since = time.monotonic() + 20, -1, time.monotonic()
    while time.monotonic() < deadline:
        n = len(stack.mock_log()["tts_requests"])
        if n != last:
            last, stable_since = n, time.monotonic()
        elif n > 0 and time.monotonic() - stable_since > 1.5:
            break
        time.sleep(0.2)
    before = len(stack.mock_log()["tts_requests"])
    assert before > 0, "no phrase was synthesised at start-up"
    c = stack.session()
    assert c.ready and c.ready.get("session_id")
    after = len(stack.mock_log()["tts_requests"])
    assert after == before, "the greeting was not served from the cache"


def test_N10_a_large_amount_is_read_back_twice_in_words(rs):
    """The confirmation question is the first readback and the saved reply the second; digits stay on the screen."""
    spoken = number_to_words(500000, "deva")
    first = rs.say("Ramesh ka 5,00,000 udhaar")
    expect_ask(first, "plausibility")
    second = rs.say("haan")
    expect_saved(second, ("credit", "ramesh", 500000), shop=rs)
    for turn in (first, second):
        assert spoken in turn.speak_text and not re.search(r"[0-9]", turn.speak_text), turn.describe()
        assert re.search(r"5,00,000|500000", turn.reply_text), f"digits belong on the screen: {turn.describe()}"
