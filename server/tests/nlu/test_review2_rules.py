"""CONTRACT 1.15: rules from the second review. Each test name carries the finding id (B1 to B12, S for should-fix).

The reviewer's context: a roster with balances, two customers named Suresh, server limits, strict and
confirm_new_customer on. Every test asserts what must not happen (a silent wrong save) and what must happen."""
from datetime import date

import pytest

from nlu.parser import parse

T = date(2026, 11, 21)
D0, D1 = "2026-11-21", "2026-11-20"
ROSTER = [
    {"id": "c1", "name": "ramesh", "tags": [], "balance": 540},
    {"id": "c2", "name": "sunita", "tags": [], "balance": 1200},
    {"id": "c3", "name": "suresh", "tags": ["chai wale"], "balance": 100},
    {"id": "c4", "name": "suresh", "tags": ["gali number 3"], "balance": 100},
    {"id": "c5", "name": "rakesh", "tags": [], "balance": 0},
    {"id": "c6", "name": "sharma", "tags": [], "balance": 0},
]
LIMITS = {"confirm_above": 50000, "max_amount": 9999999, "carry_s": 60, "duplicate_s": 30, "strict": True,
          "confirm_new_customer": True}
LAST = {"kind": "credit", "customer": "ramesh", "customer_id": "c1", "amount": 340, "date": D0, "id": 7}


def ctx(**extra):
    c = {"customers": ROSTER, "limits": dict(LIMITS)}
    c.update(extra)
    return c


def after_entry(age=10, action="append", **extra):
    return ctx(last_event=LAST, last_events=[LAST], last_turn={"action": action, "age_s": age}, **extra)


def run(utterance, c=None):
    return parse(utterance, today=T, ctx=c if c is not None else ctx())


def answer(first, utterance, c):
    cc = dict(c)
    cc["pending"] = first["pending"]
    return parse(utterance, today=T, ctx=cc)


def saved(r):
    return r["status"] == "ok" and r.get("action") in ("append", "amend")


def entries(r):
    return [(e["kind"], e["customer"], e["amount"]) for e in r.get("events") or []]


# --- B1: yes plus an undo or stop word is no ----------------------------------------------------------------------

PENDING_SOURCES = [
    ("plausibility", "Ramesh ka 75000 udhaar", ctx()),
    ("unsure", "Ramesh ne 50 phenk diye", ctx()),
    ("settle", "Ramesh ka hisaab barabar", ctx()),
    ("writeoff", "Ramesh ka baaki chhod do", ctx()),
    ("duplicate", "Ramesh ka 340 udhaar", after_entry()),
    ("new_customer", "Mohan ne 200 diye", ctx()),
    ("computed", "Ramesh ka bill 450 hai, 200 diya, baaki udhaar", ctx()),
]
YES_PLUS_UNDO = ["ok cancel karo", "haan hata do", "theek hai cancel kar do", "ok delete", "haan mita do", "haan undo",
                 "haan rehne do", "yes cancel", "haan mat likho", "हाँ हटा दो", "ok remove it"]


@pytest.mark.parametrize("label,utterance,c", PENDING_SOURCES, ids=[p[0] for p in PENDING_SOURCES])
@pytest.mark.parametrize("reply", YES_PLUS_UNDO)
def test_B1_yes_plus_undo_word_is_no(label, utterance, c, reply):
    first = run(utterance, c)
    assert first["status"] == "needs_clarification", first
    r = answer(first, reply, c)
    assert not saved(r), r
    assert r["status"] == "rejected" and r["reason"] == "cancelled", r


def test_B1_the_undo_check_question_still_reads_hata_do_as_yes():
    first = run("Sunita ki entry hata do", after_entry())
    assert first["pending"].get("mode") == "confirm_undo"
    assert answer(first, "haan hata do", after_entry())["action"] == "undo"


@pytest.mark.parametrize("reply", ["pakka?", "haan?", "sahi?"])
def test_B1_an_echoed_question_is_not_yes(reply):
    first = run("Ramesh ka 75000 udhaar")
    r = answer(first, reply, ctx())
    assert not saved(r)


