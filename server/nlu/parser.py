"""Utterance to a structured ledger result (CONTRACT section 1).

`parse(utterance, today=..., ctx=...)` is a pure function: no I/O, no clock, no state between calls. It never
raises; anything it cannot read becomes a `rejected` or `needs_clarification` result, and it never guesses an
amount, a direction, a date or a customer.

Pipeline
1. Tokenise. Roman, Devanagari and digits are all accepted; Devanagari words are romanised, and every word is
   reduced with `translit.fold` so keyword spellings vary as freely as number spellings (udhar / udhaar).
2. Mark spans: tag phrases (`chai wale`, `gali number 3`), `N din pehle` dates, number phrases (one amount each).
   Filler words are dropped.
3. A pending question (`ctx.pending`) is answered first when the utterance is an answer.
4. Otherwise: negation, future, undo, correction, query, then ledger clauses. Clauses split on `,` `aur`
   `phir` `and`, and without punctuation where a second amount brings its own date word or name.
5. Guards, in order: missing amount / customer / direction / date, customer resolution (same name), confusable
   number (`stt_alternatives`), plausibility (`limits.confirm_above`).
"""
from __future__ import annotations

import copy
import re
from datetime import date, datetime, timedelta
from typing import Any

from rapidfuzz import fuzz

from . import names as nm
from .numbers import CURRENCY_WORDS, classify_word, digits_value, value_of_items
from .translit import fold, is_devanagari, normalise, romanise_word

# ---------------------------------------------------------------------------------------------------------------
# Lexicon. Each canonical keyword lists spellings in Roman and Devanagari; all are folded at import.

_KEYWORDS = {
    "ne": "ne nay ने",
    "ko": "ko koh kou को",
    "ka": "ka kaa ki kee ke kay का की के",
    "se": "se say sey से",
    "pe": "pe par per pai पे पर",
    "from": "from",
    "udhaar": "udhaar udhar udhaari udhari udaar udhaara udhara udhar udhaarr उधार उधारी उधर",
    "credit": "credit kredit क्रेडिट",
    "debit": "debit डेबिट",
    "on": "on",
    "give": "diya diye di dia diyaa diyе dii de dediya dediye dedi diyo dijiye दिया दिए दिये दी दे दीजिए",
    "take": "liya liye li lia liyaa lee le lelo leliya लिया लिए लिये ली ले",
    "gaya": "gaya gaye gayi gai gya gaye gayaa गया गए गये गई गयी",
    "mila": "mila mile mili milaa milaa मिला मिले मिली",
    "aaya": "aaya aaye aayi aya aye ayi aai aayaa आया आए आये आई आयी",
    "payment": "payment pement paymnt paiment payement pemant पेमेंट पेमेन्ट collection",
    "received": "received recieved receive",
    "paid": "paid",
    "gave": "gave",
    "took": "took",
    "owes": "owes owe",
    "jama": "jama jamaa jma जमा",
    "chukaya": "chukaya chukaye chuka chukta chukai chukaayi chukaa chukayi चुकाया चुकाए चुकाये चुका चुकता",
    "wapas": "wapas vapas waapas vaapas wapis vapis वापस",
    "paymode": "upi online cash phonepe gpay paytm googlepay nakad nagad यूपीआई ऑनलाइन कैश नकद",
    "kiya": "kiya kiye kia kiyaa kari karaya karaye karwaya kar karo kardo karna kariye karde किया किए किये कर करो कराया करवाया",
    "likh": "likh likho likhdo likhna likhiye likhe likha likhlo लिख लिखो लिखना लिखा लिखिए",
    "add": "add jod jodo jodna जोड़ जोड़ो ऐड",
    "daal": "daal dal daalo dalo daaldo डाल डालो",
    "chadha": "chadha chadhao chadhado charha charhao chadhaa चढ़ा चढ़ाओ चढ़ा",
    "naam": "naam nam नाम",
    "khata": "khata khate khaata khaate khatey khaatey khatta खाता खाते",
    "mein": "mein me men mei mai में मे",
    "kaat": "kaat kaato kat kaatna kaatdo ghata ghatao minus काट काटो घटा घटाओ",
    "saaman": "saaman saman samaan saamaan maal saamaan सामान माल",
    "baaki": "baaki baki baqi baaqi bakaya baakee बाकी बाक़ी बकाया",
    "dene": "dene dena देने देना",
    "tha": "tha thi the था थी थे",
    "hai": "hai hain he hei hay है हैं",
    "future": ("dega degi denge dunga dungi doonga denga dengi dedega dedenge aayega aayegi aayenge ayega aaega "
               "lega legi lenge lunga karega karegi karenge bhejega bhejenge milega milegi will "
               "देगा देगी देंगे दूंगा दूँगा दूंगी आएगा आयेगा आएगी लेगा लेंगे करेगा करेंगे मिलेगा"),
    "neg": "nahi nahin nai nahee naheen nhi nahi not no नहीं नही ना",
    "mat": "mat मत",
    "galat": "galat galt ghalat galti wrong गलत ग़लत",
    "undo": ("undo cancel cancle kancel cancil hata hatao hatado hatana hataa mita mitao mitado delete remove "
             "हटा हटाओ हटाना मिटा मिटाओ डिलीट कैंसल कैंसिल"),
    "entry": "entry entri एंट्री",
    "pichla": "pichli pichla pichhli pichhla pichle pichhle last previous पिछली पिछला पिछले",
    "yes": "haan han haa haanji hanji yes yeah yep pakka sahi theek thik bilkul हाँ हां पक्का सही ठीक बिल्कुल",
    "ha": "ha हा",
    "ji": "ji jee जी",
    "ok": "ok okay okk ओके",
    "first": "pehla pehli pahla pahli first पहला पहली",
    "pehle": "pehle pahle pehele ago पहले",
    "second": "doosra doosri dusra dusri second dusre doosre दूसरा दूसरी दूसरे",
    "kitna": "kitna kitne kitni kitnaa कितना कितने कितनी",
    "kya": "kya kyaa क्या",
    "kiska": "kiska kiski kiske किसका किसकी किसके",
    "kis": "kis किस",
    "kaun": "kaun kon कौन",
    "batao": "batao bataiye bata batana bataao बताओ बताइए बता",
    "total": "total totl टोटल",
    "hisaab": "hisaab hisab hisaab हिसाब",
    "balance": "balance balence बैलेंस बैलेन्स",
    "summary": "summary bikri sale सारांश बिक्री",
    "sabse": "sabse sabsey सबसे",
    "zyada": "zyada jyada jada zada jiyada ज़्यादा ज्यादा",
    "hua": "hua hui hue huwa हुआ हुई हुए",
    "aaj": "aaj aj today आज",
    "kal": "kal yesterday कल",
    "parso": "parso parson parsoon parsu परसों परसो",
    "narson": "narson narso नरसों",
    "din": "din days day दिन",
    "time": "subah shaam sham raat rat dopahar savere morning evening night सुबह शाम रात दोपहर सवेरे",
    "weekday": ("somvar mangalvar budhvar guruvar brihaspativar shukravar shanivar ravivar itvaar itwar "
                "monday tuesday wednesday thursday friday saturday sunday "
                "सोमवार मंगलवार बुधवार गुरुवार बृहस्पतिवार शुक्रवार शनिवार रविवार इतवार"),
    "hafte": "hafte hafta week हफ्ते हफ़्ते हफ्ता",
    "mahine": "mahine mahina month महीने महीना",
    "tarikh": "tarikh tareekh taarikh date तारीख तारीख़",
    "kuch": "kuch kuchh कुछ",
    "aur": "aur or और",
    "phir": "phir fir फिर",
    "filler": ("to toh achha accha acha achchha arre are arey suno suniye dekho zara jara please plz pls "
               "abhi tak bhi bas yaar matlab umm hmm ab "
               "तो अच्छा अरे सुनो सुनिए देखो ज़रा जरा प्लीज़ प्लीज अभी तक भी बस यार"),
    "paisa": "paisa paise paisaa पैसा पैसे",
    "rehne": "rehne rahne chhodo chodo रहने छोड़ो",
}


