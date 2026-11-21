"""Y. Review findings (CONTRACT 1.15). Every case runs through the pipeline with the default server limits (strict
mode and new-customer confirmation on) and asserts that nothing wrong reaches the ledger, plus what is asked or refused."""
from __future__ import annotations

import pytest

from nlu.speak import number_to_words

from .kit import expect_ask, expect_nothing_saved, expect_query, expect_reject, expect_saved, parse, roster


def book(shop, *extra):
    shop.seed(("ramesh", "credit", 1000), ("sunita", "credit", 1000), *extra)
    return shop


def hearsay(t):
    expect_ask(t, "confirm_entry")
    assert (t.confirm or {}).get("type") == "hearsay", t.describe()


def unsure(t):
    expect_ask(t, "confirm_entry")
    assert (t.confirm or {}).get("type") == "unsure", t.describe()


# ---- Y01 ---------------------------------------------------------------------------------------------------------

Y01_SETUPS = {
    "plausibility": (["Ramesh ka 75000 udhaar"], "plausibility"),
    "unsure": (["Ramesh ka blorp 340 udhaar"], "confirm_entry"),
    "settle": (["Ramesh ne poora de diya"], "confirm_entry"),
    "writeoff": (["Ramesh ka baaki chhod do"], "confirm_entry"),
    "duplicate": (["Ramesh ne 100 diye", "Ramesh ne 100 diye"], "confirm_entry"),
    "new_customer": (["Geeta ne 150 diye"], "new_customer"),
}
Y01_ANSWERS = ["ok cancel karo", "haan hata do", "theek hai cancel kar do", "ok delete", "haan mita do", "haan undo"]


@pytest.mark.parametrize("answer", Y01_ANSWERS)
@pytest.mark.parametrize("name", Y01_SETUPS)
def test_Y01_yes_plus_an_undo_word_is_no(shop, name, answer):
    book(shop)
    say, reason = Y01_SETUPS[name]
    last = None
    for s in say:
        last = shop.say(s)
    assert last.status == "needs_clarification" and last.reason == reason, f"setup: {last.describe()}"
    n = shop.count()
    t = shop.say(answer)
    assert shop.count() == n and not t.added, f"an undo word was read as yes: {t.describe()}"


# ---- Y02 ---------------------------------------------------------------------------------------------------------

Y02_SENTENCES = ["Ramesh ka 340 udhaar hata do", "Ramesh ka 340 udhaar cancel karo", "Ramesh ka 340 udhaar delete karo",
                 "Ramesh ka 340 udhaar mita do", "hata do Ramesh ka 340 udhaar", "340 wali entry hata do",
                 "cancel Ramesh ko 500 udhaar", "Sunita ka 200 udhaar hata do"]


@pytest.mark.parametrize("text", Y02_SENTENCES)
def test_Y02_a_delete_request_naming_the_entry_never_appends(shop, text):
    book(shop)
    expect_saved(shop.say("Ramesh ka 340 udhaar"), ("credit", "ramesh", 340), shop=shop)
    t = shop.say(text)
    assert not t.saved, f"a delete request appended an entry: {t.describe()}"
    assert t.status in ("needs_clarification", "rejected"), t.describe()
    assert not t.added, f"nothing may change before the undo check is answered: {t.describe()}"


# ---- Y03 ---------------------------------------------------------------------------------------------------------

def test_Y03_a_denied_name_is_not_picked_for_a_new_customer_question(shop):
    shop.seed(("rakesh", "credit", 1000), ("sunita", "credit", 1000))
    expect_ask(shop.say("Rakes ka 50 udhaar"), "new_customer")
    t = shop.say("Rakesh nahi")
    assert not t.added, t.describe()


def test_Y03_a_denied_tag_is_not_picked_for_a_same_name_question(shop):
    shop.seed(("ramesh", "credit", 1000, 0, "chai wale"), ("ramesh", "credit", 1000, 0, "gali wale"))
    expect_ask(shop.say("Ramesh ka 50 udhaar"), "same_name")
    t = shop.say("chai wale nahi")
    assert not t.added, t.describe()


