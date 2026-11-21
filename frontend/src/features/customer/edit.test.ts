// Editing logic of the customer screen: amounts, dates, balance differences, amend diffs, the customer patch,
// error-code labels, and the mock ledger's four operations.
import { describe, expect, test } from 'vitest';
import { ApiError } from '../../services/api';
import { MockLedger } from '../../services/mock/ledger';
import {
  amendBody,
  balanceChange,
  balanceEntry,
  customerPatch,
  dateProblem,
  entryFields,
  errorKey,
  isEditable,
  isStale,
  MAX_AMOUNT,
  parseAmount,
  parseTags,
} from './edit';
import { CUSTOMER_TABLES } from './labels';
import { QueryClient } from '@tanstack/react-query';
import type { Customer, LedgerView } from '../../services/api';
import type { Entry } from '../../services/session/types';
import {
  applyBalances,
  applyChangeToCache,
  applyCustomerToCache,
  applyEntryChange,
  optimisticAdd,
  optimisticAmend,
  optimisticRemove,
  patchCustomer,
  restoreKhata,
  snapshotKhata,
} from './editCache';
import { isTempId } from './edit';

describe('parseAmount', () => {
  test('digits, commas, spaces and a leading rupee sign', () => {
    expect(parseAmount('340')).toBe(340);
    expect(parseAmount('₹1,20,000')).toBe(120000);
    expect(parseAmount(' ₹ 85 ')).toBe(85);
    expect(parseAmount('1 200')).toBe(1200);
  });
  test('whole rupees from 1 to 9,999,999', () => {
    expect(parseAmount('0')).toBeNull();
    expect(parseAmount('9999999')).toBe(MAX_AMOUNT);
    expect(parseAmount('10000000')).toBeNull();
    expect(parseAmount('12.5')).toBeNull();
    expect(parseAmount('-5')).toBeNull();
    expect(parseAmount('')).toBeNull();
    expect(parseAmount('abc')).toBeNull();
  });
  test('a balance may be zero', () => {
    expect(parseAmount('0', 0)).toBe(0);
    expect(parseAmount('', 0)).toBeNull();
  });
});

describe('dateProblem', () => {
  test('a real date up to today and from 2000', () => {
    expect(dateProblem('2026-11-21', '2026-11-21')).toBeNull();
    expect(dateProblem('2026-11-22', '2026-11-21')).toBe('future');
    expect(dateProblem('1999-12-31', '2026-11-21')).toBe('old');
    expect(dateProblem('2000-01-01', '2026-11-21')).toBeNull();
    expect(dateProblem('2026-02-30', '2026-11-21')).toBe('bad');
    expect(dateProblem('', '2026-11-21')).toBe('bad');
    expect(dateProblem('21/11/2026', '2026-11-21')).toBe('bad');
  });
});

describe('balanceChange and balanceEntry', () => {
  test('higher: one credit of the difference', () => {
    const c = balanceChange(1000, '1,500');
    expect(c).toEqual({ type: 'up', amount: 500 });
    expect(balanceEntry(c, null)).toEqual({ kind: 'credit', amount: 500 });
  });
  test('lower: nothing to save until Jama or Maaf is chosen', () => {
    const c = balanceChange(1000, '400');
    expect(c).toEqual({ type: 'down', amount: 600 });
    expect(balanceEntry(c, null)).toBeNull();
    expect(balanceEntry(c, 'payment')).toEqual({ kind: 'payment', amount: 600 });
    expect(balanceEntry(c, 'writeoff')).toEqual({ kind: 'writeoff', amount: 600 });
  });
  test('0 settles the whole balance', () => {
    expect(balanceChange(250, '0')).toEqual({ type: 'down', amount: 250 });
  });
  test('equal: nothing to save; bad input is invalid', () => {
    const same = balanceChange(1000, '1000');
    expect(same).toEqual({ type: 'same' });
    expect(balanceEntry(same, 'payment')).toBeNull();
    expect(balanceChange(1000, 'x')).toEqual({ type: 'invalid' });
    expect(balanceChange(1000, '')).toEqual({ type: 'invalid' });
  });
  test('an advance (negative balance) rises to a due figure with one credit', () => {
    expect(balanceChange(-200, '300')).toEqual({ type: 'up', amount: 500 });
  });
  test('a difference over the limit is refused', () => {
    expect(balanceChange(-5_000_000, '9999999')).toEqual({ type: 'toolarge' });
  });
});

