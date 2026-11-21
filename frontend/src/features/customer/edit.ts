// Pure logic for editing on the customer screen (docs/CONTRACT.md section 3.6): amount and date checks, the entry
// that writes a balance difference, the fields an amend changes, the customer patch, and the label of a server
// error code. Tested in edit.test.ts.
import type { AmendBody, CustomerPatch } from '../../services/api';
import { ApiError } from '../../services/api';
import type { Entry, EntryKind } from '../../services/session/types';
import type { CustomerLabelKey } from './labels';
import { normalizePhone } from './logic';

/** The largest whole-rupee amount the server accepts (MAX_AMOUNT). */
export const MAX_AMOUNT = 9_999_999;
/** The earliest entry date the server accepts. */
export const MIN_DATE = '2000-01-01';

/**
 * Whole rupees from what was typed: digits, with commas, spaces and a leading ₹ allowed. Null when it is not a
 * whole number in [min, MAX_AMOUNT]. `min` is 1 for an entry and 0 for a balance.
 */
export function parseAmount(input: string, min = 1): number | null {
  const t = input.trim().replace(/^(₹|rs\.?|inr)\s*/i, '').replace(/[,\s]/g, '');
  if (!/^\d{1,8}$/.test(t)) return null;
  const n = Number(t);
  return n >= min && n <= MAX_AMOUNT ? n : null;
}

export type DateProblem = 'bad' | 'future' | 'old';

/** Why a YYYY-MM-DD date cannot be used (not a real date, after `today`, before 2000-01-01), or null. */
export function dateProblem(date: string, today: string): DateProblem | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!m) return 'bad';
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const real = new Date(Date.UTC(y, mo - 1, d));
  if (real.getUTCFullYear() !== y || real.getUTCMonth() !== mo - 1 || real.getUTCDate() !== d) return 'bad';
  if (date > today) return 'future';
  if (date < MIN_DATE) return 'old';
  return null;
}

export type FormError = CustomerLabelKey;

export type LowerKind = Extract<EntryKind, 'payment' | 'writeoff'>;

export type BalanceChange =
  | { type: 'invalid' }
  /** Nothing to save: the figure typed is the balance shown. */
  | { type: 'same' }
  /** Higher: one `credit` entry of `amount`. */
  | { type: 'up'; amount: number }
  /** Lower: one entry of `amount`, `payment` or `writeoff` as the shopkeeper chooses. */
  | { type: 'down'; amount: number }
  /** The difference is more than one entry can hold. */
  | { type: 'toolarge' };

/** What changing the balance from `current` to what was typed means. A negative balance (advance) is a number too. */
export function balanceChange(current: number, input: string): BalanceChange {
  const target = parseAmount(input, 0);
  if (target === null) return { type: 'invalid' };
  if (target === current) return { type: 'same' };
  const amount = Math.abs(target - current);
  if (amount > MAX_AMOUNT) return { type: 'toolarge' };
  return target > current ? { type: 'up', amount } : { type: 'down', amount };
}

/** The entry that writes a balance change, or null while nothing can be saved (same balance, no choice yet). */
export function balanceEntry(change: BalanceChange, lower: LowerKind | null): { kind: EntryKind; amount: number } | null {
  if (change.type === 'up') return { kind: 'credit', amount: change.amount };
  if (change.type === 'down' && lower) return { kind: lower, amount: change.amount };
  return null;
}

export interface EntryFields {
  kind: EntryKind;
  amount: number;
  date: string;
  customerId: string;
}

/** Only the fields that differ from the entry, as the amend body; null when nothing differs. */
export function amendBody(original: EntryFields, next: EntryFields): AmendBody | null {
  const body: AmendBody = {};
  if (next.kind !== original.kind) body.kind = next.kind;
  if (next.amount !== original.amount) body.amount = next.amount;
  if (next.date !== original.date) body.date = next.date;
  if (next.customerId !== original.customerId) body.customer_id = next.customerId;
  return Object.keys(body).length ? body : null;
}