@pytest.mark.parametrize("answer", ["Ramesh nahi", "Ramesh ya Sunita", "Ramesh aur Sunita"])
def test_Y03_negated_or_two_name_answer_to_kiska_khata_saves_nothing(shop, answer):
    book(shop)
    expect_ask(shop.say("500 diya"), "missing_customer")
    t = shop.say(answer)
    assert not t.added, t.describe()


def test_Y03_ramesh_nahi_sunita_means_sunita(shop):
    book(shop)
    expect_ask(shop.say("500 udhaar"), "missing_customer")
    expect_saved(shop.say("Ramesh nahi Sunita"), ("credit", "sunita", 500), shop=shop)


# ---- Y04 ---------------------------------------------------------------------------------------------------------

Y04_SETUPS = {
    "missing_amount": ["Ramesh ne paise diye"],
    "plausibility": ["Ramesh ka 51000 udhaar"],
    "unsure": ["Ramesh ka blorp 340 udhaar"],
    "confusable": ["Ramesh ka 200 ya 300 udhaar"],
}


@pytest.mark.parametrize("answer", ["300 ya 400", "teen chaar sau", "7000 ya 7500"])
@pytest.mark.parametrize("name", Y04_SETUPS)
def test_Y04_two_amounts_in_an_answer_ask_again(shop, name, answer):
    book(shop)
    for s in Y04_SETUPS[name]:
        shop.say(s)
    n = shop.count()
    t = shop.say(answer)
    assert shop.count() == n and not t.added, f"an answer with two amounts saved: {t.describe()}"
    assert t.status == "needs_clarification", t.describe()
    if name in ("missing_amount", "plausibility", "confusable"):
        assert t.reason == "confusable_number", t.describe()


# ---- Y05 ---------------------------------------------------------------------------------------------------------

def _after_expired_question(shop, setup):
    book(shop)
    expect_saved(shop.say("Ramesh ko 340 udhaar"), ("credit", "ramesh", 340), shop=shop)
    q = shop.say(setup)
    assert q.status == "needs_clarification", q.describe()
    shop.wait(70)


@pytest.mark.parametrize("setup", ["Sunita ne 5000 diye", "Geeta ne 200 diye"])
@pytest.mark.parametrize("text", ["nahi, 300", "galat, Sunita", "cancel", "hata do"])
def test_Y05_a_correction_after_an_expired_question_touches_nothing(shop, setup, text):
    _after_expired_question(shop, setup)
    t = shop.say(text)
    assert not t.saved and not any(r["customer"] == "ramesh" for r in t.added), (
        f"an older entry was changed after the question expired: {t.describe()}")


def test_Y05_hata_do_after_an_expired_pakka_question_touches_nothing(shop):
    book(shop)
    shop.say("Ramesh ko 340 udhaar")
    expect_ask(shop.say("Ramesh ka 75000 udhaar"), "plausibility")
    shop.wait(70)
    t = shop.say("hata do")
    assert not t.saved and not any(r["customer"] == "ramesh" for r in t.added), t.describe()


@pytest.mark.parametrize("text", ["nahi, 300", "hata do", "cancel", "galat, Sunita"])
def test_Y05_a_correction_after_a_query_touches_nothing(shop, text):
    book(shop)
    shop.say("Ramesh ka 340 udhaar")
    expect_query(shop.say("Ramesh ka total?"))
    t = shop.say(text)
    assert not t.saved and not any(r["customer"] == "ramesh" for r in t.added), t.describe()


# ---- Y06 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Chacha 200 le gaye", "Seth 500 le gaya", "Diya 200 le gayi", "Lala 200 de gaya"])
def test_Y06_a_name_before_the_amount_is_the_customer_not_the_carried_one(shop, text):
    book(shop)
    shop.say("Ramesh ka 340 udhaar")
    t = shop.say(text)
    assert not any(r["customer"] == "ramesh" for r in t.added), f"saved to the carried-over customer: {t.describe()}"
    assert not t.added, f"an unknown name must be asked about first: {t.describe()}"


