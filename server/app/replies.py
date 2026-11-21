"""Fixed spoken templates (CONTRACT sections 5, 5.1 and 3.2).

Every method returns `Reply(text, speak)`. `text` is shown on screen: Roman Hinglish (or English) with the rupee sign
and digits. `speak` goes to text-to-speech: Devanagari (or plain English) with amounts written as words by
`nlu.speak.number_to_words`. No pressure language is used anywhere, and every reply stays near twelve words.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, NamedTuple

from .names import display_name, spoken

NumberToWords = Callable[[int, str], str]
NameOf = Callable[[dict], str]

CRORE = 10_000_000
MONTHS_HI = ["janvari", "farvari", "march", "april", "mai", "joon", "julai", "agast", "sitambar", "aktoobar",
             "navambar", "disambar"]
MONTHS_DEVA = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर",
               "दिसंबर"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
PERIOD_HI = {"today": ("Aaj", "आज"), "yesterday": ("Kal", "कल"), "this_week": ("Is hafte", "इस हफ़्ते"),
             "last_week": ("Pichle hafte", "पिछले हफ़्ते"), "this_month": ("Is mahine", "इस महीने"),
             "last_month": ("Pichle mahine", "पिछले महीने")}
PERIOD_EN = {"today": "Today", "yesterday": "Yesterday", "this_week": "This week", "last_week": "Last week",
             "this_month": "This month", "last_month": "Last month"}
KIND_HI = {"credit": ("udhaar", "उधार"), "payment": ("jama", "जमा"), "writeoff": ("maaf", "माफ़")}
KIND_EN = {"credit": "credit", "payment": "payment", "writeoff": "write-off"}


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
    """Names are spoken as stored (Latin script inside Devanagari sentences), or by their `say` spelling."""
    return spoken(text)


def _key_name(ev: dict) -> str:
    return display_name(str(ev.get("customer") or ""))


class Replier:
    """Hinglish replies. `EnglishReplier` overrides every template."""

    lang = "hi"

    def __init__(self, number_to_words: NumberToWords | None = None):
        self._nw = number_to_words or default_number_to_words()

    def with_lang(self, lang: str) -> "Replier":
        """A replier for `lang` ("hi" or "en") that shares the number-to-words function."""
        return EnglishReplier(self._nw) if lang == "en" else Replier(self._nw)

    _script = "deva"
    _crore_word = "करोड़"

    def words(self, n: int | float) -> str:
        """Amount as spoken words. Never raises: amounts past the number-to-words range are split into crores,
        and digits are the last resort."""
        n = int(n)
        try:
            return self._nw(n, self._script)
        except Exception:
            pass
        try:
            if n >= CRORE:
                crores, rest = divmod(n, CRORE)
                head = f"{self.words(crores)} {self._crore_word}"
                return f"{head} {self._nw(rest, self._script)}" if rest else head
        except Exception:
            pass
        return str(n)

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

    @staticmethod
    def _kind(kind: str) -> tuple[str, str]:
        return KIND_HI.get(kind, KIND_HI["payment"])

    # ---- moments ----------------------------------------------------------------------------------------------
    def disclosure(self) -> Reply:
        return Reply("Namaste! Main KhataVaani hoon, ek AI sahayak.", "नमस्ते! मैं खातावाणी हूँ, एक एआई सहायक।")

    def saved(self, events: list[dict], today: date | None = None) -> Reply:
        """Readback of saved events. Each event: kind, customer (display), amount, date, new_customer."""
        prefix_t = prefix_s = ""
        announced: set = set()
        for ev in events:
            who = ev.get("customer_id") or ev["customer"]
            if ev.get("new_customer") and who not in announced:
                announced.add(who)
                prefix_t += f"Naya khata {ev['customer']}. "
                prefix_s += f"नया खाता {_name(ev['customer'])}। "
        if len(events) == 1:
            ev = events[0]
            name, amt = ev["customer"], ev["amount"]
            dt, ds = self._day_phrase(ev.get("date"), today)
            nm_s = _name(name)
            if ev["kind"] == "writeoff":
                t = f"{name} ke {dt}₹{fmt_amount(amt)} maaf kiye."
                s = f"{nm_s} के {ds}{self.words(amt)} रुपये माफ़ किए।"
            elif ev["kind"] == "credit":
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
        n, body_t, body_s = self._several(events, today)
        t = f"{n} entry likhi: {body_t}."
        s = f"{self.words(n)} एंट्री लिखी: {body_s}।"
        return Reply(prefix_t + t, prefix_s + s)

    def _several(self, events: list[dict], today: date | None) -> tuple[int, str, str]:
        """(count, shown body, spoken body) of the several-entries reply: "Ramesh ke ₹340 udhaar, kal ke ₹200 jama"."""
        parts_t, parts_s = [], []
        prev = None
        for ev in events:
            dt, ds = self._day_phrase(ev.get("date"), today)
            amt = ev["amount"]
            word_t, word_s = self._kind(ev["kind"])
            # The name is said once for a run of entries of the same customer (section 5: "kal ke ₹200 jama").
            same = ev["customer"] == prev
            prev = ev["customer"]
            who_t = "" if same else f"{ev['customer']} ke "
            who_s = "" if same else f"{_name(ev['customer'])} के "
            parts_t.append(f"{who_t}{dt}₹{fmt_amount(amt)} {word_t}")
            parts_s.append(f"{who_s}{ds}{self.words(amt)} रुपये {word_s}")
        return len(events), ", ".join(parts_t), ", ".join(parts_s)

    def confirm_entries(self, events: list[dict], today: date | None = None) -> Reply:
        """One question about several pending entries: "2 entry likhun: Ramesh ke ₹340 udhaar, kal ke ₹200 jama?"."""
        n, body_t, body_s = self._several(events, today)
        return Reply(f"{n} entry likhun: {body_t}?", f"{self.words(n)} एंट्री लिखूँ: {body_s}?")

    def amend(self, ev: dict) -> Reply:
        word_t, word_s = self._kind(ev["kind"])
        return Reply(f"Theek kar diya: {ev['customer']}, ₹{fmt_amount(ev['amount'])} {word_t}.",
                     f"ठीक कर दिया: {_name(ev['customer'])}, {self.words(ev['amount'])} रुपये {word_s}।")

    def undo(self, ev: dict) -> Reply:
        word_t, word_s = self._kind(ev["kind"])
        return Reply(f"Pichli entry hata di: {ev['customer']}, ₹{fmt_amount(ev['amount'])} {word_t}.",
                     f"पिछली एंट्री हटा दी: {_name(ev['customer'])}, {self.words(ev['amount'])} रुपये {word_s}।")

    def entry_not_found(self) -> Reply:
        """A targeted amend whose event is no longer active or belongs to another session (section 3.1)."""
        return Reply("Pichli entry nahi mili.", "पिछली एंट्री नहीं मिली।")

    def nothing_to_amend(self) -> Reply:
        return Reply("Pehle koi entry nahi hai.", "पहले कोई एंट्री नहीं है।")

    def nothing_to_undo(self) -> Reply:
        return Reply("Undo karne ke liye kuch nahi hai.", "अनडू करने के लिए कुछ नहीं है।")

    def entry_removed(self) -> Reply:
        return Reply("Woh entry hat chuki hai. Poori entry dobara boliye.",
                     "वह एंट्री हट चुकी है। पूरी एंट्री दोबारा बोलिए।")

    def confusable(self, a: int, b: int) -> Reply:
        return Reply(f"₹{fmt_amount(a)} ya ₹{fmt_amount(b)}?", f"{self.words(a)} रुपये या {self.words(b)} रुपये?")

    def same_name(self, name: str, tags: list[str]) -> Reply:
        labels = [t if t else "pehle wale" for t in tags[:2]]
        while len(labels) < 2:
            labels.append("doosre wale")
        return Reply(f"Kaunse {name}: {labels[0]} ya {labels[1]}?",
                     f"कौन से {_name(name)}: {_name(labels[0])} या {_name(labels[1])}?")

    def which_entry(self, a: dict, b: dict) -> Reply:
        (at, as_), (bt, bs) = self._kind(a["kind"]), self._kind(b["kind"])
        return Reply(f"Kaunsi entry: ₹{fmt_amount(a['amount'])} {at} ya ₹{fmt_amount(b['amount'])} {bt}?",
                     f"कौनसी एंट्री: {self.words(a['amount'])} रुपये {as_} या {self.words(b['amount'])} रुपये {bs}?")

    def undo_check(self, name: str, amount: int, kind: str) -> Reply:
        word_t, word_s = self._kind(kind)
        return Reply(f"Sirf pichli entry hata sakta hoon: {name}, ₹{fmt_amount(amount)} {word_t}. Hata doon?",
                     f"सिर्फ़ पिछली एंट्री हटा सकता हूँ: {_name(name)}, {self.words(amount)} रुपये {word_s}। हटा दूँ?")

    def replace_check(self) -> Reply:
        return Reply("Pichli entry hata kar yeh likhoon?", "पिछली एंट्री हटा कर यह लिखूँ?")

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

    # ---- section 5.1: rejections, recordings, private mode ----------------------------------------------------
    def future(self) -> Reply:
        return Reply("Yeh baad ki baat hai, abhi kuch nahi likha.", "यह बाद की बात है, अभी कुछ नहीं लिखा।")

    def negated(self) -> Reply:
        return Reply("Theek hai, kuch nahi likha.", "ठीक है, कुछ नहीं लिखा।")

    def out_of_scope(self) -> Reply:
        return Reply("Yeh udhaar entry nahi hai, isliye nahi likha.", "यह उधार एंट्री नहीं है, इसलिए नहीं लिखा।")

    def too_large(self) -> Reply:
        return Reply("Itni badi rakam nahi likh sakta.", "इतनी बड़ी रकम नहीं लिख सकता।")

    def no_question(self) -> Reply:
        return Reply("Kis baare mein?", "किस बारे में?")

    def silence(self) -> Reply:
        return Reply("Kuch sunai nahi diya. Dobara boliye.", "कुछ सुनाई नहीं दिया। दोबारा बोलिए।")

    def too_long(self) -> Reply:
        return Reply("Bahut lamba ho gaya. Chhote vaakya mein boliye.", "बहुत लंबा हो गया। छोटे वाक्य में बोलिए।")

    def private(self) -> Reply:
        return Reply("Jawab screen par hai.", "जवाब स्क्रीन पर है।")

    # ---- section 5.1: questions -------------------------------------------------------------------------------
    def new_customer(self, name: str, close: list[str] | None = None) -> Reply:
        if close:
            ct, cs = " ya ".join(close[:2]), " या ".join(_name(c) for c in close[:2])
            return Reply(f"{name} naya grahak hai, ya {ct}?", f"{_name(name)} नया ग्राहक है, या {cs}?")
        return Reply(f"{name} naya grahak hai. Khata banaun?", f"{_name(name)} नया ग्राहक है। खाता बनाऊँ?")

    def name_alone(self, name: str) -> Reply:
        return Reply(f"{name} ka kya likhun?", f"{_name(name)} का क्या लिखूँ?")

    def quantity(self) -> Reply:
        return Reply("Kitne ka?", "कितने का?")

    def confirm_entry(self, name: str, kind: str, amount: int, day: str | None = None,
                      today: date | None = None) -> Reply:
        dt, ds = self._day_phrase(day, today)
        if kind == "credit":
            return Reply(f"{name} ke {dt}₹{fmt_amount(amount)} udhaar likhun?",
                         f"{_name(name)} के {ds}{self.words(amount)} रुपये उधार लिखूँ?")
        if kind == "writeoff":
            return Reply(f"{name} ke {dt}₹{fmt_amount(amount)} maaf karun?",
                         f"{_name(name)} के {ds}{self.words(amount)} रुपये माफ़ करूँ?")
        return Reply(f"{name} se {dt}₹{fmt_amount(amount)} jama likhun?",
                     f"{_name(name)} से {ds}{self.words(amount)} रुपये जमा लिखूँ?")

    def confirm_settle(self, name: str, balance: int) -> Reply:
        return Reply(f"{name} ke ₹{fmt_amount(balance)} baaki hain. Poore jama likhun?",
                     f"{_name(name)} के {self.words(balance)} रुपये बाकी हैं। पूरे जमा लिखूँ?")

    def confirm_half(self, name: str, amount: int) -> Reply:
        return Reply(f"Aadha yaani ₹{fmt_amount(amount)}. {name} se jama likhun?",
                     f"आधा यानी {self.words(amount)} रुपये। {_name(name)} से जमा लिखूँ?")

    def confirm_writeoff(self, name: str, balance: int) -> Reply:
        return Reply(f"{name} ke ₹{fmt_amount(balance)} baaki hain. Poore maaf karun?",
                     f"{_name(name)} के {self.words(balance)} रुपये बाकी हैं। पूरे माफ़ करूँ?")

    def confirm_roundoff(self, name: str, balance: int, amount: int) -> Reply:
        return Reply(f"{name} ke ₹{fmt_amount(balance)} baaki hain. ₹{fmt_amount(amount)} chhod doon?",
                     f"{_name(name)} के {self.words(balance)} रुपये बाकी हैं। {self.words(amount)} रुपये छोड़ दूँ?")

    def confirm_overpayment(self, name: str, balance: int, amount: int) -> Reply:
        if balance > 0:
            return Reply(f"{name} ke sirf ₹{fmt_amount(balance)} baaki hain. ₹{fmt_amount(amount)} hi likhun?",
                         f"{_name(name)} के सिर्फ़ {self.words(balance)} रुपये बाकी हैं। "
                         f"{self.words(amount)} रुपये ही लिखूँ?")
        return Reply(f"{name} ka kuch baaki nahi. ₹{fmt_amount(amount)} advance likhun?",
                     f"{_name(name)} का कुछ बाकी नहीं। {self.words(amount)} रुपये एडवांस लिखूँ?")

    def confirm_duplicate(self) -> Reply:
        return Reply("Yeh entry abhi likhi hai. Ek aur likhun?", "यह एंट्री अभी लिखी है। एक और लिखूँ?")

    # ---- queries ----------------------------------------------------------------------------------------------
    def balance(self, name: str, balance: int, has_entries: bool = True) -> Reply:
        nm = _name(name)
        if not has_entries:
            return self.no_entries(name)
        if balance > 0:
            return Reply(f"{name} ke ₹{fmt_amount(balance)} baaki hain.",
                         f"{nm} के {self.words(balance)} रुपये बाकी हैं।")
        if balance == 0:
            return Reply(f"{name} ka hisaab barabar hai.", f"{nm} का हिसाब बराबर है।")
        return Reply(f"{name} ke ₹{fmt_amount(-balance)} zyada jama hain.",
                     f"{nm} के {self.words(-balance)} रुपये ज़्यादा जमा हैं।")

    def no_entries(self, name: str) -> Reply:
        return Reply(f"{name} ka koi hisaab nahi hai.", f"{_name(name)} का कोई हिसाब नहीं है।")

    @staticmethod
    def _period(period: str) -> tuple[str, str]:
        return PERIOD_HI.get(period, PERIOD_HI["today"])

    def credit_total(self, amount: int, period: str = "today") -> Reply:
        day_t, day_s = self._period(period)
        if amount <= 0:
            return Reply(f"{day_t} koi udhaar nahi gaya.", f"{day_s} कोई उधार नहीं गया।")
        return Reply(f"{day_t} ₹{fmt_amount(amount)} udhaar gaya.", f"{day_s} {self.words(amount)} रुपये उधार गया।")

    def payment_total(self, amount: int, period: str = "today") -> Reply:
        day_t, day_s = self._period(period)
        if amount <= 0:
            return Reply(f"{day_t} koi paisa jama nahi hua.", f"{day_s} कोई पैसा जमा नहीं हुआ।")
        return Reply(f"{day_t} ₹{fmt_amount(amount)} jama hue.", f"{day_s} {self.words(amount)} रुपये जमा हुए।")

    def unknown_customer(self, name: str) -> Reply:
        return Reply(f"{name} ka khata nahi mila.", f"{_name(name)} का खाता नहीं मिला।")

    def daily_summary(self, summary: dict, period: str = "today") -> Reply:
        day_t, day_s = self._period(period)
        if not summary.get("count"):
            if period == "today":
                return Reply("Aaj abhi tak koi entry nahi.", "आज अभी तक कोई एंट्री नहीं।")
            if period == "yesterday":
                return Reply("Kal koi entry nahi thi.", "कल कोई एंट्री नहीं थी।")
            return Reply(f"{day_t} koi entry nahi.", f"{day_s} कोई एंट्री नहीं।")
        c, p = summary["credit"], summary["payment"]
        t = f"{day_t} ₹{fmt_amount(c)} udhaar gaya, ₹{fmt_amount(p)} jama hue."
        s = f"{day_s} {self.words(c)} रुपये उधार गया, {self.words(p)} रुपये जमा हुए।"
        if summary.get("top") and period in ("today", "yesterday"):
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

    def outstanding_total(self, amount: int, customers: int) -> Reply:
        if amount <= 0:
            return self.top_dues([])
        return Reply(f"Kul baaki ₹{fmt_amount(amount)} hai, {customers} grahakon par.",
                     f"कुल बाकी {self.words(amount)} रुपये है, {self.words(customers)} ग्राहकों पर।")

    def due_since(self, name: str, day: date) -> Reply:
        return Reply(f"{name} ka {day.day} {MONTHS_HI[day.month - 1]} se baaki hai.",
                     f"{_name(name)} का {self.words(day.day)} {MONTHS_DEVA[day.month - 1]} से बाकी है।")

    # ---- reminders (Q08) --------------------------------------------------------------------------------------
    def reminder_ready(self, name: str) -> Reply:
        return Reply(f"{name} ka reminder taiyaar hai, screen par dekhiye.",
                     f"{_name(name)} का रिमाइंडर तैयार है, स्क्रीन पर देखिए।")

    def reminder_no_consent(self, name: str) -> Reply:
        return Reply(f"{name} ne reminder ke liye haan nahi kaha hai.",
                     f"{_name(name)} ने रिमाइंडर के लिए हाँ नहीं कहा है।")

    def reminder_nothing_due(self, name: str) -> Reply:
        return Reply(f"{name} ka kuch baaki nahi, reminder nahi banaya.",
                     f"{_name(name)} का कुछ बाकी नहीं, रिमाइंडर नहीं बनाया।")

    def reminder_confirm(self, name: str, balance: int, said: int) -> Reply:
        b, s = fmt_amount(balance), fmt_amount(said)
        return Reply(f"{name} ke ₹{b} baaki hain, ₹{s} nahi. ₹{b} ka reminder banaun?",
                     f"{_name(name)} के {self.words(balance)} रुपये बाकी हैं, {self.words(said)} रुपये नहीं। "
                     f"{self.words(balance)} रुपये का रिमाइंडर बनाऊँ?")

    def reminder_quiet(self) -> Reply:
        return Reply("Reminder subah 9 se raat 8 baje ke beech hi bante hain.",
                     "रिमाइंडर सुबह नौ से रात आठ बजे के बीच ही बनते हैं।")

    def reminder_message(self, name: str, amount: int) -> str:
        """The customer-facing reminder (sent through a wa.me link): short, polite, no item details."""
        return f"Namaste {name} ji, aapke khate mein ₹{fmt_amount(amount)} baaki hain. Suvidha se bhej dijiye. Dhanyavaad."

    def reminder(self, name: str, amount: int) -> str:
        return self.reminder_message(name, amount)

    # ---- clarification dispatcher -----------------------------------------------------------------------------
    def clarification(self, result: dict, name_of: NameOf | None = None, today: date | None = None) -> Reply | None:
        """Template for a needs_clarification result, built from its structured fields; None when the reason
        (or the confirm type) is unknown, so the caller can fall back to the parser's question."""
        name_of = name_of or _key_name
        reason = result.get("reason")
        pending = result.get("pending") or {}
        events = [e for e in (pending.get("events") or result.get("events") or []) if isinstance(e, dict)]
        cands = result.get("candidates") or pending.get("candidates") or []
        named = next((e for e in events if e.get("customer") or e.get("customer_id")), None)
        if reason == "confusable_number" and len(cands) >= 2:
            return self.confusable(int(cands[0]), int(cands[1]))
        if reason == "same_name" and cands:
            name = display_name(str(cands[0].get("name", "")))
            return self.same_name(name, [c.get("tags", [None])[0] if c.get("tags") else "" for c in cands])
        if reason == "plausibility":
            amounts = [e["amount"] for e in events if isinstance(e.get("amount"), int)]
            if amounts:
                return self.plausibility(max(amounts))
        if reason == "missing_amount":
            if result.get("quantity") or pending.get("quantity"):
                return self.quantity()
            if (len(events) == 1 and named is not None and "kind" not in named and "amount" not in named
                    and pending.get("action", "append") == "append"):
                return self.name_alone(name_of(named))
            return self.missing_amount()
        if reason == "missing_customer":
            return self.missing_customer()
        if reason == "ambiguous_direction":
            name = name_of(named) if named else ""
            return self.direction(name or "Customer")
        if reason == "new_customer":
            target = next((e for e in events if e.get("new_customer")), named)
            if target is None:
                return None
            close = [display_name(str(c.get("name") or "")) for c in cands if isinstance(c, dict) and c.get("name")]
            return self.new_customer(name_of(target), close)
        if reason == "confirm_entry":
            return self._confirm(result, pending, events, name_of, today)
        if reason == "unclear_correction":
            kinds = ("credit", "payment", "writeoff")
            usable = [c for c in cands if isinstance(c, dict) and c.get("kind") in kinds
                      and isinstance(c.get("amount"), int)]
            if len(usable) >= 2:
                return self.which_entry(usable[0], usable[1])
            ev = events[0] if events else {}
            if pending.get("action") == "undo" and ev.get("kind") in kinds and ev.get("amount") and ev.get("customer"):
                return self.undo_check(name_of(ev), ev["amount"], ev["kind"])
            if (pending.get("action") == "amend" and ev.get("kind") in kinds and ev.get("amount")
                    and ev.get("customer")):
                return self.replace_check()
            return self.unclear_correction()
        if reason == "unclear_date":
            return self.unclear_date()
        return None

    def _confirm(self, result: dict, pending: dict, events: list[dict], name_of: NameOf,
                 today: date | None) -> Reply | None:
        confirm = result.get("confirm") or pending.get("confirm") or {}
        ctype = confirm.get("type")
        ev = events[0] if events else {}
        amount = ev.get("amount") if isinstance(ev.get("amount"), int) else None
        balance = confirm.get("balance") if isinstance(confirm.get("balance"), int) else None
        name = name_of(ev) if ev else name_of({"customer": result.get("customer") or pending.get("customer"),
                                               "customer_id": result.get("customer_id")
                                               or pending.get("customer_id")})
        if ctype == "duplicate":
            return self.confirm_duplicate()
        if ctype == "reminder":
            said = confirm.get("said")
            if balance is not None and isinstance(said, int):
                return self.reminder_confirm(name, balance, said)
            return None
        if not name:
            return None
        if ctype in ("computed", "hearsay", "unsure"):
            # `unsure` (strict mode): the unknown words in `confirm.words` are never spoken or shown.
            full = [e for e in events if isinstance(e.get("amount"), int) and e.get("kind")
                    and (e.get("customer") or e.get("customer_id"))]
            if len(events) > 1 and len(full) == len(events):
                return self.confirm_entries([dict(e, customer=name_of(e)) for e in full], today)
            if amount is not None and ev.get("kind"):
                return self.confirm_entry(name, ev["kind"], amount, ev.get("date"), today)
            return None
        if ctype == "settle" and (balance is not None or amount is not None):
            return self.confirm_settle(name, balance if balance is not None else amount)
        if ctype == "half" and amount is not None:
            return self.confirm_half(name, amount)
        if ctype == "writeoff" and (balance is not None or amount is not None):
            return self.confirm_writeoff(name, balance if balance is not None else amount)
        if ctype == "roundoff" and balance is not None and amount is not None:
            return self.confirm_roundoff(name, balance, amount)
        if ctype == "overpayment" and amount is not None:
            return self.confirm_overpayment(name, balance or 0, amount)
        return None


