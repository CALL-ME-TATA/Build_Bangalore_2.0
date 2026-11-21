// Pure outbox logic: which typed sentence goes next, when it may be sent, and what a turn's outcome does to
// the queue. No storage, no timers, no session: sync.ts wires these to IndexedDB and the session store.
//
// Rules
// - Sentences are sent in the order they were typed, one at a time; the next waits for the previous `result`.
// - Sending needs a started, greeted session on an open socket, the browser online, and the session at rest
//   (no reply playing, nothing being heard), so a queued sentence never barges in on the shopkeeper.
// - ok -> removed. needs_clarification -> removed (it reached the server; the doubt sheet asks the question)
//   and the queue waits until that question is answered. rejected or a server error -> stays, marked failed
//   with the reason. Lost connection or no answer -> back to pending; after MAX_ATTEMPTS it is marked failed.
import type { ConnStatus, ServerPhase } from '../session/types';

export type OutboxState = 'pending' | 'sending' | 'failed';

export interface OutboxRecord {
  /** IndexedDB key, increasing in insertion order. */
  id: number;
  text: string;
  /** ISO time it was typed. */
  createdAt: string;
  state: OutboxState;
  /** Why it failed (the server's reply text, or a short code); null unless failed. */
  reason: string | null;
  attempts: number;
  /**
   * The sentence's `utt_id`, made when it was typed and sent unchanged on every attempt, so the server never
   * saves it twice (contract 3.3, O02). Older records without one get one before their first send.
   */
  uttId?: string;
}

export const MAX_ATTEMPTS = 3;
/** How long to wait for the `result` of a sent sentence before trying again. */
export const RESULT_TIMEOUT_MS = 20_000;

/** Oldest first: by time typed, then by id. */
export function sortQueue(items: readonly OutboxRecord[]): OutboxRecord[] {
  return [...items].sort((a, b) => (a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : a.id - b.id));
}

/** The next sentence to send, or null when one is already in flight or nothing is pending. */
export function nextToSend(items: readonly OutboxRecord[]): OutboxRecord | null {
  if (items.some((i) => i.state === 'sending')) return null;
  return sortQueue(items).find((i) => i.state === 'pending') ?? null;
}

export interface SendGate {
  started: boolean;
  greeted: boolean;
  conn: ConnStatus;
  online: boolean;
  phase: ServerPhase;
  audioTurn: number | null;
  /** The mic is held or latched open. */
  micOpen: boolean;
  /** The last result asked a question that is not answered yet. */
  questionOpen: boolean;
}

export function canSend(g: SendGate): boolean {
  return g.started && g.greeted && g.conn === 'open' && g.online && g.phase === 'idle' && g.audioTurn == null && !g.micOpen && !g.questionOpen;
}

/** Whether a typed sentence should go to the outbox instead of the socket. */
export function shouldQueue(g: Pick<SendGate, 'started' | 'conn' | 'online'>): boolean {
  return g.started && (g.conn !== 'open' || !g.online);
}

export type Outcome =
  | { kind: 'delivered'; question: boolean }
  | { kind: 'failed'; reason: string }
  | { kind: 'retry'; reason: string };

/** Outcome of a sent sentence from its `result`. */
export function outcomeOfResult(r: { status: string; reason?: string | null; replyText?: string | null }): Outcome {
  if (r.status === 'ok') return { kind: 'delivered', question: false };
  if (r.status === 'needs_clarification') return { kind: 'delivered', question: true };
  return { kind: 'failed', reason: r.replyText || r.reason || r.status || 'rejected' };
}

/** Outcome of a sent sentence from a session error. "no_connection" means it never left the phone. */
export function outcomeOfError(code: string | null, message: string | null): Outcome {
  if (code === 'no_connection') return { kind: 'retry', reason: 'no_connection' };
  return { kind: 'failed', reason: message || code || 'error' };
}

/**
 * The queue after `id` got `outcome`. Delivered items are removed; failed ones keep their text and reason;
 * a retry puts the item back to pending, or marks it failed once it has used MAX_ATTEMPTS.
 */
export function applyOutcome(items: readonly OutboxRecord[], id: number, outcome: Outcome): OutboxRecord[] {
  if (outcome.kind === 'delivered') return items.filter((i) => i.id !== id);
  return items.map((i) => {
    if (i.id !== id) return i;
    if (outcome.kind === 'failed') return { ...i, state: 'failed', reason: outcome.reason };
    return i.attempts >= MAX_ATTEMPTS ? { ...i, state: 'failed', reason: outcome.reason } : { ...i, state: 'pending', reason: null };
  });
}

/** Marks `id` as in flight and counts the attempt. */
export function markSending(items: readonly OutboxRecord[], id: number): OutboxRecord[] {
  return items.map((i) => (i.id === id ? { ...i, state: 'sending', attempts: i.attempts + 1, reason: null } : i));
}

/** A failed item queued again by the shopkeeper. */
export function markRetry(items: readonly OutboxRecord[], id: number): OutboxRecord[] {
  return items.map((i) => (i.id === id ? { ...i, state: 'pending', attempts: 0, reason: null } : i));
}

/** After a reload nothing is in flight: an item left "sending" is pending again. */
export function recoverQueue(items: readonly OutboxRecord[]): OutboxRecord[] {
  return sortQueue(items.map((i) => (i.state === 'sending' ? { ...i, state: 'pending' } : i)));
}