@pytest.mark.parametrize("text", ["500 udhaar", "200 jama", "Kal 500 le gaya", "300 payment aaya", "200 diya"])
def test_Y06_a_new_turn_with_an_amount_and_no_name_asks_who(shop, text):
    book(shop)
    shop.say("Ramesh ka 340 udhaar")
    expect_ask(shop.say(text), "missing_customer")


def test_Y06_wahi_picks_the_customer_of_the_last_event(shop):
    book(shop)
    shop.say("Ramesh ka 340 udhaar")
    expect_ask(shop.say("200 jama"), "missing_customer")
    expect_saved(shop.say("wahi"), ("payment", "ramesh", 200), shop=shop)


@pytest.mark.parametrize("text,want", [
    ("aur 200", ("credit", "ramesh", 200)), ("200 add kar do", ("credit", "ramesh", 200)),
    ("usne 200 diye", ("payment", "ramesh", 200))])
def test_Y06_explicit_continuation_forms_still_carry_over(shop, text, want):
    book(shop)
    shop.say("Ramesh ka 340 udhaar")
    expect_saved(shop.say(text), want, shop=shop)


def test_Y06_a_second_clause_inside_one_utterance_still_carries(shop):
    book(shop)
    expect_saved(shop.say("Ramesh ka 340 udhaar, kal 200 diya tha"),
                 ("credit", "ramesh", 340), ("payment", "ramesh", 200, 1), shop=shop)


# ---- Y07 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Ramesh ko 12 ande udhaar", "Ramesh ko 50 bidi udhaar", "Ramesh 10 cigarette le gaya",
    "Ramesh took 12 eggs on credit"])
def test_Y07_a_goods_count_is_not_an_amount(shop, text):
    book(shop)
    t = shop.say(text)
    expect_ask(t, "missing_amount")


def test_Y07_devanagari_goods_count_saves_nothing(shop):
    book(shop)
    t = shop.say("रमेश को 12 अंडे उधार")
    assert not t.added and t.status in ("needs_clarification", "rejected"), t.describe()


@pytest.mark.parametrize("text", ["Ramesh ko 20 20 rupaye ke 3 packet udhaar", "Ramesh ne 2 baar 100 diye"])
def test_Y07_a_count_beside_an_amount_is_asked(shop, text):
    book(shop)
    unsure(shop.say(text))


# ---- Y08 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Ramesh saaman saath le gaya", "Ramesh sath le gaya", "Ramesh ne paise sath diye",
                                  "रमेश सामान साथ ले गया"])
def test_Y08_saath_meaning_with_is_not_sixty(shop, text):
    book(shop)
    t = shop.say(text)
    assert not t.added and not any(r["amount"] == 60 for r in t.added), t.describe()


@pytest.mark.parametrize("text,amount", [("Ramesh ka saath rupaye udhaar", 60), ("Ramesh ka ek sau saath udhaar", 160)])
def test_Y08_saath_inside_a_number_phrase_is_still_sixty(shop, text, amount):
    book(shop)
    expect_saved(shop.say(text), ("credit", "ramesh", amount), shop=shop)


# ---- Y09 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Ramesh ne 500 diye kya", "Ramesh ne 500 diye?", "Ramesh ne 500 diye na", "has Ramesh paid 500",
    "Ramesh paid 500 right?", "Ramesh ne 500 diya hoga", "Ramesh ka 500 udhaar likha hai kya"])
def test_Y09_questions_and_guesses_are_asked_never_saved(shop, text):
    book(shop)
    hearsay(shop.say(text))


@pytest.mark.parametrize("text", ["Ramesh ne 500 na diye", "Ramesh ka 500 udhaar na likhna"])
def test_Y09_na_before_a_verb_is_a_negation(shop, text):
    book(shop)
    expect_reject(shop.say(text), "negated")


# ---- Y10 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Ramesh did not pay 500", "not paid 500"])
def test_Y10_english_negation_is_never_a_correction(shop, text):
    book(shop)
    expect_saved(shop.say("Ramesh ne 100 diye"), ("payment", "ramesh", 100), shop=shop)
    expect_reject(shop.say(text), "negated")