# --- B2: a delete request is never an append ----------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ka 340 udhaar hata do", "Ramesh ka 340 udhaar cancel karo",
                                       "Ramesh ka 340 udhaar delete karo", "Ramesh ka 340 udhaar mita do",
                                       "hata do Ramesh ka 340 udhaar", "रमेश का 340 उधार हटा दो",
                                       "340 wali entry hata do", "Ramesh wali 340 ki entry hata do",
                                       "Ramesh ka teen sau chaalis hata do"])
def test_B2_delete_request_naming_the_last_entry_asks_the_undo_check(utterance):
    r = run(utterance, after_entry(age=45))
    assert not saved(r), r
    assert r["reason"] == "unclear_correction" and r["pending"].get("mode") == "confirm_undo", r
    assert answer(r, "udhaar", after_entry(age=45))["status"] != "ok"
    assert answer(r, "haan", after_entry(age=45))["action"] == "undo"


@pytest.mark.parametrize("utterance", ["Sunita ka 200 udhaar hata do", "Sunita ne 200 diye wo hata do",
                                       "cancel Ramesh ko 500 udhaar", "Mohan ka 90 udhaar delete karo",
                                       "Ramesh ka 999 udhaar hata do"])
def test_B2_delete_request_for_another_entry_asks(utterance):
    r = run(utterance, after_entry(age=45))
    assert not saved(r), r
    assert r["status"] == "needs_clarification" and r["reason"] == "unclear_correction", r


# --- B3: a negated or two-name answer never picks the denied name ------------------------------------------------

@pytest.mark.parametrize("reply", ["Rakesh nahi", "Rakesh nahi hai", "nahi Rakesh nahi", "Rakesh ya koi aur"])
def test_B3_new_customer_negated_candidate(reply):
    first = run("Rakes ka 50 udhaar")
    assert first["reason"] == "new_customer"
    r = answer(first, reply, ctx())
    assert not saved(r), r


@pytest.mark.parametrize("reply", ["Sunita nahi", "Ramesh ya Sunita", "Ramesh aur Sunita"])
def test_B3_new_customer_negated_other_name(reply):
    first = run("Mohan ne 200 diye")
    r = answer(first, reply, ctx())
    assert not saved(r), r


@pytest.mark.parametrize("reply", ["chai wale nahi", "chai wala nahi hai", "gali 3 wale nahi",
                                   "chai wale ya gali wale"])
def test_B3_same_name_negated_tag(reply):
    first = run("Suresh ka 200 udhaar")
    assert first["reason"] == "same_name"
    r = answer(first, reply, ctx())
    assert not saved(r), r


@pytest.mark.parametrize("reply", ["Ramesh nahi", "Ramesh ya Sunita", "Ramesh aur Sunita", "Sunita nahi Ramesh nahi"])
def test_B3_missing_customer_negated_or_two_names(reply):
    first = run("500 udhaar")
    assert first["reason"] == "missing_customer"
    r = answer(first, reply, ctx())
    assert not saved(r), r


@pytest.mark.parametrize("reply,customer", [("Ramesh nahi Sunita", "sunita"), ("Ramesh ka nahi Sunita ka", "sunita"),
                                            ("nahi nahi Rakesh", "rakesh")])
def test_B3_x_nahi_y_takes_y(reply, customer):
    first = run("500 udhaar")
    r = answer(first, reply, ctx())
    assert r["status"] == "ok" and entries(r) == [("credit", customer, 500)], r


def test_B3_x_nahi_y_with_two_same_name_customers_asks_which():
    first = run("500 udhaar")
    r = answer(first, "Ramesh ka nahi Suresh ka", ctx())
    assert r["reason"] == "same_name"


# --- B4: two amounts in an answer ask which --------------------------------------------------------------------

@pytest.mark.parametrize("reply,cands", [("300 ya 400", [300, 400]), ("teen chaar sau", [340, 400]),
                                         ("likh do sau", [200, 100]), ("tees ya chaalis", [30, 40])])
def test_B4_missing_amount_answer_with_two_amounts(reply, cands):
    first = run("Ramesh ko udhaar")
    r = answer(first, reply, ctx())
    assert r["reason"] == "confusable_number" and r["candidates"] == cands, r
    done = answer(r, "doosra", ctx())
    assert entries(done) == [("credit", "ramesh", cands[1])]


