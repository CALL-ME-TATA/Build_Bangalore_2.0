"""Z29 to Z50: the fourth review (CONTRACT 1.18, the 5.1 rows of v1.6 and 3.4).

The roster is the reviewer's: Ramesh owes 1,030, Mohan 140, Geeta 1,005, Sunita 0 (settled entries). Parser-driven cases
run through the pipeline (the same code the session calls); the typed-sentence case runs over /ws/session.
"""
from __future__ import annotations

import pytest

from .kit import expect_ask, expect_nothing_saved, expect_query, expect_reject, expect_saved

ROSTER_NAMES = {"ramesh", "mohan", "geeta", "sunita"}


def roster(shop):
    shop.seed(("ramesh", "credit", 1030), ("mohan", "credit", 140), ("geeta", "credit", 1005),
              ("sunita", "credit", 300), ("sunita", "payment", 300))
    return shop


def names(shop):
    return {c["name"] for c in shop.customers()}


def ctype(t):
    return (t.confirm or {}).get("type")


# ---- Z29 cash on the spot ---------------------------------------------------------------------------------------

Z29 = [
    "Ramesh ne 200 ka saaman liya paise de diye", "Ramesh ne 200 ka saaman liya aur paise de diye",
    "Ramesh ne 200 ka saaman liya, paise de diye", "Ramesh ne 200 ka saaman liya paise de gaya",
    "Ramesh ne 200 ka saaman liya usne de diye", "Ramesh ne 200 ka saaman liya payment ho gaya",
    "Ramesh ne 200 ka saaman liya payment de diya", "Ramesh ne 200 ka saaman liya cash de diya",
    "Ramesh ne 200 ka saaman liya UPI kar diya", "Ramesh ne 200 ka saaman liya Paytm kar diya",
    "Ramesh ne 200 ka saaman liya online de diya", "Ramesh ne 200 ka saaman cash mein liya",
    "Ramesh ne 200 ka saaman nakad liya", "Ramesh 200 ka saaman le gaya nakad",
    "Ramesh 200 ka saaman le gaya aur de gaya", "Ramesh ko 200 ka saaman diya aur paise le liye",
    "Ramesh ko 200 ka saaman diya usne paise de diye", "Ramesh ne 200 ka saaman liya, hisaab barabar",
    "Ramesh bought goods for 200 in cash",
]


@pytest.mark.parametrize("text", Z29)
def test_Z29_a_purchase_with_cash_handed_over_saves_nothing(shop, text):
    roster(shop)
    expect_reject(shop.say(text), "out_of_scope")


def test_Z29_english_cash_purchase_is_answered_in_english(shop):
    roster(shop)
    t = shop.say("Ramesh bought goods for 200 in cash")
    assert t.msg.get("lang") == "en" and "udhaar" not in t.reply_text.lower(), t.describe()


# ---- Z30, Z31 a repaid udhaar -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Ramesh ko 200 udhaar diye the, aaj de gaya", "Ramesh ko 200 udhaar diya tha wo aa gaya"])
def test_Z30_a_past_credit_that_came_back_asks_the_direction(shop, text):
    roster(shop)
    expect_ask(shop.say(text), "ambiguous_direction")


Z31 = ["Ramesh udhaar ke 200 de gaya", "Ramesh aaj udhaar ke 200 de gaya", "Ramesh udhaar ka 200 de gaya",
       "Ramesh pichle udhaar ke 200 de gaya", "Ramesh udhaar ke 200 rupaye de gaya", "Ramesh 200 udhaar de gaya",
       "Ramesh 200 ka udhaar de gaya", "Ramesh udhaar 200 de gaya", "Ramesh udhaar de gaya 200",
       "udhaar ke 200 Ramesh de gaya"]


@pytest.mark.parametrize("text", Z31)
def test_Z31_udhaar_with_the_customer_giving_and_no_ko_asks(shop, text):
    roster(shop)
    expect_ask(shop.say(text), "ambiguous_direction")


def test_Z31_ko_udhaar_de_diya_stays_a_credit(shop):
    roster(shop)
    expect_saved(shop.say("Ramesh ko 200 udhaar de diya"), ("credit", "ramesh", 200), shop=shop)