def _build_keywords() -> dict[str, str]:
    table: dict[str, str] = {}
    for canon, text in _KEYWORDS.items():
        for w in normalise(text).split():
            roman = romanise_word(w) if is_devanagari(w) else w
            table.setdefault(fold(roman), canon)
    return table


_KW = _build_keywords()

_MARKERS = {"ne", "ko", "ka", "se", "pe"}
_VERBS = {"give", "take", "gaya", "mila", "aaya", "kiya", "likh", "chukaya", "hua"}
_LEDGER_CUES = {"udhaar", "give", "take", "mila", "aaya", "payment", "jama", "chukaya", "likh", "add", "daal",
                "chadha", "kaat", "paid", "gave", "took", "owes", "received", "paymode", "wapas", "credit", "debit",
                "saaman", "naam"}
_PAY_CUES = {"payment", "jama", "chukaya", "paymode", "received", "paid", "gave", "mila", "aaya", "kaat"}
_YES = {"yes", "ha", "ji", "ok"}
_SURNAMES = frozenset((
    "kumar kumari singh sharma verma varma gupta yadav das lal prasad devi bai patel shah jain agarwal aggarwal "
    "khan ali rao reddy nair mishra tiwari pandey chauhan thakur mehta joshi iyer pillai ahmed sheikh shaikh chand "
    "nath babu chaudhary choudhary saxena srivastava rathore bansal goel garg malhotra kapoor khanna"
).split())

DEFAULT_CONFIRM_ABOVE = 50_000
CARRY_MAX_AGE_S = 120


class Tok:
    """One token. cls: sep, cur, amt, num, digit, and, kw, unk, hon, tag, date, aux, fill."""

    __slots__ = ("raw", "rom", "cls", "kw", "val", "items", "tag_id")

    def __init__(self, raw: str, cls: str, rom: str = "", kw: str = "", val: Any = None):
        self.raw = raw
        self.rom = rom or raw
        self.cls = cls
        self.kw = kw
        self.val = val
        self.items: list = []
        self.tag_id = -1

    def copy(self) -> "Tok":
        t = Tok(self.raw, self.cls, self.rom, self.kw, self.val)
        t.items = self.items
        t.tag_id = self.tag_id
        return t

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Tok({self.raw!r},{self.cls},{self.kw or self.val})"


_TOKEN_RE = re.compile(r"₹|\d+(?:,\d+)*(?:\.\d+)?|[a-z]+|[ऀ-ॣ॰-ॿ]+|[,;.?!।॥|]")


def _tokenise(utterance: str) -> list[Tok]:
    s = normalise(utterance)
    s = re.sub(r"\brs\.", "rs ", s).replace("/-", " ").replace("-", " ").replace("'", "")
    toks: list[Tok] = []
    for raw in _TOKEN_RE.findall(s):
        if raw == "₹":
            toks.append(Tok(raw, "cur"))
        elif raw[0].isdigit():
            toks.append(Tok(raw, "digit", val=digits_value(raw)))
        elif len(raw) == 1 and not raw.isalnum():
            toks.append(Tok(raw, "sep"))
        elif raw == "and":
            toks.append(Tok(raw, "and"))
        else:
            rom = romanise_word(raw) if is_devanagari(raw) else raw
            f = fold(rom)
            if f in CURRENCY_WORDS:
                toks.append(Tok(raw, "cur", rom))
                continue
            item = classify_word(raw)
            if item is not None:
                t = Tok(raw, "num", rom)
                t.items = [item]
                toks.append(t)
            elif nm.is_tag_word(rom):
                toks.append(Tok(raw, "wale", rom))
            elif nm.is_gali_word(rom):
                toks.append(Tok(raw, "gali", rom))
            elif f in _KW:
                toks.append(Tok(raw, "kw", rom, kw=_KW[f]))
            elif nm.is_honorific(rom):
                toks.append(Tok(raw, "hon", rom))
            else:
                toks.append(Tok(raw, "unk", rom))
    return toks


def _mark(toks: list[Tok], keep_fillers: bool = False) -> list[Tok]:
    """Mark tag phrases, N-din-pehle dates and number phrases; drop fillers. Returns a new token list."""
    # Leading "theek hai" / "haan" before more words are fillers.
    out = [t.copy() for t in toks]
    if not keep_fillers:
        sig = [t for t in out if t.cls != "sep"]
        if len(sig) > 2 and sig[0].kw == "yes" and sig[0].rom in ("theek", "thik") and sig[1].kw == "hai":
            out.remove(sig[0])
            out.remove(sig[1])
        sig = [t for t in out if t.cls != "sep"]
        while len(sig) > 1 and sig[0].kw in ("yes", "ha", "ok", "ji") and sig[0].rom not in ("pakka", "sahi"):
            out.remove(sig[0])
            sig = sig[1:]
        out = [t for t in out if not (t.cls == "kw" and t.kw == "filler")]
        for t in out:
            if t.cls == "kw" and t.kw == "ji":
                t.cls = "hon"  # "Sharma ji": part of the name run, dropped from the key

    # Tag phrases.
    tag_id = 0
    i = 0
    while i < len(out):
        t = out[i]
        if t.cls == "gali":
            t.cls, t.tag_id = "tag", tag_id
            j = i + 1
            while j < len(out) and out[j].rom in nm.TAG_FILLERS:
                out[j].cls, out[j].tag_id = "tag", tag_id
                j += 1
            if j < len(out) and out[j].cls in ("num", "digit", "unk"):
                out[j].cls, out[j].tag_id = "tag", tag_id
                j += 1
            tag_id += 1
            i = j
            continue
        if t.cls == "wale":
            prev = out[i - 1] if i > 0 else None
            if prev is not None and prev.cls in ("unk", "kw", "num", "hon") and prev.kw not in _MARKERS \
                    and prev.kw not in ("aur", "phir"):
                prev.cls, prev.tag_id = "tag", tag_id
                t.cls, t.tag_id = "tag", tag_id
                tag_id += 1
            else:
                t.cls = "fill"
        i += 1

    # "N din pehle" dates.
    i = 0
    while i < len(out):
        t = out[i]
        if t.kw == "din" and i + 1 < len(out) and out[i + 1].kw == "pehle":
            j = i
            while j > 0 and out[j - 1].cls in ("num", "digit"):
                j -= 1
            span = out[j:i]
            value = _run_value(span) if span else None
            d = Tok("date", "date", val=value if value is not None and value >= 0 else "unclear")
            if not span and i > 0 and out[i - 1].kw == "kuch":
                j = i - 1
                d.val = "unclear"
            elif not span:
                d.val = "unclear"
            out[j:i + 2] = [d]
            i = j + 1
            continue
        i += 1

    # "15 tarikh": a day of the month is not an amount and is not resolved (unclear date).
    i = 0
    while i < len(out):
        if out[i].kw == "tarikh":
            j = i
            while j > 0 and out[j - 1].cls in ("num", "digit"):
                j -= 1
            out[j:i + 1] = [Tok("date", "date", val="unclear")]
            i = j + 1
            continue
        i += 1

    # Number phrases.
    res: list[Tok] = []
    i = 0
    n = len(out)
    while i < n:
        t = out[i]
        if t.cls in ("num", "digit"):
            j = i + 1
            while j < n:
                c = out[j]
                if c.cls in ("num", "digit"):
                    j += 1
                elif (c.cls == "and" and j + 1 < n and out[j + 1].cls in ("num", "digit")
                      and out[j - 1].cls == "num" and out[j - 1].items[0][0] == "u"):
                    j += 1
                else:
                    break
            span = out[i:j]
            nxt = out[j] if j < n else None
            if (len(span) == 1 and t.cls == "num" and t.items[0][2] == "hi" and t.items[0][0] == "n"
                    and t.items[0][1] in (1, 2) and not (nxt is not None and nxt.cls == "cur")):
                res.append(Tok(t.raw, "aux", t.rom))  # "do" in "likh do", "ek" as an article
                i = j
                continue
            amt = Tok(" ".join(s.raw for s in span), "amt", val=_run_value(span))
            res.append(amt)
            i = j
            continue
        res.append(t)
        i += 1
    return res


