// Typed REST calls (docs/CONTRACT.md section 3 and server/app/main.py). All amounts are whole rupees.
// The access code from `?code=` in the page URL is sent as the X-Access-Code header.
// In mock mode (see ./session/mode.ts) the same calls are answered by the in-memory mock ledger.
import type { BalanceInfo, Entry, EntryKind } from './session/types';
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
  /** Last four digits of the stored phone number ("•••• 3210"), or null. The full number is never sent. */
  phone_hint?: string | null;
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
  /** The server's error code (`detail`, e.g. `name_taken`), or null when the body had none. */
  detail: string | null;
  constructor(path: string, status: number, detail: string | null = null) {
    super(`${path}: ${status}`);
    this.status = status;
    this.detail = detail;
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
  if (!res.ok) {
    let detail: string | null = null;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // No JSON body: the status alone is the error.
    }
    throw new ApiError(path, res.status, detail);
  }
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

/**
 * POST /api/reminders/queue: queue one reminder per opted-in customer who owes money. Returns the new ids, and
 * `quietHours: true` outside sending hours (09:00 to 20:00 shop time), when the server queues nothing.
 */
export async function queueReminders(): Promise<{ queued: number[]; quietHours: boolean }> {
  if (isMock()) return { queued: [], quietHours: false };
  const d = await request<{ queued?: number[]; quiet_hours?: boolean }>('/api/reminders/queue', { method: 'POST' });
  return { queued: d.queued ?? [], quietHours: d.quiet_hours === true };
}

/**
 * POST /api/customers/{id}/remind: queue a reminder for this one customer. `sms`: the server sends it as an SMS too
 * (Twilio through Kafka) after its own checks. `quietHours`: outside 09:00 to 20:00 nothing is queued.
 */
export async function remindCustomer(customerId: string): Promise<{ queued: number | null; quietHours: boolean; sms: boolean }> {
  if (isMock()) return { queued: null, quietHours: false, sms: false };
  const d = await request<{ queued?: number | null; quiet_hours?: boolean; sms?: boolean }>(
    `/api/customers/${encodeURIComponent(customerId)}/remind`,
    { method: 'POST' },
  );
  return { queued: d.queued ?? null, quietHours: d.quiet_hours === true, sms: d.sms === true };
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

/** The answer of the entry calls (contract 3.6): the entries touched and the balances after them. */
export interface EntryChange {
  ok: boolean;
  entries: Entry[];
  balances: BalanceInfo[];
}

export interface NewEntryBody {
  customer_id: string;
  kind: EntryKind;
  amount: number;
  /** YYYY-MM-DD shop day; the server uses today when absent. */
  date?: string;
  /** Refused with 409 `balance_changed` when the customer's balance is no longer this figure. */
  if_balance?: number;
}

export interface AmendBody {
  kind?: EntryKind;
  amount?: number;
  date?: string;
  customer_id?: string;
}

export interface CustomerPatch {
  display?: string;
  tags?: string[];
  /** A normalised 10-digit number, or null to clear it. */
  phone?: string | null;
}

function jsonPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  });
}

/** POST /api/entries: one entry written by hand. */
export async function addEntry(body: NewEntryBody): Promise<EntryChange> {
  if (isMock()) return (await mock()).addManual(body);
  return jsonPost<EntryChange>('/api/entries', body);
}

/** POST /api/entries/{id}/amend: reverses the entry and saves the changed copy. Only changed fields are sent. */
export async function amendEntry(id: Entry['id'], body: AmendBody): Promise<EntryChange> {
  if (isMock()) return (await mock()).amend(id, body);
  return jsonPost<EntryChange>(`/api/entries/${encodeURIComponent(String(id))}/amend`, body);
}

/** POST /api/entries/{id}/remove: reverses that one entry; it stays visible, struck through. */
export async function removeEntry(id: Entry['id']): Promise<EntryChange> {
  if (isMock()) return (await mock()).removeEntry(id);
  return jsonPost<EntryChange>(`/api/entries/${encodeURIComponent(String(id))}/remove`);
}

/** POST /api/customers/{id}: renames the customer, replaces the tags, sets or clears the phone number. */
export async function updateCustomer(id: string, patch: CustomerPatch): Promise<Customer> {
  if (isMock()) return (await mock()).updateCustomer(id, patch);
  const d = await jsonPost<{ customer: Customer }>(`/api/customers/${encodeURIComponent(id)}`, patch);
  return d.customer;
}