# ---- Z32 purchase, paid amount, the rest -------------------------------------------------------------------------

@pytest.mark.parametrize("text,credit", [
    ("Ramesh ne 500 ka saaman liya 200 diye baaki udhaar", 300),
    ("Ramesh ne 500 ka saaman liya 200 diye baaki udhaar likh do", 300),
    ("Ramesh 500 ka saaman le gaya 200 de gaya baaki udhaar", 300),
    ("Ramesh ne 500 ka saaman liya, 200 diye, baaki likh do", 300),
    ("Ramesh ne 500 ka saaman liya 300 baaki hai", 300),
])
def test_Z32_purchase_paid_and_the_rest_is_one_computed_credit(shop, text, credit):
    roster(shop)
    t = shop.say(text)
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "computed", t.describe()
    expect_saved(shop.say("haan"), ("credit", "ramesh", credit), shop=shop)
    assert shop.balance("ramesh") == 1030 + credit


@pytest.mark.parametrize("text", ["Ramesh ne 500 ka note diya, 200 kaate, 300 wapas kiye",
                                  "Ramesh ka 300 udhaar, 100 chawal ka aur 200 aate ka"])
def test_Z32_three_amounts_without_the_words_are_not_computed(shop, text):
    roster(shop)
    t = shop.say(text)
    assert not t.added and t.status == "needs_clarification" and ctype(t) != "computed", t.describe()


# ---- Z33 account words ------------------------------------------------------------------------------------------

Z33 = ["Ramesh ke naam se 200 jama karo", "Ramesh ke naam 200 jama karo", "Ramesh ke naam pe 200 jama kar do",
       "Ramesh ke naam 200 jama", "Ramesh ke naam ka 200 jama hua", "Ramesh ke naam 200 aaye",
       "Ramesh ke naam se 200 aaye hain", "Ramesh ke naam 200 mile", "Ramesh ke naam ka 200 payment aaya",
       "Ramesh ke naam pe 200 ka payment likh do", "Ramesh ke naam 200 kaat do",
       "Ramesh ke khate mein 200 payment likh do", "Ramesh ke khate mein payment 200 likh do",
       "Ramesh ke khate mein 200 ka payment daal do", "Ramesh ke khate mein 200 ka payment add karo"]


@pytest.mark.parametrize("text", Z33)
def test_Z33_a_payment_word_beats_the_account_words(shop, text):
    roster(shop)
    expect_saved(shop.say(text), ("payment", "ramesh", 200), shop=shop)


def test_Z33_ke_naam_with_no_direction_word_is_a_credit(shop):
    roster(shop)
    expect_saved(shop.say("Ramesh ke naam 200 likh do"), ("credit", "ramesh", 200), shop=shop)


@pytest.mark.parametrize("text", ["Ramesh ke naam 200 udhaar jama karo", "Ramesh ke khate mein 200 udhaar payment likh do"])
def test_Z33_a_credit_word_and_a_payment_word_together_ask(shop, text):
    roster(shop)
    expect_ask(shop.say(text), "ambiguous_direction")


# ---- Z34, Z35, Z36 stray words are not customers -----------------------------------------------------------------

Z34 = [
    ("Ramesh ne 500 ka saaman liya, 200 udhaar rakha", []), ("Ramesh paid 200 out of 500", []),
    ("Ramesh paid 200 in cash and 300 by UPI", []), ("he took another 100", ["Ramesh ka 340 udhaar"]),
    ("100 kam karo", ["Ramesh ka 340 udhaar"]), ("100 badha do", ["Ramesh ka 340 udhaar"]),
    ("I meant 350", ["Ramesh ka 340 udhaar"]), ("Ramesh wants 200 on credit", []),
    ("Ramesh ne 200 diye lekin 100 kam the", []), ("Ramesh ne 500 diye 300 chutte wapas diye", []),
    ("ise 430 kar do", ["Ramesh ka 340 udhaar"]), ("Ramesh ne jaldi se 200 diye aur Mohan ko 100 udhaar", []),
]


