"""One turn: transcript, parser context, parse, ledger or query, reply (docs/ARCHITECTURE.md).

The parser and the number-to-words function are injected, so the pipeline runs before `nlu` is finished and in
tests. Nothing here speaks: the caller sends `TurnResult.speak_text` to text-to-speech after this function returns,
which is after the database transaction has committed.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Settings
from .ledger import Ledger
from .replies import NumberToWords, Reply, Replier, default_number_to_words

ParseFn = Callable[..., dict]


def default_parse(utterance: str, *, today: date, ctx: dict | None = None) -> dict:
    from nlu.parser import parse

    return parse(utterance, today=today, ctx=ctx)


@dataclass
class SessionState:
    """Per-session conversation state. The last event is read from the ledger, so undo walks back correctly."""

    session_id: str
    disclosed: bool = False
    pending: dict | None = None
    turn_id: int = -1


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

    def message(self, turn_id: int) -> dict[str, Any]:
        """The `result` message of CONTRACT section 3."""
        msg: dict[str, Any] = {"type": "result", "turn_id": turn_id, "trace_id": self.trace_id, "status": self.status,
                               "action": self.action, "entries": self.entries, "reply_text": self.reply_text}
        if self.reason:
            msg["reason"] = self.reason
        if self.question:
            msg["question"] = self.question
        return msg


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


class Pipeline:
    def __init__(self, ledger: Ledger, settings: Settings, *, parse: ParseFn | None = None,
                 number_to_words: NumberToWords | None = None, now: Callable[[], datetime] | None = None):
        self.ledger = ledger
        self.settings = settings
        self.parse = parse or default_parse
        self.replies = Replier(number_to_words or default_number_to_words())
        self._tz = ZoneInfo(settings.shop_tz)
        self._now = now or (lambda: datetime.now(self._tz))

    def now(self) -> datetime:
        return self._now()

    # ---- disclosure -------------------------------------------------------------------------------------------
    def _disclose(self, state: SessionState, reply: Reply) -> Reply:
        """The first spoken reply of a session carries the AI disclosure."""
        if state.disclosed:
            return reply
        state.disclosed = True
        d = self.replies.disclosure()
        if reply.text.startswith(d.text):
            return reply
        return Reply(f"{d.text} {reply.text}", f"{d.speak} {reply.speak}")

    def greeting(self, state: SessionState, trace_id: str | None = None) -> TurnResult:
        reply = self._disclose(state, self.replies.disclosure())
        state.disclosed = True
        return TurnResult("ok", "greeting", reply.text, reply.speak, trace_id or uuid.uuid4().hex[:16],
                          uuid.uuid4().hex[:12])

    # ---- one turn ---------------------------------------------------------------------------------------------
    def build_ctx(self, state: SessionState, now: datetime) -> dict:
        ctx: dict[str, Any] = {"customers": self.ledger.customers_for_parser(),
                               "limits": {"confirm_above": self.settings.confirm_above}}
        last = self.ledger.last_active_event(state.session_id, now)
        if last:
            ctx["last_event"] = last
        if state.pending:
            ctx["pending"] = state.pending
        return ctx

    def run_turn(self, state: SessionState, transcript: str, *, trace_id: str | None = None) -> TurnResult:
        trace_id = trace_id or uuid.uuid4().hex[:16]
        utterance_id = uuid.uuid4().hex[:12]
        now = self.now()
        today = now.date()
        timings: dict[str, float] = {}

        ctx = self.build_ctx(state, now)
        t0 = time.perf_counter()
        result = self.parse(transcript, today=today, ctx=ctx)
        timings["parse"] = _ms(t0)

        status = result.get("status", "rejected")
        action = result.get("action") or "none"
        reason = result.get("reason")
        question = None
        entries: list[dict] = []
        t1 = time.perf_counter()

        if status == "ok" and result.get("action") in ("append", "amend", "undo"):
            state.pending = None
            outcome = self.ledger.apply(result, now=now, session_id=state.session_id, trace_id=trace_id,
                                        utterance_id=utterance_id)
            if outcome.nothing:
                status, reason = "rejected", "no_last_event"
                reply = self.replies.nothing_to_undo()
            elif outcome.action == "undo":
                reply = self.replies.undo(outcome.reversed[0])
                entries = self.ledger.entries_by_ids([outcome.reversed[0]["id"]])
            elif outcome.action == "amend":
                reply = self.replies.amend(outcome.saved[0])
                entries = self.ledger.entries_by_ids([outcome.reversed[0]["id"]] + [e["id"] for e in outcome.saved])
            else:
                reply = self.replies.saved(outcome.saved, today)
                entries = self.ledger.entries_by_ids([e["id"] for e in outcome.saved])
        elif status == "ok" and result.get("action") == "query":
            state.pending = None
            reply = self._query(result.get("query") or {}, today)
        elif status == "needs_clarification":
            state.pending = result.get("pending")
            reply = self.replies.clarification(result)
            if reply is None:
                q = result.get("question") or self.replies.rejected().text
                reply = Reply(q, q)
            question = reply.text
        else:
            if reason != "not_ledger":
                state.pending = None
            status = "rejected"
            if reason == "cancelled":
                reply = self.replies.cancelled()
            elif reason == "no_last_event":
                reply = self.replies.nothing_to_undo()
            else:
                reply = self.replies.rejected()
        timings["db"] = _ms(t1)

        reply = self._disclose(state, reply)
        turn = TurnResult(status, action, reply.text, reply.speak, trace_id, utterance_id, reason=reason, question=question,
                          entries=entries, timings=timings)
        self.ledger.record_utterance(utterance_id, state.session_id, now, transcript=transcript, status=status,
                                     reply_text=reply.text, timings=timings)
        return turn

    def _query(self, q: dict, today: date) -> Reply:
        kind = q.get("type")
        led = self.ledger
        if kind == "balance":
            customer = led.find_customer(key=q.get("customer"), customer_id=q.get("customer_id"))
            if customer is None:
                if not q.get("customer"):
                    return self.replies.missing_customer()
                return self.replies.balance(str(q["customer"]).title(), 0)
            return self.replies.balance(customer["display"], led.balance(customer["id"]))
        if kind == "credit_total":
            return self.replies.credit_total(led.credit_total(today))
        if kind == "payment_total":
            return self.replies.payment_total(led.payment_total(today))
        if kind == "daily_summary":
            return self.replies.daily_summary(led.daily_summary(today))
        if kind == "top_dues":
            return self.replies.top_dues(led.top_dues(3))
        return self.replies.rejected()
