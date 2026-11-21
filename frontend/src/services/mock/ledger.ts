// In-memory ledger used by the mock session and the mock REST calls, so the whole app can be built and
// demonstrated without a backend. Synthetic data only. Shapes match docs/CONTRACT.md section 3.
import type { Entry } from '../session/types';
import { ApiError, type AmendBody, type Customer, type CustomerPatch, type EntryChange, type LedgerView, type NewEntryBody, type Reminder } from '../api';

interface MockCustomer {
  id: string;
  display: string;
  tags: string[];
  reminders_opt_in: boolean;
  phone: string | null;
}

const MAX_AMOUNT = 9_999_999;
const KINDS: readonly string[] = ['credit', 'payment', 'writeoff'];

function ymd(d: Date): string {
  const p = (x: number) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export class MockLedger {
  private customers = new Map<string, MockCustomer>();
  private entries: Entry[] = [];
  private nextId = 1;
  private listeners = new Set<() => void>();
  now: () => Date = () => new Date();

  constructor(seed = true) {
    if (seed) this.seed();
  }

  /** Called after every change. */
  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private changed() {
    for (const fn of this.listeners) fn();
  }

  private seed() {
    const y = new Date(this.now().getTime() - 86400000);
    const at = (h: number, m: number) => {
      const d = new Date(y);
      d.setHours(h, m, 0, 0);
      return d;
    };
    this.add('credit', 'Sunita', 850, [], at(10, 5));
    this.add('credit', 'Shivu', 1250, ['doodh wale'], at(11, 20));
    this.add('payment', 'Shivu', 400, ['doodh wale'], at(17, 40));
    this.add('credit', 'Lakshmi', 2400, [], at(18, 2));
    this.add('credit', 'Imran', 85, [], at(19, 15));
    const lakshmi = this.find('Lakshmi');
    if (lakshmi) lakshmi.reminders_opt_in = true;
  }

  find(name: string, tag?: string): MockCustomer | undefined {
    const key = name.trim().toLowerCase();
    for (const c of this.customers.values()) {
      if (c.display.toLowerCase() === key && (!tag || c.tags.includes(tag))) return c;
    }
    return undefined;
  }

  /** Customers with this display name (more than one means the name is ambiguous). */
  named(name: string): MockCustomer[] {
    const key = name.trim().toLowerCase();
    return [...this.customers.values()].filter((c) => c.display.toLowerCase() === key);
  }

  isNew(name: string): boolean {
    return !this.find(name);
  }

  customer(name: string, tags: string[] = []): MockCustomer {
    const found = this.find(name, tags[0]) ?? (tags.length ? undefined : this.find(name));
    if (found) return found;
    const c: MockCustomer = { id: `c${this.customers.size + 1}`, display: name, tags, reminders_opt_in: false, phone: null };
    this.customers.set(c.id, c);
    return c;
  }

  add(kind: Entry['kind'], name: string, amount: number, tags: string[] = [], when: Date = this.now()): Entry {
    const c = this.customer(name, tags);
    const e: Entry = {
      id: this.nextId++,
      kind,
      customer: { id: c.id, display: c.display, tags: [...c.tags] },
      amount,
      date: ymd(when),
      ts: when.toISOString(),
      reversed: false,
      reversal_of: null,
    };
    this.entries.push(e);
    this.changed();
    return e;
  }

  /** Marks an entry reversed (append-only on the server; here the flag is what the API shows). */
  reverse(id: Entry['id']): Entry | undefined {
    const e = this.entries.find((x) => x.id === id);
    if (!e || e.reversed) return undefined;
    e.reversed = true;
    this.changed();
    return { ...e };
  }

  lastActive(): Entry | undefined {
    for (let i = this.entries.length - 1; i >= 0; i--) {
      const e = this.entries[i];
      if (e && !e.reversed) return e;
    }
    return undefined;
  }

  balance(customerId: string): number {
    let b = 0;
    for (const e of this.entries) {
      if (e.reversed || e.customer.id !== customerId) continue;
      b += e.kind === 'credit' ? e.amount : -e.amount;
    }
    return b;
  }

  totals(day = ymd(this.now())) {
    let credit = 0;
    let payment = 0;
    for (const e of this.entries) {
      if (e.reversed || e.date !== day) continue;
      if (e.kind === 'credit') credit += e.amount;
      else if (e.kind === 'payment') payment += e.amount; // a write-off is not a payment
    }
    return { credit_today: credit, payment_today: payment };
  }

  ledgerView(limit = 50, opts: { order?: 'date'; customerId?: string } = {}): LedgerView {
    let all = [...this.entries].reverse();
    if (opts.customerId) all = all.filter((e) => e.customer.id === opts.customerId);
    if (opts.order === 'date') all.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
    const list = all.slice(0, limit).map((e) => ({ ...e, customer: { ...e.customer } }));
    return { entries: list, totals: this.totals() };
  }

  customerSummaries(): { customers: Customer[] } {
    return {
      customers: [...this.customers.values()].map((c) => ({
        id: c.id,
        display: c.display,
        tags: [...c.tags],
        balance: this.balance(c.id),
        reminders_opt_in: c.reminders_opt_in,
        phone_hint: c.phone ? `•••• ${c.phone.slice(-4)}` : null,
      })),
    };
  }

  private fail(status: number, detail: string): never {
    throw new ApiError('mock', status, detail);
  }

  private checkAmount(amount: unknown): number {
    if (typeof amount !== 'number' || !Number.isInteger(amount) || amount < 1 || amount > MAX_AMOUNT) this.fail(400, 'bad_amount');
    return amount as number;
  }

  private checkDate(date: unknown): string {
    const today = ymd(this.now());
    if (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date) || date > today || date < '2000-01-01') this.fail(400, 'bad_date');
    return date as string;
  }

  private balanceOf(c: MockCustomer) {
    return { customer_id: c.id, display: c.display, balance: this.balance(c.id) };
  }

  private snapshot(e: Entry): Entry {
    return { ...e, customer: { ...e.customer } };
  }

  /** POST /api/entries: one entry written by hand, optionally guarded by the balance the screen showed. */
  addManual(body: NewEntryBody): EntryChange {
    const c = this.customers.get(body.customer_id);
    if (!c) this.fail(404, 'unknown_customer');
    if (!KINDS.includes(body.kind)) this.fail(400, 'bad_kind');
    const amount = this.checkAmount(body.amount);
    const date = body.date === undefined ? ymd(this.now()) : this.checkDate(body.date);
    if (body.if_balance !== undefined && body.if_balance !== this.balance(body.customer_id)) this.fail(409, 'balance_changed');
    const e = this.push(body.kind, c as MockCustomer, amount, date, null);
    return { ok: true, entries: [this.snapshot(e)], balances: [this.balanceOf(c as MockCustomer)] };
  }

  private push(kind: Entry['kind'], c: MockCustomer, amount: number, date: string, replaces: Entry['id'] | null): Entry {
    const when = this.now();
    const e: Entry = {
      id: this.nextId++,
      kind,
      customer: { id: c.id, display: c.display, tags: [...c.tags] },
      amount,
      date,
      ts: when.toISOString(),
      reversed: false,
      reversal_of: null,
      replaces,
    };
    this.entries.push(e);
    this.changed();
    return e;
  }

  private activeEntry(id: Entry['id']): Entry {
    const e = this.entries.find((x) => String(x.id) === String(id));
    if (!e) this.fail(404, 'unknown_entry');
    if ((e as Entry).reversed || (e as Entry).reversal_of != null) this.fail(409, 'not_active');
    return e as Entry;
  }

  /** POST /api/entries/{id}/amend: the entry is reversed and a changed copy is saved. */
  amend(id: Entry['id'], body: AmendBody): EntryChange {
    const old = this.activeEntry(id);
    const kind = body.kind ?? old.kind;
    if (!KINDS.includes(kind)) this.fail(400, 'bad_kind');
    const amount = body.amount === undefined ? old.amount : this.checkAmount(body.amount);
    const date = body.date === undefined ? old.date : this.checkDate(body.date);
    const target = this.customers.get(body.customer_id ?? old.customer.id);
    if (!target) this.fail(404, 'unknown_customer');
    const t = target as MockCustomer;
    if (kind === old.kind && amount === old.amount && date === old.date && t.id === old.customer.id) this.fail(400, 'nothing_changed');
    const before = this.snapshot(old);
    old.reversed = true;
    const fresh = this.push(kind, t, amount, date, old.id);
    const touched = new Set([old.customer.id, t.id]);
    const balances = [...touched].flatMap((cid) => {
      const c = this.customers.get(cid);
      return c ? [this.balanceOf(c)] : [];
    });
    return { ok: true, entries: [{ ...before, reversed: true }, this.snapshot(fresh)], balances };
  }

  /** POST /api/entries/{id}/remove: the entry is reversed and stays visible. */
  removeEntry(id: Entry['id']): EntryChange {
    const old = this.activeEntry(id);
    old.reversed = true;
    this.changed();
    const c = this.customers.get(old.customer.id);
    return { ok: true, entries: [this.snapshot(old)], balances: c ? [this.balanceOf(c)] : [] };
  }

  /** POST /api/customers/{id}: name, tags and phone number (a name another customer has is refused). */
  updateCustomer(id: string, patch: CustomerPatch): Customer {
    const c = this.customers.get(id);
    if (!c) this.fail(404, 'unknown_customer');
    const cust = c as MockCustomer;
    if (patch.display !== undefined) {
      const name = patch.display.trim().replace(/\s+/g, ' ');
      if (name.length < 2 || name.length > 40) this.fail(400, 'bad_name');
      const key = name.toLowerCase();
      for (const other of this.customers.values()) {
        if (other.id !== id && other.display.toLowerCase() === key) this.fail(409, 'name_taken');
      }
      cust.display = name;
    }
    if (patch.tags !== undefined) {
      if (patch.tags.length > 3 || patch.tags.some((t) => !t.trim() || t.length > 24)) this.fail(400, 'bad_tag');
      cust.tags = patch.tags.map((t) => t.trim().toLowerCase());
    }
    if (patch.phone !== undefined) {
      if (patch.phone !== null && !/^[6-9]\d{9}$/.test(patch.phone)) this.fail(400, 'bad_phone');
      cust.phone = patch.phone;
    }
    for (const e of this.entries) {
      if (e.customer.id === id) e.customer = { id, display: cust.display, tags: [...cust.tags] };
    }
    this.changed();
    return this.customerSummaries().customers.find((x) => x.id === id) as Customer;
  }

  topDues(n = 3): { display: string; balance: number }[] {
    return this.customerSummaries()
      .customers.filter((c) => c.balance > 0)
      .sort((a, b) => b.balance - a.balance)
      .slice(0, n);
  }

  setOptIn(id: string, optIn: boolean): boolean {
    const c = this.customers.get(id);
    if (!c) return false;
    c.reminders_opt_in = optIn;
    this.changed();
    return true;
  }

  reminders(): { reminders: Reminder[] } {
    return { reminders: [] };
  }
}

/** The single mock ledger shared by the mock session and the mock REST calls. */
export const mockLedger = new MockLedger();
