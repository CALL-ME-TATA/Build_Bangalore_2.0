// The demo script gives the same numbers everywhere: Ramesh ₹430 credit, ₹200 payment, ₹230 due.
// Runs the script through the same mock brain and a fresh ledger the demo uses, then the Hisaab functions.
import { describe, expect, test } from 'vitest';
import { MockBrain } from '../../services/mock/brain';
import { MockLedger } from '../../services/mock/ledger';
import type { Lang } from '../../i18n';
import { computeInsights, topDues } from '../hisaab/insights';
import { DEMO_EXPECTED, DEMO_LINES, holdMs, stepState } from './script';

describe.each<Lang>(['hi', 'en'])('demo in %s', (lang) => {
  test('script results and final numbers', () => {
    const ledger = new MockLedger(false);
    const brain = new MockBrain(ledger);
    brain.lang = lang;
    expect(brain.greeting().reply_text).toMatch(/AI/);
    const results = DEMO_LINES[lang].map((line) => brain.respond(line));
    expect(results.map((r) => [r.status, r.action])).toEqual([
      ['ok', 'append'],
      ['ok', 'amend'],
      ['ok', 'append'],
      ['ok', 'query'],
    ]);

    const { customers } = ledger.customerSummaries();
    expect(customers).toHaveLength(1);
    expect(customers[0]).toMatchObject({ display: DEMO_EXPECTED.customer, balance: DEMO_EXPECTED.balance });

    const view = ledger.ledgerView(500);
    expect(view.totals).toEqual({ credit_today: DEMO_EXPECTED.credit, payment_today: DEMO_EXPECTED.payment });
    const hisaab = computeInsights(view.entries, 'today', ledger.now(), lang);
    expect([hisaab.credit, hisaab.payment]).toEqual([DEMO_EXPECTED.credit, DEMO_EXPECTED.payment]);
    expect(topDues(customers)[0]?.balance).toBe(DEMO_EXPECTED.balance);

    // The spoken summary says the same numbers.
    expect(results[3]?.reply_text).toContain('430');
    expect(results[3]?.reply_text).toContain('200');
    expect(results[3]?.reply_text).toContain('230');
  });
});

test('step states', () => {
  expect(stepState(0, { kind: 'idle' }, 4)).toBe('next');
  expect(stepState(0, { kind: 'greeting' }, 4)).toBe('now');
  expect([0, 1, 2, 3, 4].map((i) => stepState(i, { kind: 'line', index: 1 }, 4))).toEqual(['done', 'done', 'now', 'next', 'next']);
  expect(stepState(4, { kind: 'done' }, 4)).toBe('done');
});

test('the mic is held long enough for the words to appear', () => {
  expect(holdMs('Ramesh ka 340 udhaar')).toBeGreaterThan(280 * 4);
});
