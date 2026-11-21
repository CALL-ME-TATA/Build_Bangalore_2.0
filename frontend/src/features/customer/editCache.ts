// Cache updates for editing on the customer screen. A change is written into the react-query cache at once
// (optimistic), the server's answer is written over it when it arrives, and a failure restores the snapshot taken
// before. The optimistic change has the same shape as the server's answer (`EntryChange`), so one function applies both.
// Cached data: GET /api/customers (['khata','customers']) and GET /api/ledger (['khata','ledger',limit,order,customerId]).
import type { QueryClient } from '@tanstack/react-query';
import type { AmendBody, Customer, CustomerPatch, EntryChange, LedgerView, NewEntryBody } from '../../services/api';
import type { Entry, EntryKind } from '../../services/session/types';
import { queryKeys } from '../../services/query';

let tempSeq = 0;

/** A new id for an entry the server has not confirmed (see isTempId in edit.ts). */
export function tempId(): string {
  tempSeq += 1;
  return `tmp-${tempSeq}`;
}

/** What an entry does to the balance: credit adds, payment and write-off subtract. */
export function signed(kind: EntryKind, amount: number): number {
  return kind === 'credit' ? amount : -amount;
}

function ref(c: Customer | undefined, id: string): Entry['customer'] {
  return { id, display: c?.display ?? '', tags: [...(c?.tags ?? [])] };
}

function balancesOf(customers: readonly Customer[] | undefined, deltas: Map<string, number>): EntryChange['balances'] {
  const out: EntryChange['balances'] = [];
  for (const [id, delta] of deltas) {
    const c = customers?.find((x) => x.id === id);
    if (c) out.push({ customer_id: id, display: c.display, balance: c.balance + delta });
  }
  return out;
}

function addDelta(m: Map<string, number>, id: string, d: number) {
  m.set(id, (m.get(id) ?? 0) + d);
}

/** The entry an add would write, as an answer: one entry with a temporary id and the new balance. */
export function optimisticAdd(body: NewEntryBody, customers: readonly Customer[] | undefined, now: Date, today: string): EntryChange {
  const c = customers?.find((x) => x.id === body.customer_id);
  const entry: Entry = {
    id: tempId(),
    kind: body.kind,
    customer: ref(c, body.customer_id),
    amount: body.amount,
    date: body.date ?? today,
    ts: now.toISOString(),
    reversed: false,
    reversal_of: null,
    replaces: null,
  };
  const deltas = new Map<string, number>();
  addDelta(deltas, body.customer_id, signed(body.kind, body.amount));
  return { ok: true, entries: [entry], balances: balancesOf(customers, deltas) };
}

/** An amend as an answer: the old entry reversed, then its changed copy (temporary id, `replaces` = old id). */
export function optimisticAmend(old: Entry, body: AmendBody, customers: readonly Customer[] | undefined, now: Date): EntryChange {
  const kind = body.kind ?? old.kind;
  const amount = body.amount ?? old.amount;
  const customerId = body.customer_id ?? old.customer.id;
  const fresh: Entry = {
    id: tempId(),
    kind,
    customer: customerId === old.customer.id ? { ...old.customer } : ref(customers?.find((x) => x.id === customerId), customerId),
    amount,
    date: body.date ?? old.date,
    ts: now.toISOString(),
    reversed: false,
    reversal_of: null,
    replaces: old.id,
  };
  const deltas = new Map<string, number>();
  addDelta(deltas, old.customer.id, -signed(old.kind, old.amount));
  addDelta(deltas, customerId, signed(kind, amount));
  return { ok: true, entries: [{ ...old, reversed: true }, fresh], balances: balancesOf(customers, deltas) };
}

/** A removal as an answer: the entry reversed, and the balance without it. */
export function optimisticRemove(old: Entry, customers: readonly Customer[] | undefined): EntryChange {
  const deltas = new Map<string, number>();
  addDelta(deltas, old.customer.id, -signed(old.kind, old.amount));
  return { ok: true, entries: [{ ...old, reversed: true }], balances: balancesOf(customers, deltas) };
}

