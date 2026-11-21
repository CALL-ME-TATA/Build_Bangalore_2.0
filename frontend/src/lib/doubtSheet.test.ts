// Doubt sheet state machine.
import { describe, expect, test } from 'vitest';
import type { Entry } from '../services/session/types';
import { sheetClosed, sheetReduce, type SheetEvent, type SheetState } from './doubtSheet';

const e = (id: number, reversed = false): Entry => ({
  id,
  kind: 'credit',
  customer: { id: 'c', display: 'Geeta', tags: [] },
  amount: 340,
  date: '2026-11-21',
  ts: '2026-11-21T10:00:00Z',
  reversed,
  reversal_of: null,
});

const result = (over: Partial<Extract<SheetEvent, { type: 'result' }>> = {}): SheetEvent => ({
  type: 'result',
  turnId: 1,
  status: 'ok',
  reason: null,
  question: null,
  entries: [],
  replyText: '',
  lang: 'hi',
  ...over,
});
const ask = result({ status: 'needs_clarification', reason: 'confusable_number', question: '₹340 ya ₹740?', replyText: '₹340 ya ₹740?' });

describe('sheetReduce', () => {
  test('opens on a question with derived options', () => {
    const s = sheetReduce(sheetClosed, ask);
    expect(s.stage).toBe('asking');
    expect(s.options.map((o) => o.answer)).toEqual(['340', '740']);
    expect(sheetReduce(sheetClosed, { ...ask, said: 'Geeta ka teen sau chaalis udhaar' } as SheetEvent).context).toBe(
      'Geeta ka teen sau chaalis udhaar',
    );
  });

  test('ignores ordinary results while closed', () => {
    expect(sheetReduce(sheetClosed, result({ entries: [e(1)] }))).toBe(sheetClosed);
  });

  test('tap, then the saved entry: asking -> waiting -> saved -> dismissed', () => {
    let s: SheetState = sheetReduce(sheetClosed, ask);
    const first = s.options[0];
    if (!first) throw new Error('no option');
    s = sheetReduce(s, { type: 'pick', option: first });
    expect(s).toMatchObject({ stage: 'waiting', picked: '340' });
    s = sheetReduce(s, result({ turnId: 2, entries: [e(7)], replyText: 'Geeta ke khate mein ₹340 udhaar likh diya.' }));
    expect(s.stage).toBe('saved');
    expect(s.entries.map((x) => x.id)).toEqual([7]);
    expect(sheetReduce(s, { type: 'dismiss' })).toEqual(sheetClosed);
  });

  test('an answer by voice (no tap) also reaches saved', () => {
    const s = sheetReduce(sheetReduce(sheetClosed, ask), result({ turnId: 2, entries: [e(8)] }));
    expect(s.stage).toBe('saved');
  });

  test('a result without active entries (cancelled, rejected) closes the sheet', () => {
    const s = sheetReduce(sheetReduce(sheetClosed, ask), result({ turnId: 2, replyText: 'Theek hai, entry nahi ki.' }));
    expect(s.stage).toBe('closed');
  });

  test('a follow-up question replaces the current one', () => {
    const s = sheetReduce(
      sheetReduce(sheetClosed, ask),
      result({ turnId: 2, status: 'needs_clarification', reason: 'plausibility', question: '₹5,00,000, pakka?' }),
    );
    expect(s).toMatchObject({ stage: 'asking', reason: 'plausibility', turnId: 2 });
    expect(s.options.map((o) => o.label)).toEqual(['Haan', 'Nahi']);
  });

  test('"Galat hai? Badlein" moves to correcting, and the spoken correction is shown as saved', () => {
    let s = sheetReduce(sheetReduce(sheetClosed, ask), result({ turnId: 2, entries: [e(8)] }));
    s = sheetReduce(s, { type: 'correct' });
    expect(s.stage).toBe('correcting');
    s = sheetReduce(s, result({ turnId: 3, entries: [e(8, true), { ...e(9), amount: 430 }] }));
    expect(s.stage).toBe('saved');
    expect(s.entries.map((x) => [x.id, x.reversed])).toEqual([
      [8, true],
      [9, false],
    ]);
  });

  test('pick is ignored unless a question is open', () => {
    const opt = { id: 'yes', label: 'Haan', answer: 'haan' };
    expect(sheetReduce(sheetClosed, { type: 'pick', option: opt })).toBe(sheetClosed);
  });
});

describe('contract 3.3 questions', () => {
  test('the question comes from reply_text and carries candidates', () => {
    const s = sheetReduce(sheetClosed, {
      type: 'result',
      turnId: 4,
      status: 'needs_clarification',
      reason: 'new_customer',
      question: null,
      entries: [],
      replyText: 'Rakesh naya grahak hai, ya Ramesh?',
      lang: 'hi',
      candidates: [{ id: 'c1', display: 'Ramesh', tags: [] }],
    });
    expect(s.question).toBe('Rakesh naya grahak hai, ya Ramesh?');
    expect(s.kind).toBe('choice');
    expect(s.options.map((o) => o.answer)).toEqual(['pehla', 'naya']);
  });

  test('a confirm_entry question is yes / no; an open one asks for the type box', () => {
    const yes = sheetReduce(sheetClosed, { ...ask, reason: 'confirm_entry', replyText: 'Poore maaf karun?', confirm: { type: 'writeoff', balance: 770 } } as SheetEvent);
    expect(yes.kind).toBe('yesno');
    const open = sheetReduce(sheetClosed, { ...ask, reason: 'missing_amount', replyText: 'Kitne rupaye?' } as SheetEvent);
    expect(open).toMatchObject({ kind: 'open', typeBox: true, options: [] });
  });

  test('the server dropped the question: any later result that is not a question closes the sheet', () => {
    const asking = sheetReduce(sheetClosed, ask);
    expect(sheetReduce(asking, result({ turnId: 2, status: 'rejected', replyText: 'Maaf kijiye' })).stage).toBe('closed');
    const saved = sheetReduce(asking, result({ turnId: 2, entries: [e(8)] }));
    expect(saved.stage).toBe('saved');
    expect(sheetReduce(saved, result({ turnId: 3, status: 'ok', replyText: 'Aaj ₹430 udhaar gaya.' })).stage).toBe('closed');
  });
});