def _run_value(span: list[Tok]) -> int | None:
    items = []
    for t in span:
        if t.cls == "digit":
            if t.val is None:
                return None
            items.append(("d", t.val, "dig"))
        elif t.cls == "and":
            items.append(("and", None, "en"))
        else:
            items.extend(t.items)
    if len(items) == 1 and items[0][0] == "n" and items[0][1] == 0:
        return 0
    if len(items) == 1 and items[0][0] == "d" and items[0][1] == 0:
        return 0
    if any(k == "n" and v == 0 for k, v, _ in items):
        return None
    return value_of_items(items)


# ---------------------------------------------------------------------------------------------------------------
# Small helpers


def _sig(toks: list[Tok]) -> list[Tok]:
    return [t for t in toks if t.cls not in ("sep", "cur", "fill", "aux")]


def _kws(toks: list[Tok]) -> set[str]:
    return {t.kw for t in toks if t.cls == "kw"}


def _display(key: str) -> str:
    return " ".join(w.capitalize() for w in (key or "").split())


def _rupees(n: int) -> str:
    s = str(int(n))
    if len(s) <= 3:
        return "₹" + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])


def _rejected(reason: str) -> dict[str, Any]:
    return {"status": "rejected", "reason": reason}


def _limit(ctx: dict) -> int:
    limits = ctx.get("limits")
    if isinstance(limits, dict):
        v = limits.get("confirm_above")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return DEFAULT_CONFIRM_ABOVE


def _last_event(ctx: dict) -> dict | None:
    le = ctx.get("last_event")
    if isinstance(le, dict) and le.get("customer") and le.get("kind") in ("credit", "payment"):
        return le
    return None


def _carry_ok(le: dict | None) -> bool:
    if le is None:
        return False
    age = le.get("age_s")
    if isinstance(age, (int, float)) and not isinstance(age, bool) and age > CARRY_MAX_AGE_S:
        return False
    return True


def _clean_event(e: dict) -> dict:
    out = {}
    for k in ("kind", "customer", "amount", "date", "customer_id", "new_customer", "tags"):
        if k in e and e[k] is not None:
            out[k] = e[k]
    return out


_QUESTIONS = {
    "missing_amount": "Kitne rupaye?",
    "missing_customer": "Kiska khata?",
    "unclear_correction": "Sahi amount boliye, ya hata do boliye.",
    "unclear_date": "Kaunsa din? Aaj, kal ya parso boliye.",
}


def _question(reason: str, events: list[dict], candidates: Any, index: int | None) -> str:
    if reason in _QUESTIONS:
        return _QUESTIONS[reason]
    ev = events[index] if index is not None and 0 <= index < len(events) else (events[0] if events else {})
    if reason == "ambiguous_direction":
        target = next((e for e in events if "kind" not in e), ev)
        name = _display(target.get("customer", ""))
        return f"{name} ne diye, ya {name} ko udhaar?" if name else "Diye, ya udhaar?"
    if reason == "plausibility" and isinstance(ev.get("amount"), int):
        return f"{_rupees(ev['amount'])}, pakka?"
    if reason == "confusable_number" and isinstance(candidates, list) and len(candidates) >= 2             and all(isinstance(c, int) for c in candidates[:2]):
        return f"{_rupees(candidates[0])} ya {_rupees(candidates[1])}?"
    if reason == "same_name" and isinstance(candidates, list) and candidates             and all(isinstance(c, dict) for c in candidates):
        name = _display(str(candidates[0].get("name") or ""))
        labels = [", ".join(str(t) for t in (c.get("tags") or [])) or "pehle wale" for c in candidates]
        if len(labels) > 2:
            joined = ", ".join(labels[:-1]) + " ya " + labels[-1]
        else:
            joined = " ya ".join(labels)
        return f"Kaunse {name}: {joined}?"
    return "Maaf kijiye, samajh nahi aaya. Dobara boliye."


def _clarify(reason: str, action: str, events: list[dict], *, candidates: Any = None, index: int | None = None,
             confirmed: set[str] | None = None, query: dict | None = None) -> dict[str, Any]:
    events = [_clean_event(e) for e in events]
    pending: dict[str, Any] = {"reason": reason, "action": action}
    if action == "query":
        pending["query"] = query or {}
    else:
        pending["events"] = events
    if candidates is not None:
        pending["candidates"] = candidates
    if index is not None:
        pending["index"] = index
    if confirmed:
        pending["confirmed"] = sorted(confirmed)
    result: dict[str, Any] = {
        "status": "needs_clarification",
        "reason": reason,
        "question": _question(reason, events, candidates, index),
        "pending": pending,
    }
    if candidates is not None:
        result["candidates"] = candidates
    return result


# ---------------------------------------------------------------------------------------------------------------
# Customers


def _customers(ctx: dict) -> list[dict] | None:
    cs = ctx.get("customers")
    if not isinstance(cs, list):
        return None
    return [c for c in cs if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("id") is not None]


def _alias(key: str, ctx: dict) -> str:
    aliases = ctx.get("aliases")
    if isinstance(aliases, dict) and key in aliases and isinstance(aliases[key], str):
        return nm.name_key(aliases[key]) or aliases[key].lower()
    return key


def _cand(c: dict) -> dict:
    return {"id": c.get("id"), "name": c.get("name"), "tags": list(c.get("tags") or [])}