describe('amendBody', () => {
  const entry = { kind: 'credit' as const, amount: 340, date: '2026-11-21T00:00', customer: { id: 'a', display: 'A', tags: [] } };
  const orig = entryFields({ ...entry, date: '2026-11-21' });
  test('only the changed fields', () => {
    expect(amendBody(orig, { ...orig, amount: 430 })).toEqual({ amount: 430 });
    expect(amendBody(orig, { ...orig, kind: 'payment', date: '2026-11-20' })).toEqual({ kind: 'payment', date: '2026-11-20' });
    expect(amendBody(orig, { ...orig, customerId: 'b' })).toEqual({ customer_id: 'b' });
  });
  test('null when nothing differs', () => {
    expect(amendBody(orig, { ...orig })).toBeNull();
  });
  test('the date of an entry is the day part', () => {
    expect(entryFields({ ...entry, date: '2026-11-21T10:00:00' }).date).toBe('2026-11-21');
  });
});

describe('isEditable', () => {
  test('active rows only; removed rows and reversal rows are not', () => {
    expect(isEditable({ id: 1, reversed: false, reversal_of: null })).toBe(true);
    expect(isEditable({ id: 1, reversed: true, reversal_of: null })).toBe(false);
    expect(isEditable({ id: 1, reversed: false, reversal_of: 7 })).toBe(false);
    expect(isEditable({ id: 'tmp-3', reversed: false, reversal_of: null })).toBe(false); // waiting for its server id
  });
});

describe('parseTags and customerPatch', () => {
  const orig = { display: 'Ramesh', tags: ['chai wale'], phone_hint: '•••• 3210' };
  const same = { name: 'Ramesh', tags: 'chai wale', phone: '', clearPhone: false };
  test('tags: comma separated, lower case, no repeats', () => {
    expect(parseTags(' Chai Wale, doodh ,chai wale;')).toEqual(['chai wale', 'doodh']);
    expect(parseTags('')).toEqual([]);
  });
  test('nothing changed: no patch, no error', () => {
    expect(customerPatch(orig, same)).toEqual({ patch: null, error: null });
  });
  test('only changed fields are sent', () => {
    expect(customerPatch(orig, { ...same, name: ' Ramesh  Kumar ' }).patch).toEqual({ display: 'Ramesh Kumar' });
    expect(customerPatch(orig, { ...same, tags: 'chai wale, paan' }).patch).toEqual({ tags: ['chai wale', 'paan'] });
    expect(customerPatch(orig, { ...same, tags: '' }).patch).toEqual({ tags: [] });
    expect(customerPatch(orig, { ...same, phone: '98765 43210' }).patch).toEqual({ phone: '9876543210' });
  });
  test('clearing the phone sends null, but only when a number is stored', () => {
    expect(customerPatch(orig, { ...same, clearPhone: true }).patch).toEqual({ phone: null });
    expect(customerPatch({ ...orig, phone_hint: null }, { ...same, clearPhone: true }).patch).toBeNull();
  });
  test('invalid name, tag and phone are named', () => {
    expect(customerPatch(orig, { ...same, name: 'R' }).error).toBe('errBadName');
    expect(customerPatch(orig, { ...same, name: 'Ramesh 2' }).error).toBe('errBadName');
    expect(customerPatch(orig, { ...same, name: 'रमेश' }).error).toBeNull();
    expect(customerPatch(orig, { ...same, tags: 'a, b, c, d' }).error).toBe('errBadTag');
    expect(customerPatch(orig, { ...same, tags: 'x'.repeat(25) }).error).toBe('errBadTag');
    expect(customerPatch(orig, { ...same, phone: '12345' }).error).toBe('errBadPhone');
  });
});

