// Settings helpers and the export files (pure). Synthetic data only.
import { expect, test } from 'vitest';
import type { Customer, LedgerView } from '../../services/api';
import type { Entry } from '../../services/session/types';
import { OFFLINE_LABELS } from '../../services/offline/labels';
import { DEMO_LABELS } from '../demo/labels';
import { filterCustomers, speedChoice } from './choices';
import { CSV_COLUMNS, csvCell, exportFileName, ledgerCsv, ledgerJson } from './exportData';
import { SETTINGS_LABELS } from './labels';

const e = (id: number, kind: Entry['kind'], display: string, amount: number, ts: string, reversed = false, tags: string[] = []): Entry => ({
  id,
  kind,
  customer: { id: `c${id}`, display, tags },
  amount,
  date: ts.slice(0, 10),
  ts,
  reversed,
  reversal_of: null,
});

test('voice speed snaps to the three choices', () => {
  expect([0.8, 0.9, 0.97, 1, 1.1, 1.15, 1.25].map(speedChoice)).toEqual(['0.9', '0.9', '1', '1', '1.15', '1.15', '1.15']);
});

test('customer filter matches name or tag, case-insensitive, sorted', () => {
  const cs: Customer[] = [
    { id: '1', display: 'Shivu', tags: ['doodh wale'], balance: 850, reminders_opt_in: false },
    { id: '2', display: 'Ramesh', tags: ['chai wale'], balance: 230, reminders_opt_in: false },
    { id: '3', display: 'रमेश', tags: [], balance: 0, reminders_opt_in: true },
  ];
  expect(filterCustomers(cs, '').map((c) => c.id)).toEqual(['2', '1', '3']);
  expect(filterCustomers(cs, 'WALE').map((c) => c.id)).toEqual(['2', '1']);
  expect(filterCustomers(cs, 'रमे').map((c) => c.id)).toEqual(['3']);
});

test('csv cells: quoting and formula neutralising', () => {
  expect(csvCell('Ramesh')).toBe('Ramesh');
  expect(csvCell('Sharma, ji')).toBe('"Sharma, ji"');
  expect(csvCell('say "hi"')).toBe('"say ""hi"""');
  expect(csvCell('=HYPERLINK("x")')).toBe(`"'=HYPERLINK(""x"")"`);
  expect(csvCell('+91 98')).toBe("'+91 98");
  expect(csvCell(-200)).toBe('-200');
  expect(csvCell(true)).toBe('true');
  expect(csvCell(null)).toBe('');
});

test('ledger csv: header, oldest first, signed amounts, reversed kept', () => {
  const entries = [
    e(3, 'payment', 'Ramesh', 200, '2026-11-21T06:20:00.000Z'),
    e(2, 'credit', 'Ramesh', 430, '2026-11-21T06:15:00.000Z', false, ['chai wale']),
    e(1, 'credit', 'Ramesh', 340, '2026-11-21T06:14:00.000Z', true, ['chai wale']),
  ];
  const csv = ledgerCsv(entries, { credit: 'Udhaar', payment: 'Jama' });
  const lines = csv.split('\r\n');
  expect(lines[0]).toBe(CSV_COLUMNS.join(','));
  expect(lines[1]).toBe('1,2026-11-21,2026-11-21T06:14:00.000Z,credit,Udhaar,Ramesh,chai wale,340,340,true');
  expect(lines[2]).toBe('2,2026-11-21,2026-11-21T06:15:00.000Z,credit,Udhaar,Ramesh,chai wale,430,430,false');
  expect(lines[3]).toBe('3,2026-11-21,2026-11-21T06:20:00.000Z,payment,Jama,Ramesh,,200,-200,false');
  expect(lines[4]).toBe('');
});

test('ledger json carries entries, totals and customers', () => {
  const ledger: LedgerView = { entries: [e(1, 'credit', 'Ramesh', 430, '2026-11-21T06:15:00.000Z')], totals: { credit_today: 430, payment_today: 200 } };
  const customers: Customer[] = [{ id: 'c1', display: 'Ramesh', tags: [], balance: 230, reminders_opt_in: false }];
  const out = JSON.parse(ledgerJson(ledger, customers, '2026-11-21T12:00:00.000Z'));
  expect(out).toMatchObject({ app: 'KhataVaani', exported_at: '2026-11-21T12:00:00.000Z', totals: { credit_today: 430, payment_today: 200 } });
  expect(out.entries).toHaveLength(1);
  expect(out.customers[0].balance).toBe(230);
  expect(exportFileName('csv', '2026-11-21')).toBe('khatavaani-khata-2026-11-21.csv');
});

test.each([
  ['settings', SETTINGS_LABELS],
  ['offline', OFFLINE_LABELS],
  ['demo', DEMO_LABELS],
] as const)('%s labels exist in both languages', (_name, table) => {
  const hi = table.hi as Record<string, string>;
  const en = table.en as Record<string, string>;
  expect(Object.keys(en).sort()).toEqual(Object.keys(hi).sort());
  for (const k of Object.keys(hi)) {
    expect(hi[k]).not.toBe('');
    expect(en[k]).not.toBe('');
  }
});