@pytest.mark.parametrize("text,before", Z34, ids=[c[0] for c in Z34])
def test_Z34_no_customer_is_created_from_a_stray_word(shop, text, before):
    roster(shop)
    for s in before:
        shop.say(s)
    t = shop.say(text)
    for _ in range(3):
        if t.status != "needs_clarification":
            break
        t = shop.say("haan")
    assert names(shop) == ROSTER_NAMES, f"a customer was created: {names(shop) - ROSTER_NAMES}"


@pytest.mark.parametrize("text", ["Ramesh also paid 200", "Ramesh finally paid 200", "Ramesh has given 200",
                                  "Ramesh cleared 200", "Ramesh already paid 200", "Ramesh just paid 200"])
def test_Z34_adverbs_and_auxiliaries_are_fillers_and_the_verb_is_kept(shop, text):
    roster(shop)
    expect_saved(shop.say(text), ("payment", "ramesh", 200), shop=shop)
    assert names(shop) == ROSTER_NAMES


@pytest.mark.parametrize("answer", ["haan bhai", "ha bhai", "haan bhaiya", "theek hai bhai", "haan sir", "haan madam",
                                    "haan beta", "hau", "yeah open it", "go ahead", "create", "khol do"])
def test_Z35_yes_with_an_address_word_is_yes(shop, answer):
    roster(shop)
    expect_ask(shop.say("Vikram ko 500 udhaar"), "new_customer")
    expect_saved(shop.say(answer), ("credit", "vikram", 500), shop=shop)
    assert names(shop) == ROSTER_NAMES | {"vikram"}


@pytest.mark.parametrize("text", ["Ramesh Chopra ko 200 udhaar", "Ramesh wants 200 on credit"])
def test_Z36_a_stored_first_name_plus_an_unknown_word_offers_the_stored_customer(shop, text):
    roster(shop)
    t = shop.say(text)
    expect_ask(t, "new_customer")
    assert "Ramesh" in t.reply_text and "ya" in t.reply_text.lower() or " or " in t.reply_text, t.describe()
    assert shop.cid("ramesh") in {c["id"] for c in (t.candidates or [])}, f"the stored customer is not offered: {t.describe()}"


def test_Z36_a_bare_yes_to_the_either_or_question_saves_nothing(shop):
    roster(shop)
    expect_ask(shop.say("Ramesh Chopra ko 200 udhaar"), "new_customer")
    t = shop.say("haan")
    assert not t.added and t.status == "needs_clarification", t.describe()
    assert names(shop) == ROSTER_NAMES


@pytest.mark.parametrize("answer", ["wahi", "purana", "pehla", "Ramesh"])
def test_Z36_the_offered_name_picks_the_stored_customer(shop, answer):
    roster(shop)
    shop.say("Ramesh Chopra ko 200 udhaar")
    expect_saved(shop.say(answer), ("credit", "ramesh", 200), shop=shop)


@pytest.mark.parametrize("answer", ["naya", "banao", "new"])
def test_Z36_naya_opens_the_new_account(shop, answer):
    roster(shop)
    shop.say("Ramesh Chopra ko 200 udhaar")
    expect_saved(shop.say(answer), ("credit", "ramesh chopra", 200), shop=shop)


def test_Z36_a_close_name_is_offered_the_stored_one_and_a_bare_yes_opens_nothing(shop):
    roster(shop)
    expect_ask(shop.say("Rames ko 500 udhaar"), "new_customer")
    t = shop.say("haan")
    assert "rames" not in names(shop) and not t.added, t.describe()


# ---- Z37 restated corrections ---------------------------------------------------------------------------------

Z37 = ["Ramesh ka 430 likhna tha", "430 kar do", "430 karo", "430 kar dijiye", "amount 430 karo", "sorry 430",
       "actually 430", "Ramesh ka 430 udhaar tha", "it was 430", "I meant 430"]