def _resolve(key: str, tags: list[str], ctx: dict) -> tuple[str, Any]:
    """("ok", fields) or ("same_name", candidates). fields replace customer / customer_id / new_customer / tags."""
    key = _alias(key, ctx) if key else key
    customers = _customers(ctx)
    if customers is None:
        if not key:
            return "unknown", None
        fields: dict[str, Any] = {"customer": key}
        if tags:
            fields["tags"] = tags
        return "ok", fields
    cands: list[dict] = []
    if key:
        cands = [c for c in customers if key in [str(a).lower() for a in (c.get("aliases") or [])]]
        if not cands:
            cands = [c for c in customers if c["name"] == key]
        if not cands:
            pk = nm.phonetic_key(key)
            close = [c for c in customers if nm.phonetic_key(c["name"]) == pk]
            if not close:
                close = [c for c in customers if fuzz.ratio(nm.phonetic_key(c["name"]), pk) >= 90]
            cands = close
    elif tags:
        cands = [c for c in customers if any(nm.tag_matches(t, ct) for t in tags for ct in (c.get("tags") or []))]
        if not cands:
            return "unknown", None
    if not cands:
        fields = {"customer": key, "new_customer": True}
        if tags:
            fields["tags"] = tags
        return "ok", fields
    if tags:
        tagged = [c for c in cands if any(nm.tag_matches(t, ct) for t in tags for ct in (c.get("tags") or []))]
        if len(tagged) == 1:
            return "ok", {"customer": tagged[0]["name"], "customer_id": tagged[0]["id"]}
        if len(tagged) > 1:
            return "same_name", [_cand(c) for c in tagged]
        untagged = [c for c in cands if not c.get("tags")]
        if len(cands) == 1 and untagged:
            return "ok", {"customer": cands[0]["name"], "customer_id": cands[0]["id"], "tags": tags}
        if untagged:
            return "same_name", [_cand(c) for c in cands]
        fields = {"customer": key or cands[0]["name"], "new_customer": True, "tags": tags}
        return "ok", fields
    if len(cands) == 1:
        return "ok", {"customer": cands[0]["name"], "customer_id": cands[0]["id"]}
    return "same_name", [_cand(c) for c in cands]


def _apply_fields(event: dict, fields: dict) -> None:
    for k in ("customer_id", "new_customer", "tags"):
        event.pop(k, None)
    event.update(fields)


# ---------------------------------------------------------------------------------------------------------------
# Finalisation: guards in order, then the ok result.


def _finalize(events: list[dict], action: str, ctx: dict, *, confirmed: set[str] | None = None,
              confusable: Any = None) -> dict[str, Any]:
    confirmed = set(confirmed or ())
    events = [dict(e) for e in events]
    for reason, field in (("missing_amount", "amount"), ("missing_customer", "customer"),
                          ("ambiguous_direction", "kind"), ("unclear_date", "date")):
        if any(field not in e for e in events):
            return _clarify(reason, action, events, confirmed=confirmed)
    for i, e in enumerate(events):
        if e.get("customer_id") is not None or e.get("new_customer"):
            continue
        status, data = _resolve(e.get("customer", ""), list(e.get("tags") or []), ctx)
        if status == "same_name":
            return _clarify("same_name", action, events, candidates=data, index=i, confirmed=confirmed)
        if status == "unknown":
            e.pop("customer", None)
            return _clarify("missing_customer", action, events, confirmed=confirmed)
        if status == "ok":
            _apply_fields(e, data)
    if confusable is not None and "confusable_number" not in confirmed:
        hit = confusable(events)
        if hit is not None:
            index, cands = hit
            return _clarify("confusable_number", action, events, candidates=cands, index=index,
                            confirmed=confirmed)
    if "plausibility" not in confirmed:
        limit = _limit(ctx)
        for i, e in enumerate(events):
            if e["amount"] > limit:
                return _clarify("plausibility", action, events, index=i, confirmed=confirmed)
    result: dict[str, Any] = {"status": "ok", "action": action, "events": [_clean_event(e) for e in events]}
    if action == "amend":
        result["target"] = "last"
    return result


def _finalize_query(query: dict, ctx: dict) -> dict[str, Any]:
    if query.get("customer") and query.get("customer_id") is None:
        status, data = _resolve(query["customer"], [], ctx)
        if status == "same_name":
            return _clarify("same_name", "query", [], candidates=data, query=query)
        if status == "ok":
            query = dict(query)
            query["customer"] = data.get("customer", query["customer"])
            if data.get("customer_id") is not None:
                query["customer_id"] = data["customer_id"]
    return {"status": "ok", "action": "query", "query": query}


# ---------------------------------------------------------------------------------------------------------------
# Clause analysis


class _Name:
    __slots__ = ("start", "end", "key", "tags", "words")

    def __init__(self, start: int, end: int, key: str, tags: list[str], words: list[str]):
        self.start, self.end, self.key, self.tags, self.words = start, end, key, tags, words


def _name_runs(toks: list[Tok]) -> list[_Name]:
    runs: list[_Name] = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i].cls in ("unk", "hon", "tag"):
            j = i
            while j < n and toks[j].cls in ("unk", "hon", "tag"):
                j += 1
            words = []
            for t in toks[i:j]:
                words.append(romanise_word(t.raw, long_vowels=False) if is_devanagari(t.raw) else t.raw)
            name_words, tags = nm.split_tokens(words)
            if name_words or tags:
                runs.append(_Name(i, j, " ".join(name_words), tags, name_words))
            i = j
        else:
            i += 1
    return runs


def _pick_names(toks: list[Tok], ctx: dict) -> tuple[list[_Name], int]:
    """Significant name runs (before a marker, at the clause start, after 'from') and the count of distinct names."""
    runs = _name_runs(toks)
    sig = []
    for r in runs:
        nxt = toks[r.end] if r.end < len(toks) else None
        prev = toks[r.start - 1] if r.start > 0 else None
        if (nxt is not None and nxt.kw in _MARKERS) or r.start == 0 or (prev is not None and prev.kw == "from"):
            sig.append(r)
    if not sig and runs:
        sig = [runs[0]]
    count = 0
    keys = set()
    for r in sig:
        if r.key in keys:
            continue
        keys.add(r.key)
        count += _names_in_run(r, ctx)
    return sig, count


def _names_in_run(r: _Name, ctx: dict) -> int:
    """A run such as "Ramesh Kumar" is one name; "Ramesh Sunita" is two unless the roster knows it."""
    if len(r.words) <= 1:
        return 1
    customers = _customers(ctx) or []
    if any(c["name"] == r.key for c in customers):
        return 1
    if all(fold(w) in {fold(s) for s in _SURNAMES} for w in r.words[1:]):
        return 1
    return len(r.words)


def _date_of(toks: list[Tok], today: date) -> tuple[str | None, str | None]:
    """(iso date, issue). issue is 'unclear' when the date words cannot be resolved to one day."""
    offsets = set()
    unclear = False
    for t in toks:
        if t.cls == "date":
            if t.val == "unclear":
                unclear = True
            else:
                offsets.add(int(t.val))
        elif t.kw == "aaj":
            offsets.add(0)
        elif t.kw == "kal":
            offsets.add(1)
        elif t.kw == "parso":
            offsets.add(2)
        elif t.kw in ("narson", "weekday", "hafte", "mahine", "tarikh"):
            unclear = True
    if unclear or len(offsets) > 1:
        return None, "unclear"
    off = offsets.pop() if offsets else 0
    if off > 3660:
        return None, "unclear"
    return (today - timedelta(days=off)).isoformat(), None


