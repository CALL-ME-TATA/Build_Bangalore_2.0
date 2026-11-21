// Pure logic for the Khata screen: balance state words, last activity per customer, sorting, filters and search,
// the "Kul baaki" summary and the date line under the title. No React, no I/O; tested in logic.test.ts.
import type { Customer } from '../../services/api';
import type { Entry } from '../../services/session/types';
import { ymd } from '../../lib/format';
import type { Lang } from '../../i18n';
import { khataLabels, type KhataLabelKey } from './labels';

/** What a balance means for the shopkeeper. */
export type BalanceState = 'due' | 'advance' | 'clear';

/** Positive: the customer owes the shop. Negative: paid in advance. Zero: settled. */
export function balanceState(balance: number): BalanceState {
  const b = Math.round(Number(balance) || 0);
  if (b > 0) return 'due';
  if (b < 0) return 'advance';
  return 'clear';
}

const STATE_KEY: Record<BalanceState, KhataLabelKey> = { due: 'stateDue', advance: 'stateAdvance', clear: 'stateClear' };

/** "baaki" / "advance jama" / "hisaab saaf" (or the English words). */
export function balanceWord(balance: number, lang: Lang): string {
  return khataLabels(lang)[STATE_KEY[balanceState(balance)]];
}

function tsValue(e: Pick<Entry, 'ts'>): number {
  const v = Date.parse(e.ts);
  return Number.isNaN(v) ? 0 : v;
}

function idValue(e: Pick<Entry, 'id'>): number {
  const v = Number(e.id);
  return Number.isFinite(v) ? v : 0;
}

/** Newest first: by recorded time, then by id (ids increase with every event). */
export function newerFirst(a: Pick<Entry, 'ts' | 'id'>, b: Pick<Entry, 'ts' | 'id'>): number {
  return tsValue(b) - tsValue(a) || idValue(b) - idValue(a);
}

/**
 * The latest entry of every customer in `entries`. An active entry wins over a reversed one; a customer whose
 * only entries were all removed still shows the latest removed one (history is never hidden).
 */
export function lastActivity(entries: readonly Entry[]): Map<string, Entry> {
  const sorted = [...entries].sort(newerFirst);
  const active = new Map<string, Entry>();
  const any = new Map<string, Entry>();
  for (const e of sorted) {
    const id = e.customer.id;
    if (!any.has(id)) any.set(id, e);
    if (!e.reversed && !active.has(id)) active.set(id, e);
  }
  for (const [id, e] of any) if (!active.has(id)) active.set(id, e);
  return active;
}

/** Customer ids with any entry recorded today or dated today. */
export function activeToday(entries: readonly Entry[], now: Date = new Date()): Set<string> {
  const today = ymd(now);
  const out = new Set<string>();
  for (const e of entries) {
    const recorded = Date.parse(e.ts);
    const recordedToday = !Number.isNaN(recorded) && ymd(new Date(recorded)) === today;
    if (e.date.slice(0, 10) === today || recordedToday) out.add(e.customer.id);
  }
  return out;
}

/**
 * List order: the most recently active customers first; customers with no entry in the loaded window follow,
 * the largest dues first, then by name.
 */
export function sortCustomers(customers: readonly Customer[], last: Map<string, Entry>): Customer[] {
  return [...customers].sort((a, b) => {
    const ea = last.get(a.id);
    const eb = last.get(b.id);
    if (ea && eb) return newerFirst(ea, eb) || a.display.localeCompare(b.display);
    if (ea) return -1;
    if (eb) return 1;
    return b.balance - a.balance || a.display.localeCompare(b.display);
  });
}

/** Lower case, Latin accents removed, spaces collapsed. Devanagari and Kannada are kept as they are. */
export function normalizeSearch(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLocaleLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

/** True when every word of the query appears in the name or a tag. An empty query matches everyone. */
export function matchesSearch(c: Pick<Customer, 'display' | 'tags'>, query: string): boolean {
  const q = normalizeSearch(query);
  if (!q) return true;
  const hay = normalizeSearch([c.display, ...c.tags].join(' '));
  return q.split(' ').every((word) => hay.includes(word));
}

export type KhataFilter = 'all' | 'due' | 'today';
export const FILTERS: readonly KhataFilter[] = ['all', 'due', 'today'];

/** Applies the chip filter and the search query; keeps the order of `customers`. */
export function filterCustomers(
  customers: readonly Customer[],
  opts: { filter: KhataFilter; query: string; today: Set<string> },
): Customer[] {
  return customers.filter((c) => {
    if (opts.filter === 'due' && c.balance <= 0) return false;
    if (opts.filter === 'today' && !opts.today.has(c.id)) return false;
    return matchesSearch(c, opts.query);
  });
}

/** "Kul baaki": the sum of what customers owe, and how many owe something. Advances are not netted off. */
export function duesSummary(customers: readonly Customer[]): { total: number; owing: number; count: number } {
  let total = 0;
  let owing = 0;
  for (const c of customers) {
    if (c.balance > 0) {
      total += c.balance;
      owing += 1;
    }
  }
  return { total, owing, count: customers.length };
}

const WEEKDAYS_HI = ['Ravivaar', 'Somvaar', 'Mangalvaar', 'Budhvaar', 'Guruvaar', 'Shukravaar', 'Shanivaar'];
const weekdayEn = new Intl.DateTimeFormat('en-IN', { weekday: 'long' });
const dayMonth = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'long' });

/** The date line under the title: "Shanivaar, 21 November" / "Saturday, 21 November". */
export function todayLine(now: Date, lang: Lang): string {
  const weekday = lang === 'en' ? weekdayEn.format(now) : (WEEKDAYS_HI[now.getDay()] ?? '');
  return `${weekday}, ${dayMonth.format(now)}`;
}

/** `lang` for a name written in Devanagari ("hi") or Kannada ("kn"); undefined for Latin script. */
export function scriptLang(text: string): 'hi' | 'kn' | undefined {
  if (/[ऀ-ॿ]/.test(text)) return 'hi';
  if (/[ಀ-೿]/.test(text)) return 'kn';
  return undefined;
}

/** First tag with a capital letter, as shown after the name ("Ramesh · Chai wale"). */
export function tagLabel(tags: readonly string[]): string {
  const tag = tags[0];
  return tag ? tag.charAt(0).toLocaleUpperCase() + tag.slice(1) : '';
}

function dayIndex(d: Date): number {
  return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86400000);
}

/**
 * The activity line of a row: "Aakhri entry aaj" / "kal" / "5 din pehle" (English: "Last entry today" ...),
 * from the time the latest entry was recorded. Null when the customer has no entry in the loaded window.
 */
export function lastEntryText(entry: Pick<Entry, 'ts'> | undefined, now: Date, lang: Lang): string | null {
  if (!entry) return null;
  const ms = Date.parse(entry.ts);
  if (Number.isNaN(ms)) return null;
  const K = khataLabels(lang);
  const days = Math.max(0, dayIndex(now) - dayIndex(new Date(ms)));
  const when = days === 0 ? K.whenToday : days === 1 ? K.whenYesterday : fillDays(K.whenDaysAgo, days);
  return `${K.lastEntry} ${when}`;
}

function fillDays(template: string, n: number): string {
  return template.replace('{n}', String(n));
}
