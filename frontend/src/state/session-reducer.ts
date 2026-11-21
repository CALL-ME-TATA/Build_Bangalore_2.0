// Session state and its reducer. Pure: no DOM, no timers, no network. Ported from web/store.js, with the
// conversation of this session added (`history`, `saved`).
//
// Turn handling: the server assigns turn_id. A message for a turn older than the current one is dropped.
// After the user presses (barge-in) or sends text, `barged` is set and every message for the previous turn
// id is dropped until a newer turn id arrives.
//
// Conversation: when a turn is over it is archived into `history` as a TurnRecord. A turn is over when the
// user starts the next one (`local_start`; the old turn can send nothing more that is shown) or when a newer
// turn id arrives without a local start. `saved` holds every entry this session touched, in order of first
// appearance, always in its latest state (an amend or undo flips `reversed` on the earlier row).
//
// Contract 3.3 additions handled here:
// - `duplicate: true` results show their reply but never add their entries again;
// - `ready.last_result`: if the page was waiting for a result when the socket dropped, that result is shown;
//   if the turn never reached the server, the wait ends with the no-connection notice;
// - release shows "Samajh raha hoon…" at once (`released`), even while the 300 ms tail still streams;
// - an accidental press (`local_abort`) shows a hint, no error, and the server's turn for it is ignored;
// - a reply that ends without any audio (or a text-to-speech error) bumps `beepSeq` once per turn;
// - a network or speech-service failure sets `offerTyping` so the type box opens.
import { normalizeLang, t, type LabelKey, type Lang } from '../i18n';
import type {
  BalanceInfo,
  Candidate,
  Confirm,
  ConnStatus,
  Entry,
  MicStatus,
  NoiseInfo,
  QueryInfo,
  ResultMessage,
  ResultStatus,
  ServerPhase,
  SessionAction,
  TimingKey,
} from '../services/session/types';

export interface TurnResult {
  status: ResultStatus;
  action: string;
  reason: string | null;
  entries: Entry[];
  replyText: string;
  question: string | null;
  traceId: string | null;
  candidates: Candidate[];
  confirm: Confirm | null;
  query: QueryInfo | null;
  balances: BalanceInfo[];
  /** The server saw this utt_id before; nothing new was saved. */
  duplicate: boolean;
}

export interface Timing {
  traceId: string | null;
  ms: Partial<Record<TimingKey, number>>;
  /** Spoken turns on servers with noise handling (contract 3.5); null for typed turns and older servers. */
  noise: NoiseInfo | null;
}

/** The `timing.noise` object if it is well formed, else null (absent on typed turns and older servers). */
export function parseNoise(n: unknown): NoiseInfo | null {
  if (!n || typeof n !== 'object') return null;
  const o = n as { separation_db?: unknown; noisy?: unknown; turned_down_ms?: unknown };
  if (typeof o.separation_db !== 'number' || !Number.isFinite(o.separation_db) || typeof o.noisy !== 'boolean') return null;
  const out: NoiseInfo = { separation_db: o.separation_db, noisy: o.noisy };
  if (typeof o.turned_down_ms === 'number' && Number.isFinite(o.turned_down_ms)) out.turned_down_ms = o.turned_down_ms;
  return out;
}

/** The noise measurement of a turn, or null. */
export function turnNoise(turn: Pick<TurnRecord, 'timing'>): NoiseInfo | null {
  return turn.timing?.noise ?? null;
}

/** One finished turn of the conversation. */
export interface TurnRecord {
  turnId: number;
  /** What the shopkeeper said (final transcript) or typed. Empty for the greeting. */
  said: string;
  typed: boolean;
  result: TurnResult | null;
  /** Language of the turn's reply, for the `lang` attribute. */
  lang: Lang;
  timing: Timing | null;
  /** Release (or text send) to first sample played, measured on the phone. */
  clientMs: number | null;
}