def _direction(toks: list[Tok], marker: str | None, has_name: bool) -> str | None:
    """'credit' | 'payment' | 'ambiguous' | None (no direction word at all)."""
    cues = _kws(toks)
    seq = [t.kw for t in toks if t.cls == "kw"]
    if "credit" in cues:
        for i, k in enumerate(seq):
            if k == "credit" and ((i > 0 and seq[i - 1] == "on") or (i + 1 < len(seq) and seq[i + 1] == "pe")):
                cues.add("udhaar")
    give, take, gaya = "give" in cues, "take" in cues, "gaya" in cues
    dene = any(k == "dene" and i + 1 < len(seq) and seq[i + 1] == "hai" for i, k in enumerate(seq))
    pay = cues & _PAY_CUES
    if "baaki" in cues or dene or "debit" in cues:
        return "ambiguous"
    if "wapas" in cues:
        return "payment" if marker == "ne" else "ambiguous"
    if "udhaar" in cues:
        if marker == "ne":
            return "credit" if take else "ambiguous"
        if marker == "se" or pay:
            return "ambiguous"
        return "credit"
    if "credit" in cues:
        return "ambiguous"
    if cues & {"took", "owes"}:
        return "credit"
    if cues & {"paid", "gave", "received"}:
        return "payment"
    if marker == "ne":
        if take or "saaman" in cues:
            return "credit"
        if give or pay:
            return "payment"
        return "ambiguous"
    if marker == "ko":
        if pay:
            return "ambiguous"
        if give:
            return "credit"
        return "ambiguous"
    if marker == "se":
        if pay or take or give:
            return "payment"
        return "ambiguous"
    if marker == "ka":
        if "naam" in cues:
            return "credit"
        if "jama" in cues or "kaat" in cues:
            return "payment"
        if "khata" in cues and cues & {"likh", "add", "daal", "chadha"}:
            return "credit"
        if cues & {"aaya", "mila", "payment"}:
            return "payment"
        if "saaman" in cues and take:
            return "credit"
        return "ambiguous"
    if marker == "pe":
        return "ambiguous"
    if give and gaya and not take:
        return "payment"
    if take:
        return "credit"
    if "jama" in cues or pay:
        return "payment"
    if cues & {"likh", "add", "daal", "chadha"}:
        return "credit"
    if give:
        return None if has_name else "payment"
    if has_name:
        return "ambiguous"
    return None


class _Clause:
    __slots__ = ("toks", "amount", "amount_bad", "names", "name_count", "marker", "date", "date_issue", "kind",
                 "cues")


def _analyse_clause(toks: list[Tok], ctx: dict, today: date) -> _Clause:
    c = _Clause()
    c.toks = toks
    amts = [t for t in toks if t.cls == "amt"]
    c.amount = amts[0].val if amts else None
    c.amount_bad = bool(amts) and amts[0].val is None
    sig = _sig(toks)
    c.names, c.name_count = _pick_names(sig, ctx)
    c.marker = None
    if c.names:
        r = c.names[0]
        nxt = sig[r.end] if r.end < len(sig) else None
        if nxt is not None and nxt.kw in _MARKERS:
            c.marker = nxt.kw
    c.date, c.date_issue = _date_of(toks, today)
    c.cues = _kws(toks)
    c.kind = _direction(sig, c.marker, bool(c.names))
    return c


def _split_segments(toks: list[Tok]) -> list[list[Tok]]:
    segs: list[list[Tok]] = [[]]
    for t in toks:
        if t.cls == "sep" or t.cls == "and" or (t.cls == "kw" and t.kw in ("aur", "phir")):
            if segs[-1]:
                segs.append([])
            continue
        segs[-1].append(t)
    return [s for s in segs if s]


def _has_cue(toks: list[Tok]) -> bool:
    return bool(_kws(toks) & _LEDGER_CUES)


def _split_on_amounts(seg: list[Tok]) -> list[list[Tok]]:
    """Split a segment holding several amounts: the second amount starts a clause at its date word or name."""
    idx = [i for i, t in enumerate(seg) if t.cls == "amt"]
    if len(idx) < 2:
        return [seg]
    cuts = []
    for a, b in zip(idx, idx[1:]):
        cut = b
        for k in range(a + 1, b):
            t = seg[k]
            if t.cls == "date" or t.kw in ("aaj", "kal", "parso", "narson", "weekday") or t.cls in ("unk", "tag"):
                cut = k
                break
        cuts.append(cut)
    parts = []
    start = 0
    for cut in cuts:
        parts.append(seg[start:cut])
        start = cut
    parts.append(seg[start:])
    return [p for p in parts if p]


def _clauses(toks: list[Tok]) -> list[list[Tok]]:
    segs = _split_segments(toks)
    merged: list[list[Tok]] = []
    for seg in segs:
        has_amt = any(t.cls == "amt" for t in seg)
        if has_amt:
            merged.append(seg)
            continue
        if _name_runs(_sig(seg)) and _has_cue(seg):
            merged.append(seg)  # a name with a ledger word but no amount: its own clause (missing amount)
            continue
        if merged:
            merged[-1] = merged[-1] + seg
        else:
            merged.append(seg)
    # A leading segment without an amount was kept alone; fold it into the next one.
    out: list[list[Tok]] = []
    carry: list[Tok] = []
    for seg in merged:
        has_amt = any(t.cls == "amt" for t in seg)
        if not has_amt and not (_name_runs(_sig(seg)) and _has_cue(seg)):
            carry += seg
            continue
        out.append(carry + seg)
        carry = []
    if carry:
        if out:
            out[-1] = out[-1] + carry
        else:
            out.append(carry)
    result = []
    for seg in out:
        result.extend(_split_on_amounts(seg))
    return result


# ---------------------------------------------------------------------------------------------------------------
# Fresh parse


class _Draft:
    """Outcome of analysing an utterance without a pending question."""

    __slots__ = ("result", "events", "action", "query", "complete")

    def __init__(self):
        self.result: dict | None = None
        self.events: list[dict] | None = None
        self.action = "append"
        self.query: dict | None = None
        self.complete = False


def _negated(marked: list[Tok]) -> bool:
    """"nahi diya", "abhi tak nahi aaya", "diya nahi": a negated verb. "nahi, 430" is a correction instead."""
    sig = [t for t in marked if t.cls not in ("cur", "fill", "aux")]
    for i, t in enumerate(sig):
        if t.kw in ("neg", "mat"):
            nxt = sig[i + 1] if i + 1 < len(sig) else None
            if nxt is not None and nxt.cls == "kw" and nxt.kw in _VERBS:
                return True
            prev = sig[i - 1] if i > 0 else None
            if (prev is not None and prev.cls == "kw" and prev.kw in ("give", "aaya", "mila")
                    and (nxt is None or nxt.cls == "sep" or nxt.kw in ("hai", "tha"))):
                return True
    return False


