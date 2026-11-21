// In-memory ledger used by the mock session and the mock REST calls, so the whole app can be built and
// demonstrated without a backend. Synthetic data only. Shapes match docs/CONTRACT.md section 3.
import type { Entry } from '../session/types';
import type { Customer, LedgerView, Reminder } from '../api';

interface MockCustomer {
  id: string;
  display: string;
  tags: string[];
  reminders_opt_in: boolean;
}

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
    const c: MockCustomer = { id: `c${this.customers.size + 1}`, display: name, tags, reminders_opt_in: false };
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
      })),
    };
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
