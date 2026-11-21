// Application state and its reducer. Pure: no DOM, no timers, no network.
//
// Turn handling: the server assigns turn_id. A message for a turn older than the
// current one is dropped. After the user presses (barge-in) or sends text, `barged`
// is set and every message for the previous turn id is dropped until a newer turn
// id arrives.

import { t, normalizeLang } from './i18n.js';

export const initialState = {
  lang: 'hi', // language of the fixed labels: the chosen one, then the language of the latest result
  conn: 'idle', // idle | connecting | open | reconnecting | closed
  sessionId: null,
  turnId: 0,
  barged: false,
  phase: 'idle',
  transcript: '',
  greeted: false, // true after the greeting audio ended uncancelled, or after the fallback timeout
  typedText: null, // sentence sent from the Type box, shown as the transcript of its turn
  transcriptFinal: false, // false while the text is still a partial
  result: null, // { status, action, reason, entries, replyText, question, traceId }
  timing: null, // { traceId, ms }
  audioTurn: null, // turn whose audio is being played, null when none is accepted
  releaseAt: null, // performance.now() at release (or text send)
  clientMs: null, // release to first scheduled sample
  error: null,
  resultCount: 0, // bumped on every result so the UI knows when to refresh the ledger
};

function resetTurn(s, turnId) {
  return {
    ...s,
    turnId,
    barged: false,
    phase: 'idle',
    transcript: s.typedText || '',
    transcriptFinal: Boolean(s.typedText),
    typedText: null,
    result: null,
    timing: null,
    audioTurn: null,
    error: null,
    clientMs: null,
  };
}

/** True when a server message belongs to a turn that must be ignored. */
export function isStale(s, m) {
  if (m.turn_id == null) return false;
  const id = Number(m.turn_id);
  return s.barged ? id <= s.turnId : id < s.turnId;
}

export function reduce(s, m) {
  switch (m.type) {
    case 'conn':
      return { ...s, conn: m.status };
    case 'local_start': // button pressed, or text submitted
      return { ...s, barged: true, phase: 'listening', audioTurn: null, releaseAt: null, clientMs: null, error: null, typedText: null };
    case 'local_text':
      return { ...s, typedText: m.text, transcript: m.text, transcriptFinal: true };
    case 'local_end':
      return { ...s, releaseAt: m.t };
    case 'first_sound':
      if (s.audioTurn == null || s.releaseAt == null || s.clientMs != null) return s;
      return { ...s, clientMs: m.t - s.releaseAt };
    case 'ready':
      // A different session id (server restart, expired resume) starts again at turn 0.
      if (s.sessionId && s.sessionId !== m.session_id) {
        return { ...s, sessionId: m.session_id, turnId: 0, barged: false, audioTurn: null, phase: 'idle', greeted: false, result: null, timing: null };
      }
      return { ...s, sessionId: m.session_id };
    case 'greeting_timeout':
      return { ...s, greeted: true };
    case 'notice':
      return { ...s, error: t(s.lang, 'noConn') };
    case 'set_lang':
      return { ...s, lang: normalizeLang(m.lang) };
    case 'pong':
      return s;
    default:
      break;
  }

  if (isStale(s, m)) return s;
  if (m.turn_id != null && Number(m.turn_id) > s.turnId) s = resetTurn(s, Number(m.turn_id));

  switch (m.type) {
    case 'state':
      return { ...s, phase: m.state };
    case 'transcript': {
      // The text is always the whole turn so far, so it replaces what is shown.
      return { ...s, transcript: m.text || "", transcriptFinal: Boolean(m.final) };
    }
    case 'result':
      return {
        ...s,
        resultCount: s.resultCount + 1,
        lang: m.lang ? normalizeLang(m.lang) : s.lang,
        result: {
          status: m.status,
          action: m.action,
          reason: m.reason || null,
          entries: m.entries || [],
          replyText: m.reply_text || '',
          question: m.question || null,
          traceId: m.trace_id || null,
        },
      };
    case 'audio_start':
      return { ...s, audioTurn: Number(m.turn_id), phase: 'speaking' };
    case 'audio_end':
      return {
        ...s,
        audioTurn: null,
        phase: s.phase === 'speaking' ? 'idle' : s.phase,
        greeted: s.greeted || !m.cancelled,
      };
    case 'timing':
      return { ...s, timing: { traceId: m.trace_id || null, ms: m.ms || {} } };
    case 'error':
      return { ...s, error: m.message || m.code || 'error' };
    default:
      return s;
  }
}