def _draft(toks: list[Tok], today: date, ctx: dict) -> _Draft:
    d = _Draft()
    marked = _mark(toks)
    sig = _sig(marked)
    if not sig:
        d.result = _rejected("not_ledger")
        return d
    kws = _kws(sig)
    amts = [t for t in sig if t.cls == "amt"]
    le = _last_event(ctx)

    if _negated(marked):
        d.result = _rejected("negated")
        return d
    if "future" in kws:
        d.result = _rejected("future")
        return d
    if "undo" in kws and not amts:
        d.result = {"status": "ok", "action": "undo", "target": "last"} if le else _rejected("no_last_event")
        d.action = "undo"
        return d
    if kws & {"neg", "galat"}:
        return _correction(marked, sig, today, ctx, d)
    if not amts:
        return _no_amount(marked, sig, today, ctx, d)
    return _entries(marked, today, ctx, d)


def _no_amount(marked: list[Tok], sig: list[Tok], today: date, ctx: dict, d: _Draft) -> _Draft:
    kws = _kws(sig)
    runs, count = _pick_names(sig, ctx)
    name = runs[0] if runs else None
    seq = [t.kw for t in sig if t.cls == "kw"]
    # Queries
    if ("sabse" in kws and kws & {"zyada", "baaki", "udhaar"}) or seq.count("kis") >= 2 \
            or ("kiska" in kws and kws & {"baaki", "udhaar"}):
        d.query = {"type": "top_dues"}
    elif name is not None and name.key:
        nxt = sig[name.end] if name.end < len(sig) else None
        if nxt is not None and nxt.kw in ("ka", "pe") and kws & {"total", "hisaab", "balance", "baaki", "khata",
                                                                  "udhaar", "kitna"} \
                and not kws & {"give", "take", "mila", "aaya", "payment", "jama", "likh", "add", "daal", "chadha"}:
            d.query = {"type": "balance", "customer": name.key}
    elif name is None:
        asked = kws & {"aaj", "kitna", "batao", "kya"}
        if asked:
            if "udhaar" in kws and not kws & _PAY_CUES:
                d.query = {"type": "credit_total", "period": "today"}
            elif kws & {"aaya", "jama", "mila", "payment"}:
                d.query = {"type": "payment_total", "period": "today"}
            elif kws & {"hisaab", "total", "summary"}:
                d.query = {"type": "daily_summary", "period": "today"}
    if d.query is not None:
        d.action = "query"
        d.complete = True
        if d.query.get("customer"):
            d.query["customer"] = _alias(d.query["customer"], ctx)
        d.result = _finalize_query(d.query, ctx)
        return d
    if not _has_cue(sig):
        d.result = _rejected("not_ledger")
        return d
    # A ledger sentence without an amount.
    clause = _analyse_clause(marked, ctx, today)
    ev: dict[str, Any] = {}
    if clause.kind in ("credit", "payment"):
        ev["kind"] = clause.kind
    if name is not None and name.key or (name is not None and name.tags):
        ev["customer"] = name.key
        if name.tags:
            ev["tags"] = name.tags
    if clause.date:
        ev["date"] = clause.date
    d.events = [ev]
    d.result = _clarify("missing_amount", "append", [ev])
    return d


def _entries(marked: list[Tok], today: date, ctx: dict, d: _Draft) -> _Draft:
    sig_all = _sig(marked)
    leading_aur = bool(sig_all) and sig_all[0].kw == "aur"
    clause_toks = _clauses([t for t in marked if t.cls not in ("fill", "aux", "cur")])
    le = _last_event(ctx)
    events: list[dict] = []
    issues: list[str] = []
    prev_customer: dict | None = None
    explicit_any = False
    zero = False
    two_names = False
    for ci, toks in enumerate(clause_toks):
        c = _analyse_clause(toks, ctx, today)
        ev: dict[str, Any] = {}
        if c.amount is not None and c.amount > 0:
            ev["amount"] = c.amount
        elif c.amount == 0 and not c.amount_bad:
            zero = True
        if c.name_count > 1:
            two_names = True
        carried_from_last = False
        if c.names and (c.names[0].key or c.names[0].tags):
            r = c.names[0]
            ev["customer"] = r.key
            if r.tags:
                ev["tags"] = r.tags
            prev_customer = {"customer": r.key, "tags": r.tags}
            if "amount" in ev:
                explicit_any = True
        elif prev_customer is not None:
            ev["customer"] = prev_customer["customer"]
            if prev_customer.get("tags"):
                ev["tags"] = prev_customer["tags"]
        elif _carry_ok(le):
            ev["customer"] = le["customer"]
            if le.get("customer_id") is not None:
                ev["customer_id"] = le["customer_id"]
            carried_from_last = True
            prev_customer = {"customer": le["customer"], "customer_id": le.get("customer_id")}
        kind = c.kind
        if kind is None and ci == 0 and leading_aur and carried_from_last:
            kind = le["kind"]
        if kind == "payment" and not c.names and "customer" not in ev:
            kind = None  # bare "diya" is a payment only when the customer is carried over
        if kind in ("credit", "payment"):
            ev["kind"] = kind
        if c.date:
            ev["date"] = c.date
        if prev_customer is not None and prev_customer.get("customer_id") is not None \
                and ev.get("customer") == prev_customer["customer"] and "customer_id" not in ev and not c.names:
            ev["customer_id"] = prev_customer["customer_id"]
        events.append(ev)
    d.events = events
    d.complete = explicit_any
    if zero:
        d.result = _rejected("invalid_number")
        return d
    if two_names:
        for e in events:
            e.pop("customer", None)
            e.pop("customer_id", None)
            e.pop("amount", None)
        d.result = _clarify("missing_amount", "append", events)
        return d
    d.result = None  # finalised by the caller (needs the confusable check)
    return d


