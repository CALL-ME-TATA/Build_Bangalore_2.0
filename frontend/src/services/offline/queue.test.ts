// Outbox queue rules (pure).
import { describe, expect, test } from 'vitest';
import {
  MAX_ATTEMPTS,
  applyOutcome,
  canSend,
  markRetry,
  markSending,
  nextToSend,
  outcomeOfError,
  outcomeOfResult,
  recoverQueue,
  shouldQueue,
  type OutboxRecord,
  type SendGate,
} from './queue';

const rec = (id: number, text: string, createdAt: string, extra: Partial<OutboxRecord> = {}): OutboxRecord => ({
  id,
  text,
  createdAt,
  state: 'pending',
  reason: null,
  attempts: 0,
  ...extra,
});

const q = [
  rec(3, 'Sunita ne 150 diye', '2026-11-21T10:02:00.000Z'),
  rec(1, 'Ramesh ka 340 udhaar', '2026-11-21T10:00:00.000Z'),
  rec(2, 'Imran ka 85 udhaar', '2026-11-21T10:01:00.000Z'),
];

const gate: SendGate = {
  started: true,
  greeted: true,
  conn: 'open',
  online: true,
  phase: 'idle',
  audioTurn: null,
  micOpen: false,
  questionOpen: false,
};

describe('order', () => {
  test('oldest pending goes first', () => {
    expect(nextToSend(q)?.text).toBe('Ramesh ka 340 udhaar');
  });
  test('nothing goes while one is in flight', () => {
    expect(nextToSend(markSending(q, 1))).toBeNull();
  });
  test('failed items stay but are skipped; later ones still go', () => {
    const next = applyOutcome(markSending(q, 1), 1, { kind: 'failed', reason: 'Maaf kijiye, samajh nahi aaya.' });
    expect(next).toHaveLength(3);
    expect(nextToSend(next)?.id).toBe(2);
  });
  test('a full run sends each once, in order, and empties the queue', () => {
    let items: OutboxRecord[] = q;
    const sent: string[] = [];
    for (let n = nextToSend(items); n; n = nextToSend(items)) {
      sent.push(n.text);
      items = applyOutcome(markSending(items, n.id), n.id, outcomeOfResult({ status: 'ok' }));
    }
    expect(sent).toEqual(['Ramesh ka 340 udhaar', 'Imran ka 85 udhaar', 'Sunita ne 150 diye']);
    expect(items).toEqual([]);
  });
});

describe('gate', () => {
  test('open, greeted, online and at rest', () => {
    expect(canSend(gate)).toBe(true);
  });
  test.each<[string, Partial<SendGate>]>([
    ['not started', { started: false }],
    ['greeting still playing', { greeted: false }],
    ['socket reconnecting', { conn: 'reconnecting' }],
    ['browser offline', { online: false }],
    ['reply playing', { phase: 'speaking', audioTurn: 4 }],
    ['shopkeeper talking', { micOpen: true }],
    ['question open', { questionOpen: true }],
  ])('blocked when %s', (_name, patch) => {
    expect(canSend({ ...gate, ...patch })).toBe(false);
  });
  test('typed text is queued only when started and not connected', () => {
    expect(shouldQueue({ started: true, conn: 'reconnecting', online: true })).toBe(true);
    expect(shouldQueue({ started: true, conn: 'open', online: false })).toBe(true);
    expect(shouldQueue({ started: true, conn: 'open', online: true })).toBe(false);
    expect(shouldQueue({ started: false, conn: 'idle', online: false })).toBe(false);
  });
});

describe('outcomes', () => {
  test('ok and questions are delivered; a question holds the queue', () => {
    expect(outcomeOfResult({ status: 'ok' })).toEqual({ kind: 'delivered', question: false });
    expect(outcomeOfResult({ status: 'needs_clarification', reason: 'confusable_number' })).toEqual({ kind: 'delivered', question: true });
  });
  test('a rejection fails with the reply text as the reason and keeps the sentence', () => {
    const o = outcomeOfResult({ status: 'rejected', reason: 'no_amount', replyText: 'Kitne rupaye?' });
    expect(o).toEqual({ kind: 'failed', reason: 'Kitne rupaye?' });
    const items = applyOutcome(markSending(q, 1), 1, o);
    expect(items.find((i) => i.id === 1)).toMatchObject({ state: 'failed', reason: 'Kitne rupaye?', text: 'Ramesh ka 340 udhaar' });
  });
  test('server errors fail; the local no-connection notice retries', () => {
    expect(outcomeOfError('stt_upstream', 'Network problem')).toEqual({ kind: 'failed', reason: 'Network problem' });
    expect(outcomeOfError('no_connection', 'Connection nahi hai')).toEqual({ kind: 'retry', reason: 'no_connection' });
  });
  test('retries go back to pending until MAX_ATTEMPTS, then fail; Send again resets', () => {
    let items: OutboxRecord[] = [rec(1, 'Ramesh ka 340 udhaar', '2026-11-21T10:00:00.000Z')];
    for (let i = 1; i < MAX_ATTEMPTS; i++) {
      items = applyOutcome(markSending(items, 1), 1, { kind: 'retry', reason: 'timeout' });
      expect(items[0]).toMatchObject({ state: 'pending', attempts: i });
    }
    items = applyOutcome(markSending(items, 1), 1, { kind: 'retry', reason: 'timeout' });
    expect(items[0]).toMatchObject({ state: 'failed', reason: 'timeout', attempts: MAX_ATTEMPTS });
    expect(markRetry(items, 1)[0]).toMatchObject({ state: 'pending', attempts: 0, reason: null });
  });
  test('after a reload, an item left sending is pending again and the order is kept', () => {
    const items = recoverQueue(markSending(q, 2));
    expect(items.map((i) => [i.id, i.state])).toEqual([
      [1, 'pending'],
      [2, 'pending'],
      [3, 'pending'],
    ]);
  });
});