/** The fields of an entry row, as the form edits them. */
export function entryFields(e: Pick<Entry, 'kind' | 'amount' | 'date' | 'customer'>): EntryFields {
  return { kind: e.kind, amount: e.amount, date: e.date.slice(0, 10), customerId: e.customer.id };
}

/** Ids made on the page for an entry the server has not confirmed yet. They are never sent to the server. */
export function isTempId(id: Entry['id']): boolean {
  return typeof id === 'string' && id.startsWith('tmp-');
}

/**
 * A history row can be edited while it is active: not removed or changed already, not a reversal row, and
 * confirmed by the server (a row still waiting for its server id cannot be amended yet).
 */
export function isEditable(e: Pick<Entry, 'id' | 'reversed' | 'reversal_of'>): boolean {
  return !e.reversed && (e.reversal_of === null || e.reversal_of === undefined) && !isTempId(e.id);
}

const NAME_CHARS = /^[\p{L}\p{M} .'-]+$/u;

/** Names and tags as typed: trimmed, single spaces. */
export function tidy(s: string): string {
  return s.trim().replace(/\s+/g, ' ');
}

/** Tags from one comma-separated field: tidy, lower case, no empties, no repeats. */
export function parseTags(input: string): string[] {
  const out: string[] = [];
  for (const part of input.split(/[,;]/)) {
    const t = tidy(part).toLowerCase();
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

export interface CustomerForm {
  name: string;
  tags: string;
  phone: string;
  clearPhone: boolean;
}

export type CustomerPatchResult = { patch: CustomerPatch | null; error: FormError | null };

/**
 * The patch for POST /api/customers/{id}: only what changed. `error` names the first field that is not valid;
 * `patch` is null while nothing changed (or an error is shown).
 */
export function customerPatch(
  original: { display: string; tags: readonly string[]; phone_hint?: string | null },
  form: CustomerForm,
): CustomerPatchResult {
  const patch: CustomerPatch = {};
  const name = tidy(form.name);
  if (name.length < 2 || name.length > 40 || !NAME_CHARS.test(name)) return { patch: null, error: 'errBadName' };
  if (name !== tidy(original.display)) patch.display = name;

  const tags = parseTags(form.tags);
  if (tags.length > 3 || tags.some((t) => t.length > 24 || !NAME_CHARS.test(t))) return { patch: null, error: 'errBadTag' };
  const before = original.tags.map((t) => tidy(t).toLowerCase());
  if (tags.join('\n') !== before.join('\n')) patch.tags = tags;

  if (form.clearPhone) {
    if (original.phone_hint) patch.phone = null;
  } else if (form.phone.trim()) {
    const phone = normalizePhone(form.phone);
    if (!phone) return { patch: null, error: 'errBadPhone' };
    patch.phone = phone;
  }
  return { patch: Object.keys(patch).length ? patch : null, error: null };
}

const ERROR_KEYS: Record<string, FormError> = {
  bad_kind: 'errBadKind',
  bad_amount: 'errBadAmount',
  bad_date: 'errBadDate',
  nothing_changed: 'errNothingChanged',
  bad_name: 'errBadName',
  bad_tag: 'errBadTag',
  bad_phone: 'errBadPhone',
  unknown_entry: 'errUnknownEntry',
  unknown_customer: 'errUnknownCustomer',
  not_active: 'errNotActive',
  name_taken: 'errNameTaken',
  balance_changed: 'errBalanceChanged',
};

/** The label for a failed save: the server's `detail` code when it has one here, else the general line. */
export function errorKey(error: unknown): FormError {
  if (error instanceof ApiError && error.detail && error.detail in ERROR_KEYS) return ERROR_KEYS[error.detail] as FormError;
  return 'errGeneric';
}

/** Codes after which the screen's figures were out of date: refresh them whatever the sheet does next. */
export function isStale(error: unknown): boolean {
  return error instanceof ApiError && (error.detail === 'balance_changed' || error.detail === 'not_active' || error.detail === 'unknown_entry');
}
