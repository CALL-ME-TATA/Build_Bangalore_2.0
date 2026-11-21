"""Pipeline behaviour (disclosure, clarification saves nothing) and reply rendering for each template."""
from __future__ import annotations

from datetime import date

from app.replies import Replier, fmt_amount

from .conftest import fake_nw

R = Replier(fake_nw)
TODAY = date(2026, 11, 21)


def test_first_reply_discloses_ai(pipeline, state):
    first = pipeline.run_turn(state, "ramesh ka 340 udhaar")
    assert "ek AI sahayak" in first.reply_text
    assert "एआई" in first.speak_text
    # Until a reply carrying the disclosure has been fully sent, every reply repeats it.
    assert "ek AI sahayak" in pipeline.run_turn(state, "sunita ne 150 diye").reply_text
    pipeline.mark_spoken(state, first)
    second = pipeline.run_turn(state, "sunita ne 150 diye")
    assert "AI sahayak" not in second.reply_text


def test_greeting_is_the_disclosure(pipeline, state):
    g = pipeline.greeting(state)
    pipeline.mark_spoken(state, g)
    assert g.action == "greeting" and g.reply_text == "Namaste! Main KhataVaani hoon, ek AI sahayak."
    assert "AI" not in pipeline.run_turn(state, "ramesh ka 340 udhaar").reply_text


def test_needs_clarification_saves_nothing(pipeline, state, ledger, parser):
    pipeline.mark_spoken(state, pipeline.greeting(state))
    t = pipeline.run_turn(state, "ramesh 340")
    assert t.status == "needs_clarification" and t.question == "Ramesh ne diye, ya Ramesh ko udhaar?"
    assert ledger.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert state.pending["reason"] == "ambiguous_direction"
    t2 = pipeline.run_turn(state, "udhaar")
    assert parser.calls[-1]["ctx"]["pending"]["reason"] == "ambiguous_direction"
    assert t2.status == "ok" and state.pending is None
    assert ledger.balance(ledger.find_customer(key="ramesh")["id"]) == 340


def test_ctx_has_last_event_and_limits(pipeline, state, parser):
    pipeline.run_turn(state, "ramesh ka 340 udhaar")
    pipeline.run_turn(state, "nahi 430")
    ctx = parser.calls[-1]["ctx"]
    assert ctx["last_event"]["amount"] == 340 and ctx["last_event"]["kind"] == "credit"
    assert "age_s" in ctx["last_event"] and ctx["limits"]["confirm_above"] == 50000


def test_amend_undo_entries_and_replies(pipeline, state):
    pipeline.mark_spoken(state, pipeline.greeting(state))
    pipeline.run_turn(state, "ramesh ka 340 udhaar")
    a = pipeline.run_turn(state, "nahi 430")
    assert a.reply_text == "Theek kar diya: Ramesh, ₹430 udhaar."
    assert [e["reversed"] for e in a.entries] == [True, False] and a.entries[1]["amount"] == 430
    u = pipeline.run_turn(state, "undo karo")
    assert u.reply_text == "Pichli entry hata di: Ramesh, ₹430 udhaar."
    assert len(u.entries) == 1 and u.entries[0]["reversed"] is True
    assert pipeline.run_turn(state, "undo karo").reply_text == "Undo karne ke liye kuch nahi hai."


def test_queries(pipeline, state):
    pipeline.mark_spoken(state, pipeline.greeting(state))
    pipeline.run_turn(state, "ramesh ka 340 udhaar")
    assert pipeline.run_turn(state, "ramesh ka total").reply_text == "Ramesh ke ₹340 baaki hain."
    s = pipeline.run_turn(state, "aaj ka hisaab")
    assert s.reply_text == "Aaj ₹340 udhaar gaya, ₹0 jama hue. Sabse zyada baaki: Ramesh, ₹340."
    assert s.entries == []


def test_rejected_reply(pipeline, state):
    pipeline.mark_spoken(state, pipeline.greeting(state))
    t = pipeline.run_turn(state, "kuch bhi")
    assert t.status == "rejected" and t.reply_text == "Maaf kijiye, samajh nahi aaya. Dobara boliye."


def ev(kind, name, amt, day="2026-11-21", new=False):
    return {"kind": kind, "customer": name, "amount": amt, "date": day, "new_customer": new}