describe('errorKey and isStale', () => {
  test('every server code has its own line; anything else is the general line', () => {
    const codes = [
      ['bad_kind', 'errBadKind'],
      ['bad_amount', 'errBadAmount'],
      ['bad_date', 'errBadDate'],
      ['nothing_changed', 'errNothingChanged'],
      ['bad_name', 'errBadName'],
      ['bad_tag', 'errBadTag'],
      ['bad_phone', 'errBadPhone'],
      ['unknown_entry', 'errUnknownEntry'],
      ['unknown_customer', 'errUnknownCustomer'],
      ['not_active', 'errNotActive'],
      ['name_taken', 'errNameTaken'],
      ['balance_changed', 'errBalanceChanged'],
    ] as const;
    for (const [code, key] of codes) {
      expect(errorKey(new ApiError('/x', 400, code))).toBe(key);
      expect(key in CUSTOMER_TABLES.hi).toBe(true);
    }
    expect(errorKey(new ApiError('/x', 500))).toBe('errGeneric');
    expect(errorKey(new ApiError('/x', 400, 'something_new'))).toBe('errGeneric');
    expect(errorKey(new TypeError('network'))).toBe('errGeneric');
  });
  test('name_taken tells the shopkeeper what to do', () => {
    expect(CUSTOMER_TABLES.hi.errNameTaken).toMatch(/tag/);
    expect(CUSTOMER_TABLES.en.errNameTaken).toMatch(/tag/);
  });
  test('stale codes ask for a refresh', () => {
    expect(isStale(new ApiError('/x', 409, 'balance_changed'))).toBe(true);
    expect(isStale(new ApiError('/x', 409, 'not_active'))).toBe(true);
    expect(isStale(new ApiError('/x', 400, 'bad_amount'))).toBe(false);
  });
});