/**
 * One ledger view with an answer applied: entries with a known id are replaced, new ones go first (newest first),
 * and `dropIds` (the temporary ids this change made) are removed. A view of one customer takes only that
 * customer's entries.
 */
export function applyEntryChange(
  view: LedgerView | undefined,
  change: Pick<EntryChange, 'entries'>,
  opts: { customerId?: string | null; dropIds?: readonly (string | number)[] } = {},
): LedgerView | undefined {
  if (!view) return view;
  const drop = new Set((opts.dropIds ?? []).map(String));
  const entries = view.entries.filter((e) => !drop.has(String(e.id)));
  const fresh: Entry[] = [];
  for (const ce of change.entries) {
    if (opts.customerId && ce.customer.id !== opts.customerId) continue;
    const i = entries.findIndex((e) => String(e.id) === String(ce.id));
    if (i >= 0) entries[i] = ce;
    else fresh.unshift(ce);
  }
  return { ...view, entries: [...fresh, ...entries] };
}

/** The customers list with the answer's balances written in. */
export function applyBalances(customers: Customer[] | undefined, balances: EntryChange['balances']): Customer[] | undefined {
  if (!customers) return customers;
  return customers.map((c) => {
    const b = balances.find((x) => x.customer_id === c.id);
    return b ? { ...c, balance: b.balance } : c;
  });
}

/** The cached customer after a patch (the phone shows only as a hint). */
export function patchCustomer(c: Customer, patch: CustomerPatch): Customer {
  const next: Customer = { ...c };
  if (patch.display !== undefined) next.display = patch.display;
  if (patch.tags !== undefined) next.tags = [...patch.tags];
  if (patch.phone !== undefined) next.phone_hint = patch.phone ? `•••• ${patch.phone.slice(-4)}` : null;
  return next;
}

type LedgerKey = readonly unknown[];

function eachLedger(qc: QueryClient, fn: (customerId: string | null) => (v: LedgerView | undefined) => LedgerView | undefined) {
  for (const [key] of qc.getQueriesData<LedgerView>({ queryKey: ['khata', 'ledger'] })) {
    const cid = (key as LedgerKey)[4];
    qc.setQueryData<LedgerView | undefined>(key, fn(typeof cid === 'string' ? cid : null));
  }
}

/** Writes an answer (optimistic or the server's) into the customers list and every ledger view. */
export function applyChangeToCache(qc: QueryClient, change: EntryChange, dropIds: readonly (string | number)[] = []): void {
  qc.setQueryData<Customer[] | undefined>(queryKeys.customers(), (c) => applyBalances(c, change.balances));
  eachLedger(qc, (customerId) => (v) => applyEntryChange(v, change, { customerId, dropIds }));
}

/** Writes a customer change into the customers list and the names shown on cached entries. */
export function applyCustomerToCache(qc: QueryClient, id: string, next: (c: Customer) => Customer): void {
  let updated: Customer | undefined;
  qc.setQueryData<Customer[] | undefined>(queryKeys.customers(), (list) =>
    list?.map((c) => {
      if (c.id !== id) return c;
      updated = next(c);
      return updated;
    }),
  );
  const u = updated as Customer | undefined;
  if (!u) return;
  eachLedger(qc, () => (v) =>
    v ? { ...v, entries: v.entries.map((e) => (e.customer.id === id ? { ...e, customer: { id, display: u.display, tags: [...u.tags] } } : e)) } : v,
  );
}

export type KhataSnapshot = ReturnType<QueryClient['getQueriesData']>;

/** Every cached khata query as it is now, for a rollback. */
export function snapshotKhata(qc: QueryClient): KhataSnapshot {
  return qc.getQueriesData({ queryKey: queryKeys.all });
}

/** Puts a snapshot back. */
export function restoreKhata(qc: QueryClient, snap: KhataSnapshot): void {
  for (const [key, data] of snap) qc.setQueryData(key, data);
}
