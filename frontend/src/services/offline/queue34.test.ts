// Contract 3.4: the queue is held while any question is open; a stale replay is renewed once.
import { describe, expect, test } from 'vitest';
import {
  QUESTION_OPEN_MS,
  applyOutcome,
  leavesQuestionOpen,
  markSending,
  outcomeOfResult,
  questionOpenAt,
  trackQuestion,
  type OutboxRecord,
} from './queue';

const rec = (over: Partial<OutboxRecord> = {}): OutboxRecord => ({
  id: 1,
  text: 'Geeta ka teen sau chaalis udhaar',
  createdAt: '2026-11-21T10:00:00.000Z',
  state: 'sending',
  reason: null,
  attempts: 2,
  uttId: 'first-id',
  ...over,
});

describe('the open question, whoever raised it', () => {
  const question = { status: 'needs_clarification', action: 'none', reason: 'plausibility', replyText: '₹5,00,000, pakka?' };

  test('a question opens it; an answer, a cancellation or a new sentence closes it', () => {
    const open = trackQuestion(null, question, 1000);
    expect(open).toBe(1000);
    expect(trackQuestion(open, { status: 'ok', action: 'append', replyText: 'Likh diya.' }, 2000)).toBeNull();
    expect(trackQuestion(open, { status: 'rejected', action: 'none', reason: 'cancelled', replyText: 'Theek hai, entry nahi ki.' }, 2000)).toBeNull();
    expect(trackQuestion(open, { status: 'rejected', action: 'none', reason: 'not_ledger', replyText: 'Maaf kijiye…' }, 2000)).toBeNull();
  });

  test('the silent turn of an accidental press and a replayed duplicate leave it open', () => {
    const open = trackQuestion(null, question, 1000);
    expect(leavesQuestionOpen({ status: 'rejected', action: 'none', reason: 'too_short', replyText: '' })).toBe(true);
    expect(trackQuestion(open, { status: 'rejected', action: 'none', reason: 'cancelled', replyText: '' }, 2000)).toBe(1000);
    expect(trackQuestion(open, { status: 'ok', action: 'append', duplicate: true }, 2000)).toBe(1000);
  });

  test('a repeated question restarts the expiry; it expires 60 s after it was last asked', () => {
    const again = trackQuestion(1000, question, 30_000);
    expect(again).toBe(30_000);
    expect(questionOpenAt(again, 30_000 + QUESTION_OPEN_MS - 1)).toBe(true);
    expect(questionOpenAt(again, 30_000 + QUESTION_OPEN_MS)).toBe(false);
    expect(questionOpenAt(null, 0)).toBe(false);
  });
});

describe('a queued sentence whose replay comes back cancelled', () => {
  const cancelled = { status: 'rejected', reason: 'cancelled', replyText: 'Theek hai, entry nahi ki.' };

  test('a replay (sent before under the same id) is renewed under a new id, exactly once', () => {
    const o = outcomeOfResult(cancelled, rec(), () => 'new-id');
    expect(o).toEqual({ kind: 'renew', uttId: 'new-id' });
    const [after] = applyOutcome([rec()], 1, o);
    expect(after).toMatchObject({ state: 'pending', uttId: 'new-id', renewed: true, attempts: 0, reason: null });

    // The renewed send fails again: it stays in the queue, marked failed (needs attention), never dropped.
    const resent = markSending([after!], 1);
    const again = outcomeOfResult(cancelled, resent[0], () => 'third-id');
    expect(again.kind).toBe('failed');
    const final = applyOutcome(resent, 1, again);
    expect(final).toHaveLength(1);
    expect(final[0]).toMatchObject({ state: 'failed', uttId: 'new-id', renewed: true });
  });

  test('a first send that is itself cancelled is not renewed', () => {
    expect(outcomeOfResult(cancelled, rec({ attempts: 1 })).kind).toBe('failed');
    expect(outcomeOfResult({ status: 'rejected', reason: 'not_ledger' }, rec()).kind).toBe('failed');
    expect(outcomeOfResult({ status: 'ok' }, rec()).kind).toBe('delivered');
  });
});