def test_reply_templates():
    assert fmt_amount(125000) == "1,25,000" and fmt_amount(340) == "340"
    assert R.disclosure().text == "Namaste! Main KhataVaani hoon, ek AI sahayak."
    assert R.saved([ev("credit", "Ramesh", 340)], TODAY).text == "Ramesh ke khate mein ₹340 udhaar likh diya."
    assert R.saved([ev("payment", "Ramesh", 200)], TODAY).text == "Ramesh se ₹200 mile, jama kar diya."
    assert R.saved([ev("payment", "Ramesh", 200, "2026-11-20")], TODAY).text == "Ramesh se kal ke ₹200 jama kiye."
    assert R.saved([ev("credit", "Ramesh", 200, "2026-11-19")], TODAY).text == "Ramesh ke parso ke ₹200 udhaar likhe."
    two = R.saved([ev("credit", "Ramesh", 340), ev("payment", "Ramesh", 200, "2026-11-20")], TODAY)
    assert two.text == "2 entry likhi: Ramesh ke ₹340 udhaar, kal ke ₹200 jama."
    assert two.speak == "<2> एंट्री लिखी: Ramesh के <340> रुपये उधार, कल के <200> रुपये जमा।"
    mixed = R.saved([ev("credit", "Ramesh", 340), ev("payment", "Sunita", 200)], TODAY)
    assert mixed.text == "2 entry likhi: Ramesh ke ₹340 udhaar, Sunita ke ₹200 jama."
    assert R.saved([ev("credit", "Ramesh", 5, new=True)], TODAY).text.startswith("Naya khata Ramesh. ")
    assert R.amend(ev("payment", "Ramesh", 430)).text == "Theek kar diya: Ramesh, ₹430 jama."
    assert R.undo(ev("credit", "Ramesh", 340)).text == "Pichli entry hata di: Ramesh, ₹340 udhaar."
    assert R.entry_not_found().text == "Pichli entry nahi mili."
    assert R.nothing_to_undo().text == "Undo karne ke liye kuch nahi hai."
    assert R.nothing_to_amend().text == "Pehle koi entry nahi hai."
    assert R.confusable(340, 740).text == "₹340 ya ₹740?"
    assert R.same_name("Ramesh", ["chai wale", ""]).text == "Kaunse Ramesh: chai wale ya pehle wale?"
    assert R.missing_amount().text == "Kitne rupaye?" and R.missing_customer().text == "Kiska khata?"
    assert R.direction("Ramesh").text == "Ramesh ne diye, ya Ramesh ko udhaar?"
    assert R.plausibility(60000).text == "₹60,000, pakka?"
    assert R.unclear_correction().text == "Sahi amount boliye, ya hata do boliye."
    assert R.unclear_date().text == "Kaunsa din? Aaj, kal ya parso boliye."
    assert R.cancelled().text == "Theek hai, entry nahi ki."
    assert R.rejected().text == "Maaf kijiye, samajh nahi aaya. Dobara boliye."
    assert R.upstream_failure().text == "Network mein dikkat hai, dobara boliye."
    assert R.balance("Ramesh", 340).text == "Ramesh ke ₹340 baaki hain."
    assert R.balance("Ramesh", 0).text == "Ramesh ka hisaab barabar hai."
    assert R.balance("Ramesh", 0, has_entries=False).text == "Ramesh ka koi hisaab nahi hai."
    assert R.balance("Ramesh", -50).text == "Ramesh ke ₹50 zyada jama hain."
    assert R.credit_total(500).text == "Aaj ₹500 udhaar gaya."
    assert R.credit_total(0).text == "Aaj koi udhaar nahi gaya."
    assert R.payment_total(500).text == "Aaj ₹500 jama hue."
    assert R.daily_summary({"count": 0}).text == "Aaj abhi tak koi entry nahi."
    assert R.top_dues([("A", 3), ("B", 2), ("C", 1)]).text == "Sabse zyada baaki: A ₹3, B ₹2, C ₹1."
    assert R.top_dues([]).text == "Kisi ka kuch baaki nahi."


def test_speak_text_is_devanagari_with_number_words():
    r = R.saved([ev("credit", "Ramesh", 340)], TODAY)
    assert "<340>" in r.speak and "रुपये" in r.speak and "₹" not in r.speak
    assert "Ramesh के खाते में" in r.speak


def test_clarification_dispatch():
    r = R.clarification({"reason": "confusable_number", "candidates": [340, 740]})
    assert r.text == "₹340 ya ₹740?"
    r = R.clarification({"reason": "same_name", "candidates": [
        {"id": "a", "name": "ramesh", "tags": ["chai wale"]}, {"id": "b", "name": "ramesh", "tags": []}]})
    assert r.text == "Kaunse Ramesh: chai wale ya pehle wale?"
    r = R.clarification({"reason": "plausibility", "pending": {"events": [{"amount": 60000}]}})
    assert r.text == "₹60,000, pakka?"


def test_same_name_label_in_replies(pipeline, state, ledger):
    from datetime import datetime

    ledger.apply({"action": "append", "events": [
        {"kind": "credit", "customer": "ramesh", "amount": 280, "date": "2026-11-21", "new_customer": True,
         "tags": ["chai wale"]}]}, now=datetime.now().astimezone(), session_id=state.session_id)
    out = ledger.apply({"action": "append", "events": [
        {"kind": "credit", "customer": "ramesh", "amount": 50, "date": "2026-11-21", "new_customer": True,
         "tags": ["gali number 3"]}]}, now=datetime.now().astimezone(), session_id=state.session_id)
    r = R.saved(out.saved, date(2026, 11, 21))
    assert r.text == "Naya khata Ramesh gali number 3. Ramesh gali number 3 ke khate mein ₹50 udhaar likh diya."
    assert "Ramesh gali number 3 के खाते में" in r.speak
    t = pipeline.run_turn(state, "aaj ka hisaab")
    assert "Sabse zyada baaki: Ramesh chai wale, ₹280." in t.reply_text