def _correction(marked: list[Tok], sig: list[Tok], today: date, ctx: dict, d: _Draft) -> _Draft:
    k = next(i for i, t in enumerate(sig) if t.kw in ("neg", "galat"))
    prefix = sig[:k]
    suffix = [t for t in sig[k + 1:] if t.kw not in ("neg", "galat", "hai", "tha")]
    p_amts = [t for t in prefix if t.cls == "amt"]
    p_names = _name_runs(prefix)
    p_fields = (1 if p_amts else 0) + (1 if p_names else 0) + (1 if _kws(prefix) & _LEDGER_CUES else 0)
    other = [t for t in prefix if t.cls not in ("amt", "unk", "hon", "tag") and t.kw not in _MARKERS
             and t.kw not in _LEDGER_CUES]
    if p_fields > 1 or other:
        # A self-correction inside a new sentence: the words after "nahi" replace those before it.
        s_amts = [t for t in suffix if t.cls == "amt"]
        s_names = _name_runs(suffix)
        keep = []
        for t in prefix:
            if s_amts and t.cls == "amt":
                continue
            if s_names and t.cls in ("unk", "hon", "tag"):
                continue
            keep.append(t)
        rebuilt = keep + suffix
        if not any(t.cls == "amt" for t in rebuilt):
            return _no_amount(rebuilt, _sig(rebuilt), today, ctx, d)
        return _entries(rebuilt, today, ctx, d)
    le = _last_event(ctx)
    d.action = "amend"
    if le is None:
        d.result = _rejected("no_last_event")
        return d
    base = _clean_event(le)
    if not suffix:
        d.result = _clarify("unclear_correction", "amend", [base])
        return d
    if p_names and nm.phonetic_key(p_names[0].key) != nm.phonetic_key(le["customer"]) \
            and fuzz.ratio(nm.phonetic_key(p_names[0].key), nm.phonetic_key(le["customer"])) < 90:
        d.result = _clarify("unclear_correction", "amend", [base])
        return d
    if p_amts and p_amts[0].val is not None and p_amts[0].val != le.get("amount"):
        d.result = _clarify("unclear_correction", "amend", [base])
        return d
    new = dict(base)
    changed = False
    s_amts = [t for t in suffix if t.cls == "amt"]
    if len(s_amts) > 1:
        d.result = _clarify("unclear_correction", "amend", [base])
        return d
    if s_amts:
        v = s_amts[0].val
        if v is None or v == 0:
            d.result = _clarify("unclear_correction", "amend", [base])
            return d
        new["amount"] = v
        changed = True
    s_names = _name_runs(suffix)
    if s_names:
        r = s_names[0]
        new["customer"] = r.key
        for key in ("customer_id", "new_customer", "tags"):
            new.pop(key, None)
        if r.tags:
            new["tags"] = r.tags
        changed = True
    kind = _direction(suffix, None, False) if _kws(suffix) & _LEDGER_CUES else None
    if kind in ("credit", "payment"):
        new["kind"] = kind
        changed = True
    if any(t.cls == "date" or t.kw in ("aaj", "kal", "parso", "narson", "weekday", "hafte", "tarikh")
           for t in suffix):
        iso, issue = _date_of(suffix, today)
        if issue:
            d.result = _clarify("unclear_date", "amend", [{k2: v2 for k2, v2 in new.items() if k2 != "date"}])
            return d
        new["date"] = iso
        changed = True
    if not changed:
        d.result = _clarify("unclear_correction", "amend", [base])
        return d
    d.events = [new]
    d.result = _finalize([new], "amend", ctx)
    return d


def _confusable_checker(utterance: str, events: list[dict], today: date, ctx: dict):
    alts = ctx.get("stt_alternatives")
    if not isinstance(alts, list) or not alts:
        return None
    sub_ctx = {k: v for k, v in ctx.items() if k not in ("stt_alternatives", "pending")}
    base_norm = " ".join(normalise(utterance).split())
    alt_events = []
    for alt in alts:
        if not isinstance(alt, str) or " ".join(normalise(alt).split()) == base_norm:
            continue
        ad = _draft(_tokenise(alt), today, sub_ctx)
        if ad.result is None and ad.events:
            alt_events.append(ad.events)

    def check(final_events: list[dict]):
        for other in alt_events:
            if len(other) != len(events):
                continue
            for i, (a, b) in enumerate(zip(events, other)):
                if a.get("kind") != b.get("kind") or a.get("customer") != b.get("customer") \
                        or a.get("date") != b.get("date"):
                    break
            else:
                for i, (a, b) in enumerate(zip(events, other)):
                    if "amount" in b and a.get("amount") != b["amount"]:
                        return i, [final_events[i]["amount"], b["amount"]]
        return None

    return check


def _fresh(toks: list[Tok], utterance: str, today: date, ctx: dict) -> tuple[dict, _Draft]:
    d = _draft(toks, today, ctx)
    if d.result is not None:
        return d.result, d
    events = d.events or []
    checker = _confusable_checker(utterance, events, today, ctx)
    return _finalize(events, "append", ctx, confusable=checker), d


# ---------------------------------------------------------------------------------------------------------------
# Answers to a pending question


def _answer_tokens(toks: list[Tok]) -> list[Tok]:
    return [t for t in _mark(toks, keep_fillers=True) if t.cls not in ("sep", "cur")]


def _only_number(sig: list[Tok]) -> int | None | str:
    rest = [t for t in sig if not (t.cls == "kw" and t.kw in ("filler", "hai", "tha", "ji", "ok"))]
    if len(rest) == 1 and rest[0].cls == "amt":
        return rest[0].val if rest[0].val is not None else "bad"
    if len(rest) == 1 and rest[0].cls == "aux":  # a lone "do" or "ek" as an answer
        v = classify_word(rest[0].raw)
        return v[1] if v else None
    return None


def _is_yes(sig: list[Tok]) -> bool:
    kws = [t.kw if t.cls == "kw" else t.cls for t in sig]
    return bool(kws) and all(k in _YES or k in ("hai", "filler") for k in kws) and any(k in _YES for k in kws)


def _is_no(sig: list[Tok]) -> bool:
    kws = [t.kw if t.cls == "kw" else t.cls for t in sig]
    return bool(kws) and all(k in ("neg", "galat", "hai", "filler", "undo") for k in kws) \
        and any(k in ("neg", "galat", "undo") for k in kws)


def _is_cancel(sig: list[Tok]) -> bool:
    kws = [t.kw if t.cls == "kw" else t.cls for t in sig]
    if not kws:
        return False
    if "rehne" in kws or ("mat" in kws and "likh" in kws):
        return True
    return all(k in ("undo", "kiya", "aux", "hai", "filler", "entry", "pichla") for k in kws) and "undo" in kws


def _ordinal(sig: list[Tok]) -> int | None:
    kws = [t.kw if t.cls == "kw" else t.cls for t in sig if not (t.cls == "kw" and t.kw in ("filler", "hai"))]
    if kws in (["first"], ["pehle"]):
        return 0
    if kws == ["second"]:
        return 1
    return None


def _pehle_wale(sig: list[Tok]) -> bool:
    raws = [t.rom for t in sig]
    return len(raws) == 2 and fold(raws[0]) in (fold("pehle"), fold("pahle"), fold("pehla"), fold("pehli")) \
        and nm.is_tag_word(raws[1])


def _target_index(events: list[dict], pending: dict, field: str | None = None, value: Any = None) -> int:
    idx = pending.get("index")
    if isinstance(idx, int) and 0 <= idx < len(events):
        return idx
    for i, e in enumerate(events):
        if field is not None and value is not None and e.get(field) == value:
            return i
        if field is not None and value is None and field not in e:
            return i
    return 0


def _reask(pending: dict, ctx: dict) -> dict[str, Any]:
    reason = pending.get("reason")
    action = pending.get("action") or "append"
    events = [e for e in (pending.get("events") or []) if isinstance(e, dict)]
    return _clarify(reason, action, events, candidates=pending.get("candidates"), index=pending.get("index")
                    if isinstance(pending.get("index"), int) else None,
                    confirmed=set(pending.get("confirmed") or []), query=pending.get("query"))


