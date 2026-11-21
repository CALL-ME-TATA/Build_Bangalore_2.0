"""M. Speech-to-text behaviour (docs/EDGE_CASES.md section M, CONTRACT 3.3 and 4).

The session tests run the real app against the mock Gnani server. Cases that need recordings, a browser or a
person (M04, M05, M12 to M16) are listed as manual in docs/EDGE_REPORT.md.
"""
from __future__ import annotations

import time

import pytest

from .kit import expect_nothing_saved, expect_reject
from .wskit import pcm_audio


@pytest.fixture
def rs_live(live_stack):
    live_stack.seed_customer("ramesh", credit=1000)
    live_stack.seed_customer("sunita", credit=1000)
    return live_stack


def _spoken_reply(turn) -> str:
    return turn.result["reply_text"].lower()


def test_M01_empty_transcript_saves_nothing_and_says_so(rs_live):
    c = rs_live.session()
    n = rs_live.count()
    turn = c.speak("")
    assert rs_live.count() == n
    assert turn.result["entries"] == [], turn.result
    text = _spoken_reply(turn)
    assert "samajh nahi aaya" in text and "dobara boliye" in text, turn.result
    assert turn["audio_start"] is not None, "the reply must be spoken"


def test_M02_button_held_in_silence_says_nothing_heard(rs_live):
    c = rs_live.session()
    n = rs_live.count()
    turn = c.speak({"silence": True}, audio_ms=1200)
    assert rs_live.count() == n
    assert "kuch sunai nahi diya" in _spoken_reply(turn), turn.result
    assert turn["audio_start"] is not None, "the silence reply must be spoken"


def test_M03_recording_under_half_a_second_is_ignored(rs_live):
    c = rs_live.session()
    n = rs_live.count()
    turn = c.speak("Ramesh ka 340 udhaar", audio_ms=300)
    assert rs_live.count() == n
    assert turn.result["action"] == "none" and turn["audio_start"] is None, turn.result
    assert turn["frames"] == 0, "nothing may be spoken for an accidental press"


def test_M06_only_the_final_transcript_is_parsed(rs_live):
    c = rs_live.session()
    turn = c.speak({"partials": ["Ramesh ka 34 udhaar", "Ramesh ka 340 udhaar"], "text": "Ramesh ka 3400 udhaar"})
    amounts = [r["amount"] for r in rs_live.rows() if r["customer"] == "ramesh" and r["session_id"] != "seed"]
    assert amounts == [3400], (amounts, turn.result)
    finals = [m for m in turn.of("transcript") if m.get("final")]
    assert len(finals) == 1 and finals[0]["text"] == "Ramesh ka 3400 udhaar", turn["msgs"]
    assert turn.of("transcript")[-1]["final"] is True


def test_M07_audio_over_30_seconds_is_cut_with_a_message(rs_live):
    c = rs_live.session()
    n = rs_live.count()
    turn = c.speak("Ramesh ka 340 udhaar", audio_ms=31_000, realtime=False)
    assert rs_live.count() == n, "a cut turn must save nothing"
    assert "lamba" in _spoken_reply(turn) or "too long" in _spoken_reply(turn), turn.result


def test_M09_no_final_transcript_gives_the_failure_reply(rs_live):
    c = rs_live.session()
    n = rs_live.count()
    t0 = time.monotonic()
    turn = c.speak({"no_transcript": True}, audio_ms=800)
    assert time.monotonic() - t0 < 9, "the turn must give up within about 5 seconds of `end`"
    assert rs_live.count() == n
    assert turn.result["status"] == "rejected" and "dobara boliye" in _spoken_reply(turn), turn.result


def test_M10_overlapping_requests_are_each_saved_at_most_once(rs_live):
    c = rs_live.session()
    rs_live.mock_script(transcripts=["Ramesh ne 11 diye", "Sunita ne 22 diye"], stt_delay_ms=400)
    audio = pcm_audio(800)
    for _ in range(2):
        c.send({"type": "start", "mode": "ptt"})
        for i in range(0, len(audio), 640):
            c.ws.send(audio[i:i + 640])
            time.sleep(0.005)
        c.send({"type": "end"})
        time.sleep(0.1)  # a quick second press while the first turn is still being transcribed
    results, quiet_since = [], time.monotonic()
    while time.monotonic() - quiet_since < 2.5:
        try:
            msg = c.recv(0.5)
        except TimeoutError:
            continue
        quiet_since = time.monotonic()
        if isinstance(msg, dict) and msg["type"] == "result":
            results.append(msg)
    saved = [(r["customer"], r["amount"]) for r in rs_live.rows() if r["session_id"] != "seed" and r["kind"] == "payment"]
    assert saved.count(("ramesh", 11)) <= 1 and saved.count(("sunita", 22)) == 1, (saved, results)


def test_M11_nonsense_and_other_languages_are_rejected(rs):
    for text in ["asdf qwer zxcv", "bonjour comment allez vous", "ನಮಸ್ಕಾರ ಹೇಗಿದ್ದೀರಾ", "the weather is nice today"]:
        t = rs.say(text)
        expect_reject(t, ("not_ledger", "invalid_number"))


def test_M17_three_forty_by_voice(rs_live):
    c = rs_live.session()
    turn = c.speak("Ramesh ka three forty udhaar")
    entry = turn.result["entries"][0]
    assert (entry["kind"], entry["amount"], entry["customer"]["display"]) == ("credit", 340, "Ramesh"), turn.result


def test_M18_five_hundred_payment_by_voice(rs_live):
    c = rs_live.session()
    turn = c.speak("Sunita ne five hundred diya")
    entry = turn.result["entries"][0]
    assert (entry["kind"], entry["amount"], entry["customer"]["display"]) == ("payment", 500, "Sunita"), turn.result


@pytest.mark.parametrize("text", [
    "Ramesh ne 500 paisa diya", "Ramesh ne 500 paise diye", "Ramesh ne 500 rupaye diye",
    "Ramesh ne rs 500 diye", "Ramesh ne ₹500 diye"])
def test_M19_every_currency_word_is_recognised(rs, text):
    t = rs.say(text)
    assert t.status == "ok" and [(r["kind"], r["amount"]) for r in t.saved] == [("payment", 500)], t.describe()


def test_M08_a_dropped_socket_and_a_resend_does_not_duplicate_the_entry(rs_live):
    a = rs_live.session()
    first = a.text("Ramesh ne 40 diye", utt_id="utt-m08")
    assert first.result["status"] == "ok"
    sid, last_turn = a.session_id, a.turn
    a.close()
    b = rs_live.session(resume=sid)
    assert b.ready.get("last_turn_id") == last_turn, b.ready
    again = b.text("Ramesh ne 40 diye", utt_id="utt-m08")
    assert again.result.get("duplicate") is True, again.result
    assert rs_live.balance("ramesh") == 960
