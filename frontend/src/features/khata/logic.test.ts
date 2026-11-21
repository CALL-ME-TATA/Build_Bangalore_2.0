// Khata list logic: balance words, last activity, "Aaj", sorting, search and filters, the dues summary, labels.
import { describe, expect, test } from 'vitest';
import type { Customer } from '../../services/api';
import type { Entry } from '../../services/session/types';
import {
  activeToday,
  balanceState,
  balanceWord,
  duesSummary,
  filterCustomers,
  lastActivity,
  lastEntryText,
  matchesSearch,
  normalizeSearch,
  scriptLang,
  sortCustomers,
  tagLabel,
  todayLine,
} from './logic';
import { KHATA_TABLES, fill } from './labels';
import { syntheticCount } from './data';

const NOW = new Date(2026, 10, 21, 12, 0, 0); // Sat 21 Nov 2026, local time

function at(day: number, h: number, m = 0): string {
  return new Date(2026, 10, day, h, m).toISOString();
}

function entry(id: number, cid: string, kind: Entry['kind'], amount: number, ts: string, date: string, reversed = false): Entry {
  return { id, kind, customer: { id: cid, display: cid, tags: [] }, amount, date, ts, reversed, reversal_of: null };
}

function cust(id: string, display: string, balance: number, tags: string[] = []): Customer {
  return { id, display, tags, balance, reminders_opt_in: false };
}

describe('balance state and words', () => {
  test('positive is due, negative is advance, zero is settled', () => {
    expect(balanceState(340)).toBe('due');
    expect(balanceState(-200)).toBe('advance');
    expect(balanceState(0)).toBe('clear');
  });
  test('words in both languages', () => {
    expect(balanceWord(5, 'hi')).toBe('baaki');
    expect(balanceWord(-5, 'hi')).toBe('advance jama');
    expect(balanceWord(0, 'hi')).toBe('hisaab saaf');
    expect(balanceWord(100000, 'en')).toBe('due');
    expect(balanceWord(-1, 'en')).toBe('paid in advance');
    expect(balanceWord(0, 'en')).toBe('settled');
  });
});

describe('lastActivity', () => {
  test('newest entry per customer, by time then id', () => {
    const e = [
      entry(1, 'a', 'credit', 100, at(19, 10), '2026-11-19'),
      entry(3, 'a', 'payment', 50, at(21, 9), '2026-11-21'),
      entry(2, 'b', 'credit', 85, at(20, 18), '2026-11-20'),
    ];
    const last = lastActivity(e);
    expect(last.get('a')?.id).toBe(3);
    expect(last.get('b')?.id).toBe(2);
  });
  test('an active entry wins over a newer removed one; only-removed customers still show', () => {
    const e = [
      entry(1, 'a', 'credit', 340, at(21, 9), '2026-11-21'),
      entry(2, 'a', 'credit', 740, at(21, 10), '2026-11-21', true),
      entry(3, 'c', 'credit', 20, at(21, 11), '2026-11-21', true),
    ];
    const last = lastActivity(e);
    expect(last.get('a')?.id).toBe(1);
    expect(last.get('c')?.id).toBe(3);
  });
});

describe('lastEntryText', () => {
  test('date and time the last entry was written', () => {
    expect(lastEntryText({ ts: at(21, 9) }, NOW, 'hi')).toBe('Aakhri entry: Aaj, 21 Nov · 09:00');
    expect(lastEntryText({ ts: at(20, 23, 59) }, NOW, 'hi')).toBe('Aakhri entry: Kal, 20 Nov · 23:59');
    expect(lastEntryText({ ts: at(16, 10) }, NOW, 'hi')).toBe('Aakhri entry: 16 Nov · 10:00');
    expect(lastEntryText({ ts: at(19, 10) }, NOW, 'en')).toBe('Last entry: Day before, 19 Nov · 10:00');
    expect(lastEntryText(undefined, NOW, 'hi')).toBeNull();
    expect(lastEntryText({ ts: 'bad' }, NOW, 'hi')).toBeNull();
  });
});

describe('activeToday', () => {
  test('dated today or recorded today', () => {
    const e = [
      entry(1, 'a', 'credit', 100, at(21, 9), '2026-11-21'),
      entry(2, 'b', 'payment', 200, at(21, 9), '2026-11-20'), // "kal 200 diya tha", said today
      entry(3, 'c', 'credit', 50, at(19, 9), '2026-11-19'),
    ];
    expect([...activeToday(e, NOW)].sort()).toEqual(['a', 'b']);
  });
});

