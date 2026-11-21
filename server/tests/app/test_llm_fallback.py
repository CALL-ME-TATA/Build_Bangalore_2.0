"""LLM fallback (app/llm.py): the LLM only rewrites refused sentences; the real parser decides, grounded and read back."""
from __future__ import annotations

from datetime import date

from app.llm import LlmParse, grounded, spoken_amounts
from app.pipeline import Pipeline, SessionState, default_parse

from .conftest import apply_events, fake_nw

TODAY = date(2026, 11, 21)
CTX = {"customers": [{"id": 1, "key": "ramesh", "name": "Ramesh", "tags": ["chai wale"], "aliases": []},
                     {"id": 2, "key": "sunita", "name": "Sunita", "tags": [], "aliases": []}],
       "limits": {"strict": True, "confirm_new_customer": True}}


class FakeLlm:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, sentence, names):
        self.calls.append(sentence)
        if self.error:
            raise self.error
        return self.reply


def run(sentence, reply=None, error=None, ctx=CTX):
    llm = FakeLlm(reply, error)
    return LlmParse(default_parse, llm)(sentence, today=TODAY, ctx=ctx), llm


def test_spoken_amounts_reads_words_and_digits():
    assert {340, 200} <= spoken_amounts("Ramesh ne teen sau chaalis liye, 200 baad mein")


def test_sentence_the_rules_handle_never_calls_the_llm():
    r, llm = run("Ramesh ka 340 udhaar", reply="Ramesh ka 999 udhaar")
    assert llm.calls == [] and r["status"] == "ok" and r["events"][0]["amount"] == 340


def test_refused_sentence_becomes_a_read_back_not_a_save():
    # "Sunita aayi thi, do sau de gayi": the rules ask "how much?" although 200 was said
    r, llm = run("Sunita aayi thi, do sau de gayi", reply="Sunita ne do sau diye")
    assert llm.calls and r["status"] == "needs_clarification" and r["reason"] == "confirm_entry"
    ev = r["pending"]["events"][0]
    assert (ev["kind"], ev["amount"], ev["customer_id"], r["via"]) == ("payment", 200, 2, "llm")


def test_invented_amount_keeps_the_original_result():
    original, _ = run("Sunita aayi thi, do sau de gayi")
    r, _ = run("Sunita aayi thi, do sau de gayi", reply="Sunita ne 700 diye")
    assert r == original and "via" not in r


def test_invented_customer_keeps_the_original_result():
    r, _ = run("kya haal hai", reply="Mohan ka 340 udhaar")
    assert r["status"] == "rejected" and r["reason"] == "not_ledger"


def test_llm_says_none_or_fails():
    for kw in ({"reply": "NONE"}, {"reply": None}, {"error": TimeoutError()}):
        r, _ = run("kya haal hai", **kw)
        assert r["status"] == "rejected" and r["reason"] == "not_ledger"


def test_open_question_never_reaches_the_llm():
    ctx = dict(CTX, pending={"reason": "new_customer", "action": "append", "events": []})
    _, llm = run("kya haal hai", reply="Ramesh ka 340 udhaar", ctx=ctx)
    assert llm.calls == []


def test_undo_from_the_llm_is_refused():
    r, _ = run("kya haal hai", reply="pichli entry hata do")
    assert r["status"] == "rejected"


def test_query_from_the_llm_is_answered():
    r, _ = run("Ramesh bhai ka khata dikhao zara", reply="Ramesh ka total kitna hai")
    if r.get("via") == "llm":  # only when the rules refused it
        assert r["action"] == "query" and r["query"]["customer_id"] == 1


def test_grounding_unit():
    res = {"status": "needs_clarification", "pending": {"events": [{"amount": 340, "customer": "Mohan"}]}}
    assert grounded(res, "mohan ko teen sau chaalis", CTX)
    assert not grounded(res, "sohan ko teen sau chaalis", CTX)
    assert not grounded(res, "mohan ko teen sau", CTX)


def test_end_to_end_saved_only_after_yes(ledger, settings):
    apply_events(ledger, [{"kind": "credit", "customer": "sunita", "amount": 500, "date": TODAY.isoformat(),
                           "new_customer": True}])
    p = Pipeline(ledger, settings, parse=LlmParse(default_parse, FakeLlm("Sunita ne do sau diye")),
                 number_to_words=fake_nw)
    s = SessionState(session_id="sess0002")
    first = p.run_turn(s, "Sunita aayi thi, do sau de gayi")
    assert first.status == "needs_clarification" and not first.entries
    sid = ledger.find_customer(key="sunita")["id"]
    assert ledger.balance(sid) == 500
    second = p.run_turn(s, "haan")
    assert second.status == "ok" and ledger.balance(sid) == 300


# ---- guardrails: the LLM below is deliberately wrong; the code must still refuse -------------------------------
def test_sentence_without_any_money_word_never_reaches_the_llm():
    for s, bad in [("Ramesh ki beti 5 saal ki hai", "Ramesh ka 5 udhaar"),
                   ("kal match mein 250 run bane", "Ramesh ka 250 udhaar"),
                   ("Sunita bahut acchi hai", "Sunita ne 100 diye")]:
        r, llm = run(s, reply=bad)
        assert llm.calls == [] and "via" not in r, s


def test_llm_may_not_choose_the_direction():
    # only "de gayi" (a payment word) was said: a credit from the LLM is refused
    original, _ = run("Sunita aayi thi, do sau de gayi")
    r, _ = run("Sunita aayi thi, do sau de gayi", reply="Sunita ka do sau udhaar")
    assert r == original


def test_count_age_or_time_is_never_an_amount():
    from app.llm import spoken_amounts
    assert 3 not in spoken_amounts("Ramesh ne 3 kilo chawal liya")
    assert 5 not in spoken_amounts("beti 5 saal ki hai")
    assert 250 not in spoken_amounts("250 run bane")
    r, _ = run("Ramesh ne 3 kilo chawal udhaar liye, paise baad mein", reply="Ramesh ka 3 udhaar")
    assert "via" not in r


def test_query_needs_a_query_word():
    r, _ = run("Ramesh ke paise ka scene", reply="Ramesh ka total kitna hai")
    assert "via" not in r


def test_settle_or_writeoff_never_comes_from_a_rewrite():
    r, _ = run("Ramesh ka hisaab, paise", reply="Ramesh ka poora baaki maaf karo")
    assert "via" not in r