class EnglishReplier(Replier):
    """English replies (CONTRACT section 3.2). Speech is plain English; amounts are `number_to_words(n, "en")`."""

    lang = "en"
    _script = "en"
    _crore_word = "crore"

    def _rs(self, n: int | float) -> str:
        return f"{self.words(n)} rupees"

    @staticmethod
    def _same(text: str, spoken_text: str | None = None) -> Reply:
        return Reply(text, spoken_text if spoken_text is not None else text)

    @staticmethod
    def _day(day: str | None, today: date | None) -> str:
        if not day or today is None:
            return ""
        try:
            diff = (today - date.fromisoformat(day)).days
        except ValueError:
            return ""
        if diff <= 0:
            return ""
        if diff == 1:
            return "yesterday"
        if diff == 2:
            return "the day before yesterday"
        return f"{diff} days ago"

    def disclosure(self) -> Reply:
        return self._same("Hello! I am KhataVaani, an AI assistant.")

    def saved(self, events: list[dict], today: date | None = None) -> Reply:
        pre_t = pre_s = ""
        announced: set = set()
        for ev in events:
            who = ev.get("customer_id") or ev["customer"]
            if ev.get("new_customer") and who not in announced:
                announced.add(who)
                pre_t += f"New account for {ev['customer']}. "
                pre_s += f"New account for {_name(ev['customer'])}. "
        if len(events) == 1:
            ev = events[0]
            name, amt, day = ev["customer"], ev["amount"], self._day(ev.get("date"), today)
            nm = _name(name)
            tail = f", dated {day}" if day else ""
            if ev["kind"] == "writeoff":
                t = f"Wrote off ₹{fmt_amount(amt)} for {name}{tail}."
                s = f"Wrote off {self._rs(amt)} for {nm}{tail}."
            elif ev["kind"] == "credit":
                t = f"Added ₹{fmt_amount(amt)} credit for {name}{tail}."
                s = f"Added {self._rs(amt)} credit for {nm}{tail}."
            else:
                t = f"Received ₹{fmt_amount(amt)} from {name}{tail}."
                s = f"Received {self._rs(amt)} from {nm}{tail}."
            return Reply(pre_t + t, pre_s + s)
        n, body_t, body_s = self._several(events, today)
        return Reply(f"{pre_t}{n} entries: {body_t}.", f"{pre_s}{self.words(n)} entries: {body_s}.")

    def _several(self, events: list[dict], today: date | None) -> tuple[int, str, str]:
        parts_t, parts_s = [], []
        prev = None
        for ev in events:
            amt, day = ev["amount"], self._day(ev.get("date"), today)
            show_name = ev["customer"] != prev
            prev = ev["customer"]
            if ev["kind"] == "credit":
                t, s, prep = f"₹{fmt_amount(amt)} credit", f"{self._rs(amt)} credit", "for"
            elif ev["kind"] == "writeoff":
                t, s, prep = f"₹{fmt_amount(amt)} written off", f"{self._rs(amt)} written off", "for"
            else:
                t, s, prep = f"₹{fmt_amount(amt)} received", f"{self._rs(amt)} received", "from"
            who_t = f" {prep} {ev['customer']}" if show_name else ""
            who_s = f" {prep} {_name(ev['customer'])}" if show_name else ""
            suffix = f" {day}" if day else ""
            parts_t.append(t + who_t + suffix)
            parts_s.append(s + who_s + suffix)
        body_t = ", ".join(parts_t[:-1]) + ", and " + parts_t[-1]
        body_s = ", ".join(parts_s[:-1]) + ", and " + parts_s[-1]
        return len(events), body_t, body_s

    def confirm_entries(self, events: list[dict], today: date | None = None) -> Reply:
        n, body_t, body_s = self._several(events, today)
        return Reply(f"Save {n} entries: {body_t}?", f"Save {self.words(n)} entries: {body_s}?")

    def amend(self, ev: dict) -> Reply:
        k = KIND_EN.get(ev["kind"], ev["kind"])
        return Reply(f"Corrected: {ev['customer']}, ₹{fmt_amount(ev['amount'])} {k}.",
                     f"Corrected: {_name(ev['customer'])}, {self._rs(ev['amount'])} {k}.")

    def undo(self, ev: dict) -> Reply:
        k = KIND_EN.get(ev["kind"], ev["kind"])
        return Reply(f"Removed the last entry: {ev['customer']}, ₹{fmt_amount(ev['amount'])} {k}.",
                     f"Removed the last entry: {_name(ev['customer'])}, {self._rs(ev['amount'])} {k}.")

    def entry_not_found(self) -> Reply:
        return self._same("No previous entry found.")

    def nothing_to_amend(self) -> Reply:
        return self._same("There is no earlier entry.")

    def nothing_to_undo(self) -> Reply:
        return self._same("There is nothing to undo.")

    def entry_removed(self) -> Reply:
        return self._same("That entry was removed. Please say the full entry again.")

    def confusable(self, a: int, b: int) -> Reply:
        return Reply(f"₹{fmt_amount(a)} or ₹{fmt_amount(b)}?", f"{self._rs(a)} or {self._rs(b)}?")

    def same_name(self, name: str, tags: list[str]) -> Reply:
        labels = [t if t else "the first one" for t in tags[:2]]
        while len(labels) < 2:
            labels.append("the second one")
        return self._same(f"Which {name}: {labels[0]} or {labels[1]}?",
                          f"Which {_name(name)}: {labels[0]} or {labels[1]}?")

    def which_entry(self, a: dict, b: dict) -> Reply:
        ak, bk = KIND_EN.get(a["kind"], a["kind"]), KIND_EN.get(b["kind"], b["kind"])
        return Reply(f"Which entry: ₹{fmt_amount(a['amount'])} {ak} or ₹{fmt_amount(b['amount'])} {bk}?",
                     f"Which entry: {self._rs(a['amount'])} {ak} or {self._rs(b['amount'])} {bk}?")

    def undo_check(self, name: str, amount: int, kind: str) -> Reply:
        k = KIND_EN.get(kind, kind)
        return Reply(f"I can only remove the last entry: {name}, ₹{fmt_amount(amount)} {k}. Remove it?",
                     f"I can only remove the last entry: {_name(name)}, {self._rs(amount)} {k}. Remove it?")

    def replace_check(self) -> Reply:
        return self._same("Replace the last entry with this one?")

    def missing_amount(self) -> Reply:
        return self._same("How many rupees?")

    def missing_customer(self) -> Reply:
        return self._same("Whose account?")

    def direction(self, name: str) -> Reply:
        return self._same(f"Did {name} pay, or did {name} take credit?",
                          f"Did {_name(name)} pay, or did {_name(name)} take credit?")

    def plausibility(self, amount: int) -> Reply:
        return Reply(f"₹{fmt_amount(amount)}, are you sure?", f"{self._rs(amount)}, are you sure?")

    def unclear_correction(self) -> Reply:
        return self._same("Say the right amount, or say remove it.")

    def unclear_date(self) -> Reply:
        return self._same("Which day? Say today, yesterday or the day before.")

    def cancelled(self) -> Reply:
        return self._same("Okay, nothing was saved.")

    def rejected(self) -> Reply:
        return self._same("Sorry, I did not understand. Please say it again.")

    def upstream_failure(self) -> Reply:
        return self._same("Network problem, please say it again.")

    def future(self) -> Reply:
        return self._same("That has not happened yet, so nothing was saved.")

    def negated(self) -> Reply:
        return self._same("Okay, nothing was saved.")

    def out_of_scope(self) -> Reply:
        return self._same("That is not a credit entry, so nothing was saved.")

    def too_large(self) -> Reply:
        return self._same("That amount is too large to save.")

    def no_question(self) -> Reply:
        return self._same("About what?")

    def silence(self) -> Reply:
        return self._same("I could not hear anything. Please say it again.")

    def too_long(self) -> Reply:
        return self._same("That was too long. Please use a short sentence.")

    def private(self) -> Reply:
        return self._same("The answer is on the screen.")

    def new_customer(self, name: str, close: list[str] | None = None) -> Reply:
        if close:
            return self._same(f"Is {name} a new customer, or {' or '.join(close[:2])}?",
                              f"Is {_name(name)} a new customer, or {' or '.join(_name(c) for c in close[:2])}?")
        return self._same(f"{name} is a new customer. Open an account?",
                          f"{_name(name)} is a new customer. Open an account?")

    def name_alone(self, name: str) -> Reply:
        return self._same(f"What should I note for {name}?", f"What should I note for {_name(name)}?")

    def quantity(self) -> Reply:
        return self._same("For how many rupees?")

    def confirm_entry(self, name: str, kind: str, amount: int, day: str | None = None,
                      today: date | None = None) -> Reply:
        d = self._day(day, today)
        tail = f", dated {d}" if d else ""
        if kind == "credit":
            return Reply(f"Add ₹{fmt_amount(amount)} credit for {name}{tail}?",
                         f"Add {self._rs(amount)} credit for {_name(name)}{tail}?")
        if kind == "writeoff":
            return Reply(f"Write off ₹{fmt_amount(amount)} for {name}?",
                         f"Write off {self._rs(amount)} for {_name(name)}?")
        return Reply(f"Record ₹{fmt_amount(amount)} received from {name}{tail}?",
                     f"Record {self._rs(amount)} received from {_name(name)}{tail}?")

    def confirm_settle(self, name: str, balance: int) -> Reply:
        return Reply(f"{name} owes ₹{fmt_amount(balance)}. Record all of it as received?",
                     f"{_name(name)} owes {self._rs(balance)}. Record all of it as received?")

    def confirm_half(self, name: str, amount: int) -> Reply:
        return Reply(f"Half is ₹{fmt_amount(amount)}. Record it as received from {name}?",
                     f"Half is {self._rs(amount)}. Record it as received from {_name(name)}?")

    def confirm_writeoff(self, name: str, balance: int) -> Reply:
        return Reply(f"{name} owes ₹{fmt_amount(balance)}. Write all of it off?",
                     f"{_name(name)} owes {self._rs(balance)}. Write all of it off?")

    def confirm_roundoff(self, name: str, balance: int, amount: int) -> Reply:
        return Reply(f"{name} owes ₹{fmt_amount(balance)}. Drop ₹{fmt_amount(amount)}?",
                     f"{_name(name)} owes {self._rs(balance)}. Drop {self._rs(amount)}?")

    def confirm_overpayment(self, name: str, balance: int, amount: int) -> Reply:
        if balance > 0:
            return Reply(f"{name} owes only ₹{fmt_amount(balance)}. Record ₹{fmt_amount(amount)} anyway?",
                         f"{_name(name)} owes only {self._rs(balance)}. Record {self._rs(amount)} anyway?")
        return Reply(f"{name} owes nothing. Record ₹{fmt_amount(amount)} as an advance?",
                     f"{_name(name)} owes nothing. Record {self._rs(amount)} as an advance?")

    def confirm_duplicate(self) -> Reply:
        return self._same("I just saved this entry. Save another one?")

    def balance(self, name: str, balance: int, has_entries: bool = True) -> Reply:
        nm = _name(name)
        if not has_entries:
            return self.no_entries(name)
        if balance > 0:
            return Reply(f"{name} owes ₹{fmt_amount(balance)}.", f"{nm} owes {self._rs(balance)}.")
        if balance == 0:
            return self._same(f"{name}'s account is settled.", f"{nm}'s account is settled.")
        return Reply(f"{name} has paid ₹{fmt_amount(-balance)} extra.", f"{nm} has paid {self._rs(-balance)} extra.")

    def no_entries(self, name: str) -> Reply:
        return self._same(f"{name} has no entries.", f"{_name(name)} has no entries.")

    def unknown_customer(self, name: str) -> Reply:
        return self._same(f"No account found for {name}.", f"No account found for {_name(name)}.")

    def credit_total(self, amount: int, period: str = "today") -> Reply:
        day = PERIOD_EN.get(period, "Today")
        if amount <= 0:
            return self._same(f"No credit given {day.lower()}.")
        return Reply(f"{day} ₹{fmt_amount(amount)} was given on credit.",
                     f"{day} {self._rs(amount)} was given on credit.")

    def payment_total(self, amount: int, period: str = "today") -> Reply:
        day = PERIOD_EN.get(period, "Today")
        if amount <= 0:
            return self._same(f"Nothing received {day.lower()}.")
        return Reply(f"{day} ₹{fmt_amount(amount)} was received.", f"{day} {self._rs(amount)} was received.")

    def daily_summary(self, summary: dict, period: str = "today") -> Reply:
        day = PERIOD_EN.get(period, "Today")
        if not summary.get("count"):
            if period == "today":
                return self._same("No entries yet today.")
            return self._same(f"No entries {day.lower()}.")
        c, p = summary["credit"], summary["payment"]
        t = f"{day}: ₹{fmt_amount(c)} credit, ₹{fmt_amount(p)} received."
        s = f"{day}: {self._rs(c)} credit, {self._rs(p)} received."
        if summary.get("top") and period in ("today", "yesterday"):
            name, amt = summary["top"]
            t += f" Highest due: {name}, ₹{fmt_amount(amt)}."
            s += f" Highest due: {_name(name)}, {self._rs(amt)}."
        return Reply(t, s)

    def top_dues(self, dues: list[tuple[str, int]]) -> Reply:
        if not dues:
            return self._same("Nobody owes anything.")
        return Reply("Highest dues: " + ", ".join(f"{n} ₹{fmt_amount(a)}" for n, a in dues) + ".",
                     "Highest dues: " + ", ".join(f"{_name(n)} {self._rs(a)}" for n, a in dues) + ".")

    def outstanding_total(self, amount: int, customers: int) -> Reply:
        if amount <= 0:
            return self.top_dues([])
        return Reply(f"Total outstanding is ₹{fmt_amount(amount)}, from {customers} customers.",
                     f"Total outstanding is {self._rs(amount)}, from {self.words(customers)} customers.")

    def due_since(self, name: str, day: date) -> Reply:
        return Reply(f"{name} has owed since {day.day} {MONTHS_EN[day.month - 1]}.",
                     f"{_name(name)} has owed since {self.words(day.day)} {MONTHS_EN[day.month - 1]}.")

    def reminder_ready(self, name: str) -> Reply:
        return self._same(f"The reminder for {name} is ready, see the screen.",
                          f"The reminder for {_name(name)} is ready, see the screen.")

    def reminder_no_consent(self, name: str) -> Reply:
        return self._same(f"{name} has not agreed to reminders.", f"{_name(name)} has not agreed to reminders.")

    def reminder_nothing_due(self, name: str) -> Reply:
        return self._same(f"{name} owes nothing, so no reminder was made.",
                          f"{_name(name)} owes nothing, so no reminder was made.")

    def reminder_confirm(self, name: str, balance: int, said: int) -> Reply:
        b, s = fmt_amount(balance), fmt_amount(said)
        return Reply(f"{name} owes ₹{b}, not ₹{s}. Make a reminder for ₹{b}?",
                     f"{_name(name)} owes {self._rs(balance)}, not {self._rs(said)}. "
                     f"Make a reminder for {self._rs(balance)}?")

    def reminder_quiet(self) -> Reply:
        return Reply("Reminders are made only between 9 am and 8 pm.",
                     "Reminders are made only between nine am and eight pm.")

    def reminder_message(self, name: str, amount: int) -> str:
        return f"Hello {name}, your account shows ₹{fmt_amount(amount)} due. Please pay when convenient. Thank you."


def fixed_replies(replier: Replier) -> list[Reply]:
    """Replies with no customer name and no amount, in the replier's language: safe to cache on disk and to
    synthesise ahead of time."""
    r = replier
    return [r.disclosure(), r.missing_amount(), r.missing_customer(), r.unclear_correction(), r.unclear_date(),
            r.replace_check(), r.cancelled(), r.rejected(), r.upstream_failure(), r.entry_not_found(),
            r.nothing_to_amend(), r.nothing_to_undo(), r.entry_removed(), r.future(), r.negated(),
            r.out_of_scope(), r.too_large(), r.no_question(), r.silence(), r.too_long(), r.private(),
            r.quantity(), r.confirm_duplicate(), r.top_dues([]), r.reminder_quiet()]
