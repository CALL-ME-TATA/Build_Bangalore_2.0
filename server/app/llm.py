"""LLM fallback for sentences the rule parser refuses as `not_ledger` (CONTRACT: the money path stays deterministic).

The LLM never produces an entry. It only rewrites the shopkeeper's sentence into the simple form the parser already
understands ("Ramesh ka teen sau chaalis udhaar"), and that rewrite goes back through the same parser. Four guards
keep a wrong save impossible:

1. Grounding: every amount in the result must be a number the shopkeeper actually said, and every customer must be
   an existing one or a name that appears in the original sentence. Otherwise the original refusal stands.
2. Read-back: the rewrite is parsed with `limits.noisy`, so any entry becomes "Ramesh ke ₹340 udhaar likhun?" and is
   saved only after a yes. Queries (read-only) are answered directly.
3. Intent: the sentence must hold a money or ledger word before the LLM is called at all, and the direction of
   each entry (credit or payment) must have its own cue word in the original. Numbers followed by a unit that makes
   them a count, age, time or score ("5 saal", "2 baje", "250 run") are never amounts.
4. Scope: only a fresh `not_ledger` refusal or a missing-amount / missing-customer question reaches the LLM. Answers to an open question, undo, amend, reminders and
   the parser's deliberate refusals (future, negated, out_of_scope, ...) never do. Any error or timeout keeps the
   original refusal, so the LLM can only turn a refusal into a question or an answer, never into a silent save.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx

from nlu.numbers import parse_number
from nlu.translit import fold, is_devanagari, romanise_word

log = logging.getLogger("khata.llm")

Rewrite = Callable[[str, list[str]], "str | None"]  # (sentence, customer names) -> canonical sentence or None
# The parser's results the LLM may try to improve: a refusal, or a question for something the sentence may hold.
TRIGGERS = {("rejected", "not_ledger"), ("needs_clarification", "missing_amount"),
            ("needs_clarification", "missing_customer")}
MAX_SPAN = 6  # longest number phrase looked for in the original sentence ("saadhe teen sau chaalis rupaye")

# ---- guardrails: fixed word lists, checked in code, so they hold even when the LLM is wrong --------------------
# The sentence must say, in the shopkeeper's own words, that money moved (or ask about money). No cue: no LLM call.
PAYMENT_CUES = set("""diya diye di de dia die dena jama mila mile mili chukaya chukaye chuka chukta lautaya lautaye
    lautai wapas vapas thamaya thamaye thamai bhara bhare payment paid pay gave received upi phonepe gpay""".split())
CREDIT_CUES = set("""udhaar udhar udhari credit liya liye li le lena uthaya uthaye uthai saman samaan saaman maal
    khate khata likh likho likhdo baaki baki bill took owes owe""".split())
QUERY_CUES = set("""kitna kitne kitni total hisaab hisab baaki baki balance kiska kiske batao bata summary dues
    outstanding dikhao dikha""".split())
MONEY_WORDS = set("""rupaye rupay rupees rupee rupiya rupaiye paisa paise rs inr""".split())
# A number right before one of these is a count, an age, a time or a score, never an amount ("5 saal", "250 run").
NOT_MONEY_UNITS = set("""saal sal baje baj log logon aadmi run runs kilo kg gram litre liter din mahine mahina
    ghante ghanta minute minat percent pratishat number no packet packets dabba dabbe bachche bacche wicket over
    overs class km meter""".split())

SYSTEM = """You rewrite a kirana shopkeeper's spoken Hindi/Hinglish/English sentence into ONE short canonical \
Hinglish sentence for a rule-based udhaar ledger parser. Output only that sentence, or NONE.

Canonical forms:
- credit (customer took goods on udhaar): "<Name> ka <amount> udhaar"
- payment (customer paid the shop): "<Name> ne <amount> diye"
- several entries: join with " aur ", e.g. "Ramesh ka 340 udhaar aur Sunita ne 200 diye"
- balance question: "<Name> ka total kitna hai"
- today's summary: "aaj ka hisaab batao"
- top dues: "sabse zyada baaki kiska hai"

Rules:
- Copy every amount EXACTLY as the shopkeeper said it (digits or number words). Never compute, convert or guess.
- Use names exactly as said. Never invent a name or an amount.
- Output NONE unless the sentence clearly says money moved between the shop and a customer, or asks about a
  customer's money. Ages, times, phone numbers, counts, prices of things not bought, cricket scores, gossip,
  chit-chat, promises ("kal dunga"), supplier or expense payments, or anything you are unsure about: NONE.