export interface SessionState {
  /** Language of the fixed labels: the chosen one, then the language of the latest result. */
  lang: Lang;
  conn: ConnStatus;
  sessionId: string | null;
  turnId: number;
  barged: boolean;
  phase: ServerPhase;
  transcript: string;
  /** True after the greeting audio ended uncancelled, or after the fallback timeout. */
  greeted: boolean;
  /** Sentence sent from the Type box, shown as the transcript of its turn. */
  typedText: string | null;
  /** False while the text is still a partial. */
  transcriptFinal: boolean;
  /** True when the transcript of the current turn came from the Type box. */
  transcriptTyped: boolean;
  result: TurnResult | null;
  timing: Timing | null;
  /** Turn whose audio is being played, null when none is accepted. */
  audioTurn: number | null;
  /** performance.now() at release (or text send). */
  releaseAt: number | null;
  /** Release to first scheduled sample. */
  clientMs: number | null;
  error: string | null;
  /** Code of the current error: the server's `code`, or "no_connection" for the local notice. */
  errorCode: string | null;
  /** Bumped on every result so views know when to refresh server data. */
  resultCount: number;
  mic: MicStatus;
  /** Turn id already archived by local_start, so it is not archived twice. */
  archivedTurn: number | null;
  history: TurnRecord[];
  saved: Entry[];
  /** For an amended entry (by id), the entry it replaced, so views can show the old amount struck through. */
  amendedFrom: Record<string, Entry>;
  /** The button was released: "Samajh raha hoon…" from now on, whatever the server's state says. */
  released: boolean;
  /** A reply sample was played in the current turn. */
  soundPlayed: boolean;
  /** Accidental presses whose server turn has not arrived yet; that turn is ignored. */
  abortPending: number;
  /** A short hint under the mic (no error), e.g. after an accidental press. */
  hint: LabelKey | null;
  /** The network or speech service failed: open the type box. */
  offerTyping: boolean;
  /** Bumped once per turn whose reply came as text only; the page plays a short beep. */
  beepSeq: number;
  beepedTurn: number | null;
}

export const initialState: SessionState = {
  lang: 'hi',
  conn: 'idle',
  sessionId: null,
  turnId: 0,
  barged: false,
  phase: 'idle',
  transcript: '',
  greeted: false,
  typedText: null,
  transcriptFinal: false,
  transcriptTyped: false,
  result: null,
  timing: null,
  audioTurn: null,
  releaseAt: null,
  clientMs: null,
  error: null,
  errorCode: null,
  resultCount: 0,
  mic: 'unknown',
  archivedTurn: null,
  history: [],
  saved: [],
  amendedFrom: {},
  released: false,
  soundPlayed: false,
  abortPending: 0,
  hint: null,
  offerTyping: false,
  beepSeq: 0,
  beepedTurn: null,
};

const FAILURE_CODES = new Set(['stt_upstream', 'tts_upstream', 'upstream']);

/**
 * Rejections that end a recording (contract 3.3): silence, too_long, empty_transcript, too_short, cancelled,
 * internal. The turn ends at once on screen (the mic goes back to idle; a spoken reply, if any, still moves it to
 * "speaking" when its audio starts). `too_short` and `cancelled` are not errors: too_short shows the hold hint.
 */
export const ENDING_REASONS = new Set(['silence', 'too_long', 'empty_transcript', 'too_short', 'cancelled', 'internal']);
export const QUIET_REASONS = new Set(['too_short', 'cancelled']);

function turnResult(m: Omit<ResultMessage, 'type' | 'turn_id'>): TurnResult {
  const entries = m.duplicate ? [] : m.entries || [];
  return {
    status: m.status,
    action: m.action,
    reason: m.reason || null,
    entries,
    replyText: m.reply_text || '',
    question: m.question || null,
    traceId: m.trace_id || null,
    candidates: m.candidates ?? [],
    confirm: m.confirm ?? null,
    query: m.query ?? null,
    balances: m.balances ?? [],
    duplicate: Boolean(m.duplicate),
  };
}

/** Marks the current turn for a beep (once). */
function cueBeep(s: SessionState): SessionState {
  if (s.beepedTurn === s.turnId || !s.result?.replyText) return s;
  return { ...s, beepSeq: s.beepSeq + 1, beepedTurn: s.turnId };
}

/** The fields the conversation selectors read. */
export type ConversationInput = Pick<
  SessionState,
  'history' | 'transcript' | 'transcriptTyped' | 'result' | 'turnId' | 'lang' | 'timing' | 'clientMs' | 'archivedTurn'
>;

/** The current turn as a record, or null when it has nothing to show. */
export function currentRecord(s: ConversationInput): TurnRecord | null {
  if (!s.transcript && !s.result && !s.timing && s.clientMs == null) return null;
  return {
    turnId: s.turnId,
    said: s.transcript,
    typed: s.transcriptTyped,
    result: s.result,
    lang: s.lang,
    timing: s.timing,
    clientMs: s.clientMs,
  };
}

function archive(s: SessionState): SessionState {
  if (s.archivedTurn === s.turnId) return s;
  const rec = currentRecord(s);
  if (!rec) return s;
  return { ...s, history: [...s.history, rec], archivedTurn: s.turnId };
}

function mergeSaved(saved: Entry[], entries: Entry[]): Entry[] {
  if (!entries.length) return saved;
  const out = saved.slice();
  for (const e of entries) {
    const i = out.findIndex((x) => x.id === e.id);
    if (i >= 0) out[i] = { ...out[i], ...e };
    else out.push(e);
  }
  return out;
}

/**
 * Pairs each reversed entry of an amend result with the active entry that follows it
 * (`result.entries` lists the old entry, reversed, then the new one).
 */
