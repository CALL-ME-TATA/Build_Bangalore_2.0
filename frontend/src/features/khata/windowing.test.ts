// Windowing maths, and the whole list pipeline on 250 to 2,000 synthetic customers.
import { describe, expect, test } from 'vitest';
import { buildLayout, estimateHeight, renderedIndices, rowAt, visibleRange } from './windowing';
import { syntheticKhata } from './synthetic';
import { activeToday, filterCustomers, lastActivity, sortCustomers } from './logic';

const NOW = new Date(2026, 10, 21, 12, 0, 0);

describe('layout', () => {
  test('prefix sums with measured heights and the estimate for the rest', () => {
    const measured = new Map([
      [0, 60],
      [2, 100],
    ]);
    const l = buildLayout(4, (i) => measured.get(i), 70);
    expect(Array.from(l.offsets)).toEqual([0, 60, 130, 230, 300]);
    expect(l.total).toBe(300);
  });
  test('estimate is the mean of measured rows, else the fallback', () => {
    expect(estimateHeight([60, 80], 66)).toBe(70);
    expect(estimateHeight([], 66)).toBe(66);
    expect(estimateHeight([0, -1], 66)).toBe(66);
  });
  test('empty list', () => {
    const l = buildLayout(0, () => undefined, 66);
    expect(l.total).toBe(0);
    expect(visibleRange(l, 0, 800, 5)).toEqual({ start: 0, end: 0 });
  });
});

describe('rowAt', () => {
  const l = buildLayout(10, () => 50, 50); // rows at 0, 50, ... 450; total 500
  test('finds the row containing a position, clamped', () => {
    expect(rowAt(l, -10)).toBe(0);
    expect(rowAt(l, 0)).toBe(0);
    expect(rowAt(l, 49.9)).toBe(0);
    expect(rowAt(l, 50)).toBe(1);
    expect(rowAt(l, 275)).toBe(5);
    expect(rowAt(l, 499)).toBe(9);
    expect(rowAt(l, 10000)).toBe(9);
  });
});

describe('visibleRange', () => {
  const l = buildLayout(1000, () => 64, 64); // total 64,000
  test('top of the list', () => {
    expect(visibleRange(l, 0, 640, 0)).toEqual({ start: 0, end: 10 });
    expect(visibleRange(l, 0, 640, 8)).toEqual({ start: 0, end: 18 });
  });
  test('middle, with overscan on both sides', () => {
    expect(visibleRange(l, 6400, 640, 5)).toEqual({ start: 95, end: 115 });
  });
  test('partly visible rows are included', () => {
    expect(visibleRange(l, 32, 640, 0)).toEqual({ start: 0, end: 11 });
  });
  test('end of the list is clamped', () => {
    expect(visibleRange(l, 64000 - 640, 640, 8)).toEqual({ start: 982, end: 1000 });
  });
  test('list below the viewport (content above it): a few first rows; above it: a few last rows', () => {
    expect(visibleRange(l, -2000, 640, 6)).toEqual({ start: 0, end: 6 });
    expect(visibleRange(l, 70000, 640, 6)).toEqual({ start: 994, end: 1000 });
  });
  test('list starting part way down the screen', () => {
    expect(visibleRange(l, -320, 640, 0)).toEqual({ start: 0, end: 5 });
  });
  test('unknown viewport height still renders a screenful', () => {
    expect(visibleRange(l, 0, 0, 0).end).toBeGreaterThan(5);
  });
});

describe('renderedIndices', () => {
  test('the range, plus a pinned (focused) row outside it, in order', () => {
    expect(renderedIndices({ start: 10, end: 13 }, null, 100)).toEqual([10, 11, 12]);
    expect(renderedIndices({ start: 10, end: 13 }, 11, 100)).toEqual([10, 11, 12]);
    expect(renderedIndices({ start: 10, end: 13 }, 2, 100)).toEqual([2, 10, 11, 12]);
    expect(renderedIndices({ start: 10, end: 13 }, 50, 100)).toEqual([10, 11, 12, 50]);
    expect(renderedIndices({ start: 10, end: 13 }, 500, 100)).toEqual([10, 11, 12]);
  });
});

describe('200+ synthetic customers', () => {
  test('the generated khata is consistent: balances match entries, amounts ₹5 to ₹1,00,000, mixed scripts', () => {
    const k = syntheticKhata(250, NOW);
    expect(k.customers).toHaveLength(250);
    expect(k.ledger.entries.length).toBeLessThanOrEqual(500);
    const ids = new Set(k.customers.map((c) => c.id));
    expect(ids.size).toBe(250);
    const sums = new Map<string, number>();
    for (const e of k.ledger.entries) {
      expect(ids.has(e.customer.id)).toBe(true);
      expect(e.amount).toBeGreaterThanOrEqual(5);
      expect(e.amount).toBeLessThanOrEqual(100000);
      if (!e.reversed) sums.set(e.customer.id, (sums.get(e.customer.id) ?? 0) + (e.kind === 'credit' ? e.amount : -e.amount));
    }
    for (const c of k.customers) expect(c.balance).toBe(sums.get(c.id) ?? 0);
    expect(k.customers.some((c) => /[ऀ-ॿ]/.test(c.display))).toBe(true);
    expect(k.customers.some((c) => /[ಀ-೿]/.test(c.display))).toBe(true);
    expect(k.customers.some((c) => c.display.length > 30)).toBe(true);
    // Deterministic
    expect(syntheticKhata(250, NOW).customers).toEqual(k.customers);
  });

  test('only a screenful of rows is rendered anywhere in a 250-row list', () => {
    const k = syntheticKhata(250, NOW);
    const last = lastActivity(k.ledger.entries);
    const rows = filterCustomers(sortCustomers(k.customers, last), { filter: 'all', query: '', today: activeToday(k.ledger.entries, NOW) });
    expect(rows).toHaveLength(250);
    // Mixed heights: long names wrap to two lines.
    const layout = buildLayout(rows.length, (i) => ((rows[i]?.display.length ?? 0) > 20 ? 88 : 66), 66);
    const viewport = 740;
    for (let top = 0; top < layout.total; top += 997) {
      const r = visibleRange(layout, top, viewport, 8);
      expect(r.end - r.start).toBeLessThanOrEqual(Math.ceil(viewport / 66) + 1 + 16);
      // Every row that intersects the viewport is inside the range.
      for (let i = 0; i < rows.length; i++) {
        const a = layout.offsets[i] ?? 0;
        const b = layout.offsets[i + 1] ?? 0;
        if (b > top && a < top + viewport) {
          expect(i).toBeGreaterThanOrEqual(r.start);
          expect(i).toBeLessThan(r.end);
        }
      }
    }
  });

  test('2,000 customers: sorting, filtering and layout stay fast', () => {
    const k = syntheticKhata(2000, NOW);
    const t0 = performance.now();
    for (let n = 0; n < 10; n++) {
      const last = lastActivity(k.ledger.entries);
      const today = activeToday(k.ledger.entries, NOW);
      const rows = filterCustomers(sortCustomers(k.customers, last), { filter: 'due', query: 'ra', today });
      const layout = buildLayout(rows.length, () => undefined, 66);
      visibleRange(layout, layout.total / 2, 740, 8);
    }
    const per = (performance.now() - t0) / 10;
    // Generous bound for a slow CI machine; a phone is slower than a laptop, but this is the whole pipeline.
    expect(per).toBeLessThan(50);
  });
});