def _answer_pending(toks: list[Tok], utterance: str, today: date, ctx: dict, pending: dict) -> dict | None:
    reason = pending.get("reason")
    action = pending.get("action") or "append"
    events = [dict(e) for e in (pending.get("events") or []) if isinstance(e, dict)]
    confirmed = set(c for c in (pending.get("confirmed") or []) if isinstance(c, str))
    candidates = pending.get("candidates")
    sig = _answer_tokens(toks)
    if not sig:
        return _reask(pending, ctx)
    le = _last_event(ctx)

    if reason == "unclear_correction":
        base = le or (events[0] if events else None)
        kws = _kws(sig)
        if "undo" in kws and not any(t.cls == "amt" for t in sig):
            return {"status": "ok", "action": "undo", "target": "last"} if base else _rejected("no_last_event")
        num = _only_number(sig)
        if isinstance(num, int):
            if base is None:
                return _rejected("no_last_event")
            if num <= 0:
                return _rejected("invalid_number")
            new = _clean_event(base)
            new["amount"] = num
            return _finalize([new], "amend", ctx)
        if _is_no(sig) or _is_cancel(sig):
            return _rejected("cancelled")
        result, d = _fresh(toks, utterance, today, ctx)
        if d.complete or d.action in ("amend", "undo"):
            return result
        return _reask(pending, ctx)

    if _is_cancel(sig):
        return _rejected("cancelled")

    if reason == "plausibility":
        if _is_yes(sig):
            confirmed.add("plausibility")
            return _finalize(events, action, ctx, confirmed=confirmed)
        if _is_no(sig):
            return _rejected("cancelled")
        num = _only_number(sig)
        if isinstance(num, int) and events:
            if num <= 0:
                return _rejected("invalid_number")
            limit = _limit(ctx)
            i = pending.get("index") if isinstance(pending.get("index"), int) and \
                0 <= pending["index"] < len(events) else next(
                (j for j, e in enumerate(events) if e.get("amount", 0) > limit), 0)
            events[i]["amount"] = num
            confirmed.add("plausibility")
            return _finalize(events, action, ctx, confirmed=confirmed)

    elif reason == "confusable_number":
        cands = candidates if isinstance(candidates, list) and len(candidates) >= 2 else None
        choice = None
        num = _only_number(sig)
        if isinstance(num, int):
            choice = num
        elif cands is not None:
            o = _ordinal(sig)
            if o is not None:
                choice = cands[o]
            elif _is_yes(sig):
                choice = cands[0]
        if choice is not None and events:
            if choice <= 0:
                return _rejected("invalid_number")
            i = _target_index(events, pending, "amount", cands[0] if cands else None)
            events[i]["amount"] = choice
            confirmed |= {"confusable_number", "plausibility"}
            return _finalize(events, action, ctx, confirmed=confirmed)
        if _is_no(sig):
            return _rejected("cancelled")

    elif reason == "missing_amount":
        num = _only_number(sig)
        if num == "bad" or num == 0:
            return _reask(pending, ctx) if num == "bad" else _rejected("invalid_number")
        if isinstance(num, int) and events:
            i = _target_index(events, pending, "amount", None)
            events[i]["amount"] = num
            return _finalize(events, action, ctx, confirmed=confirmed)

    elif reason == "same_name":
        cands = [c for c in (candidates or []) if isinstance(c, dict)]
        pick = None
        if cands:
            o = _ordinal(sig)
            if _pehle_wale(sig):
                untagged = [c for c in cands if not c.get("tags")]
                pick = untagged[0] if len(untagged) == 1 else cands[0]
            elif o is not None and o < len(cands):
                pick = cands[o]
            else:
                spoken = " ".join(t.raw if not is_devanagari(t.raw) else romanise_word(t.raw, False) for t in sig
                                  if not (t.cls == "kw" and t.kw in ("filler", "hai", "ji", "ok", "yes")))
                hits = [c for c in cands if any(nm.tag_matches(spoken, ct) for ct in (c.get("tags") or []))]
                if len(hits) == 1:
                    pick = hits[0]
        if pick is not None:
            if action == "query":
                q = dict(pending.get("query") or {})
                q["customer"] = pick.get("name", q.get("customer"))
                q["customer_id"] = pick.get("id")
                return {"status": "ok", "action": "query", "query": q}
            i = _target_index(events, pending, "customer", pick.get("name"))
            if events:
                _apply_fields(events[i], {"customer": pick.get("name"), "customer_id": pick.get("id")})
            return _finalize(events, action, ctx, confirmed=confirmed)

    elif reason == "missing_customer":
        rest = [t for t in sig if not (t.cls == "kw" and t.kw in ("filler", "hai", "ji", "ok", "yes")
                                       or t.kw in _MARKERS)]
        if rest and all(t.cls in ("unk", "hon", "tag") for t in rest) and events:
            runs = _name_runs(rest)
            if runs and (runs[0].key or runs[0].tags):
                i = _target_index(events, pending, "customer", None)
                events[i]["customer"] = runs[0].key
                for key in ("customer_id", "new_customer", "tags"):
                    events[i].pop(key, None)
                if runs[0].tags:
                    events[i]["tags"] = runs[0].tags
                return _finalize(events, action, ctx, confirmed=confirmed)

    elif reason == "ambiguous_direction":
        kind = _answer_kind(sig)
        if kind is not None and events:
            i = _target_index(events, pending, "kind", None)
            events[i]["kind"] = kind
            return _finalize(events, action, ctx, confirmed=confirmed)

    elif reason == "unclear_date":
        only_date = all(t.cls == "date" or t.kw in ("aaj", "kal", "parso", "time", "filler", "hai", "tha")
                        for t in sig)
        if only_date:
            iso, issue = _date_of(sig, today)
            if iso and events:
                i = _target_index(events, pending, "date", None)
                events[i]["date"] = iso
                return _finalize(events, action, ctx, confirmed=confirmed)

    result, d = _fresh(toks, utterance, today, ctx)
    if d.complete:
        return result
    if reason == "plausibility" or reason == "confusable_number":
        if _is_no(sig):
            return _rejected("cancelled")
    return _reask(pending, ctx)


def _answer_kind(sig: list[Tok]) -> str | None:
    kws = [t.kw for t in sig if t.cls == "kw" and t.kw not in ("filler", "hai", "tha", "kiya")]
    others = [t for t in sig if t.cls not in ("kw", "aux")]
    if others:
        return None
    s = set(kws)
    if not s:
        return None
    if s <= {"udhaar", "credit", "ko", "give", "on"} and s & {"udhaar", "credit", "ko"}:
        return "credit"
    if s <= {"payment", "jama", "mila", "ne", "give", "paymode", "aaya"} and s:
        return "payment"
    if kws == ["first"]:
        return "payment"
    if kws == ["second"]:
        return "credit"
    return None


# ---------------------------------------------------------------------------------------------------------------


def parse(utterance: str, *, today: date, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse one utterance. See the module docstring and CONTRACT section 1 for the result shape."""
    try:
        return _parse(utterance, today, ctx)
    except Exception:  # never raise on the latency path; an unreadable input is simply not understood
        return _rejected("not_ledger")


def _parse(utterance: Any, today: date, ctx: Any) -> dict[str, Any]:
    """`parse` without the safety net, so tests can see any exception the net would hide."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(utterance, str):
        utterance = ""
    ctx = ctx if isinstance(ctx, dict) else {}
    toks = _tokenise(utterance)
    pending = ctx.get("pending")
    if isinstance(pending, dict) and isinstance(pending.get("reason"), str):
        res = _answer_pending(toks, utterance, today, ctx, copy.deepcopy(pending))
        if res is not None:
            return res
    result, _d = _fresh(toks, utterance, today, ctx)
    return result
