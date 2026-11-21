// State machine of the doubt sheet, kept pure so it can be tested without a browser.
//
//   closed --(result needs_clarification)--> asking --(tap)--> waiting
//   asking / waiting / correcting --(result with active entries)--> saved (the answer was written)
//   asking / waiting --(result without entries)--> closed (the server dropped the question; the conversation
//                                                          shows the reply)
//   saved --("Galat hai? Badlein")--> correcting (the talk control in the sheet takes the spoken correction)
//   saved --(any later result that is not a question)--> closed
//   any --(dismiss: Esc, swipe down, scrim; or the 60 s question expiry)--> closed
// A new question always replaces what the sheet shows. The question text is the result's `reply_text`.
// The server repeats an open question after a silence, an empty transcript, a too-long recording or a speech
// failure (same reason, a short notice before the question): the sheet updates its text in place, keeping its
// `seq`, so it neither closes nor moves focus. A result with `action: "none"` and reason too_short / cancelled
// leaves an open sheet exactly as it is. A replayed result (`duplicate: true`) never opens or changes the sheet.
// Nothing here is stored: a reloaded page never restores a question (contract 3.3, L05).
import type { Lang } from '../i18n';
import type { Candidate, Confirm, Entry } from '../services/session/types';
import { doubtSpec, type DoubtKind, type DoubtOption } from './doubt';

export type SheetStage = 'closed' | 'asking' | 'waiting' | 'saved' | 'correcting';

/** The server drops an open question 60 seconds after asking it (E02); the sheet closes then too. */
export const QUESTION_TTL_MS = 60_000;

export interface SheetState {
  stage: SheetStage;
  turnId: number | null;
  question: string;
  reason: string | null;
  kind: DoubtKind;
  options: DoubtOption[];
  /** Show the type box in the sheet (open questions without buttons). */
  typeBox: boolean;
  lang: Lang;
  /** Entries saved by the answer (stage 'saved'). */
  entries: Entry[];
  replyText: string;
  /** The answer that was tapped, shown while waiting. */
  picked: string | null;
  /** What the shopkeeper said in the turn that raised the question (the server sends no other context). */
  context: string;
  /** The question's `confirm` object (amend shows old and new amounts). */
  confirm: Confirm | null;
  /** Bumped when a different question opens; a repeated question keeps it (focus moves only on a new one). */
  seq: number;
}

export const sheetClosed: SheetState = {
  stage: 'closed',
  turnId: null,
  question: '',
  reason: null,
  kind: 'open',
  options: [],
  typeBox: false,
  lang: 'hi',
  entries: [],
  replyText: '',
  picked: null,
  context: '',
  confirm: null,
  seq: 0,
};

/** Reasons of a result that must leave an open question untouched. */
const IGNORED_WHILE_ASKING = new Set(['too_short', 'cancelled']);

export type SheetEvent =
  | {
      type: 'result';
      turnId: number;
      status: string;
      reason: string | null;
      /** The `question` field (legacy); the shown question is `replyText`. */
      question: string | null;
      entries: Entry[];
      replyText: string;
      lang: Lang;
      /** The turn's transcript. */
      said?: string;
      candidates?: Candidate[];
      confirm?: Confirm | null;
      action?: string;
      duplicate?: boolean;
    }
  | { type: 'pick'; option: DoubtOption }
  | { type: 'correct' }
  | { type: 'dismiss' };

export function sheetReduce(s: SheetState, e: SheetEvent): SheetState {
  switch (e.type) {
    case 'result': {
      if (e.duplicate) return s; // a replay: never opens, changes or closes the sheet
      const asking = s.stage === 'asking' || s.stage === 'waiting';
      // The silent turn after an accidental press (no reply text). A spoken "Theek hai, entry nahi ki." is the
      // answer "Nahi" and closes the sheet as usual.
      if (s.stage !== 'closed' && e.action === 'none' && IGNORED_WHILE_ASKING.has(e.reason ?? '') && !e.replyText) return s;
      const text = e.replyText || e.question || '';
      if (e.status === 'needs_clarification' && text) {
        const spec = doubtSpec({ reason: e.reason, question: text, candidates: e.candidates, confirm: e.confirm, lang: e.lang });
        const repeat = asking && e.reason === s.reason && (e.confirm?.type ?? null) === (s.confirm?.type ?? null);
        return {
          ...sheetClosed,
          stage: 'asking',
          turnId: e.turnId,
          question: text,
          reason: e.reason,
          kind: spec.kind,
          options: spec.options,
          typeBox: spec.typeBox,
          lang: e.lang,
          // A repeat keeps what the shopkeeper first said (the new turn heard nothing usable).
          context: repeat ? s.context : (e.said ?? ''),
          confirm: e.confirm ?? null,
          seq: repeat ? s.seq : s.seq + 1,
        };
      }
      if (s.stage === 'closed' || s.stage === 'saved') return { ...sheetClosed, seq: s.seq };
      const active = e.entries.filter((x) => !x.reversed);
      if (active.length) {
        return { ...s, stage: 'saved', turnId: e.turnId, entries: e.entries, replyText: e.replyText, lang: e.lang, picked: null };
      }
      return { ...sheetClosed, seq: s.seq };
    }
    case 'pick':
      if (s.stage !== 'asking') return s;
      return { ...s, stage: 'waiting', picked: e.option.label };
    case 'correct':
      if (s.stage !== 'saved') return s;
      return { ...s, stage: 'correcting' };
    case 'dismiss':
      return { ...sheetClosed, seq: s.seq };
    default:
      return s;
  }
}