@pytest.mark.parametrize("text", Z37)
def test_Z37_a_restatement_right_after_an_entry_is_an_amend_confirmation(shop, text):
    roster(shop)
    expect_saved(shop.say("Ramesh ka 340 udhaar"), ("credit", "ramesh", 340), shop=shop)
    t = shop.say(text)
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "amend" and (t.confirm.get("old"), t.confirm.get("new")) == (340, 430), t.describe()
    done = shop.say("haan")
    assert done.status == "ok" and [(r["kind"], r["amount"]) for r in done.saved] == [("credit", 430)], done.describe()
    active = [r for r in shop.entries(active_only=True) if r["session_id"] == shop.state.session_id]
    assert [r["amount"] for r in active] == [430], f"two entries are active: {active}"


# ---- Z38 not that entry -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Ramesh ka udhaar 200 ho gaya", "Ramesh ka 200 udhaar batao"])
def test_Z38_a_stated_balance_or_a_request_is_the_balance_query(shop, text):
    roster(shop)
    expect_query(shop.say(text))


@pytest.mark.parametrize("text", ["Ramesh se 200 vasool karne hain", "Ramesh se 200 lene hain", "Ramesh ko 200 lena hai"])
def test_Z38_money_still_to_be_collected_is_future(shop, text):
    roster(shop)
    expect_reject(shop.say(text), "future")


@pytest.mark.parametrize("text", ["Ramesh ka 200 udhaar likhna mat", "Ramesh ka 200 udhaar mat likhna",
                                  "Ramesh ka 200 udhaar na likhna"])
def test_Z38_a_negation_after_the_verb_is_negated(shop, text):
    roster(shop)
    expect_reject(shop.say(text), "negated")


@pytest.mark.parametrize("text", ["Ramesh ne 200 diye the kya aur Mohan ko 100 udhaar", "Ramesh ka 200 udhaar likha tha"])
def test_Z38_a_question_or_stative_clause_makes_the_whole_utterance_hearsay(shop, text):
    roster(shop)
    t = shop.say(text)
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "hearsay", t.describe()


def test_Z38_given_and_taken_back_asks_the_direction(shop):
    roster(shop)
    expect_ask(shop.say("Ramesh ne 200 diye the wo wapas le gaya"), "ambiguous_direction")


def test_Z38_an_instruction_for_later_asks_the_date(shop):
    roster(shop)
    expect_ask(shop.say("Ramesh ka 200 udhaar likh dena kal"), "unclear_date")


# ---- Z39 dates --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Ramesh paid 200 last night", "Ramesh ne kal raat 200 diye"])
def test_Z39_last_night_is_yesterday(shop, text):
    roster(shop)
    expect_saved(shop.say(text), ("payment", "ramesh", 200, 1), shop=shop)


def test_Z39_last_night_is_answered_in_english(shop):
    roster(shop)
    t = shop.say("Ramesh paid 200 last night")
    assert t.msg.get("lang") == "en" and "Received" in t.reply_text, t.describe()


@pytest.mark.parametrize("text", [
    "kal Ramesh ne 200 diye the aur Mohan ne bhi 100 diye the", "kal Ramesh ne 200 diye, Mohan ne 100 diye",
    "yesterday Ramesh paid 200 and Mohan paid 100"])
def test_Z39_a_leading_date_word_dates_every_clause(shop, text):
    roster(shop)
    t = shop.say(text)
    expect_saved(t, ("payment", "ramesh", 200, 1), ("payment", "mohan", 100, 1), shop=shop)


def test_Z39_a_morning_today(shop):
    roster(shop)
    expect_saved(shop.say("Ramesh paid 200 this morning"), ("payment", "ramesh", 200), shop=shop)


@pytest.mark.parametrize("text", ["Ramesh paid 200 last week", "Ramesh ne 15 ko 200 diye"])
def test_Z39_other_last_phrases_and_a_day_of_the_month_ask_the_date(shop, text):
    roster(shop)
    expect_ask(shop.say(text), "unclear_date")


def test_Z39_sath_sau_asks_700_or_6000(shop):
    roster(shop)
    t = shop.say("Ramesh ko sath sau udhaar")
    expect_ask(t, "confusable_number")
    assert t.candidates == [700, 6000], t.describe()


# ---- Z40 guards -------------------------------------------------------------------------------------------------

def test_Z40_two_payments_that_together_exceed_the_balance_ask(shop):
    roster(shop)
    t = shop.say("Mohan ne 100 diye aur 100 diye")
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "overpayment", t.describe()