@pytest.mark.parametrize("source,reply,cands", [
    ("Ramesh ka 75000 udhaar", "7000 ya 7500", [7000, 7500]),
    ("Ramesh ne 50 phenk diye", "300 ya 400", [300, 400]),
    ("Ramesh ka 340 ya 740 udhaar", "300 ya 700", [300, 700]),
])
def test_B4_other_questions_answered_with_two_amounts(source, reply, cands):
    first = run(source)
    r = answer(first, reply, ctx())
    assert r["reason"] == "confusable_number" and r["candidates"] == cands, r


@pytest.mark.parametrize("reply", ["chai wale ko 300", "chai wale 300", "chai wale ke 999 rupaye"])
def test_B4_answer_with_a_different_amount_where_none_was_asked(reply):
    first = run("Suresh ka 200 udhaar")
    r = answer(first, reply, ctx())
    assert not saved(r), r


# --- B5: corrections and cancel only right after an entry ---------------------------------------------------------

@pytest.mark.parametrize("action", ["question", "none", "query", "rejected"])
@pytest.mark.parametrize("utterance", ["nahi, 300", "nahi kal ka", "nahi jama", "galat, Sunita"])
def test_B5_no_correction_after_another_kind_of_turn(action, utterance):
    r = run(utterance, after_entry(age=70, action=action))
    assert not saved(r), r


@pytest.mark.parametrize("action", ["question", "none", "query"])
@pytest.mark.parametrize("utterance", ["cancel", "hata do", "undo karo"])
def test_B5_cancel_after_another_kind_of_turn_asks_the_undo_check(action, utterance):
    r = run(utterance, after_entry(age=70, action=action))
    assert not saved(r) and r.get("action") != "undo", r
    assert r["reason"] == "unclear_correction" and r["pending"]["mode"] == "confirm_undo", r


def test_B5_right_after_an_entry_corrections_still_work():
    r = run("nahi, 300", after_entry())
    assert r["action"] == "amend" and r["events"][0]["amount"] == 300
    assert run("hata do", after_entry())["action"] == "undo"


# --- B6: carry-over only by an explicit continuation; a first word before the amount is a name ------------------

@pytest.mark.parametrize("utterance,name", [
    ("Chacha 200 le gaye", "chacha"), ("Bhai 500 le gaya", "bhai"), ("Seth 500 le gaya", "seth"),
    ("Sara 500 le gayi", "sara"), ("Diya 200 le gayi", "diya"), ("Sham 300 le gaya", "sham"),
    ("Mila 500 le gayi", "mila"), ("Puri 500 le gaya", "puri"), ("Lala 200 de gaya", "lala"),
    ("Babu 200 de gaya", "babu"), ("Kamal 150 le gaya", "kamal"),
])
def test_B6_first_word_before_the_amount_is_the_customer(utterance, name):
    r = run(utterance, after_entry())
    assert r["status"] == "needs_clarification" and r["reason"] == "new_customer", r
    assert r["pending"]["events"][0]["customer"] == name


@pytest.mark.parametrize("utterance", ["500 udhaar", "200 jama", "Kal 500 le gaya", "300 payment aaya", "200 diya",
                                       "kal 200 diya tha", "150 diye", "200 payment mila"])
def test_B6_new_turn_without_name_asks_the_customer(utterance):
    r = run(utterance, after_entry())
    assert r["reason"] == "missing_customer", r


@pytest.mark.parametrize("utterance,kind,amount", [("aur 200", "credit", 200), ("200 aur", "credit", 200),
                                                   ("200 add kar do", "credit", 200), ("usne 50 diye", "payment", 50),
                                                   ("aur 100 jama", "payment", 100)])
def test_B6_explicit_continuations_still_carry(utterance, kind, amount):
    r = run(utterance, after_entry())
    assert entries(r) == [(kind, "ramesh", amount)], r


@pytest.mark.parametrize("reply", ["wahi", "usi ka", "same"])
def test_B6_wahi_picks_the_last_customer(reply):
    first = run("500 udhaar", after_entry())
    r = answer(first, reply, after_entry())
    assert entries(r) == [("credit", "ramesh", 500)], r


def test_B6_inside_one_utterance_the_customer_still_carries():
    r = run("Ramesh ka 340 udhaar, kal 200 diya tha", ctx(limits={"strict": False}))
    assert entries(r) == [("credit", "ramesh", 340), ("payment", "ramesh", 200)]