- Examples of NONE: "Ramesh ki beti 5 saal ki hai", "Sunita 2 baje aayegi", "kal match mein 250 run bane",
  "Ramesh ko 500 ki zarurat hai shayad", "Sunita ne 300 wali saree pehni"."""


def _words(text: str) -> list[str]:
    out: list[str] = []
    for w in text.replace(",", " ").split():
        w = w.strip(".?!।\"'").lower()
        if not w:
            continue
        out.extend(romanise_word(w).split() if is_devanagari(w) else [w])
    return out


def spoken_amounts(text: str) -> set[int]:
    """Every value any 1..MAX_SPAN-word span of the sentence reads as a number, except spans followed by a unit
    that makes them a count, an age, a time or a score ("5 saal", "2 baje", "250 run")."""
    words = text.replace(",", " ").split()
    folded = [fold(w.strip(".?!।\"'").lower()) for w in words]
    out: set[int] = set()
    for i in range(len(words)):
        for j in range(i + 1, min(len(words), i + MAX_SPAN) + 1):
            if j < len(words) and folded[j] in {fold(u) for u in NOT_MONEY_UNITS}:
                continue
            v = parse_number(" ".join(words[i:j]).replace("₹", " "))
            if v is not None:
                out.add(v)
    return out


def _cues(text: str) -> set[str]:
    return {fold(w) for w in _words(text)}


def _has(cues: set[str], vocab: set[str]) -> bool:
    return bool(cues & {fold(w) for w in vocab})


def worth_asking(text: str) -> bool:
    """Pre-gate: only a sentence with a money or ledger word goes to the LLM at all."""
    c = _cues(text)
    return "₹" in text or _has(c, PAYMENT_CUES | CREDIT_CUES | QUERY_CUES | MONEY_WORDS)


def intent_matches(result: dict, original: str) -> bool:
    """Every entry's direction must have a cue for it in the original sentence, and a query needs a query word.
    The LLM may not decide credit or payment on its own."""
    c = _cues(original)
    for ev in _events(result):
        kind = ev.get("kind")
        if kind == "payment" and not _has(c, PAYMENT_CUES):
            return False
        if kind == "credit" and not _has(c, CREDIT_CUES):
            return False
        if kind not in (None, "credit", "payment"):
            return False  # settle, write-off, discount and the like are never taken from a rewrite
    if result.get("action") == "query" and not _has(c, QUERY_CUES):
        return False
    return True


def _events(result: dict) -> list[dict]:
    pending = result.get("pending") if isinstance(result.get("pending"), dict) else {}
    return [e for e in (result.get("events") or []) + (pending.get("events") or []) if isinstance(e, dict)]


def grounded(result: dict, original: str, ctx: dict) -> bool:
    """True when every amount and every new name in `result` comes from the shopkeeper's own sentence."""
    said = spoken_amounts(original)
    known_ids = {c.get("id") for c in ctx.get("customers") or [] if isinstance(c, dict)}
    folded = {fold(w) for w in _words(original)}
    for ev in _events(result):
        amount = ev.get("amount")
        if amount is not None and amount not in said:
            return False
        if ev.get("customer_id") in known_ids and ev.get("customer_id") is not None:
            continue
        name = str(ev.get("customer") or "")
        if name and not all(fold(w) in folded for w in _words(name)):
            return False
    q = result.get("query") if isinstance(result.get("query"), dict) else {}
    qname = q.get("customer") if isinstance(q.get("customer"), str) else ""
    if qname and q.get("customer_id") not in known_ids and not all(fold(w) in folded for w in _words(qname)):
        return False
    return True


def _allowed(result: dict) -> bool:
    status, action = result.get("status"), result.get("action")
    if status == "ok":
        return action == "query"  # read-only; appends were already turned into a read-back by limits.noisy
    if status == "needs_clarification":
        pending = result.get("pending") if isinstance(result.get("pending"), dict) else {}
        return pending.get("action") in ("append", None)
    return False


class LlmParse:
    """Wraps the rule parser: same call signature, LLM consulted only for TRIGGERS on a fresh sentence."""

    def __init__(self, base: Callable[..., dict], rewrite: Rewrite):
        self.base, self.rewrite = base, rewrite
        self.last_ms: float | None = None  # time spent in the LLM on the last call that used it

    def __call__(self, utterance: str, *, today, ctx: dict | None = None) -> dict:
        ctx = ctx or {}
        result = self.base(utterance, today=today, ctx=ctx)
        if ctx.get("pending") or (result.get("status"), result.get("reason")) not in TRIGGERS:
            return result
        if not worth_asking(utterance):
            return result  # no money word at all: chit-chat stays refused and the LLM is never called
        names = [str(c.get("name") or c.get("key") or "") for c in ctx.get("customers") or [] if isinstance(c, dict)]
        t0 = time.perf_counter()
        try:
            canonical = self.rewrite(utterance, [n for n in names if n])
        except Exception as exc:  # timeout, network, bad key: keep the refusal
            log.warning("llm rewrite failed: %s", type(exc).__name__)
            return result
        finally:
            self.last_ms = round((time.perf_counter() - t0) * 1000, 1)
        if not canonical or canonical.strip().upper().startswith("NONE"):
            return result
        limits = dict(ctx.get("limits") or {}, noisy=True)  # any entry is read back before it is saved
        second = self.base(canonical.strip()[:300], today=today, ctx=dict(ctx, limits=limits))
        if not _allowed(second) or not grounded(second, utterance, ctx) or not intent_matches(second, utterance):
            return result
        if result.get("lang") and not second.get("lang"):
            second["lang"] = result["lang"]
        second["via"] = "llm"
        return second


class OpenAICompatRewrite:
    """Chat-completions client for any OpenAI-compatible host (Groq, Cerebras, ...). One kept-alive connection."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout_s: float, reasoning_effort: str = ""):
        self.model, self.reasoning_effort = model, reasoning_effort
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_s,
                                   headers={"Authorization": f"Bearer {api_key}"})

    def __call__(self, sentence: str, names: list[str]) -> str | None:
        user = f"Customers in the khata: {', '.join(names[:200]) or 'none'}\nSentence: {sentence}"
        body: dict[str, Any] = {"model": self.model, "temperature": 0, "max_tokens": 60,
                                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort  # no thinking step: a rewrite needs none
        r = self.client.post("/chat/completions", json=body)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"] or ""
        return text.strip().splitlines()[0].strip().strip('"') if text.strip() else None

    def close(self) -> None:
        self.client.close()


def from_settings(base: Callable[..., dict], cfg: Any) -> LlmParse | None:
    """The wrapped parser when LLM_API_KEY is set, else None (rules only)."""
    if not getattr(cfg, "llm_api_key", ""):
        return None
    return LlmParse(base, OpenAICompatRewrite(cfg.llm_api_key, cfg.llm_base_url, cfg.llm_model, cfg.llm_timeout_s,
                                              cfg.llm_reasoning_effort))
