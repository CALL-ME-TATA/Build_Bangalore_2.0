// Pure pieces of the Bolo screen: the latency breakdown, the balances line and the answer names.
import { expect, test } from 'vitest';
import { latencyRows } from './LatencyLine';
import { balanceLine } from './Conversation';
import { answerName } from './DoubtSheet';

test('latencyRows lists the stages in plain words, in pipeline order, then the phone', () => {
  const rows = latencyRows({ parse: 2.4, stt_final: 410, end_to_first_audio: 912.6, db: null }, 1010.2, 'en');
  expect(rows).toEqual([
    { label: 'End of speech to the full text', ms: 410 },
    { label: 'Understanding the sentence', ms: 2 },
    { label: 'End of speech to first reply audio (server)', ms: 913 },
    { label: 'Button release to hearing the reply (this phone)', ms: 1010 },
  ]);
  expect(latencyRows({}, null, 'hi')).toEqual([]);
});

test('balanceLine: owes, advance, settled', () => {
  expect(balanceLine({ customer_id: 'c', display: 'Ramesh', balance: 770 }, 'hi')).toBe('Ramesh · ab baaki ₹770');
  expect(balanceLine({ customer_id: 'c', display: 'Ramesh', balance: -200 }, 'hi')).toBe('Ramesh · ₹200 advance jama');
  expect(balanceLine({ customer_id: 'c', display: 'Ramesh', balance: 0 }, 'en')).toBe('Ramesh · settled');
});

test('answer buttons have one clean accessible name', () => {
  expect(answerName({ id: 'a', label: '340', answer: '340', amount: 340 }, 'confusable_number', 'hi')).toBe('340 rupaye');
  expect(answerName({ id: 'e', label: '200', answer: '200', amount: 200, kind: 'payment', sub: 'Sunita' }, 'unclear_correction', 'en')).toBe(
    '200 rupees, Payment, Sunita',
  );
  expect(answerName({ id: 'c', label: 'Ramesh', sub: 'Chai wale', answer: 'chai wale' }, 'same_name', 'hi')).toBe('Ramesh, Chai wale');
  expect(answerName({ id: 'y', label: 'Haan', answer: 'haan' }, 'plausibility', 'hi')).toBe('Haan');
});