def test_Z40_a_writeoff_above_the_balance_states_the_balance(shop):
    roster(shop)
    t = shop.say("Mohan ka 400 maaf kar do")
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "writeoff" and t.confirm.get("balance") == 140 and "140" in t.reply_text, t.describe()


def test_Z40_a_writeoff_for_a_customer_who_owes_nothing_is_the_balance_query(shop):
    roster(shop)
    t = shop.say("Sunita ka 50 maaf kar do")
    expect_query(t)


def test_Z40_the_duplicate_question_is_asked_every_time(shop):
    roster(shop)
    expect_saved(shop.say("Ramesh ka 200 udhaar"), ("credit", "ramesh", 200), shop=shop)
    expect_ask(shop.say("Ramesh ka 200 udhaar"), "confirm_entry")
    expect_saved(shop.say("haan"), ("credit", "ramesh", 200), shop=shop)
    third = shop.say("Ramesh ka 200 udhaar")
    expect_ask(third, "confirm_entry")
    assert ctype(third) == "duplicate", third.describe()


def test_Z40_a_repeated_entry_inside_a_two_entry_sentence_is_asked(shop):
    roster(shop)
    shop.say("Ramesh ka 200 udhaar")
    t = shop.say("Ramesh ka 200 udhaar aur Mohan ka 50 udhaar")
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "duplicate", t.describe()


# ---- Z41 answers ------------------------------------------------------------------------------------------------

def test_Z41_no_to_the_replace_check_saves_nothing_and_the_old_entry_stays(shop):
    roster(shop)
    expect_saved(shop.say("Ramesh ne 100 diye"), ("payment", "ramesh", 100), shop=shop)
    q = shop.say("nahi Geeta ko 500 udhaar")
    expect_ask(q, "unclear_correction")
    assert "Geeta" in q.reply_text and "500" in q.reply_text, f"the question must name the new entry: {q.describe()}"
    t = shop.say("nahi")
    assert not t.added, t.describe()
    active = [r for r in shop.entries(active_only=True) if r["session_id"] == shop.state.session_id]
    assert [(r["kind"], r["customer"], r["amount"]) for r in active] == [("payment", "ramesh", 100)]


@pytest.mark.parametrize("answer", ["kal udhaar", "udhaar kal ka"])
def test_Z41_a_date_word_beside_a_direction_answer_is_kept(shop, answer):
    roster(shop)
    expect_ask(shop.say("Ramesh 200"), "ambiguous_direction")
    expect_saved(shop.say(answer), ("credit", "ramesh", 200, 1), shop=shop)


@pytest.mark.parametrize("answer", ["Mohan", "Mohan wali"])
def test_Z41_the_customers_name_answers_a_which_entry_question(shop, answer):
    roster(shop)
    expect_saved(shop.say("Ramesh ka 100 udhaar aur Mohan ka 100 udhaar"),
                 ("credit", "ramesh", 100), ("credit", "mohan", 100), shop=shop)
    expect_ask(shop.say("100 nahi 150"), "unclear_correction")
    t = shop.say(answer)
    if t.status == "needs_clarification":
        assert ctype(t) == "amend", t.describe()
        t = shop.say("haan")
    assert [(r["kind"], r["customer"], r["amount"]) for r in t.saved] == [("credit", "mohan", 150)], t.describe()
    active = {(r["customer"], r["amount"]) for r in shop.entries(active_only=True) if r["session_id"] == shop.state.session_id}
    assert active == {("ramesh", 100), ("mohan", 150)}


def test_Z41_aur_with_an_amount_adds_an_entry_and_amends_nothing(shop):
    roster(shop)
    shop.say("Ramesh ka 10 udhaar")
    t = shop.say("uska 5 rupaye aur likh do")
    assert t.status == "ok" and not t.reversals, f"an amend was made: {t.describe()}"
    assert [(r["kind"], r["customer"], r["amount"]) for r in t.saved] == [("credit", "ramesh", 5)], t.describe()


# ---- Z42 same name ----------------------------------------------------------------------------------------------

