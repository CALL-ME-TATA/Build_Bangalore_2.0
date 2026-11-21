// Shapes of the browser <-> server session protocol (docs/CONTRACT.md section 3) and the
// SessionService interface that both the WebSocket and the mock implementation satisfy.
import type { Lang } from '../../i18n';

/** One ledger entry as the API sends it. Amounts are whole rupees. */
export interface Entry {
  id: number | string;
  /** `writeoff` (v1.2): the customer owes that much less; it is not a payment. */
  kind: EntryKind;
  customer: { id: string; display: string; tags: string[] };
  amount: number;
  /** Effective date, YYYY-MM-DD. */
  date: string;
  /** Time the event was recorded, ISO 8601. */
  ts: string;
  reversed: boolean;
  reversal_of: number | string | null;
}

export type EntryKind = 'credit' | 'payment' | 'writeoff';

/** A customer offered as a choice (`same_name`, `new_customer`). */
export interface CandidateCustomer {
  id: string;
  display: string;
  tags?: string[];
}

/** An entry offered as a choice (`unclear_correction`): the contract lists "those events". */
export interface CandidateEvent {
  id?: number | string;
  kind?: EntryKind;
  amount?: number;
  customer?: string | { display?: string };
  display?: string;
}

export type Candidate = number | CandidateCustomer | CandidateEvent;

/** The `confirm` object of a `confirm_entry` question (contract 1.14). */
export interface Confirm {
  type:
    | 'computed'
    | 'settle'
    | 'half'
    | 'writeoff'
    | 'roundoff'
    | 'overpayment'
    | 'duplicate'
    | 'hearsay'
    | 'reminder'
    | 'review'
    | 'amend'
    | string;
  balance?: number;
  bill?: number;
  paid?: number;
  /** `writeoff` may name the amount. */
  amount?: number;
  /** `amend`: the amount being replaced and the new one. */
  old?: number;
  new?: number;
}

/** What a query turn asked (contract 3.3), so the page can show more than was spoken. */
export interface QueryInfo {
  type: string;
  period?: string;
  customer_id?: string;
}

/** A customer's balance after a saving turn. Shown on screen, never spoken. */
export interface BalanceInfo {
  customer_id: string;
  display: string;
  balance: number;
}

export interface ResultMessage {
  type: 'result';
  turn_id: number;
  trace_id?: string;
  status: ResultStatus;
  action: string;
  reason?: string;
  entries?: Entry[];
  reply_text?: string;
  question?: string;
  lang?: string;
  candidates?: Candidate[];
  confirm?: Confirm;
  query?: QueryInfo;
  balances?: BalanceInfo[];
  /** The turn repeated an `utt_id`; nothing new was saved. */
  duplicate?: boolean;
}

export type ServerPhase = 'listening' | 'hearing' | 'transcribing' | 'thinking' | 'speaking' | 'idle';

export type ResultStatus = 'ok' | 'needs_clarification' | 'rejected' | string;

export type ServerMessage =
  | {
      type: 'ready';
      session_id: string;
      /** On resume: the session's last turn and its result (contract 3.3). */
      last_turn_id?: number;
      last_result?: Omit<ResultMessage, 'type' | 'turn_id'> & { type?: 'result'; turn_id?: number };
      /** Set by the client, not the server: this `ready` answered a `hello` with `resume` for the same id. */
      resumed?: boolean;
    }
  | { type: 'state'; turn_id: number; state: ServerPhase }
  | { type: 'transcript'; turn_id: number; text: string; segment?: number; final: boolean }
  | ResultMessage
  | { type: 'audio_start'; turn_id: number; sample_rate: number; encoding?: string; channels?: number }
  | { type: 'audio_end'; turn_id: number; cancelled?: boolean }
  | { type: 'timing'; turn_id: number; trace_id?: string; ms: Partial<Record<TimingKey, number>> }
  | { type: 'error'; turn_id?: number; code?: string; message?: string }
  | { type: 'pong'; t?: number }
  /** Acknowledges a `settings` message (contract 3.3). */
  | { type: 'settings'; private?: boolean };

export type TimingKey =
  | 'stt_final'
  | 'parse'
  | 'db'
  | 'tts_first_chunk'
  | 'end_to_first_audio'
  | 'gnani_stt_latency';

export type ConnStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';

/** Events raised on the page itself; they go through the same reducer as server messages. */
export type LocalAction =
  | { type: 'conn'; status: ConnStatus }
  | { type: 'local_start' }
  | { type: 'local_text'; text: string }
  | { type: 'local_end'; t: number }
  /** A hold-to-talk press released too soon (accidental): the turn was cancelled. */
  | { type: 'local_abort' }
  /** The shopkeeper closed the type box that a failure had opened. */
  | { type: 'typing_closed' }
  | { type: 'first_sound'; t: number }
  | { type: 'greeting_timeout' }
  | { type: 'notice' }
  | { type: 'set_lang'; lang: Lang }
  | { type: 'mic'; status: MicStatus };

export type SessionAction = ServerMessage | LocalAction;

/** State of the microphone after start(): unknown until the user starts, then ready / denied / failed. */
/**
 * State of the microphone after start(): unknown until the user starts, then ready, or why it is not:
 * denied (permission refused), nodevice (no microphone found), insecure (the page is not a secure origin, so
 * the browser offers no microphone), failed (anything else).
 */
export type MicStatus = 'unknown' | 'ready' | 'denied' | 'nodevice' | 'insecure' | 'failed';

/** What a SessionService needs from the app: a way to report events, read state and report the mic level. */
export interface SessionHost {
  dispatch(action: SessionAction): void;
  getState(): {
    greeted: boolean;
    audioTurn: number | null;
    turnId: number;
  };
  /** Microphone level in [0, 1], about 30 times a second while capturing. */
  onLevel(level: number): void;
}

/**
 * The voice session. The UI only talks to this interface; `createSessionService` in ./index.ts
 * decides which implementation is used.
 */
export interface SessionService {
  readonly kind: 'ws' | 'mock';
  /**
   * Called from a user tap: unlocks audio, opens the session (hello) and asks for the microphone.
   * `audio` is an AudioContext created synchronously inside the tap (see ./index.ts); implementations
   * that play sound use it instead of creating their own after an await.
   */
  start(lang: Lang, audio?: AudioContext | null): Promise<MicStatus>;
  /** Push-to-talk pressed. Also barge-in: playback stops at once. */
  press(): void;
  /** Push-to-talk released: audio keeps flowing for 300 ms, then the tail is flushed and `end` is sent. */
  release(): void;
  /** Press released too soon (accidental): `cancel` is sent and nothing is recorded. */
  abort(): void;
  /** Typed sentence, same pipeline without speech recognition. A retried sentence passes its first `uttId`. */
  sendText(text: string, opts?: SendOptions): void;
  /** Private mode: `hello.private`, and a `settings` message when changed inside a session. */
  setPrivate(on: boolean): void;
  /** A short soft beep (a reply came as text only). */
  beep(): void;
  /** Language for later reconnects (hello.lang). */
  setLang(lang: Lang): void;
  /** Playback speed of the spoken reply, 0.8 to 1.25. */
  setVoiceSpeed(rate: number): void;
  close(): void;
}

export interface SendOptions {
  /** Idempotency key; a new one is made when absent. */
  uttId?: string;
  /** When the sentence was typed (ISO); defaults to now. */
  clientTs?: string;
}