export function amendPairs(entries: Entry[]): Record<string, Entry> {
  const out: Record<string, Entry> = {};
  let pending: Entry | null = null;
  for (const e of entries) {
    if (e.reversed) pending = e;
    else if (pending) {
      out[String(e.id)] = pending;
      pending = null;
    }
  }
  return out;
}

function resetTurn(s: SessionState, turnId: number): SessionState {
  const a = s.archivedTurn === s.turnId ? s : archive(s);
  return {
    ...a,
    turnId,
    barged: false,
    phase: 'idle',
    transcript: a.typedText || '',
    transcriptFinal: Boolean(a.typedText),
    transcriptTyped: Boolean(a.typedText),
    typedText: null,
    result: null,
    timing: null,
    audioTurn: null,
    error: null,
    errorCode: null,
    clientMs: null,
    soundPlayed: false,
  };
}

/** True when a server message belongs to a turn that must be ignored. */
export function isStale(s: SessionState, m: SessionAction): boolean {
  if (!('turn_id' in m) || m.turn_id == null) return false;
  const id = Number(m.turn_id);
  return s.barged ? id <= s.turnId : id < s.turnId;
}

export function reduce(s: SessionState, m: SessionAction): SessionState {
  // The server's turn for an accidental (cancelled) press: adopt its id and drop everything it sends.
  if (s.abortPending > 0 && 'turn_id' in m && m.turn_id != null && Number(m.turn_id) > s.turnId && s.barged) {
    return { ...s, turnId: Number(m.turn_id), abortPending: s.abortPending - 1 };
  }
  switch (m.type) {
    case 'conn':
      return { ...s, conn: m.status };
    case 'mic':
      return { ...s, mic: m.status };
    case 'local_start': {
      // Button pressed, or text submitted. The previous turn is over: archive it and clear the live view.
      const a = archive(s);
      return {
        ...a,
        barged: true,
        phase: 'listening',
        audioTurn: null,
        releaseAt: null,
        clientMs: null,
        error: null,
        errorCode: null,
        hint: null,
        released: false,
        soundPlayed: false,
        typedText: null,
        transcript: '',
        transcriptFinal: false,
        transcriptTyped: false,
        result: null,
        timing: null,
      };
    }
    case 'local_text':
      return { ...s, typedText: m.text, transcript: m.text, transcriptFinal: true, transcriptTyped: true };
    case 'local_end':
      return {
        ...s,
        releaseAt: m.t,
        released: true,
        phase: s.phase === 'listening' || s.phase === 'hearing' ? 'transcribing' : s.phase,
      };
    case 'local_abort': {
      // If the server's turn for this press has already arrived (barged was cleared by its first message),
      // mark it barged so the rest of it is dropped as stale; otherwise drop it when it arrives.
      const base = { ...s, phase: 'idle' as const, released: false, releaseAt: null, hint: 'micTooShort' as const };
      return s.barged ? { ...base, abortPending: s.abortPending + 1 } : { ...base, barged: true };
    }
    case 'typing_closed':
      return { ...s, offerTyping: false };
    case 'first_sound': {
      if (s.audioTurn == null) return s;
      const played = { ...s, soundPlayed: true };
      if (s.releaseAt == null || s.clientMs != null) return played;
      return { ...played, clientMs: m.t - s.releaseAt };
    }
    case 'ready': {
      // Waiting for a result when the socket dropped: show the server's last result, or end the wait.
      const awaiting = s.releaseAt != null && s.result == null && (s.phase !== 'idle' || s.released);
      if (awaiting && (m.resumed || s.sessionId === m.session_id)) {
        const base: SessionState = { ...s, sessionId: m.session_id, released: false };
        const lastId = m.last_turn_id;
        const newer = lastId != null && (s.barged ? lastId > s.turnId : lastId >= s.turnId);
        if (m.last_result && lastId != null && newer) {
          const shown = reduce(base, { ...m.last_result, type: 'result', turn_id: lastId } as ResultMessage);
          return { ...shown, phase: 'idle' };
        }
        return { ...base, phase: 'idle', releaseAt: null, error: t(s.lang, 'noConnection'), errorCode: 'no_connection' };
      }
      // A different session id (server restart, expired resume) starts again at turn 0.
      if (s.sessionId && s.sessionId !== m.session_id) {
        const a = archive(s);
        return {
          ...a,
          sessionId: m.session_id,
          turnId: 0,
          barged: false,
          audioTurn: null,
          phase: 'idle',
          greeted: false,
          result: null,
          timing: null,
          transcript: '',
          transcriptFinal: false,
          transcriptTyped: false,
          archivedTurn: null,
          released: false,
          abortPending: 0,
        };
      }
      return { ...s, sessionId: m.session_id };
    }
    case 'greeting_timeout':
      return { ...s, greeted: true };
    case 'notice':
      return { ...s, error: t(s.lang, 'noConnection'), errorCode: 'no_connection' };
    case 'set_lang':
      return { ...s, lang: normalizeLang(m.lang) };
    case 'pong':
    case 'settings': // the server's acknowledgement of a `settings` message; nothing to show
      return s;
    default:
      break;
  }

  if (isStale(s, m)) return s;
  if ('turn_id' in m && m.turn_id != null && Number(m.turn_id) > s.turnId) s = resetTurn(s, Number(m.turn_id));

  switch (m.type) {
    case 'state':
      // After release the tail is still streaming; the server may still say "hearing". Keep "Samajh raha hoon…".
      if (s.released && (m.state === 'listening' || m.state === 'hearing')) return { ...s, phase: 'transcribing' };
      return { ...s, phase: m.state };
    case 'transcript':
      // The text is always the whole turn so far, so it replaces what is shown.
      return { ...s, transcript: m.text || '', transcriptFinal: Boolean(m.final), transcriptTyped: false };
    case 'result': {
      const r = turnResult(m);
      return {
        ...s,
        resultCount: s.resultCount + 1,
        released: false,
        lang: m.lang ? normalizeLang(m.lang) : s.lang,
        saved: mergeSaved(s.saved, r.entries),
        amendedFrom: m.action === 'amend' && !r.duplicate ? { ...s.amendedFrom, ...amendPairs(r.entries) } : s.amendedFrom,
        offerTyping: m.reason === 'upstream' ? true : r.status === 'ok' ? false : s.offerTyping,
        result: r,
        ...(ENDING_REASONS.has(m.reason ?? '')
          ? {
              phase: s.phase === 'speaking' ? s.phase : ('idle' as const),
              hint: m.reason === 'too_short' ? ('micTooShort' as const) : s.hint,
            }
          : {}),
      };
    }
    case 'audio_start':
      return { ...s, audioTurn: Number(m.turn_id), phase: 'speaking' };
    case 'audio_end': {
      const next = {
        ...s,
        audioTurn: null,
        phase: s.phase === 'speaking' ? ('idle' as const) : s.phase,
        greeted: s.greeted || !m.cancelled,
      };
      // A reply with text whose audio never played: beep (N04).
      return !m.cancelled && !s.soundPlayed ? cueBeep(next) : next;
    }
    case 'timing':
      return { ...s, timing: { traceId: m.trace_id || null, ms: m.ms || {}, noise: parseNoise(m.noise) } };
    case 'error': {
      const next = {
        ...s,
        error: m.message || m.code || 'error',
        errorCode: m.code || 'error',
        released: false,
        offerTyping: s.offerTyping || FAILURE_CODES.has(m.code ?? ''),
      };
      return m.code === 'tts_upstream' ? cueBeep(next) : next;
    }
    default:
      return s;
  }
}

