// Customer detail logic: timeline grouping and pairing of removed entries, entry times, reminder rules, phone
// numbers, labels; and the timeline markup (struck-through removed entries stay visible).
import { describe, expect, test } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Entry } from '../../services/session/types';
import type { Reminder } from '../../services/api';
import {
  customerTimeline,
  entryTime,
  groupLabel,
  historyMayBeCut,
  normalizePhone,
  reminderAvailability,
  reminderFor,
} from './logic';
import { CUSTOMER_TABLES } from './labels';
import { Timeline } from './Timeline';

const NOW = new Date(2026, 10, 21, 12, 0, 0); // Sat 21 Nov 2026

function at(day: number, h: number, m = 0, month = 10, year = 2026): string {
  return new Date(year, month, day, h, m).toISOString();
}

function entry(id: number, cid: string, kind: Entry['kind'], amount: number, ts: string, date: string, reversed = false): Entry {
  return { id, kind, customer: { id: cid, display: 'Ramesh', tags: [] }, amount, date, ts, reversed, reversal_of: null };
}

describe('groupLabel', () => {
  test('Aaj, Kal · 20 Nov, 19 Nov, and the year for older years', () => {
    expect(groupLabel('2026-11-21', NOW, 'hi')).toBe('Aaj');
    expect(groupLabel('2026-11-20', NOW, 'hi')).toBe('Kal · 20 Nov');
    expect(groupLabel('2026-11-19', NOW, 'hi')).toBe('19 Nov');
    expect(groupLabel('2026-11-20', NOW, 'en')).toBe('Yesterday · 20 Nov');
    expect(groupLabel('2025-12-31', NOW, 'en')).toBe('31 Dec 2025');
  });
  test('yesterday across a month boundary', () => {
    const first = new Date(2026, 11, 1, 9);
    expect(groupLabel('2026-11-30', first, 'hi')).toBe('Kal · 30 Nov');
  });
});