# --- B7: counts of goods are not rupees ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ko 12 ande udhaar", "Ramesh ko 50 bidi udhaar",
                                       "Ramesh 10 cigarette le gaya",
                                       "Ramesh 12 Maggi le gaya", "Ramesh took 12 eggs on credit",
                                       "रमेश को बारह अंडे उधार",
                                       "Sunita ko 2 doodh udhaar", "Ramesh ko teen sabun udhaar"])
def test_B7_count_of_goods_asks_the_price(utterance):
    r = run(utterance)
    assert not saved(r), r
    assert r["reason"] == "missing_amount" and r.get("quantity") is True, r


@pytest.mark.parametrize("utterance", ["Ramesh ko 20 20 rupaye ke 3 packet udhaar", "Ramesh ne 2 baar 100 diye",
                                       "Sunita ko 4 ande 40 rupaye ke udhaar"])
def test_B7_count_beside_an_amount_is_unsure(utterance):
    r = run(utterance)
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "unsure", r


def test_B7_goods_with_a_currency_word_are_an_amount():
    assert entries(run("Ramesh ko 50 rupaye ki bidi udhaar")) == [("credit", "ramesh", 50)]


# --- B8: saath / sath (with) ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh saaman saath le gaya", "Ramesh sath le gaya",
                                       "Ramesh ne paise sath diye",
                                       "रमेश सामान साथ ले गया", "Sunita saath mein 300 le gayi"])
def test_B8_saath_meaning_with_is_not_60(utterance):
    r = run(utterance)
    assert 60 not in [e["amount"] for e in r.get("events") or []], r
    assert 60 not in [e.get("amount") for e in (r.get("pending") or {}).get("events") or []], r


@pytest.mark.parametrize("utterance,amount", [("Ramesh ko saath rupaye udhaar", 60),
                                              ("Ramesh ko saath hazaar udhaar", 60000),
                                              ("रमेश को साठ रुपये उधार", 60)])
def test_B8_saath_in_a_number_phrase_or_with_currency_is_60(utterance, amount):
    r = run(utterance, ctx(limits={"strict": False}))
    amounts = [e.get("amount") for e in (r.get("events") or (r.get("pending") or {}).get("events") or [])]
    assert amounts == [amount], r


def test_B8_bare_saath_in_the_amount_position_confirms():
    r = run("Ramesh ka saath udhaar", ctx(limits={"strict": False}))
    assert r["reason"] == "plausibility", r


# --- B9: questions, negations and guesses -------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh ne 500 diye kya", "Ramesh ne 500 de diye kya?", "Ramesh ne 500 diye?",
                                       "Ramesh ne 500 diye na", "रमेश ने 500 दिए क्या", "has Ramesh paid 500",
                                       "is Ramesh paid 500", "Ramesh paid 500 right?", "Ramesh ne 500 diya hoga",
                                       "Ramesh ka 500 udhaar likha hai kya", "shayad Ramesh ne 500 diye",
                                       "Sunita ka 200 udhaar tha kya"])
def test_B9_questions_and_guesses_confirm(utterance):
    r = run(utterance, ctx(limits={"strict": False}))
    assert not saved(r), r
    assert r["status"] == "needs_clarification" and r["reason"] == "confirm_entry" and \
        r["confirm"]["type"] == "hearsay", r


def test_B9_a_did_question_is_never_saved():
    r = run("did Ramesh pay 500", ctx(limits={"strict": False}))
    assert r["status"] == "needs_clarification", r  # "pay" alone asks the direction first


@pytest.mark.parametrize("utterance", ["Ramesh ne 500 na diye", "रमेश ने पांच सौ न दिए",
                                       "Ramesh ka 500 udhaar na likhna",
                                       "Sunita ne 200 na diya"])
def test_B9_na_before_a_verb_is_a_negation(utterance):
    r = run(utterance)
    assert r["status"] == "rejected" and r["reason"] == "negated", r


@pytest.mark.parametrize("utterance", ["Ramesh ka 500 udhaar hai", "Ramesh ka 500 udhaar tha",
                                       "Ramesh pe 500 udhaar hai",
                                       "Sunita ka 300 udhaar hai"])
def test_B9_stative_sentence_confirms(utterance):
    r = run(utterance, ctx(limits={"strict": False}))
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "hearsay", r


def test_B9_ka_note_is_not_an_action_word():
    assert not saved(run("Ramesh ka 500 ka note", ctx(limits={"strict": False})))


