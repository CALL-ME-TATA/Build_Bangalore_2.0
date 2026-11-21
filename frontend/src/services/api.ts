// Typed REST calls (docs/CONTRACT.md section 3 and server/app/main.py). All amounts are whole rupees.
// The access code from `?code=` in the page URL is sent as the X-Access-Code header.
// In mock mode (see ./session/mode.ts) the same calls are answered by the in-memory mock ledger.
import type { Entry } from './session/types';
import { accessCode } from './accessCode';
import { sessionMode } from './session/mode';

export interface LedgerView {
  entries: Entry[];
  totals: { credit_today: number; payment_today: number };
}

export interface Customer {
  id: string;
  display: string;
  tags: string[];
  /** Positive: the customer owes the shop. Negative: paid in advance. */
  balance: number;
  reminders_opt_in: boolean;
}

export interface Reminder {
  id: number;
  customer: { id: string; display: string };
  amount: number;
  message: string;
  /** wa.me link, or null when no phone number is stored. */
  wa_link: string | null;
  status: string;
}

export class ApiError extends Error {
  status: number;
  constructor(path: string, status: number) {
    super(`${path}: ${status}`);
    this.status = status;
  }
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const code = accessCode();
  return code ? { 'X-Access-Code': code, ...extra } : extra;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    cache: 'no-store',
    ...init,
    headers: headers((init.headers as Record<string, string>) ?? {}),
  });
  if (!res.ok) throw new ApiError(path, res.status);
  return (await res.json()) as T;
}

async function mock() {
  return (await import('./mock/ledger')).mockLedger;
}

const isMock = () => sessionMode() === 'mock';

export interface LedgerOptions {
  /** 'date': by entry date, newest first (a back-dated entry sits under its own day). Default: creation order. */
  order?: 'date';
  /** Only this customer's entries. */
  customerId?: string;
}

/** The query string of GET /api/ledger. */
export function ledgerPath(limit: number, opts: LedgerOptions = {}): string {
  const q = new URLSearchParams({ limit: String(limit) });
  if (opts.order) q.set('order', opts.order);
  if (opts.customerId) q.set('customer_id', opts.customerId);
  return `/api/ledger?${q.toString()}`;
}

/** GET /api/ledger?limit=N[&order=date][&customer_id=X]: newest entries first, and today's totals. */
export async function getLedger(limit = 50, opts: LedgerOptions = {}): Promise<LedgerView> {
  if (isMock()) return (await mock()).ledgerView(limit, opts);
  const d = await request<Partial<LedgerView>>(ledgerPath(limit, opts));
  return { entries: d.entries ?? [], totals: d.totals ?? { credit_today: 0, payment_today: 0 } };
}

/** GET /api/customers: every customer with balance and reminder opt-in. */
export async function getCustomers(): Promise<Customer[]> {
  if (isMock()) return (await mock()).customerSummaries().customers;
  const d = await request<{ customers?: Customer[] }>('/api/customers');
  return d.customers ?? [];
}

/** GET /api/reminders: pending reminder outbox rows (opted-in customers only). */
export async function getReminders(): Promise<Reminder[]> {
  if (isMock()) return (await mock()).reminders().reminders;
  const d = await request<{ reminders?: Reminder[] }>('/api/reminders');
  return d.reminders ?? [];
}

/** POST /api/reminders/queue: queue one reminder per opted-in customer who owes money. Returns the new ids. */
export async function queueReminders(): Promise<number[]> {
  if (isMock()) return [];
  const d = await request<{ queued?: number[] }>('/api/reminders/queue', { method: 'POST' });
  return d.queued ?? [];
}

/** POST /api/customers/{id}/reminders: set the reminder opt-in (and optionally the phone number). */
export async function setReminderOptIn(customerId: string, optIn: boolean, phone?: string | null): Promise<void> {
  if (isMock()) {
    (await mock()).setOptIn(customerId, optIn);
    return;
  }
  const body: { opt_in: boolean; phone?: string | null } = { opt_in: optIn };
  if (phone !== undefined) body.phone = phone;
  await request<{ ok: boolean }>(`/api/customers/${encodeURIComponent(customerId)}/reminders`, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  });
}