describe('customerTimeline', () => {
  const entries = [
    entry(1, 'r', 'credit', 850, at(19, 10), '2026-11-19'),
    entry(2, 'x', 'credit', 99, at(20, 9), '2026-11-20'), // another customer
    entry(3, 'r', 'payment', 200, at(20, 18), '2026-11-20'),
    entry(4, 'r', 'credit', 340, at(21, 11, 40), '2026-11-21', true), // corrected...
    entry(5, 'r', 'credit', 430, at(21, 11, 41), '2026-11-21'), // ...to this
    entry(6, 'r', 'credit', 85, at(21, 11, 50), '2026-11-21', true), // undone, nothing replaced it
  ];

  test('only this customer, grouped by date, newest first', () => {
    const g = customerTimeline(entries, 'r', NOW, 'hi');
    expect(g.map((x) => x.label)).toEqual(['Aaj', 'Kal · 20 Nov', '19 Nov']);
    expect(g[1]?.items.map((i) => i.entry.id)).toEqual([3]);
    expect(g[2]?.items.map((i) => i.entry.id)).toEqual([1]);
  });

  test('a removed entry sits with the entry recorded after it; an undo stays on its own; nothing is dropped', () => {
    const today = customerTimeline(entries, 'r', NOW, 'hi')[0];
    expect(today?.items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([
      [6, null],
      [5, 4],
    ]);
    const shown = customerTimeline(entries, 'r', NOW, 'hi').flatMap((g) => g.items.flatMap((i) => [i.entry.id, ...(i.replaced ? [i.replaced.id] : [])]));
    expect(shown.sort()).toEqual([1, 3, 4, 5, 6]);
  });

  test('two removed entries in a row: only the newer pairs, the older stays visible', () => {
    const e = [
      entry(1, 'r', 'credit', 100, at(21, 9), '2026-11-21', true),
      entry(2, 'r', 'credit', 200, at(21, 9, 1), '2026-11-21', true),
      entry(3, 'r', 'credit', 300, at(21, 9, 2), '2026-11-21'),
    ];
    const items = customerTimeline(e, 'r', NOW, 'hi')[0]?.items ?? [];
    expect(items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([
      [3, 2],
      [1, null],
    ]);
  });

  test('unknown customer: empty', () => {
    expect(customerTimeline(entries, 'nobody', NOW, 'hi')).toEqual([]);
  });
});

describe('entryTime', () => {
  test('clock time when recorded on its own date, else when it was written', () => {
    expect(entryTime({ date: '2026-11-21', ts: at(21, 11, 42) }, NOW, 'hi')).toBe('11:42');
    expect(entryTime({ date: '2026-11-20', ts: at(21, 9, 5) }, NOW, 'hi')).toBe('likha Aaj, 09:05');
    expect(entryTime({ date: '2026-11-20', ts: at(21, 9, 5) }, NOW, 'en')).toBe('written Today, 09:05');
    expect(entryTime({ date: '2026-11-20', ts: 'bad' }, NOW, 'hi')).toBe('');
  });
});

describe('reminders', () => {
  test('needs opt-in and a due balance, with a reason otherwise', () => {
    expect(reminderAvailability({ reminders_opt_in: false, balance: 340 })).toEqual({ enabled: false, reason: 'reasonNotOptedIn' });
    expect(reminderAvailability({ reminders_opt_in: true, balance: 0 })).toEqual({ enabled: false, reason: 'reasonNothingDue' });
    expect(reminderAvailability({ reminders_opt_in: true, balance: -50 })).toEqual({ enabled: false, reason: 'reasonNothingDue' });
    expect(reminderAvailability({ reminders_opt_in: true, balance: 5 })).toEqual({ enabled: true, reason: null });
  });
  test('the newest pending reminder of this customer', () => {
    const r = (id: number, cid: string): Reminder => ({ id, customer: { id: cid, display: cid }, amount: 340, message: 'm', has_phone: false, status: 'pending' });
    expect(reminderFor([r(1, 'a'), r(3, 'a'), r(2, 'b')], 'a')?.id).toBe(3);
    expect(reminderFor([r(2, 'b')], 'a')).toBeNull();
  });
  test('history may be cut when the server returned its maximum', () => {
    expect(historyMayBeCut(500, 500)).toBe(true);
    expect(historyMayBeCut(42, 500)).toBe(false);
  });
});

describe('normalizePhone', () => {
  test('accepts Indian mobiles in common forms', () => {
    expect(normalizePhone('98765 43210')).toBe('9876543210');
    expect(normalizePhone('+91 98765-43210')).toBe('9876543210');
    expect(normalizePhone('09876543210')).toBe('9876543210');
  });
  test('rejects short, long and landline-like numbers', () => {
    expect(normalizePhone('12345')).toBeNull();
    expect(normalizePhone('1234567890')).toBeNull();
    expect(normalizePhone('98765432101234')).toBeNull();
    expect(normalizePhone('')).toBeNull();
  });
});

describe('labels', () => {
  test('both languages have the same keys and no empty label', () => {
    const hi = Object.keys(CUSTOMER_TABLES.hi).sort();
    expect(Object.keys(CUSTOMER_TABLES.en).sort()).toEqual(hi);
    for (const t of Object.values(CUSTOMER_TABLES)) for (const v of Object.values(t)) expect(v.trim()).not.toBe('');
  });
});

describe('Timeline markup', () => {
  test('a corrected entry shows the old amount struck through above the new one; an undo stays, labelled', () => {
    const entries = [
      entry(8, 'r', 'credit', 85, at(21, 11, 50), '2026-11-21', true),
      entry(4, 'r', 'credit', 340, at(21, 11, 40), '2026-11-21', true),
      entry(5, 'r', 'credit', 430, at(21, 11, 41), '2026-11-21'),
      entry(7, 'r', 'payment', 100000, at(20, 10), '2026-11-20'),
    ];
    const groups = customerTimeline(entries, 'r', NOW, 'hi');
    const html = renderToStaticMarkup(createElement(Timeline, { groups, lang: 'hi', now: NOW, cut: false }));
    expect(html).toContain('Aaj');
    expect(html).toContain('Kal · 20 Nov');
    expect(html).toContain('line-through');
    expect(html).toContain('Udhaar · sudhaara');
    expect(html).toContain('Udhaar · hataya');
    expect(html.indexOf('>340<')).toBeLessThan(html.indexOf('>430<'));
    expect(html).toContain('pehle: ');
    expect(html).toContain('1,00,000');
    expect(html).toContain('minus 100000 rupaye, jama');
    // Date groups are the headings (eyebrows), one per day.
    expect(html.match(/<h2/g)?.length).toBe(2);
  });
});

describe('customerTimeline pairing by replaces', () => {
  const withReplaces = (e: Entry, replaces: number | null): Entry => ({ ...e, replaces });

  test('a correction pairs with the entry it names, even on another date', () => {
    const e = [
      entry(1, 'r', 'credit', 340, at(19, 10), '2026-11-19', true),
      entry(2, 'r', 'payment', 50, at(20, 10), '2026-11-20'),
      withReplaces(entry(3, 'r', 'credit', 430, at(21, 9), '2026-11-21'), 1),
    ];
    const g = customerTimeline(e, 'r', NOW, 'hi');
    expect(g.map((x) => x.date)).toEqual(['2026-11-21', '2026-11-20']);
    expect(g[0]?.items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([[3, 1]]);
    expect(g[1]?.items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([[2, null]]);
  });

  test('the id wins over position; replaces null is not a correction, so it never takes a removed entry', () => {
    const e = [
      entry(1, 'r', 'credit', 100, at(21, 9), '2026-11-21', true), // removed on the screen; entry 3 comes right after
      entry(2, 'r', 'credit', 200, at(21, 9, 1), '2026-11-21', true), // replaced by 4
      withReplaces(entry(3, 'r', 'credit', 300, at(21, 9, 2), '2026-11-21'), null),
      withReplaces(entry(4, 'r', 'credit', 250, at(21, 9, 3), '2026-11-21'), 2),
    ];
    const items = customerTimeline(e, 'r', NOW, 'hi')[0]?.items ?? [];
    expect(items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([
      [4, 2],
      [3, null],
      [1, null],
    ]);
  });

  test('a correction that was later removed is labelled hataya, with the old amount still shown', () => {
    const e = [
      withReplaces(entry(1, 'r', 'credit', 111, at(21, 9), '2026-11-21', true), null),
      withReplaces(entry(2, 'r', 'credit', 122, at(21, 9, 1), '2026-11-21', true), 1),
    ];
    const groups = customerTimeline(e, 'r', NOW, 'hi');
    const html = renderToStaticMarkup(createElement(Timeline, { groups, lang: 'hi', now: NOW, cut: false }));
    expect(html).toContain('Udhaar · hataya');
    expect(html).not.toContain('Udhaar · sudhaara');
    expect(html.indexOf('>111<')).toBeLessThan(html.indexOf('>122<'));
  });

  test('without the replaces field (an older server) a removed entry still pairs by position', () => {
    const e = [
      entry(1, 'r', 'credit', 100, at(21, 9), '2026-11-21', true),
      entry(2, 'r', 'credit', 300, at(21, 9, 2), '2026-11-21'),
    ];
    const items = customerTimeline(e, 'r', NOW, 'hi')[0]?.items ?? [];
    expect(items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([[2, 1]]);
  });

  test('a chain keeps every entry visible', () => {
    const e = [
      entry(1, 'r', 'credit', 100, at(21, 9), '2026-11-21', true),
      withReplaces(entry(2, 'r', 'credit', 200, at(21, 9, 1), '2026-11-21', true), 1),
      withReplaces(entry(3, 'r', 'credit', 300, at(21, 9, 2), '2026-11-21'), 2),
    ];
    const shown = customerTimeline(e, 'r', NOW, 'hi').flatMap((g) => g.items.flatMap((i) => [i.entry.id, ...(i.replaced ? [i.replaced.id] : [])]));
    expect(shown.sort()).toEqual([1, 2, 3]);
  });

  test('a correction moved here from another customer shows no old amount; the old row stays on the other screen', () => {
    const old: Entry = { ...entry(1, 'x', 'credit', 340, at(21, 9), '2026-11-21', true) };
    const moved = withReplaces(entry(2, 'r', 'credit', 340, at(21, 10), '2026-11-21'), 1);
    expect(customerTimeline([old, moved], 'r', NOW, 'hi')[0]?.items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([[2, null]]);
    expect(customerTimeline([old, moved], 'x', NOW, 'hi')[0]?.items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([[1, null]]);
  });

  test('a replaces that names nothing loaded falls back to no pairing, not to position', () => {
    const e = [
      entry(1, 'r', 'credit', 100, at(21, 9), '2026-11-21', true),
      withReplaces(entry(2, 'r', 'credit', 200, at(21, 9, 1), '2026-11-21'), 99),
    ];
    const items = customerTimeline(e, 'r', NOW, 'hi')[0]?.items ?? [];
    expect(items.map((i) => [i.entry.id, i.replaced?.id ?? null])).toEqual([
      [2, null],
      [1, null],
    ]);
  });
});

describe('Timeline edit rows', () => {
  test('active rows are buttons with a pencil; removed rows are plain; no onEdit means no buttons', () => {
    const entries = [
      entry(1, 'r', 'credit', 340, at(21, 9), '2026-11-21', true),
      entry(2, 'r', 'credit', 430, at(21, 10), '2026-11-21'),
    ];
    const groups = customerTimeline(entries, 'r', NOW, 'hi');
    const on = renderToStaticMarkup(createElement(Timeline, { groups, lang: 'hi', now: NOW, cut: false, onEdit: () => undefined }));
    expect(on.match(/<button/g)?.length).toBe(1);
    expect(on).toContain('id="entry-edit-2"');
    const off = renderToStaticMarkup(createElement(Timeline, { groups, lang: 'hi', now: NOW, cut: false }));
    expect(off).not.toContain('<button');
  });
});
