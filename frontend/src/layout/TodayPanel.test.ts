// The "Abhi likha gaya" list: server entries merged with this session's, newest first, amended rows folded.
import { expect, test } from 'vitest';
import type { Entry } from '../services/session/types';
import { amendPairs } from '../state/session-reducer';
import { recentEntries } from './TodayPanel';

const e = (id: number, minute: number, extra: Partial<Entry> = {}): Entry => ({
  id,
  kind: 'credit',
  customer: { id: 'c1', display: 'Ramesh', tags: [] },
  amount: 100 * id,
  date: '2026-11-21',
  ts: `2026-11-21T10:${String(minute).padStart(2, '0')}:00Z`,
  reversed: false,
  reversal_of: null,
  ...extra,
});

test('amendPairs pairs each reversed entry with the active entry after it', () => {
  const pairs = amendPairs([e(1, 0, { reversed: true }), e(2, 1)]);
  expect(Object.keys(pairs)).toEqual(['2']);
  expect(pairs['2']?.id).toBe(1);
  expect(amendPairs([e(3, 0)])).toEqual({});
});

test('recentEntries: newest first, session state wins, replaced entries fold into their replacement', () => {
  const server = [e(5, 20), e(1, 0)];
  const saved = [e(1, 0, { reversed: true }), e(2, 1), e(3, 30, { kind: 'payment' })];
  const list = recentEntries(server, saved, amendPairs([e(1, 0, { reversed: true }), e(2, 1)]));
  expect(list.map((x) => x.id)).toEqual([3, 5, 2]);
  expect(recentEntries(server, [], {}, 1).map((x) => x.id)).toEqual([5]);
});

test('an undone entry stays in the list, reversed', () => {
  const list = recentEntries([], [e(4, 5, { reversed: true })], {});
  expect(list[0]?.reversed).toBe(true);
});
