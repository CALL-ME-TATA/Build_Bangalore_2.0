"""I. Out of scope (docs/EDGE_CASES.md section I, CONTRACT 1.14)."""
from __future__ import annotations

import pytest

from .kit import expect_reject


@pytest.mark.parametrize("text", ["Wholesaler ko 5000 diya", "Supplier ko 5000 diye", "maal ka paisa 3000 diya"])
def test_I01_supplier_payments_are_not_customer_credit(rs, text):
    expect_reject(rs.say(text), "out_of_scope")


def test_I01_a_stored_customer_with_a_supplier_word_name_is_still_a_customer(shop):
    shop.seed(("agency", "credit", 100))
    t = shop.say("Agency ne 50 diye")
    assert t.status == "ok" and [(r["kind"], r["customer"], r["amount"]) for r in t.saved] == [
        ("payment", "agency", 50)], t.describe()


def test_I02_expense_is_rejected_with_the_fixed_reply(rs):
    t = rs.say("Dukaan ka kiraya 8000")
    expect_reject(t, "out_of_scope")
    assert t.reply_text.startswith("Yeh udhaar entry nahi hai"), t.describe()


def test_I03_cash_sale_is_rejected(rs):
    expect_reject(rs.say("Cash mein 300 becha"), "out_of_scope")
