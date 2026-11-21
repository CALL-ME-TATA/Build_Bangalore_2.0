// The open question survives what the server does not treat as an answer (contract 3.3): accidental presses,
// cancelled turns, replayed duplicates; a repeated question updates in place; amend and review confirmations.
import { describe, expect, test } from 'vitest';
import { sheetClosed, sheetReduce, type SheetEvent, type SheetState } from './doubtSheet';
import { doubtSpec } from './doubt';
import { longQuestion } from '../features/bolo/DoubtSheet';

const ev = (over: Partial<Extract<SheetEvent, { type: 'result' }>> = {}): SheetEvent => ({
  type: 'result',
  turnId: 1,
  status: 'needs_clarification',
  reason: 'plausibility',
  question: null,
  entries: [],
  replyText: '₹5,00,000, pakka?',
  lang: 'hi',
  action: 'none',
  said: 'Mohan ka paanch lakh udhaar',
  ...over,
});

const open = (): SheetState => sheetReduce(sheetClosed, ev());

describe('results that are not answers leave the question alone', () => {
  test.each(['too_short', 'cancelled'])('%s (action none) leaves an open sheet exactly as it is', (reason) => {
    const s = open();
    expect(sheetReduce(s, ev({ turnId: 2, status: 'rejected', reason, replyText: '' }))).toBe(s);
    const waiting = sheetReduce(s, { type: 'pick', option: s.options[0]! });
    expect(sheetReduce(waiting, ev({ turnId: 2, status: 'rejected', reason, replyText: '' }))).toBe(waiting);
  });

  test('a replayed duplicate never opens, changes or closes the sheet', () => {
    expect(sheetReduce(sheetClosed, ev({ duplicate: true }))).toBe(sheetClosed);
    const s = open();
    expect(sheetReduce(s, ev({ turnId: 3, status: 'ok', duplicate: true, replyText: 'Likh diya.' }))).toBe(s);
  });

  test('other rejections still close it (the server dropped the question)', () => {
    expect(sheetReduce(open(), ev({ turnId: 2, status: 'rejected', reason: 'negated', replyText: 'Theek hai, kuch nahi likha.' })).stage).toBe('closed');
  });
});

describe('a repeated question updates in place', () => {
  test('after a silence: new text, same seq (no focus move), back to asking, the first context kept', () => {
    const s = open();
    const waiting = sheetReduce(s, { type: 'pick', option: s.options[0]! });
    const again = sheetReduce(
      waiting,
      ev({ turnId: 2, said: '', replyText: 'Kuch sunai nahi diya. ₹5,00,000, pakka?' }),
    );
    expect(again).toMatchObject({ stage: 'asking', seq: s.seq, picked: null, context: 'Mohan ka paanch lakh udhaar', turnId: 2 });
    expect(again.question).toBe('Kuch sunai nahi diya. ₹5,00,000, pakka?');
  });

  test('a different question is a new one: seq moves on', () => {
    const s = open();
    const next = sheetReduce(s, ev({ turnId: 2, reason: 'confusable_number', replyText: '₹340 ya ₹740?', candidates: [340, 740] }));
    expect(next.seq).toBe(s.seq + 1);
    const reopened = sheetReduce(sheetReduce(s, { type: 'dismiss' }), ev({ turnId: 3 }));
    expect(reopened.seq).toBe(s.seq + 1);
  });
});

describe('amend and review confirmations', () => {
  test('both are yes / no; amend keeps its old and new amounts for the sheet', () => {
    const amend = sheetReduce(sheetClosed, ev({ reason: 'confirm_entry', replyText: 'Ramesh ka ₹340 hata kar ₹430 likhun?', confirm: { type: 'amend', old: 340, new: 430 } }));
    expect(amend.kind).toBe('yesno');
    expect(amend.confirm).toEqual({ type: 'amend', old: 340, new: 430 });
    expect(doubtSpec({ reason: 'confirm_entry', question: 'x', confirm: { type: 'review' }, lang: 'en' }).options.map((o) => o.answer)).toEqual(['haan', 'nahi']);
    expect(doubtSpec({ reason: 'confirm_entry', question: 'x', confirm: { type: 'writeoff', amount: 70 }, lang: 'hi' }).kind).toBe('yesno');
  });

  test('a review question (or any long one) uses the smaller heading so it wraps', () => {
    expect(longQuestion({ question: 'Teen entry likhun?', confirm: { type: 'review' } })).toBe(true);
    expect(longQuestion({ question: 'Ramesh ke ₹340 udhaar, Sunita se ₹200 jama, aur Mohan ke ₹150 udhaar likhun?', confirm: null })).toBe(true);
    expect(longQuestion({ question: '340 ya 740?', confirm: null })).toBe(false);
  });
});

test('a spoken "Theek hai, entry nahi ki." (the answer Nahi) closes the sheet; the silent cancel does not', () => {
  const s = open();
  expect(sheetReduce(s, ev({ turnId: 2, status: 'rejected', reason: 'cancelled', replyText: '' }))).toBe(s);
  expect(sheetReduce(s, ev({ turnId: 2, status: 'rejected', reason: 'cancelled', replyText: 'Theek hai, entry nahi ki.' })).stage).toBe('closed');
});