# --- B10: English negation is never a correction --------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["Ramesh did not pay 500", "not paid 500", "Ramesh didn't pay 500",
                                       "Ramesh has not paid 500", "Ramesh never paid 500"])
def test_B10_english_negation_is_rejected(utterance):
    r = run(utterance, after_entry())
    assert r["status"] == "rejected" and r["reason"] == "negated", r


# --- B11: strict mode follows the entry through every question ---------------------------------------------------

@pytest.mark.parametrize("utterance", ["Mohan bina 500 diye chala gaya", "Ramesh bina 500 diye chala gaya"])
def test_B11_bina_is_a_negation(utterance):
    r = run(utterance)
    assert r["status"] == "rejected" and r["reason"] == "negated", r


def test_B11_hone_wala_tha_is_not_an_entry():
    r = run("Ramesh ka Monday ko 500 udhaar hone wala tha")
    assert not saved(r)
    assert r["status"] == "rejected" and r["reason"] == "future", r


def test_B11_unknown_words_are_confirmed_after_another_question():
    first = run("Mohan ne 500 phenk diye")
    assert first["reason"] == "new_customer"
    r = answer(first, "naya", ctx())
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "unsure" and "phenk" in r["confirm"]["words"]
    assert entries(answer(r, "haan", ctx())) == [("payment", "mohan", 500)]


def test_B11_unknown_words_survive_a_date_question():
    first = run("Ramesh ne somvar ko 500 phenk diye")
    assert first["reason"] == "unclear_date"
    r = answer(first, "kal", ctx())
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "unsure"


# --- B12: direction -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", ["took 500 from Ramesh", "I took 500 from Ramesh"])
def test_B12_took_from_is_a_payment(utterance):
    assert entries(run(utterance, ctx(limits={"strict": False}))) == [("payment", "ramesh", 500)]


@pytest.mark.parametrize("utterance", ["I paid Ramesh 500", "paid Ramesh 500", "Ramesh was paid 500", "Ramesh got 500",
                                       "Ramesh received 500 from me", "Ramesh collected 500", "I owe Ramesh 500",
                                       "I borrowed 500 from Ramesh", "Ramesh lent me 500", "Sunita got 200"])
def test_B12_shop_paying_or_owing_is_out_of_scope(utterance):
    r = run(utterance, ctx(limits={"strict": False}))
    assert r["status"] == "rejected" and r["reason"] == "out_of_scope", r


def test_B12_two_customers_paying_one_amount_asks():
    r = run("Ramesh and Sunita paid 500")
    assert r["reason"] == "missing_customer"  # 1.17: the amount and direction are kept
    assert r["pending"]["events"] == [{"kind": "payment", "amount": 500, "date": "2026-11-21"}]


@pytest.mark.parametrize("utterance", ["Ramesh ne 500 ka maal lautaya", "Ramesh ne saaman wapas kiya 200",
                                       "Ramesh se 500 ka saaman liya", "Sunita ne 300 ka saamaan wapas kiya"])
def test_B12_goods_returned_or_bought_asks_the_direction(utterance):
    r = run(utterance, ctx(limits={"strict": False}))
    assert r["reason"] == "ambiguous_direction", r


@pytest.mark.parametrize("utterance,expect", [("Ramesh paid 500", ("payment", "ramesh", 500)),
                                              ("received 500 from Ramesh", ("payment", "ramesh", 500)),
                                              ("got 300 from Sunita", ("payment", "sunita", 300)),
                                              ("Ramesh took 200 on credit", ("credit", "ramesh", 200))])
def test_B12_customer_side_english_still_works(utterance, expect):
    assert entries(run(utterance, ctx(limits={"strict": False}))) == [expect]


# --- Should-fix items ---------------------------------------------------------------------------------------------

def test_S_writeoff_is_a_last_event():
    last = {"kind": "writeoff", "customer": "ramesh", "customer_id": "c1", "amount": 40, "date": D0}
    c = ctx(last_event=last, last_events=[last], last_turn={"action": "append", "age_s": 5})
    assert run("undo karo", c)["action"] == "undo"
    r = run("nahi, 30", c)
    assert r["action"] == "amend" and r["events"][0]["kind"] == "writeoff" and r["events"][0]["amount"] == 30