def suresh3(shop):
    shop.seed(("suresh", "credit", 500, 0, "chai wale"), ("suresh", "credit", 500, 0, "gali 4"), ("suresh", "credit", 500))


def which(shop, cid):
    return [r for r in shop.entries() if r["customer_id"] == cid and r["session_id"] == shop.state.session_id]


def test_Z42_three_customers_are_all_offered(shop):
    suresh3(shop)
    t = shop.say("Suresh ka 200 udhaar")
    expect_ask(t, "same_name")
    assert len(t.candidates or []) == 3, t.describe()
    low = t.reply_text.lower()
    assert "chai wale" in low and "gali 4" in low and "bina tag" in low, t.describe()


@pytest.mark.parametrize("answer,tag", [("pehla", "chai wale"), ("doosra", "gali 4"), ("teesra", None),
                                         ("pehla wala", "chai wale"), ("teesra wala", None)])
def test_Z42_ordinals_follow_the_spoken_order(shop, answer, tag):
    suresh3(shop)
    shop.say("Suresh ka 200 udhaar")
    t = shop.say(answer)
    assert t.status == "ok" and [r["customer_id"] for r in t.saved] == [shop.cid("suresh", tag)], t.describe()


def test_Z42_an_untagged_second_customer_is_offered_and_ordered(shop):
    shop.seed(("suresh", "credit", 500, 0, "chai wale"), ("suresh", "credit", 500))
    t = shop.say("Suresh ka 200 udhaar")
    expect_ask(t, "same_name")
    assert len(t.candidates or []) == 2 and "bina tag" in t.reply_text.lower(), t.describe()
    done = shop.say("doosra")
    assert [r["customer_id"] for r in done.saved] == [shop.cid("suresh", None)], done.describe()


def test_Z42_an_answer_that_fits_none_saves_nothing(shop):
    suresh3(shop)
    shop.say("Suresh ka 200 udhaar")
    t = shop.say("laal wale")
    assert not t.added, t.describe()


def test_Z42_settle_goes_on_after_the_same_name_answer(shop):
    suresh3(shop)
    expect_ask(shop.say("Suresh ne poora de diya"), "same_name")
    t = shop.say("chai wale")
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "settle" and t.confirm.get("balance") == 500, t.describe()
    done = shop.say("haan")
    assert [(r["kind"], r["amount"], r["customer_id"]) for r in done.saved] == [
        ("payment", 500, shop.cid("suresh", "chai wale"))], done.describe()


def test_Z42_writeoff_goes_on_after_the_same_name_answer(shop):
    suresh3(shop)
    expect_ask(shop.say("Suresh ka maaf kar do"), "same_name")
    t = shop.say("chai wale")
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "writeoff", t.describe()


# ---- Z43 payment plus "baaki chhod do" ----------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Mohan ne 100 diye baaki chhod do", "Mohan ne 100 diye aur baaki maaf kar do",
                                  "Mohan ne 100 diye baaki 40 chhod do"])
def test_Z43_payment_and_the_rest_written_off_after_a_review(shop, text):
    roster(shop)
    t = shop.say(text)
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "review", t.describe()
    expect_saved(shop.say("haan"), ("payment", "mohan", 100), ("writeoff", "mohan", 40), shop=shop)
    assert shop.balance("mohan") == 0


def test_Z43_the_paid_amount_is_never_the_writeoff_amount(shop):
    roster(shop)
    t = shop.say("Geeta ne 1000 diye baaki chhod do")
    expect_ask(t, "confirm_entry")
    done = shop.say("haan")
    assert [(r["kind"], r["amount"]) for r in done.saved] == [("payment", 1000), ("writeoff", 5)], done.describe()


def test_Z43_when_the_balance_is_not_above_the_payment_the_writeoff_amount_is_asked(shop):
    roster(shop)
    t = shop.say("Mohan ne 140 diye baaki chhod do")
    expect_ask(t, "missing_amount")
    assert "Mohan" in t.reply_text and "maaf" in t.reply_text.lower(), t.describe()


# ---- Z44 English ------------------------------------------------------------------------------------------------

