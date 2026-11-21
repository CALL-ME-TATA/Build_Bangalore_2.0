// Hisaab numbers (pure). Synthetic data only.
import { expect, test } from 'vitest';
import type { Customer } from '../../services/api';
import type { Entry } from '../../services/session/types';
import { HISAAB_LABELS } from './labels';
import { barPercent, chartMax, computeInsights, dateLine, duesTotal, partOfDay, topDues, weekDays } from './insights';

const NOW = new Date(2026, 10, 21, 18, 30); // 21 Nov 2026, 18:30 local

let nextId = 1;
function entry(kind: Entry['kind'], name: string, amount: number, date: string, hour = 11, reversed = false): Entry {
  const [y, m, d] = date.split('-').map(Number);
  const ts = new Date(y ?? 2026, (m ?? 1) - 1, d ?? 1, hour, 5).toISOString();
  return { id: nextId++, kind, customer: { id: name.toLowerCase(), display: name, tags: [] }, amount, date, ts, reversed, reversal_of: null };
}

const ledger: Entry[] = [
  entry('credit', 'Ramesh', 340, '2026-11-21', 11, true), // corrected: does not count
  entry('credit', 'Ramesh', 430, '2026-11-21', 11),
  entry('payment', 'Ramesh', 200, '2026-11-21', 17),
  entry('credit', 'Imran', 85, '2026-11-21', 21),
  entry('credit', 'Lakshmi', 2400, '2026-11-20', 18),
  entry('payment', 'Shivu', 400, '2026-11-20', 17),
  entry('credit', 'Sunita', 850, '2026-11-15', 10), // the first day of the week
  entry('credit', 'Geeta', 1250, '2026-11-14', 10), // outside the week
];

test('the week is the seven days ending today', () => {
  expect(weekDays(NOW)).toEqual(['2026-11-15', '2026-11-16', '2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20', '2026-11-21']);
  expect(weekDays(new Date(2026, 2, 3))[0]).toBe('2026-02-25'); // across a month end
});

test('parts of the day', () => {
  const at = (h: number) => new Date(2026, 10, 21, h, 0).toISOString();
  expect([at(9), at(12), at(16), at(19), at(20), at(23)].map(partOfDay)).toEqual([0, 1, 2, 2, 3, 3]);
});

test('today: totals skip reversed entries; buckets by part of the day', () => {
  const r = computeInsights(ledger, 'today', NOW, 'hi');
  expect(r.credit).toBe(515);
  expect(r.payment).toBe(200);
  expect(r.count).toBe(3);
  expect(r.buckets.map((b) => [b.label, b.credit, b.payment])).toEqual([
    ['Subah', 430, 0],
    ['Dopahar', 0, 0],
    ['Shaam', 0, 200],
    ['Raat', 85, 0],
  ]);
  expect(r.truncated).toBe(false);
});

test('week: seven day buckets, oldest first, labelled Kal / Aaj', () => {
  const r = computeInsights(ledger, 'week', NOW, 'hi');
  expect(r.credit).toBe(430 + 85 + 2400 + 850);
  expect(r.payment).toBe(600);
  expect(r.buckets).toHaveLength(7);
  expect(r.buckets[0]).toMatchObject({ key: '2026-11-15', credit: 850 });
  expect(r.buckets[5]).toMatchObject({ label: 'Kal', credit: 2400, payment: 400 });
  expect(r.buckets[6]).toMatchObject({ label: 'Aaj', credit: 515, payment: 200 });
  expect(computeInsights(ledger, 'week', NOW, 'en').buckets[6]?.label).toBe('Today');
});

test('the effective date counts, not the time it was recorded', () => {
  const late = { ...entry('payment', 'Ramesh', 200, '2026-11-20'), ts: new Date(2026, 10, 21, 10, 0).toISOString() };
  expect(computeInsights([late], 'today', NOW, 'hi').payment).toBe(0);
  expect(computeInsights([late], 'week', NOW, 'hi').buckets[5]?.payment).toBe(200);
});

test('a full page whose oldest entry is inside the period may be missing older entries', () => {
  const full = Array.from({ length: 4 }, () => entry('credit', 'Ramesh', 5, '2026-11-21'));
  expect(computeInsights(full, 'today', NOW, 'hi', 4).truncated).toBe(true);
  expect(computeInsights([...full.slice(0, 3), entry('credit', 'Geeta', 5, '2026-11-01')], 'week', NOW, 'hi', 4).truncated).toBe(false);
});

test('top five dues: owing only, highest first, ties by name', () => {
  const cs: Customer[] = [
    { id: 'a', display: 'Ramesh', tags: [], balance: 230, reminders_opt_in: false },
    { id: 'b', display: 'Lakshmi', tags: [], balance: 2400, reminders_opt_in: true },
    { id: 'c', display: 'Shivu', tags: ['doodh wale'], balance: 850, reminders_opt_in: false },
    { id: 'd', display: 'Sunita', tags: [], balance: 850, reminders_opt_in: false },
    { id: 'e', display: 'Imran', tags: [], balance: 85, reminders_opt_in: false },
    { id: 'f', display: 'Geeta', tags: [], balance: 5, reminders_opt_in: false },
    { id: 'g', display: 'Arjun', tags: [], balance: -150, reminders_opt_in: false },
    { id: 'h', display: 'Meena', tags: [], balance: 0, reminders_opt_in: false },
  ];
  expect(topDues(cs).map((c) => c.display)).toEqual(['Lakshmi', 'Shivu', 'Sunita', 'Ramesh', 'Imran']);
  expect(duesTotal(cs)).toEqual({ total: 2400 + 850 + 850 + 230 + 85 + 5, count: 6 });
});

test('bar lengths', () => {
  expect(chartMax([])).toBe(1);
  expect(chartMax([{ key: 'a', label: 'a', credit: 430, payment: 200 }])).toBe(430);
  expect(barPercent(430, 430)).toBe(100);
  expect(barPercent(0, 430)).toBe(0);
  expect(barPercent(5, 100000)).toBe(1.5);
});

test('labels exist in both languages', () => {
  const keys = Object.keys(HISAAB_LABELS.hi);
  expect(Object.keys(HISAAB_LABELS.en).sort()).toEqual([...keys].sort());
  for (const k of keys) {
    expect(HISAAB_LABELS.hi[k as keyof typeof HISAAB_LABELS.hi]).not.toBe('');
    expect(HISAAB_LABELS.en[k as keyof typeof HISAAB_LABELS.en]).not.toBe('');
  }
});

test('date line under the title', () => {
  expect(dateLine(NOW, 'hi')).toBe('Shanivaar, 21 November');
  expect(dateLine(NOW, 'en')).toBe('Saturday, 21 November');
});