describe('mock ledger editing', () => {
  const fresh = () => new MockLedger(true);
  const sunita = (l: MockLedger) => l.find('Sunita')?.id ?? '';

  test('addManual writes one entry and guards with if_balance', () => {
    const l = fresh();
    const id = sunita(l);
    const r = l.addManual({ customer_id: id, kind: 'credit', amount: 150, if_balance: 850 });
    expect(r.entries).toHaveLength(1);
    expect(r.balances[0]?.balance).toBe(1000);
    expect(() => l.addManual({ customer_id: id, kind: 'credit', amount: 1, if_balance: 850 })).toThrow(ApiError);
    try {
      l.addManual({ customer_id: id, kind: 'credit', amount: 1, if_balance: 850 });
    } catch (e) {
      expect((e as ApiError).detail).toBe('balance_changed');
      expect((e as ApiError).status).toBe(409);
    }
  });

  test('addManual refuses a future date and a bad amount', () => {
    const l = fresh();
    const id = sunita(l);
    expect(() => l.addManual({ customer_id: id, kind: 'credit', amount: 5, date: '2999-01-01' })).toThrow(/400/);
    expect(() => l.addManual({ customer_id: id, kind: 'credit', amount: 0 })).toThrow(/400/);
  });

  test('amend reverses the entry, saves a copy with replaces, and can move it to another customer', () => {
    const l = fresh();
    const a = l.find('Sunita');
    const b = l.find('Imran');
    const e = l.ledgerView().entries.find((x) => x.customer.id === a?.id);
    expect(e).toBeDefined();
    const r = l.amend(e?.id ?? 0, { amount: 900, customer_id: b?.id });
    expect(r.entries[0]?.reversed).toBe(true);
    expect(r.entries[1]?.replaces).toBe(e?.id);
    expect(r.entries[1]?.customer.id).toBe(b?.id);
    expect(l.balance(a?.id ?? '')).toBe(0);
    expect(l.balance(b?.id ?? '')).toBe(85 + 900);
    expect(r.balances).toHaveLength(2);
    expect(() => l.amend(e?.id ?? 0, { amount: 1 })).toThrow(ApiError); // already reversed: not_active
  });

  test('amend with nothing different is refused', () => {
    const l = fresh();
    const e = l.ledgerView().entries[0];
    expect(() => l.amend(e?.id ?? 0, { amount: e?.amount })).toThrow(ApiError);
  });

  test('remove reverses one entry and keeps it listed', () => {
    const l = fresh();
    const e = l.ledgerView().entries.find((x) => x.customer.display === 'Imran');
    const r = l.removeEntry(e?.id ?? 0);
    expect(r.entries[0]?.reversed).toBe(true);
    expect(l.balance(e?.customer.id ?? '')).toBe(0);
    expect(l.ledgerView().entries.some((x) => x.id === e?.id && x.reversed)).toBe(true);
  });

  test('updateCustomer renames, sets and clears the phone hint, and refuses a taken name', () => {
    const l = fresh();
    const id = sunita(l);
    expect(l.updateCustomer(id, { phone: '9876543210' }).phone_hint).toBe('•••• 3210');
    expect(l.updateCustomer(id, { phone: null }).phone_hint).toBeNull();
    expect(l.updateCustomer(id, { display: 'Sunita Devi', tags: ['paan'] })).toMatchObject({ display: 'Sunita Devi', tags: ['paan'] });
    try {
      l.updateCustomer(id, { display: 'imran' });
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).detail).toBe('name_taken');
    }
  });
});

