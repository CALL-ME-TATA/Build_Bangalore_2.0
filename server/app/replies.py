"""Fixed spoken templates (CONTRACT section 5).

Every method returns `Reply(text, speak)`. `text` is Roman Hinglish with the rupee sign and digits, shown on screen.
`speak` is Devanagari with amounts written as words, sent to text-to-speech. No pressure language is used anywhere.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, NamedTuple

NumberToWords = Callable[[int, str], str]


class Reply(NamedTuple):
    text: str
    speak: str


def default_number_to_words() -> NumberToWords:
    """`nlu.speak.number_to_words` when it exists, otherwise plain digits."""
    try:
        from nlu.speak import number_to_words  # type: ignore[import-not-found]

        return number_to_words
    except Exception:
        return lambda n, script="deva": str(n)


def fmt_amount(n: int | float) -> str:
    """Rupee amount with Indian digit grouping, for example 125000 becomes 1,25,000."""
    n = int(n)
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups + [tail])


def _name(text: str) -> str:
    """Names and tags are spoken exactly as stored (Latin script inside Devanagari sentences)."""
    return text


class Replier:
    def __init__(self, number_to_words: NumberToWords | None = None):
        self._nw = number_to_words or default_number_to_words()

    def words(self, n: int | float) -> str:
        return self._nw(int(n), "deva")

    # ---- helpers ----------------------------------------------------------------------------------------------
    def _day_phrase(self, day: str | None, today: date | None) -> tuple[str, str]:
        """Return (roman, devanagari) phrases such as ('kal ke ', 'कल के ') or empty strings for today."""
        if not day or today is None:
            return "", ""
        try:
            diff = (today - date.fromisoformat(day)).days
        except ValueError:
            return "", ""
        if diff <= 0:
            return "", ""
        if diff == 1:
            return "kal ke ", "कल के "
        if diff == 2:
            return "parso ke ", "परसों के "
        return f"{diff} din pehle ke ", f"{self.words(diff)} दिन पहले के "

    # ---- moments ----------------------------------------------------------------------------------------------
    def disclosure(self) -> Reply:
        return Reply("Namaste! Main KhataVaani hoon, ek AI sahayak.", "नमस्ते! मैं खातावाणी हूँ, एक एआई सहायक।")

    def saved(self, events: list[dict], today: date | None = None) -> Reply:
        """Readback of saved events. Each event: kind, customer (display), amount, date, new_customer."""
        prefix_t = prefix_s = ""
        for ev in events:
            if ev.get("new_customer"):
                prefix_t += f"Naya khata {ev['customer']}. "
                prefix_s += f"नया खाता {_name(ev['customer'])}। "
        if len(events) == 1:
            ev = events[0]
            name, amt = ev["customer"], ev["amount"]
            dt, ds = self._day_phrase(ev.get("date"), today)
            nm_s = _name(name)
            if ev["kind"] == "credit":
                if dt:
                    t = f"{name} ke {dt}₹{fmt_amount(amt)} udhaar likhe."
                    s = f"{nm_s} के {ds}{self.words(amt)} रुपये उधार लिखे।"
                else:
                    t = f"{name} ke khate mein ₹{fmt_amount(amt)} udhaar likh diya."
                    s = f"{nm_s} के खाते में {self.words(amt)} रुपये उधार लिख दिया।"
            else:
                if dt:
                    t = f"{name} se {dt}₹{fmt_amount(amt)} jama kiye."
                    s = f"{nm_s} से {ds}{self.words(amt)} रुपये जमा किए।"
                else:
                    t = f"{name} se ₹{fmt_amount(amt)} mile, jama kar diya."
                    s = f"{nm_s} से {self.words(amt)} रुपये मिले, जमा कर दिया।"
            return Reply(prefix_t + t, prefix_s + s)
        parts_t, parts_s = [], []
        for ev in events:
            dt, ds = self._day_phrase(ev.get("date"), today)
            amt = ev["amount"]
            word_t, word_s = ("udhaar", "उधार") if ev["kind"] == "credit" else ("jama", "जमा")
            parts_t.append(f"{ev['customer']} ke {dt}₹{fmt_amount(amt)} {word_t}")
            parts_s.append(f"{_name(ev['customer'])} के {ds}{self.words(amt)} रुपये {word_s}")
        n = len(events)
        body_t = ", aur ".join([", ".join(parts_t[:-1]), parts_t[-1]]) if n > 1 else parts_t[0]
        body_s = ", और ".join([", ".join(parts_s[:-1]), parts_s[-1]])
        t = f"{n} entry likh di: {body_t}."
        s = f"{self.words(n)} एंट्री लिख दी: {body_s}।"
        return Reply(prefix_t + t, prefix_s + s)

    def amend(self, ev: dict) -> Reply:
        word_t, word_s = ("udhaar", "उधार") if ev["kind"] == "credit" else ("jama", "जमा")
        return Reply(f"Theek kar diya: {ev['customer']}, ₹{fmt_amount(ev['amount'])} {word_t}.",
                     f"ठीक कर दिया: {_name(ev['customer'])}, {self.words(ev['amount'])} रुपये {word_s}।")

    def undo(self, ev: dict) -> Reply:
        word_t, word_s = ("udhaar", "उधार") if ev["kind"] == "credit" else ("jama", "जमा")
        return Reply(f"Pichli entry hata di: {ev['customer']}, ₹{fmt_amount(ev['amount'])} {word_t}.",
                     f"पिछली एंट्री हटा दी: {_name(ev['customer'])}, {self.words(ev['amount'])} रुपये {word_s}।")

    def nothing_to_undo(self) -> Reply:
        return Reply("Pichli entry nahi mili.", "पिछली एंट्री नहीं मिली।")

    def confusable(self, a: int, b: int) -> Reply:
        return Reply(f"₹{fmt_amount(a)} ya ₹{fmt_amount(b)}?", f"{self.words(a)} रुपये या {self.words(b)} रुपये?")

    def same_name(self, name: str, tags: list[str]) -> Reply:
        labels = [t if t else "pehle wale" for t in tags[:2]]
        while len(labels) < 2:
            labels.append("doosre wale")
        return Reply(f"Kaunse {name}: {labels[0]} ya {labels[1]}?",
                     f"कौन से {_name(name)}: {_name(labels[0])} या {_name(labels[1])}?")

    def missing_amount(self) -> Reply:
        return Reply("Kitne rupaye?", "कितने रुपये?")

    def missing_customer(self) -> Reply:
        return Reply("Kiska khata?", "किसका खाता?")

    def direction(self, name: str) -> Reply:
        return Reply(f"{name} ne diye, ya {name} ko udhaar?",
                     f"{_name(name)} ने दिए, या {_name(name)} को उधार?")

    def plausibility(self, amount: int) -> Reply:
        return Reply(f"₹{fmt_amount(amount)}, pakka?", f"{self.words(amount)} रुपये, पक्का?")

    def unclear_correction(self) -> Reply:
        return Reply("Sahi amount boliye, ya hata do boliye.", "सही अमाउंट बोलिए, या हटा दो बोलिए।")

    def unclear_date(self) -> Reply:
        return Reply("Kaunsa din? Aaj, kal ya parso boliye.", "कौन सा दिन? आज, कल या परसों बोलिए।")

    def cancelled(self) -> Reply:
        return Reply("Theek hai, entry nahi ki.", "ठीक है, एंट्री नहीं की।")

    def rejected(self) -> Reply:
        return Reply("Maaf kijiye, samajh nahi aaya. Dobara boliye.", "माफ़ कीजिए, समझ नहीं आया। दोबारा बोलिए।")

    def upstream_failure(self) -> Reply:
        return Reply("Network mein dikkat hai, dobara boliye.", "नेटवर्क में दिक्कत है, दोबारा बोलिए।")

    # ---- queries ----------------------------------------------------------------------------------------------
    def balance(self, name: str, balance: int) -> Reply:
        nm = _name(name)
        if balance > 0:
            return Reply(f"{name} ke ₹{fmt_amount(balance)} baaki hain.",
                         f"{nm} के {self.words(balance)} रुपये बाकी हैं।")
        if balance == 0:
            return Reply(f"{name} ka kuch baaki nahi.", f"{nm} का कुछ बाकी नहीं।")
        return Reply(f"{name} ke ₹{fmt_amount(-balance)} zyada jama hain.",
                     f"{nm} के {self.words(-balance)} रुपये ज़्यादा जमा हैं।")

    def credit_total(self, amount: int) -> Reply:
        if amount <= 0:
            return Reply("Aaj koi udhaar nahi gaya.", "आज कोई उधार नहीं गया।")
        return Reply(f"Aaj ₹{fmt_amount(amount)} udhaar gaya.", f"आज {self.words(amount)} रुपये उधार गया।")

    def payment_total(self, amount: int) -> Reply:
        if amount <= 0:
            return Reply("Aaj koi paisa jama nahi hua.", "आज कोई पैसा जमा नहीं हुआ।")
        return Reply(f"Aaj ₹{fmt_amount(amount)} jama hue.", f"आज {self.words(amount)} रुपये जमा हुए।")

    def daily_summary(self, summary: dict) -> Reply:
        if not summary.get("count"):
            return Reply("Aaj abhi tak koi entry nahi.", "आज अभी तक कोई एंट्री नहीं।")
        c, p = summary["credit"], summary["payment"]
        t = f"Aaj ₹{fmt_amount(c)} udhaar gaya, ₹{fmt_amount(p)} jama hue."
        s = f"आज {self.words(c)} रुपये उधार गया, {self.words(p)} रुपये जमा हुए।"
        if summary.get("top"):
            name, amt = summary["top"]
            t += f" Sabse zyada baaki: {name}, ₹{fmt_amount(amt)}."
            s += f" सबसे ज़्यादा बाकी: {_name(name)}, {self.words(amt)} रुपये।"
        return Reply(t, s)

    def top_dues(self, dues: list[tuple[str, int]]) -> Reply:
        if not dues:
            return Reply("Kisi ka kuch baaki nahi.", "किसी का कुछ बाकी नहीं।")
        t = "Sabse zyada baaki: " + ", ".join(f"{n} ₹{fmt_amount(a)}" for n, a in dues) + "."
        s = "सबसे ज़्यादा बाकी: " + ", ".join(f"{_name(n)} {self.words(a)} रुपये" for n, a in dues) + "।"
        return Reply(t, s)

    # ---- clarification dispatcher -----------------------------------------------------------------------------
    def clarification(self, result: dict) -> Reply | None:
        """Template for a needs_clarification result, or None when the reason is unknown."""
        reason = result.get("reason")
        pending = result.get("pending") or {}
        events = pending.get("events") or []
        cands = result.get("candidates") or pending.get("candidates") or []
        if reason == "confusable_number" and len(cands) >= 2:
            return self.confusable(int(cands[0]), int(cands[1]))
        if reason == "same_name" and cands:
            name = str(cands[0].get("name", "")).title()
            return self.same_name(name, [c.get("tags", [None])[0] if c.get("tags") else "" for c in cands])
        if reason == "plausibility":
            amounts = [e["amount"] for e in events if isinstance(e.get("amount"), int)]
            if amounts:
                return self.plausibility(max(amounts))
        if reason == "missing_amount":
            return self.missing_amount()
        if reason == "missing_customer":
            return self.missing_customer()
        if reason == "ambiguous_direction":
            name = next((str(e["customer"]).title() for e in events if e.get("customer")), "")
            return self.direction(name or "Customer")
        if reason == "unclear_correction":
            return self.unclear_correction()
        if reason == "unclear_date":
            return self.unclear_date()
        return None

    def reminder(self, name: str, amount: int) -> str:
        """Polite reminder text for an opted-in customer (Roman Hinglish, sent through a wa.me link)."""
        return (f"Namaste {name} ji, aapke khate mein ₹{fmt_amount(amount)} baaki hain. "
                f"Jab suvidha ho, bhej dijiye. Dhanyavaad.")