// ---- selectors (pure) --------------------------------------------------------------------------------------

/** Finished turns followed by the live one, oldest first. */
export function conversation(s: ConversationInput): TurnRecord[] {
  const live = s.archivedTurn === s.turnId && !s.transcript ? null : currentRecord(s);
  return live ? [...s.history, live] : s.history;
}

/** Latest state of an entry this session touched. */
export function latestEntry(s: Pick<SessionState, 'saved'>, e: Entry): Entry {
  return s.saved.find((x) => x.id === e.id) ?? e;
}

/** Id of the newest entry that is still active (the only one that shows Undo), or null. */
export function newestActiveId(saved: Entry[]): Entry['id'] | null {
  let best: Entry | null = null;
  for (const e of saved) {
    if (e.reversed) continue;
    if (!best || compareEntries(e, best) > 0) best = e;
  }
  return best ? best.id : null;
}

/** Orders entries by record time, then by id. */
function compareEntries(a: Entry, b: Entry): number {
  const ta = Date.parse(a.ts) || 0;
  const tb = Date.parse(b.ts) || 0;
  if (ta !== tb) return ta - tb;
  return Number(a.id) - Number(b.id);
}

/** Server and phone latency of the most recent turn that has either, with that turn's per-stage figures. */
export function lastLatency(
  turns: TurnRecord[],
): { server: number | null; phone: number | null; ms: Partial<Record<TimingKey, number>>; noise: NoiseInfo | null } | null {
  for (let i = turns.length - 1; i >= 0; i--) {
    const r = turns[i];
    if (!r) continue;
    const server = r.timing?.ms.end_to_first_audio;
    if (server != null || r.clientMs != null) {
      return {
        server: server != null ? Math.round(server) : null,
        phone: r.clientMs != null ? Math.round(r.clientMs) : null,
        ms: r.timing?.ms ?? {},
        noise: r.timing?.noise ?? null,
      };
    }
  }
  return null;
}