# ---- Y11 ---------------------------------------------------------------------------------------------------------

def test_Y11_bina_diye_with_an_unknown_name_never_saves_even_after_yes(shop):
    book(shop)
    first = shop.say("Mohan bina 500 diye chala gaya")
    assert not first.added, first.describe()
    second = shop.say("haan")
    assert not second.added, f"strict mode was lost after the new-customer answer: {second.describe()}"


def test_Y11_bina_diye_is_a_negation(shop):
    book(shop)
    expect_reject(shop.say("Ramesh bina 500 diye chala gaya"), "negated")


def test_Y11_a_date_answer_does_not_skip_the_unsure_question(shop):
    book(shop)
    first = shop.say("Ramesh ka Monday ko 500 udhaar hone wala tha")
    assert not first.added and first.status in ("needs_clarification", "rejected"), first.describe()
    if first.status == "rejected":  # refused outright as a future plan: nothing to answer
        return
    t = shop.say("kal")
    assert not t.added, f"saved without the unsure confirmation: {t.describe()}"


# ---- Y12 ---------------------------------------------------------------------------------------------------------

def test_Y12_took_from_is_a_payment(shop):
    book(shop)
    expect_saved(shop.say("took 500 from Ramesh"), ("payment", "ramesh", 500), shop=shop)


@pytest.mark.parametrize("text", [
    "I paid Ramesh 500", "Ramesh was paid 500", "Ramesh got 500", "I owe Ramesh 500", "I borrowed 500 from Ramesh",
    "Ramesh lent me 500"])
def test_Y12_the_shop_paying_or_owing_the_customer_is_refused(shop, text):
    book(shop)
    expect_reject(shop.say(text), "out_of_scope")


def test_Y12_two_names_paying_asks_whose_account_and_saves_nothing(shop):
    """CONTRACT 1.17: one amount, one direction, two names -> `missing_customer`, the payment of 500 kept."""
    book(shop)
    t = shop.say("Ramesh and Sunita paid 500")
    expect_ask(t, "missing_customer")
    events = (shop.state.pending or {}).get("events") or []
    assert [(e.get("kind"), e.get("amount"), e.get("customer")) for e in events] == [("payment", 500, None)], (
        f"the pending entry must keep the payment of 500 and name nobody: {shop.state.pending}")
    assert not any(r["customer"] in ("ramesh", "sunita") for r in t.added)


@pytest.mark.parametrize("text", ["Ramesh ne 500 ka maal lautaya", "Ramesh se 500 ka saaman liya"])
def test_Y12_goods_returned_or_bought_asks_direction(shop, text):
    book(shop)
    expect_ask(shop.say(text), "ambiguous_direction")


# ---- Y13 ---------------------------------------------------------------------------------------------------------

def _written_off(shop):
    shop.seed(("ramesh", "credit", 340))
    expect_ask(shop.say("Ramesh ka baaki chhod do"), "confirm_entry")
    expect_saved(shop.say("haan"), ("writeoff", "ramesh", 340), shop=shop)
    assert shop.balance("ramesh") == 0


def test_Y13_a_write_off_can_be_undone_by_voice(shop):
    _written_off(shop)
    t = shop.say("undo karo")
    assert t.status == "ok" and t.action == "undo" and len(t.reversals) == 1, t.describe()
    assert shop.balance("ramesh") == 340


def test_Y13_a_write_off_can_be_corrected_by_voice(shop):
    _written_off(shop)
    t = shop.say("nahi, 100")
    assert t.status == "ok" and t.action == "amend", t.describe()
    assert [(r["kind"], r["amount"]) for r in t.saved] == [("writeoff", 100)], t.describe()
    assert shop.balance("ramesh") == 240


# ---- Y14 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Ramesh ka 500 ka aadha udhaar", "Ramesh ka 500 se zyada udhaar", "Ramesh ka 500 nahi to 600 udhaar",
    "Ramesh ka lagbhag 500 udhaar", "Ramesh ka around 500 udhaar", "Ramesh ka double 500 udhaar"])