def test_Z44_he_paid_carries_over_after_an_entry(shop):
    roster(shop)
    shop.say("Ramesh ka 300 udhaar")
    expect_saved(shop.say("he paid 200"), ("payment", "ramesh", 200), shop=shop)


@pytest.mark.parametrize("text,reply_start", [("Ramesh bought items worth 250 on credit", "Added"),
                                              ("Ramesh paid 200 this morning", "Received")])
def test_Z44_english_sentences_get_english_replies(shop, text, reply_start):
    roster(shop)
    t = shop.say(text)
    assert t.status == "ok" and t.msg.get("lang") == "en" and t.reply_text.startswith(reply_start), t.describe()


@pytest.mark.parametrize("text", ["Ramesh paid in full", "Ramesh paid everything", "Ramesh paid the full amount",
                                  "Ramesh cleared everything"])
def test_Z44_paid_in_full_reaches_the_settle_confirmation(shop, text):
    roster(shop)
    t = shop.say(text)
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "settle" and t.confirm.get("balance") == 1030, t.describe()


def test_Z44_write_off_the_balance_reaches_the_writeoff_confirmation(shop):
    roster(shop)
    t = shop.say("write off Ramesh's balance")
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "writeoff", t.describe()


def test_Z44_paid_n_not_m_with_no_earlier_entry_is_hearsay_for_n(shop):
    roster(shop)
    t = shop.say("Ramesh paid 200 not 300")
    expect_ask(t, "confirm_entry")
    assert ctype(t) == "hearsay", t.describe()
    assert [e.get("amount") for e in (shop.state.pending or {}).get("events", [])] == [200], shop.state.pending


# ---- Z45 the switch off, strict on -----------------------------------------------------------------------------

Z45 = [
    ("Ramesh ne 500 ka saaman liya, 200 udhaar rakha", []), ("Ramesh paid 200 in cash and 300 by UPI", []),
    ("he took another 100", ["Ramesh ka 340 udhaar"]), ("sabko 50 udhaar", []), ("kisi ne 50 diye", []),
    ("200 udhaar", ["Ramesh ka 340 udhaar"]),
]


@pytest.mark.parametrize("text,before", Z45, ids=[c[0] for c in Z45])
def test_Z45_without_the_new_customer_question_strict_mode_still_asks(make_shop, text, before):
    s = roster(make_shop(env={"CONFIRM_NEW_CUSTOMER": "0"}))
    for b in before:
        s.say(b)
    t = s.say(text)
    assert names(s) == ROSTER_NAMES, f"a customer was created: {names(s) - ROSTER_NAMES}"
    assert not [r for r in t.added if r["customer"] not in ROSTER_NAMES], t.describe()
    assert t.status != "ok" or t.action != "append", f"saved without a question: {t.describe()}"


def test_Z45_a_close_name_always_asks(make_shop):
    s = roster(make_shop(env={"CONFIRM_NEW_CUSTOMER": "0"}))
    expect_ask(s.say("Rames ko 500 udhaar"), "new_customer")


# ---- Z46 typed sentence while a spoken question is open (CONTRACT 3.4, server half) ------------------------------

def test_Z46_a_typed_full_sentence_while_a_spoken_question_is_open_replaces_it(live_stack):
    """What the server does today: a complete typed sentence is parsed fresh and the open question is dropped
    (1.9, last line). The page-side queue rule of 3.4 keeps such a sentence from being sent while a question is open."""
    live_stack.seed_customer("ramesh", credit=1030)
    live_stack.seed_customer("mohan", credit=140)
    c = live_stack.session()
    asked = c.speak("Ramesh ka 200").result
    assert asked["status"] == "needs_clarification", asked
    typed = c.text("Mohan ne 100 diye").result
    assert typed["status"] == "ok", typed
    rows = [(r["kind"], r["customer"], r["amount"]) for r in live_stack.rows() if r["session_id"] != "seed"]
    assert rows == [("payment", "mohan", 100)], rows
    after = c.text("udhaar").result
    assert after["status"] != "ok", "the dropped question must not be answered later"
    assert [(r["kind"], r["customer"], r["amount"]) for r in live_stack.rows() if r["session_id"] != "seed"] == rows