describe('sortCustomers', () => {
  test('recent activity first, then the rest by due then name', () => {
    const list = [cust('x', 'Zoya', 10), cust('y', 'Arjun', 500), cust('a', 'Ramesh', 0), cust('b', 'Imran', 85), cust('z', 'Bina', 10)];
    const last = lastActivity([
      entry(1, 'a', 'credit', 100, at(20, 9), '2026-11-20'),
      entry(2, 'b', 'credit', 85, at(21, 9), '2026-11-21'),
    ]);
    expect(sortCustomers(list, last).map((c) => c.id)).toEqual(['b', 'a', 'y', 'z', 'x']);
  });
});

describe('search', () => {
  test('normalises case, accents and spaces; keeps Devanagari and Kannada', () => {
    expect(normalizeSearch('  RaMésh   Kumar ')).toBe('ramesh kumar');
    expect(normalizeSearch('रमेश')).toBe('रमेश'.normalize('NFD'));
    expect(normalizeSearch('ರಮೇಶ್')).toBe('ರಮೇಶ್'.normalize('NFD'));
  });
  test('matches name and tags, every word', () => {
    const c = cust('1', 'Ramesh', 0, ['chai wale']);
    expect(matchesSearch(c, '')).toBe(true);
    expect(matchesSearch(c, 'ram')).toBe(true);
    expect(matchesSearch(c, 'CHAI')).toBe(true);
    expect(matchesSearch(c, 'ramesh chai')).toBe(true);
    expect(matchesSearch(c, 'ramesh doodh')).toBe(false);
    expect(matchesSearch(cust('2', 'रमेश', 0), 'रमे')).toBe(true);
    expect(matchesSearch(cust('3', 'ಲಕ್ಷ್ಮಿ', 0), 'ಲಕ್ಷ್ಮಿ')).toBe(true);
  });
  test('filters: all, with dues, today; combined with search, order kept', () => {
    const list = [cust('a', 'Ramesh', 340, ['chai wale']), cust('b', 'Sunita', -200), cust('c', 'Ravi', 0), cust('d', 'Rekha', 5)];
    const today = new Set(['b', 'd']);
    expect(filterCustomers(list, { filter: 'all', query: '', today }).map((c) => c.id)).toEqual(['a', 'b', 'c', 'd']);
    expect(filterCustomers(list, { filter: 'due', query: '', today }).map((c) => c.id)).toEqual(['a', 'd']);
    expect(filterCustomers(list, { filter: 'today', query: '', today }).map((c) => c.id)).toEqual(['b', 'd']);
    expect(filterCustomers(list, { filter: 'due', query: 're', today }).map((c) => c.id)).toEqual(['d']);
    expect(filterCustomers(list, { filter: 'all', query: 'zzz', today })).toEqual([]);
  });
});

describe('duesSummary', () => {
  test('sums only what is owed and counts who owes', () => {
    const s = duesSummary([cust('a', 'A', 5), cust('b', 'B', 100000), cust('c', 'C', -300), cust('d', 'D', 0)]);
    expect(s).toEqual({ total: 100005, owing: 2, count: 4 });
    expect(duesSummary([])).toEqual({ total: 0, owing: 0, count: 0 });
  });
});

describe('display helpers', () => {
  test('date line in Hinglish and English', () => {
    expect(todayLine(NOW, 'hi')).toBe('Shanivaar, 21 November');
    expect(todayLine(NOW, 'en')).toBe('Saturday, 21 November');
  });
  test('script language for names', () => {
    expect(scriptLang('Ramesh')).toBeUndefined();
    expect(scriptLang('रमेश')).toBe('hi');
    expect(scriptLang('ರಮೇಶ್')).toBe('kn');
  });
  test('tag label', () => {
    expect(tagLabel(['chai wale'])).toBe('Chai wale');
    expect(tagLabel([])).toBe('');
  });
});

describe('labels', () => {
  test('both languages have the same keys and no empty label', () => {
    const hi = Object.keys(KHATA_TABLES.hi).sort();
    expect(Object.keys(KHATA_TABLES.en).sort()).toEqual(hi);
    for (const t of Object.values(KHATA_TABLES)) for (const v of Object.values(t)) expect(v.trim()).not.toBe('');
  });
  test('fill replaces placeholders and leaves unknown ones', () => {
    expect(fill('{n} grahak', { n: 3 })).toBe('3 grahak');
    expect(fill('{x} y', {})).toBe('{x} y');
  });
});

describe('syntheticCount', () => {
  test('only when allowed, clamped, ignores junk', () => {
    expect(syntheticCount('?synthetic=250', true)).toBe(250);
    expect(syntheticCount('?synthetic=250', false)).toBeNull();
    expect(syntheticCount('?synthetic=99999', true)).toBe(5000);
    expect(syntheticCount('?synthetic=abc', true)).toBeNull();
    expect(syntheticCount('', true)).toBeNull();
  });
});