def test_Y14_amount_modifiers_never_save_directly(shop, text):
    book(shop)
    t = shop.say(text)
    assert not t.added and t.status == "needs_clarification", t.describe()
    assert t.reason == "confirm_entry", t.describe()


# ---- Y15 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,days", [("Ramesh ne raat ko 500 diye", 0), ("Ramesh ne shaam ko 500 diye", 0),
                                       ("Ramesh ne kal raat ko 500 diye", 1), ("Ramesh ne subah 500 diye", 0)])
def test_Y15_time_words_are_ignored_and_never_a_name(shop, text, days):
    book(shop)
    expect_saved(shop.say(text), ("payment", "ramesh", 500, days), shop=shop)


# ---- Y16 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Ramesh ne 1 saal pehle 500 diye", "Ramesh ne 2 hafte pehle 500 diye",
                                  "Ramesh ne 3 mahine pehle 500 diye"])
def test_Y16_long_ago_asks_the_date(shop, text):
    book(shop)
    expect_ask(shop.say(text), "unclear_date")


# ---- Y17 ---------------------------------------------------------------------------------------------------------

def test_Y17_a_correction_that_changes_nothing_asks_and_does_not_say_corrected(shop):
    book(shop)
    shop.say("Ramesh ka 340 udhaar")
    t = shop.say("nahi 340")
    expect_ask(t, "unclear_correction")
    assert "theek kar diya" not in t.reply_text.lower() and "corrected" not in t.reply_text.lower(), t.describe()


# ---- Y18 ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Ramesh ka 500 udhaar hai", "Ramesh ka 500 udhaar tha", "Ramesh pe 500 udhaar hai"])
def test_Y18_a_stative_sentence_is_asked_before_saving(shop, text):
    book(shop)
    hearsay(shop.say(text))


# ---- Y19 ---------------------------------------------------------------------------------------------------------

def test_Y19_kochar_is_a_new_customer_not_ko_plus_char(shop):
    book(shop)
    t = shop.say("Kochar ko 500 udhaar")
    expect_ask(t, "new_customer")
    events = (shop.state.pending or {}).get("events") or []
    assert [e.get("customer") for e in events] == ["kochar"], shop.state.pending


def test_Y19_parser_keeps_the_token_whole_without_a_roster_match():
    r = parse("Kochar ko 500 udhaar", ctx={"customers": roster("ramesh"), "limits": {"confirm_new_customer": True}})
    assert r["status"] == "needs_clarification" and r["reason"] == "new_customer", r
    assert r["pending"]["events"][0]["customer"] == "kochar", r


# ---- Y20, Y21 (server) ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Ramesh ne poora de diya", "Ramesh ne 5000 diye", "Ramesh ka baaki chhod do"])
def test_Y20_private_mode_never_speaks_a_balance_in_a_confirm_question(live_stack, text):
    live_stack.seed_customer("ramesh", credit=1340)
    c = live_stack.session(private=True)
    turn = c.text(text)
    assert turn.result["status"] == "needs_clarification", turn.result
    spoken = " ".join(str(r.get("text")) for r in live_stack.mock_log()["tts_requests"])
    assert "1340" not in spoken and "1,340" not in spoken and number_to_words(1340, "deva") not in spoken, (
        f"the balance was sent to speech: {spoken!r}")


def test_Y21_a_reused_utt_id_with_a_different_sentence_is_not_answered_with_the_old_result(live_stack):
    live_stack.seed_customer("ramesh", credit=1000)
    c = live_stack.session()
    first = c.text("Ramesh ne 40 diye", utt_id="utt-y21")
    n = live_stack.count()
    try:
        second = c.text("Ramesh ka 900 udhaar", utt_id="utt-y21")
    except AssertionError as exc:  # no result: acceptable only when the server refused with an error message
        assert "error" in str(exc) and "utt_id" in str(exc), f"no refusal and no result: {exc}"
        assert live_stack.count() == n
        return
    assert live_stack.count() == n, "a reused id with another sentence must save nothing"
    assert second.result["reply_text"] != first.result["reply_text"] and not second.result.get("duplicate"), second.result
