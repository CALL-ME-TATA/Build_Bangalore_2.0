// Outbox sync driver (loaded lazily). Watches the session store and sends queued sentences as `text` turns,
// one at a time, each waiting for its `result` (rules in ./queue.ts). Every change is written back to the
// encrypted outbox in IndexedDB and mirrored in the `useOffline` store for the UI.
import { announce } from '../../components/LiveRegion';
import { useMicGesture } from '../../state/mic';
import { sendTextNow, useSession, type SessionStore } from '../../state/session';
import { addOutbox, deleteOutbox, loadOutbox, writeOutbox } from './outbox';
import { offlineLabels } from './labels';
import {
  RESULT_TIMEOUT_MS,
  applyOutcome,
  canSend,
  markRetry,
  markSending,
  nextToSend,
  outcomeOfError,
  outcomeOfResult,
  recoverQueue,
  sortQueue,
  type Outcome,
  type OutboxRecord,
} from './queue';
import { useOffline } from './status';
import { newUttId } from '../../lib/ids';
import { QUESTION_TTL_MS } from '../../lib/doubtSheet';

let loaded: Promise<void> | null = null;
let running = false;
let inflight: { id: number; resultCount: number; timer: ReturnType<typeof setTimeout> } | null = null;
/**
 * An outbox sentence got a question back: hold the rest until the question is answered or dropped (a later
 * result that is not a question, or the server's 60 s expiry), so a later sentence is never taken as the answer.
 */
let heldByQuestion = false;
let heldSince = 0;

const items = () => useOffline.getState().outbox;

/** Shows `next` at once and writes the differences to IndexedDB. */
function commit(next: OutboxRecord[]): void {
  const before = new Map(items().map((i) => [i.id, i]));
  useOffline.setState({ outbox: sortQueue(next) });
  const after = new Set<number>();
  for (const rec of next) {
    after.add(rec.id);
    if (before.get(rec.id) !== rec) void writeOutbox(rec).catch(() => undefined);
  }
  for (const id of before.keys()) if (!after.has(id)) void deleteOutbox(id).catch(() => undefined);
}

function ensureLoaded(): Promise<void> {
  loaded ??= loadOutbox()
    .then((rows) => {
      const recovered = recoverQueue(rows);
      // Keep anything enqueued while loading.
      const extra = items().filter((i) => !recovered.some((r) => r.id === i.id));
      commit([...recovered, ...extra]);
    })
    .catch(() => {
      loaded = null;
    });
  return loaded;
}

function gateOf(s: SessionStore) {
  return {
    started: s.started,
    greeted: s.greeted,
    conn: s.conn,
    online: typeof navigator === 'undefined' || navigator.onLine,
    phase: s.phase,
    audioTurn: s.audioTurn,
    micOpen: useMicGesture.getState().open,
    questionOpen: heldByQuestion && s.result?.status === 'needs_clarification' && Date.now() - heldSince < QUESTION_TTL_MS,
  };
}

function tick(): void {
  if (!running || inflight) return;
  const s = useSession.getState();
  if (heldByQuestion && s.result?.status !== 'needs_clarification') heldByQuestion = false;
  let next = nextToSend(items());
  if (!next || !canSend(gateOf(s))) return;
  if (!next.uttId) {
    const withId: OutboxRecord = { ...next, uttId: newUttId() };
    commit(items().map((i) => (i.id === withId.id ? withId : i)));
    next = withId;
  }
  commit(markSending(items(), next.id));
  inflight = {
    id: next.id,
    resultCount: s.resultCount,
    timer: setTimeout(() => settle({ kind: 'retry', reason: 'timeout' }), RESULT_TIMEOUT_MS),
  };
  // The same utt_id on every attempt; client_ts is when it was typed.
  sendTextNow(next.text, { uttId: next.uttId, clientTs: next.createdAt });
}

function settle(outcome: Outcome): void {
  if (!inflight) return;
  clearTimeout(inflight.timer);
  const id = inflight.id;
  inflight = null;
  const L = offlineLabels(useSession.getState().lang);
  if (outcome.kind === 'delivered') {
    heldByQuestion = outcome.question;
    if (outcome.question) {
      heldSince = Date.now();
      setTimeout(tick, QUESTION_TTL_MS + 500); // the server drops the question then; carry on
    }
    announce(L.sentFromOutbox);
  } else if (outcome.kind === 'failed') {
    announce(L.failedFromOutbox);
  }
  commit(applyOutcome(items(), id, outcome));
  setTimeout(tick, 400); // let the reply's state messages arrive before judging the gate again
}

function onSession(s: SessionStore, prev: SessionStore): void {
  if (!inflight) {
    tick();
    return;
  }
  if (s.resultCount > inflight.resultCount && s.result) settle(outcomeOfResult(s.result));
  else if (s.error && s.error !== prev.error) settle(outcomeOfError(s.errorCode, s.error));
  else if (s.conn !== 'open' && prev.conn === 'open') settle({ kind: 'retry', reason: 'no_connection' });
}

/** Loads the outbox and starts watching the session. Idempotent. */
export async function startSync(): Promise<void> {
  await ensureLoaded();
  if (running) return;
  running = true;
  useSession.subscribe(onSession);
  useMicGesture.subscribe(() => tick());
  window.addEventListener('online', tick);
  tick();
}

/** Adds a typed sentence to the outbox. */
export async function enqueue(text: string): Promise<void> {
  await ensureLoaded();
  const rec = await addOutbox(text);
  useOffline.setState((s) => ({ outbox: sortQueue([...s.outbox, rec]) }));
  void startSync();
}

/** Queues a failed sentence again. */
export function retry(id: number): void {
  commit(markRetry(items(), id));
  tick();
}

/** Removes a sentence from the outbox without sending it. */
export function remove(id: number): void {
  if (inflight?.id === id) return;
  commit(items().filter((i) => i.id !== id));
}