describe('optimistic cache updates', () => {
  const NOW = new Date(2026, 10, 21, 12, 0, 0);
  const cust = (id: string, display: string, balance: number): Customer => ({ id, display, tags: [], balance, reminders_opt_in: false });
  const ent = (id: number | string, cid: string, kind: Entry['kind'], amount: number, reversed = false): Entry => ({
    id,
    kind,
    customer: { id: cid, display: cid, tags: [] },
    amount,
    date: '2026-11-21',
    ts: NOW.toISOString(),
    reversed,
    reversal_of: null,
  });
  const setup = () => {
    const qc = new QueryClient();
    qc.setQueryData(['khata', 'customers'], [cust('a', 'A', 1000), cust('b', 'B', 0)]);
    const all: LedgerView = { entries: [ent(2, 'b', 'credit', 5), ent(1, 'a', 'credit', 1000)], totals: { credit_today: 0, payment_today: 0 } };
    qc.setQueryData(['khata', 'ledger', 500, 'created', null], all);
    qc.setQueryData(['khata', 'ledger', 500, 'date', 'a'], { ...all, entries: [ent(1, 'a', 'credit', 1000)] });
    qc.setQueryData(['khata', 'ledger', 500, 'date', 'b'], { ...all, entries: [ent(2, 'b', 'credit', 5)] });
    return qc;
  };
  const customers = (qc: QueryClient) => qc.getQueryData<Customer[]>(['khata', 'customers']);
  const balance = (qc: QueryClient, id: string) => customers(qc)?.find((c) => c.id === id)?.balance;
  const ids = (qc: QueryClient, key: unknown[]) => qc.getQueryData<LedgerView>(key)?.entries.map((e) => String(e.id));

  test('an add changes the balance and the views at once, with a temporary id', () => {
    const qc = setup();
    const change = optimisticAdd({ customer_id: 'a', kind: 'payment', amount: 300 }, customers(qc), NOW, '2026-11-21');
    applyChangeToCache(qc, change);
    expect(balance(qc, 'a')).toBe(700);
    expect(isTempId(change.entries[0]?.id ?? 0)).toBe(true);
    expect(ids(qc, ['khata', 'ledger', 500, 'date', 'a'])).toEqual([String(change.entries[0]?.id), '1']);
    expect(ids(qc, ['khata', 'ledger', 500, 'date', 'b'])).toEqual(['2']);
  });

  test('an amend reverses the old entry and adds the copy with replaces; moving customers moves the balances', () => {
    const qc = setup();
    const change = optimisticAmend(ent(1, 'a', 'credit', 1000), { amount: 400, customer_id: 'b' }, customers(qc), NOW);
    applyChangeToCache(qc, change);
    expect(balance(qc, 'a')).toBe(0);
    expect(balance(qc, 'b')).toBe(400);
    const fresh = change.entries[1];
    expect(fresh?.replaces).toBe(1);
    expect(fresh?.customer.id).toBe('b');
    const view = qc.getQueryData<LedgerView>(['khata', 'ledger', 500, 'created', null]);
    expect(view?.entries.find((e) => e.id === 1)?.reversed).toBe(true);
    expect(ids(qc, ['khata', 'ledger', 500, 'date', 'b'])).toContain(String(fresh?.id));
  });

  test('a removal reverses the entry and lowers the balance', () => {
    const qc = setup();
    applyChangeToCache(qc, optimisticRemove(ent(1, 'a', 'credit', 1000), customers(qc)));
    expect(balance(qc, 'a')).toBe(0);
    expect(qc.getQueryData<LedgerView>(['khata', 'ledger', 500, 'date', 'a'])?.entries[0]?.reversed).toBe(true);
  });

  test('the server answer replaces the temporary entry and sets the balances', () => {
    const qc = setup();
    const change = optimisticAdd({ customer_id: 'a', kind: 'credit', amount: 50 }, customers(qc), NOW, '2026-11-21');
    applyChangeToCache(qc, change);
    const tmp = change.entries[0]?.id ?? 0;
    applyChangeToCache(qc, { ok: true, entries: [ent(9, 'a', 'credit', 50)], balances: [{ customer_id: 'a', display: 'A', balance: 1050 }] }, [tmp]);
    expect(ids(qc, ['khata', 'ledger', 500, 'date', 'a'])).toEqual(['9', '1']);
    expect(balance(qc, 'a')).toBe(1050);
  });

  test('a rollback puts every khata query back as it was', () => {
    const qc = setup();
    const snap = snapshotKhata(qc);
    applyChangeToCache(qc, optimisticAdd({ customer_id: 'a', kind: 'credit', amount: 50 }, customers(qc), NOW, '2026-11-21'));
    applyCustomerToCache(qc, 'a', (c) => patchCustomer(c, { display: 'Z' }));
    restoreKhata(qc, snap);
    expect(balance(qc, 'a')).toBe(1000);
    expect(customers(qc)?.[0]?.display).toBe('A');
    expect(ids(qc, ['khata', 'ledger', 500, 'date', 'a'])).toEqual(['1']);
  });

  test('a customer patch shows in the list and on cached entries; the phone is a hint', () => {
    const qc = setup();
    applyCustomerToCache(qc, 'a', (c) => patchCustomer(c, { display: 'Anita', tags: ['paan'], phone: '9876543210' }));
    const c = customers(qc)?.[0];
    expect(c).toMatchObject({ display: 'Anita', tags: ['paan'], phone_hint: '•••• 3210' });
    expect(qc.getQueryData<LedgerView>(['khata', 'ledger', 500, 'date', 'a'])?.entries[0]?.customer.display).toBe('Anita');
    expect(patchCustomer(c as Customer, { phone: null }).phone_hint).toBeNull();
  });

  test('helpers leave a missing cache alone', () => {
    expect(applyEntryChange(undefined, { entries: [] })).toBeUndefined();
    expect(applyBalances(undefined, [])).toBeUndefined();
  });
});
