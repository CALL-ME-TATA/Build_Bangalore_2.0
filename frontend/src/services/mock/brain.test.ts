// The mock replays the pitch flow with consistent numbers: Ramesh ends at ₹430 credit and ₹200 payment.
import { expect, test } from 'vitest';
import { MockBrain } from './brain';
import { MockLedger } from './ledger';

test('greeting -> 340 -> "Nahi, 430" -> 200 payment -> balance -> summary', () => {
  const ledger = new MockLedger(false);
  const b = new MockBrain(ledger);
  expect(b.greeting().reply_text).toBe('Namaste! Main KhataVaani hoon, ek AI sahayak.');

  const r1 = b.respond('Ramesh ka 340 udhaar');
  expect(r1.reply_text).toBe('Naya khata Ramesh. Ramesh ke khate mein ₹340 udhaar likh diya.');
  expect(r1.entries.map((e) => [e.kind, e.amount])).toEqual([['credit', 340]]);

  const r2 = b.respond('Nahi, 430');
  expect(r2.action).toBe('amend');
  expect(r2.reply_text).toBe('Theek kar diya: Ramesh, ₹430 udhaar.');
  expect(r2.entries.map((e) => [e.amount, e.reversed])).toEqual([
    [340, true],
    [430, false],
  ]);

  const r3 = b.respond('Aur 200 payment mila');
  expect(r3.reply_text).toBe('Ramesh se ₹200 mile, jama kar diya.');

  expect(b.respond('Ramesh ka total kitna hai').reply_text).toBe('Ramesh ke ₹230 baaki hain.');
  expect(b.respond('Aaj ka hisaab batao').reply_text).toBe('Aaj ₹430 udhaar gaya, ₹200 jama hue. Sabse zyada baaki: Ramesh, ₹230.');
});

test('a confusable number opens a question and a tapped answer saves it', () => {
  const b = new MockBrain(new MockLedger(false));
  const q = b.respond('Geeta ka teen sau chaalis udhaar');
  expect(q).toMatchObject({ status: 'needs_clarification', reason: 'confusable_number', question: '₹340 ya ₹740?' });
  const a = b.respond('340');
  expect(a.status).toBe('ok');
  expect(a.entries[0]?.amount).toBe(340);
});

test('plausibility: "nahi" saves nothing; English replies follow the session language', () => {
  const b = new MockBrain(new MockLedger(false));
  b.lang = 'en';
  expect(b.respond('Mohan 5 lakh credit').question).toBe('₹5,00,000, are you sure?');
  expect(b.respond('no').reply_text).toBe('Okay, nothing was saved.');
  expect(b.respond('undo').reply_text).toBe('There is nothing to undo.');
});

test('the mock raises every question type with the 3.3 fields', () => {
  const ledger = new MockLedger(false);
  const b = new MockBrain(ledger);
  b.respond('Ramesh ka 340 udhaar');
  const close = b.respond('Rakesh ka 50 udhaar');
  expect(close).toMatchObject({ reason: 'new_customer', candidates: [{ display: 'Ramesh' }] });
  expect(b.respond('Ramesh').entries[0]?.customer.display).toBe('Ramesh');
  expect(b.respond('Ramesh')).toMatchObject({ reason: 'missing_amount', reply_text: 'Ramesh ka kya likhun?' });
  expect(b.respond('100 udhaar').status).toBe('ok');
  expect(b.respond('Ramesh 300 udhaar pichle saal')).toMatchObject({ reason: 'unclear_date' });
  expect(b.respond('kal').status).toBe('ok');
  const bill = b.respond('Ramesh ka bill 500 hai, 200 diya');
  expect(bill).toMatchObject({ reason: 'confirm_entry', confirm: { type: 'computed', bill: 500, paid: 200 } });
  expect(b.respond('haan').entries[0]?.amount).toBe(300);
  const woff = b.respond('Ramesh ka maaf kar do');
  expect(woff).toMatchObject({ reason: 'confirm_entry', confirm: { type: 'writeoff' } });
  const wrote = b.respond('haan');
  expect(wrote.entries[0]?.kind).toBe('writeoff');
  expect(wrote.balances?.[0]).toMatchObject({ display: 'Ramesh', balance: 0 });
  expect(ledger.totals().payment_today).toBe(0); // a write-off is not a payment
});

test('unclear_correction after a two-entry turn, answered with the old amount', () => {
  const b = new MockBrain(new MockLedger(false));
  b.saveTwo({ kind: 'credit', name: 'Ramesh', amount: 340 }, { kind: 'payment', name: 'Sunita', amount: 200 });
  const q = b.respond('nahi');
  expect(q).toMatchObject({ reason: 'unclear_correction', reply_text: 'Kaunsi entry: ₹340 udhaar ya ₹200 jama?' });
  expect(q.candidates).toHaveLength(2);
  const a = b.respond('200');
  expect(a.entries[0]).toMatchObject({ amount: 200, reversed: true });
});

test('private mode: balance answers are shown, and the voice says only that they are on screen', () => {
  const b = new MockBrain(new MockLedger(false));
  b.respond('Ramesh ka 340 udhaar');
  b.privateMode = true;
  const r = b.respond('Ramesh ka total kitna hai');
  expect(r.reply_text).toBe('Ramesh ke ₹340 baaki hain.');
  expect(r.speak).toBe('Jawab screen par hai.');
  expect(b.respond('sabse zyada baaki').query).toEqual({ type: 'top_dues' });
});