@pytest.mark.parametrize("utterance", ["Ramesh ne 500 ka aadha diya", "Ramesh ne 500 se zyada diye",
                                       "Ramesh ko 500 nahi to 600 udhaar", "Ramesh ko lagbhag 500 udhaar",
                                       "Ramesh paid around 500", "Ramesh ko double 200 udhaar",
                                       "Ramesh ne 500 se kam diye"])
def test_S_amount_modifiers_confirm(utterance):
    r = run(utterance, ctx(limits={"strict": False}))
    assert not saved(r), r
    assert r["reason"] == "confirm_entry" and r["confirm"]["type"] == "unsure", r


def test_S_hoga_confirms():
    assert run("Ramesh ka 500 udhaar hoga", ctx(limits={"strict": False}))["confirm"]["type"] == "hearsay"


@pytest.mark.parametrize("utterance,day", [("Ramesh ne raat ko 500 diye", D0), ("Ramesh ne shaam ko 500 diye", D0),
                                           ("Ramesh ne kal raat ko 500 diye", D1), ("Ramesh ne subah ko 200 diye", D0),
                                           ("Ramesh ne dopahar ko 100 diye", D0)])
def test_S_time_word_before_ko_is_ignored(utterance, day):
    r = run(utterance)
    assert r["status"] == "ok" and r["events"][0]["customer"] == "ramesh" and r["events"][0]["date"] == day, r


@pytest.mark.parametrize("utterance", ["Ramesh ne 1 saal pehle 500 diye", "Ramesh ne do hafte pehle 500 diye",
                                       "Ramesh ne teen mahine pehle 500 diye"])
def test_S_weeks_months_years_ago_ask_the_date(utterance):
    assert run(utterance)["reason"] == "unclear_date"


def test_S_no_op_correction_asks():
    r = run("nahi 340", after_entry())
    assert r["reason"] == "unclear_correction"


@pytest.mark.parametrize("utterance,kind", [("that was credit not payment", "credit"), ("nahi, payment tha", "payment"),
                                            ("credit tha payment nahi", "credit"), ("jama tha udhaar nahi", "payment")])
def test_S_correction_naming_a_kind_changes_the_kind(utterance, kind):
    last = dict(LAST, kind="payment") if kind == "credit" else LAST
    c = ctx(last_event=last, last_events=[last], last_turn={"action": "append", "age_s": 5})
    r = run(utterance, c)
    assert r["action"] == "amend" and r["events"][0]["kind"] == kind, r


def test_S_yaad_is_not_a_reminder_word():
    r = run("yaad se Ramesh ko 500 udhaar likho")
    assert r.get("action") != "reminder"


@pytest.mark.parametrize("utterance,name", [("Kochar ko 500 udhaar", "kochar"), ("Kochhar ne 300 diye", "kochhar"),
                                            ("Sattar ko 500 udhaar", "sattar"), ("Das ko 200 udhaar", "das"),
                                            ("Assi ne 100 diye", "assi")])
def test_S_names_that_look_like_numbers_or_cuts_stay_whole(utterance, name):
    r = run(utterance)
    assert r["reason"] == "new_customer" and r["pending"]["events"][0]["customer"] == name, r


def test_S_glued_particle_number_still_cuts_with_a_stored_customer():
    assert entries(run("Sunita kofivehundred diya", ctx(limits={"strict": False}))) == [("credit", "sunita", 500)]


@pytest.mark.parametrize("utterance,reply,expect", [
    ("kal 200 diya tha", "wahi", ("payment", "ramesh", 200, D1)),
    ("kal 200 diya tha", "Ramesh", ("payment", "ramesh", 200, D1)),
    ("200 jama", "usi ka", ("payment", "ramesh", 200, D0)),
    ("500 udhaar", "same", ("credit", "ramesh", 500, D0)),
    ("kal 500 le gaya", "wahi", ("credit", "ramesh", 500, D1)),
    ("300 payment aaya", "Sunita", ("payment", "sunita", 300, D0)),
])
def test_B6_C01_the_kind_the_words_give_survives_the_customer_question(utterance, reply, expect):
    c = after_entry(limits={"strict": False})
    first = run(utterance, c)
    assert first["reason"] == "missing_customer"
    r = answer(first, reply, c)
    assert r["status"] == "ok", r
    e = r["events"][0]
    assert (e["kind"], e["customer"], e["amount"], e["date"]) == expect
