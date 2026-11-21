"""One turn: transcript, parser context, parse, ledger or query, reply (docs/ARCHITECTURE.md).

The parser and the number-to-words function are injected, so the pipeline runs before `nlu` is finished and in
tests. Nothing here speaks: the caller sends `TurnResult.speak_text` to text-to-speech after `run_turn` returns,
which is after the database transaction has committed. For a saving turn the reply is built inside that
transaction, so a reply that cannot be built rolls the entry back and the turn becomes the rejected reply.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Settings
from .logsafe import describe
from .ledger import PERIODS, DuplicateUtterance, Ledger, Outcome, in_quiet_hours, period_range
from .names import display_name
from .replies import NumberToWords, Reply, Replier, default_number_to_words, fixed_replies

log = logging.getLogger("khata.pipeline")

ParseFn = Callable[..., dict]

PENDING_TTL_S = 60          # an open question expires after this (E02)
CONFIRM_BELOW = 10          # amounts below this without a currency word are confirmed (parser rule)
CARRY_S = 60                # customer carry-over window (parser rule)
DUPLICATE_S = 30            # repeated-entry window (parser rule)
NUMBER_WORDS_MAX = 9_999_999
PRIVATE_QUERIES = {"balance", "top_dues", "outstanding_total", "due_since", "daily_summary"}
BALANCE_CONFIRMS = {"settle", "half", "writeoff", "roundoff", "overpayment", "reminder"}  # questions stating a balance
UTT_ID_MAX = 64


def default_parse(utterance: str, *, today: date, ctx: dict | None = None) -> dict:
    from nlu.parser import parse

    return parse(utterance, today=today, ctx=ctx)


def warm_default_parser() -> bool:
    """Load the parser vocabulary now, so the first live turn does not pay for it. Returns True when warmed."""
    try:
        from nlu.parser import warm
    except ImportError:
        return False
    try:
        warm()
    except Exception as exc:
        log.warning("parser warm-up failed: %s", type(exc).__name__)
        return False
    return True


@dataclass
class SessionState:
    """Per-session conversation state. The last event is read from the ledger, so undo walks back correctly."""

    session_id: str
    disclosed: bool = False
    pending: dict | None = None
    pending_at: datetime | None = None
    turn_id: int = -1
    lang: str = "hi"  # language of replies: "hi" (Hinglish) or "en"
    private: bool = False
    last_turn: dict | None = None  # {"action", "at", "customer"?, "customer_id"?}
    last_result: dict | None = None  # the last `result` message sent, replayed in `ready` on resume
    last_turn_id: int | None = None

    def set_pending(self, pending: dict | None, now: datetime) -> None:
        self.pending = pending
        self.pending_at = now if pending else None

    def clear_pending(self) -> None:
        self.pending = None
        self.pending_at = None


@dataclass
class TurnResult:
    status: str
    action: str
    reply_text: str
    speak_text: str
    trace_id: str
    utterance_id: str
    reason: str | None = None
    question: str | None = None
    entries: list[dict] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    discloses: bool = False  # the reply text carries the AI disclosure sentence
    lang: str = "hi"
    cacheable: bool = False  # fixed wording with no name and no amount: audio may be cached on disk
    query: dict | None = None
    balances: list[dict] | None = None
    candidates: list | None = None
    confirm: dict | None = None
    duplicate: bool = False
    error_code: str | None = None  # set instead of a result: the session answers with an `error` message

    def message(self, turn_id: int) -> dict[str, Any]:
        """The `result` message of CONTRACT sections 3 and 3.3."""
        msg: dict[str, Any] = {"type": "result", "turn_id": turn_id, "trace_id": self.trace_id, "status": self.status,
                               "action": self.action, "entries": self.entries, "reply_text": self.reply_text,
                               "lang": self.lang}
        for key in ("reason", "question", "query", "balances", "candidates", "confirm"):
            value = getattr(self, key)
            if value is not None:
                msg[key] = value
        if self.duplicate:
            msg["duplicate"] = True
        return msg

    _RECORD = ("status", "action", "reply_text", "speak_text", "reason", "question", "entries", "lang", "cacheable",
               "query", "balances", "candidates", "confirm", "trace_id", "discloses")

    def record(self, plain: Reply) -> dict:
        """What the utterance row keeps so a repeated `utt_id` gets the same result: the result as sent, plus the
        reply without the disclosure prefix (`plain_text`, `plain_speak`)."""
        d = {k: v for k, v in asdict(self).items() if k in self._RECORD}
        d["reply_text"], d["speak_text"] = str(self.reply_text), str(self.speak_text)
        d["plain_text"], d["plain_speak"] = str(plain.text), str(plain.speak)
        return d


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _amounts(result: dict) -> list[int]:
    """Every amount in a parser result that the server may save or speak."""
    out: list[int] = []
    pending = result.get("pending") if isinstance(result.get("pending"), dict) else {}
    for evs in (result.get("events"), pending.get("events")):
        for ev in evs or []:
            if isinstance(ev, dict) and _is_int(ev.get("amount")):
                out.append(ev["amount"])
    for cands in (result.get("candidates"), pending.get("candidates")):
        out.extend(c for c in cands or [] if _is_int(c))
    for confirm in (result.get("confirm"), pending.get("confirm")):
        if isinstance(confirm, dict):
            out.extend(v for k, v in confirm.items() if k != "type" and _is_int(v))
    if _is_int(result.get("amount")):
        out.append(result["amount"])
    return out


def clean_device_ts(value: Any) -> str | None:
    """The client's clock reading: an ISO 8601 timestamp, returned in normalised form; anything else is None."""
    if not isinstance(value, str) or not (10 <= len(value.strip()) <= 40):
        return None
    try:
        return datetime.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def text_fingerprint(transcript: str, session_id: str | None = None) -> str:
    """Hash of the transcript an utterance id was first used with (kept inside the encrypted body).

    The session is deliberately not part of it: the page's offline queue resends a typed sentence after a reload,
    in a new session, and that retry must be recognised (O02). A different sentence under the same id is refused."""
    raw = " ".join(transcript.split()).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_utt_id(value: Any) -> str | None:
    """A client utterance id: a non-empty string of printable characters, at most 64 long, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > UTT_ID_MAX or not value.isprintable():
        return None
    return value


class Pipeline:
    def __init__(self, ledger: Ledger, settings: Settings, *, parse: ParseFn | None = None,
                 number_to_words: NumberToWords | None = None, now: Callable[[], datetime] | None = None):
        self.ledger = ledger
        self.settings = settings
        self.parse = parse or default_parse
        self.uses_default_parser = parse is None
        self.replies = Replier(number_to_words or default_number_to_words())
        self._r = self.replies  # replier for the language of the turn in progress
        self._tz = ZoneInfo(settings.shop_tz)
        self._now = now or (lambda: datetime.now(self._tz))
        self._fixed = {lang: {r.speak for r in fixed_replies(self.replies.with_lang(lang))} for lang in ("hi", "en")}

    def now(self) -> datetime:
        """The server clock in SHOP_TZ: every ledger `ts` and the shop day come from it (C05, C06)."""
        t = self._now()
        return t.astimezone(self._tz) if t.tzinfo is not None else t.replace(tzinfo=self._tz)

    # ---- disclosure -------------------------------------------------------------------------------------------
    def _disclose(self, state: SessionState, reply: Reply) -> tuple[Reply, bool]:
        """Prefix the AI disclosure to every reply until a spoken reply carrying it has been fully sent."""
        if state.disclosed:
            return reply, False
        d = self._r.disclosure()
        if reply.text.startswith(d.text):
            return reply, True
        return Reply(f"{d.text} {reply.text}", f"{d.speak} {reply.speak}"), True

    def mark_spoken(self, state: SessionState, turn: TurnResult) -> None:
        """Record that a reply was sent to its end without being cancelled. Only then is the session disclosed."""
        if turn.discloses:
            state.disclosed = True

    def _use_lang(self, state: SessionState) -> None:
        self._r = self.replies.with_lang(state.lang)

    def _fixed_reply(self, state: SessionState, reply: Reply, action: str, reason: str) -> TurnResult:
        """A spoken rejection outside the parser (silence, too long, empty transcript, upstream failure). It is a
        turn: a correction after it must not change an older entry, so `last_turn` becomes `none`."""
        self._use_lang(state)
        self._set_last_turn(state, "none", self.now())
        plain = reply
        reply, discloses = self._disclose(state, reply)
        return TurnResult("rejected", action, reply.text, reply.speak, uuid.uuid4().hex[:16], uuid.uuid4().hex[:12],
                          reason=reason, discloses=discloses, cacheable=self._cacheable(state, plain),
                          lang=state.lang)

    def greeting(self, state: SessionState, trace_id: str | None = None) -> TurnResult:
        self._use_lang(state)
        reply, _ = self._disclose(state, self._r.disclosure())
        return TurnResult("ok", "greeting", reply.text, reply.speak, trace_id or uuid.uuid4().hex[:16],
                          uuid.uuid4().hex[:12], discloses=True, cacheable=True, lang=state.lang)

    def upstream_failure(self, state: SessionState) -> TurnResult:
        self._use_lang(state)
        return self._fixed_reply(state, self._r.upstream_failure(), "none", "upstream")

    def silence(self, state: SessionState) -> TurnResult:
        """A recording of half a second or more in which no speech was detected (M02)."""
        self._use_lang(state)
        return self._fixed_reply(state, self._r.silence(), "none", "silence")

    def too_long(self, state: SessionState) -> TurnResult:
        """A recording cut at 30 seconds (M07). Nothing is parsed or saved."""
        self._use_lang(state)
        return self._fixed_reply(state, self._r.too_long(), "none", "too_long")

    def empty_transcript(self, state: SessionState) -> TurnResult:
        """Speech was detected but the transcript is empty (M01)."""
        self._use_lang(state)
        return self._fixed_reply(state, self._r.rejected(), "none", "empty_transcript")

    def _cacheable(self, state: SessionState, plain: Reply) -> bool:
        return plain.speak in self._fixed.get(state.lang, set())

    # ---- parser context ---------------------------------------------------------------------------------------
    def limits(self) -> dict:
        s = self.settings
        return {"confirm_above": s.confirm_above, "confirm_below": CONFIRM_BELOW, "max_amount": s.max_amount,
                "carry_s": CARRY_S, "duplicate_s": DUPLICATE_S, "confirm_new_customer": bool(s.confirm_new_customer),
                "strict": bool(s.strict_save)}

    def expire_pending(self, state: SessionState, now: datetime) -> None:
        if state.pending and state.pending_at is not None:
            if (now - state.pending_at).total_seconds() > PENDING_TTL_S:
                state.clear_pending()

    def build_ctx(self, state: SessionState, now: datetime) -> dict:
        ctx: dict[str, Any] = {"customers": self.ledger.customers_for_parser(), "limits": self.limits(),
                               "confusables": self.ledger.confusables()}
        last = self.ledger.last_active_event(state.session_id, now)
        if last:
            ctx["last_event"] = last
            ctx["last_events"] = self.ledger.last_events(state.session_id, now)
        if state.last_turn:
            lt = {k: v for k, v in state.last_turn.items() if k != "at" and v is not None}
            lt["age_s"] = max(0, int((now - state.last_turn["at"]).total_seconds()))
            ctx["last_turn"] = lt
        self.expire_pending(state, now)
        if state.pending:
            ctx["pending"] = state.pending
        return ctx

    # ---- one turn ---------------------------------------------------------------------------------------------
    def run_turn(self, state: SessionState, transcript: str, *, trace_id: str | None = None,
                 utt_id: str | None = None, device_ts: str | None = None) -> TurnResult:
        """Parse and apply one utterance. Never raises: a failure becomes the rejected reply with nothing saved."""
        trace_id = trace_id or uuid.uuid4().hex[:16]
        client_id = clean_utt_id(utt_id)
        utterance_id = client_id or uuid.uuid4().hex[:12]
        device_ts = clean_device_ts(device_ts)
        fingerprint = text_fingerprint(transcript, state.session_id)
        self._use_lang(state)
        try:
            if client_id:
                prior = self.ledger.find_utterance(client_id)
                if prior is not None:
                    return self._repeat(state, prior, fingerprint, trace_id, utterance_id)
            return self._run(state, transcript, trace_id, utterance_id, device_ts)
        except DuplicateUtterance as dup:
            return self._repeat(state, dup.record, fingerprint, trace_id, utterance_id)
        except Exception as exc:
            # Only the exception type and the code location are logged: messages can hold amounts or names.
            log.error("turn failed: %s", describe(exc))
            state.clear_pending()
            self._use_lang(state)
            turn = self._fixed_reply(state, self._r.rejected(), "none", "internal")
            turn.trace_id, turn.utterance_id = trace_id, uuid.uuid4().hex[:12]
            self._record(state, turn, transcript, self._r.rejected(), device_ts)
            return turn

    def _repeat(self, state: SessionState, prior: dict, fingerprint: str, trace_id: str,
                utterance_id: str) -> TurnResult:
        """A repeated `utt_id`. The same sentence is a retry (from any session) and gets the first result back;
        a different sentence is a reused id: an error, and nothing is saved."""
        if prior.get("fingerprint") == fingerprint and isinstance(prior.get("result"), dict):
            return self._replay(state, prior["result"], trace_id, utterance_id)
        return TurnResult("rejected", "none", "", "", trace_id, utterance_id, reason="utt_id_reused",
                          lang=state.lang, error_code="utt_id_reused")

    def _replay(self, state: SessionState, rec: dict, trace_id: str, utterance_id: str) -> TurnResult:
        """The first result of a repeated `utt_id`, unchanged apart from `duplicate: true`. Nothing is saved and no
        state changes. Only when this session has not been disclosed yet and the first reply did not carry the
        disclosure is the disclosure put in front (CONTRACT section 7: every session's first reply discloses)."""
        self._use_lang(state)
        sent = Reply(rec.get("reply_text") or self._r.rejected().text, rec.get("speak_text") or "")
        if not sent.speak:
            sent = Reply(sent.text, sent.text)
        reply, discloses = sent, bool(rec.get("discloses"))
        if not state.disclosed and not discloses:
            plain = Reply(rec.get("plain_text") or sent.text, rec.get("plain_speak") or sent.speak)
            reply, discloses = self._disclose(state, plain)
        return TurnResult(rec.get("status", "rejected"), rec.get("action", "none"), reply.text, reply.speak,
                          rec.get("trace_id") or trace_id, utterance_id, reason=rec.get("reason"),
                          question=rec.get("question"),
                          entries=rec.get("entries") or [], discloses=discloses, lang=rec.get("lang") or state.lang,
                          cacheable=bool(rec.get("cacheable")), query=rec.get("query"), balances=rec.get("balances"),
                          candidates=rec.get("candidates"), confirm=rec.get("confirm"), duplicate=True)

    def _name_of(self, ev: dict) -> str:
        cid = ev.get("customer_id")
        if cid and self.ledger.find_customer(customer_id=cid) is not None:
            return self.ledger.label(cid)
        return display_name(str(ev.get("customer") or ""))

    def _candidates(self, result: dict) -> list | None:
        pending = result.get("pending") if isinstance(result.get("pending"), dict) else {}
        cands = result.get("candidates") or pending.get("candidates")
        if not cands:
            return None
        out: list = []
        for c in cands:
            if _is_int(c):
                out.append(c)
            elif isinstance(c, dict) and "kind" not in c and ("name" in c or "id" in c):
                cid = c.get("id")
                known = cid and self.ledger.find_customer(customer_id=cid) is not None
                out.append({"id": cid, "display": str(self.ledger.label(cid)) if known
                            else display_name(str(c.get("name") or "")), "tags": list(c.get("tags") or [])})
            elif isinstance(c, dict) and "kind" in c:
                # An entry of an `unclear_correction` question: {"id","kind","amount","customer" (display)}.
                cid = c.get("customer_id")
                known = cid and self.ledger.find_customer(customer_id=cid) is not None
                name = str(self.ledger.label(cid)) if known else display_name(str(c.get("customer") or ""))
                out.append({"id": c.get("id"), "kind": c.get("kind"), "amount": c.get("amount"), "customer": name})
        return out

    def _guard(self, result: dict) -> dict:
        """A result with an amount the server cannot save or voice becomes the `too_large` rejection."""
        limit = min(self.settings.max_amount, NUMBER_WORDS_MAX)
        if any(a > limit for a in _amounts(result)):
            out = {"status": "rejected", "reason": "too_large"}
            if result.get("lang") in ("hi", "en"):
                out["lang"] = result["lang"]
            return out
        return result

    def _set_last_turn(self, state: SessionState, action: str, now: datetime, customer: dict | None = None) -> None:
        lt: dict[str, Any] = {"action": action, "at": now}
        if customer:
            lt["customer"], lt["customer_id"] = customer.get("key"), customer.get("id")
        state.last_turn = lt

    def _run(self, state: SessionState, transcript: str, trace_id: str, utterance_id: str,
             device_ts: str | None) -> TurnResult:
        now = self.now()
        today = now.date()
        timings: dict[str, float] = {}

        ctx = self.build_ctx(state, now)
        asked = state.pending
        t0 = time.perf_counter()
        result = self.parse(transcript, today=today, ctx=ctx)
        timings["parse"] = _ms(t0)
        if not isinstance(result, dict):
            raise TypeError("parser returned a non-dict")
        if (asked and asked.get("action") == "reminder" and result.get("status") == "ok"
                and result.get("action") == "reminder" and not (result.get("customer") or result.get("customer_id"))):
            # "Yes" to a reminder question names no customer: it is the one the question was about.
            result = dict(result, customer=asked.get("customer"), customer_id=asked.get("customer_id"))
        if result.get("lang") in ("hi", "en"):
            state.lang = result["lang"]  # a result without `lang` keeps the session language
        self._use_lang(state)
        result = self._guard(result)
        r = self._r

        status = result.get("status", "rejected")
        action = result.get("action") or "none"
        t1 = time.perf_counter()

        if status == "ok" and action in ("append", "amend", "undo"):
            return self._save(state, result, transcript, now, today, trace_id, utterance_id, device_ts, timings, t1)

        reason = result.get("reason")
        question = None
        query_info = None
        candidates = None
        confirm = None
        speak_override: str | None = None
        last_customer: dict | None = None

        if status == "ok" and action == "query":
            state.clear_pending()
            q = result.get("query") or {}
            reply, last_customer, query_info = self._query(q, today)
            if state.private and q.get("type") in PRIVATE_QUERIES:
                speak_override = r.private().speak
            self._set_last_turn(state, "query", now, last_customer)
        elif status == "ok" and action == "reminder":
            confirmed = bool(state.pending and (state.pending.get("confirm") or {}).get("type") == "reminder")
            state.clear_pending()
            reply, question_pending, last_customer = self._reminder(result, now, confirmed)
            if question_pending is not None:
                status, reason = "needs_clarification", "confirm_entry"
                state.set_pending(question_pending, now)
                confirm = question_pending["confirm"]
                question = reply.text
                if state.private:
                    speak_override = r.private_question().speak
                self._set_last_turn(state, "question", now)
            else:
                self._set_last_turn(state, "reminder", now, last_customer)
        elif status == "needs_clarification":
            state.set_pending(result.get("pending"), now)
            reply = r.clarification(result, self._name_of, today)
            if reply is None:
                q = result.get("question") or r.rejected().text
                reply = Reply(q, q)
            question = reply.text
            candidates = self._candidates(result)
            confirm = result.get("confirm") or (result.get("pending") or {}).get("confirm")
            if isinstance(confirm, dict):
                confirm = {k: v for k, v in confirm.items() if k != "words"}  # unknown words are never shown
                if state.private and confirm.get("type") in BALANCE_CONFIRMS:
                    speak_override = r.private_question().speak  # the balance stays on the screen
            self._set_last_turn(state, "question", now)
        else:
            if status == "ok":
                reason = reason or "unknown_action"
            status = "rejected"
            if reason != "not_ledger":
                state.clear_pending()
            reply = self._rejection(state, result, reason)
            self._set_last_turn(state, "none", now)
            action = result.get("action") or "none"
        timings["db"] = _ms(t1)

        plain = reply if speak_override is None else Reply(reply.text, speak_override)
        shown, discloses = self._disclose(state, plain)
        turn = TurnResult(status, action, shown.text, shown.speak, trace_id, utterance_id, reason=reason,
                          question=question, timings=timings, discloses=discloses,
                          cacheable=self._cacheable(state, plain), lang=state.lang, query=query_info,
                          candidates=candidates, confirm=confirm)
        self._record(state, turn, transcript, plain, device_ts)
        return turn

    def _record(self, state: SessionState, turn: TurnResult, transcript: str, plain: Reply,
                device_ts: str | None) -> None:
        try:
            self.ledger.record_utterance(turn.utterance_id, state.session_id, self.now(), transcript=transcript,
                                         status=turn.status, reply_text=turn.reply_text, timings=turn.timings,
                                         result=turn.record(plain), device_ts=device_ts,
                                         fingerprint=text_fingerprint(transcript, state.session_id))
        except Exception as exc:
            # Nothing was saved by this turn; a failed log row must not change the reply.
            log.warning("could not record utterance: %s", type(exc).__name__)

    def _rejection(self, state: SessionState, result: dict, reason: str | None) -> Reply:
        r = self._r
        if reason == "no_last_event":
            if result.get("action") == "undo":
                return r.nothing_to_undo()
            if (state.last_turn or {}).get("action") == "undo":
                return r.entry_removed()
            return r.nothing_to_amend()
        table = {"cancelled": r.cancelled, "future": r.future, "negated": r.negated, "out_of_scope": r.out_of_scope,
                 "too_large": r.too_large, "no_question": r.no_question}
        return table.get(reason or "", r.rejected)()

    def _save(self, state: SessionState, result: dict, transcript: str, now: datetime, today: date, trace_id: str,
              utterance_id: str, device_ts: str | None, timings: dict, t1: float) -> TurnResult:
        """Apply an append, amend or undo. The reply and the utterance row are built inside the transaction."""
        r = self._r
        holder: dict[str, Any] = {}
        prior_turn = state.last_turn

        def finish(outcome: Outcome) -> dict:
            status, reason = "ok", None
            entries: list[dict] = []
            touched: list[str] = []
            if outcome.nothing:
                status, reason = "rejected", "no_last_event"
                target = result.get("target")
                if outcome.action == "undo":
                    reply = r.nothing_to_undo()
                elif isinstance(target, dict):
                    reply = r.entry_not_found()
                elif (prior_turn or {}).get("action") == "undo":
                    reply = r.entry_removed()
                else:
                    reply = r.nothing_to_amend()
            elif outcome.action == "undo":
                reply = r.undo(outcome.reversed[0])
                entries = self.ledger.entries_by_ids([outcome.reversed[0]["id"]])
                touched = [outcome.reversed[0]["customer_id"]]
            elif outcome.action == "amend":
                reply = r.amend(outcome.saved[0])
                entries = self.ledger.entries_by_ids([outcome.reversed[0]["id"]] + [e["id"] for e in outcome.saved])
                touched = [outcome.saved[0]["customer_id"], outcome.reversed[0]["customer_id"]]
            else:
                reply = r.saved(outcome.saved, today)
                entries = self.ledger.entries_by_ids([e["id"] for e in outcome.saved])
                touched = [e["customer_id"] for e in outcome.saved]
            balances = self.ledger.balance_items(touched) if touched else None
            timings["db"] = _ms(t1)
            shown, discloses = self._disclose(state, reply)
            turn = TurnResult(status, outcome.action if status == "ok" else (result.get("action") or "none"),
                              shown.text, shown.speak, trace_id, utterance_id, reason=reason, entries=entries,
                              timings=timings, discloses=discloses, cacheable=self._cacheable(state, reply),
                              lang=state.lang, balances=balances)
            holder["turn"], holder["outcome"] = turn, outcome
            return {"transcript": transcript, "status": status, "reply_text": shown.text, "timings": timings,
                    "result": turn.record(reply), "fingerprint": text_fingerprint(transcript, state.session_id)}

        self.ledger.apply(result, now=now, session_id=state.session_id, trace_id=trace_id,
                          utterance_id=utterance_id, finish=finish, device_ts=device_ts)
        turn: TurnResult = holder["turn"]
        outcome: Outcome = holder["outcome"]
        state.clear_pending()
        if outcome.nothing:
            self._set_last_turn(state, "none", now)
        else:
            ev = (outcome.saved or outcome.reversed)[-1]
            self._set_last_turn(state, outcome.action, now, {"key": ev.get("key"), "id": ev.get("customer_id")})
        return turn

    # ---- queries ----------------------------------------------------------------------------------------------
    def _query(self, q: dict, today: date) -> tuple[Reply, dict | None, dict]:
        """Answer a query. Returns the reply, the customer asked about (if one) and the `result.query` object."""
        r = self._r
        led = self.ledger
        kind = q.get("type")
        period = q.get("period") or "today"
        info: dict[str, Any] = {"type": kind}
        if q.get("period"):
            info["period"] = period
        if period not in PERIODS:
            return r.unclear_date(), None, info
        start, end = period_range(period, today)

        if kind in ("balance", "due_since"):
            if q.get("unknown_customer"):
                uc = q["unknown_customer"]
                name = uc if isinstance(uc, str) else (q.get("customer") or "")
                return (r.unknown_customer(display_name(str(name))) if name else r.missing_customer()), None, info
            customer = led.find_customer(key=q.get("customer"), customer_id=q.get("customer_id"))
            if customer is None:
                if not q.get("customer"):
                    return r.missing_customer(), None, info
                return r.unknown_customer(display_name(str(q["customer"]))), None, info
            info["customer_id"] = customer["id"]
            cid, name = customer["id"], led.label(customer["id"])
            bal, has = led.balance(cid), led.has_entries(cid)
            if kind == "due_since" and has and bal > 0:
                since = led.due_since(cid)
                if since is not None:
                    return r.due_since(name, since), customer, info
            return r.balance(name, bal, has), customer, info
        if kind == "credit_total":
            return r.credit_total(led.credit_total(start, end), period), None, info
        if kind == "payment_total":
            return r.payment_total(led.payment_total(start, end), period), None, info
        if kind == "daily_summary":
            return r.daily_summary(led.daily_summary(start, end), period), None, info
        if kind == "top_dues":
            return r.top_dues(led.top_dues(3)), None, info
        if kind == "outstanding_total":
            o = led.outstanding_total()
            return r.outstanding_total(o["amount"], o["customers"]), None, info
        return r.rejected(), None, info

    # ---- reminders (Q08) --------------------------------------------------------------------------------------
    def _reminder(self, result: dict, now: datetime, confirmed: bool) -> tuple[Reply, dict | None, dict | None]:
        """Queue a reminder after checking consent, the real balance and sending hours. A spoken amount that differs
        from the balance asks first. Returns (reply, pending question or None, customer)."""
        r = self._r
        led = self.ledger
        customer = led.find_customer(key=result.get("customer"), customer_id=result.get("customer_id"))
        if customer is None:
            if result.get("customer"):
                return r.unknown_customer(display_name(str(result["customer"]))), None, None
            return r.missing_customer(), None, None
        cid, name = customer["id"], led.label(customer["id"])
        if not customer.get("reminders_opt_in"):
            return r.reminder_no_consent(name), None, customer
        bal = led.balance(cid)
        if bal <= 0:
            return r.reminder_nothing_due(name), None, customer
        if in_quiet_hours(now):
            return r.reminder_quiet(), None, customer
        said = result.get("amount")
        if not confirmed and _is_int(said) and said != bal:
            confirm = {"type": "reminder", "balance": bal, "said": said}
            pending = {"reason": "confirm_entry", "action": "reminder", "customer": customer["key"],
                       "customer_id": cid, "amount": bal, "events": [], "confirm": confirm}
            return r.reminder_confirm(name, bal, said), pending, customer
        led.queue_reminder(cid, now)
        return r.reminder_ready(name), None, customer
