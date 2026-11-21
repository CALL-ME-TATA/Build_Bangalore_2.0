// Pure numbers for the Hisaab screen, computed in the browser from GET /api/ledger?limit=500 and
// GET /api/customers. Reversed entries never count. Dates are the entries' effective dates (YYYY-MM-DD), so
// "kal 200 diya tha" said today counts for yesterday.
import type { Lang } from '../../i18n';
import type { Customer } from '../../services/api';
import type { Entry } from '../../services/session/types';
import { dayLabel, ymd } from '../../lib/format';
import { HISAAB_LABELS } from './labels';

export type Period = 'today' | 'week';

export const LEDGER_LIMIT = 500;

export interface Bucket {
  key: string;
  label: string;
  credit: number;
  payment: number;
}

export interface Insights {
  credit: number;
  payment: number;
  /** Active entries in the period. */
  count: number;
  /** Today: four parts of the day. Week: seven days, oldest first. */
  buckets: Bucket[];
  /** The ledger hit the limit and its oldest entry is inside the period, so older ones may be missing. */
  truncated: boolean;
}

export function activeEntries(entries: readonly Entry[]): Entry[] {
  return entries.filter((e) => !e.reversed);
}

/** The seven dates ending at `today` (YYYY-MM-DD), oldest first. */
export function weekDays(today: Date): string[] {
  const out: string[] = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
    out.push(ymd(d));
  }
  return out;
}

/** Part of the day of a timestamp in local time: 0 morning (< 12), 1 afternoon (< 16), 2 evening (< 20), 3 night. */
export function partOfDay(ts: string): 0 | 1 | 2 | 3 {
  const ms = Date.parse(ts);
  const h = Number.isNaN(ms) ? 9 : new Date(ms).getHours();
  if (h < 12) return 0;
  if (h < 16) return 1;
  if (h < 20) return 2;
  return 3;
}

export function computeInsights(entries: readonly Entry[], period: Period, now: Date, lang: Lang, limit = LEDGER_LIMIT): Insights {
  const L = HISAAB_LABELS[lang];
  const today = ymd(now);
  const days = period === 'today' ? [today] : weekDays(now);
  const first = days[0] ?? today;
  const inPeriod = activeEntries(entries).filter((e) => days.includes(e.date.slice(0, 10)));

  let buckets: Bucket[];
  if (period === 'today') {
    buckets = [L.morning, L.afternoon, L.evening, L.night].map((label, i) => ({ key: `p${i}`, label, credit: 0, payment: 0 }));
    for (const e of inPeriod) {
      const b = buckets[partOfDay(e.ts)];
      if (b && e.kind !== 'writeoff') b[e.kind] += e.amount; // a write-off is neither udhaar nor jama
    }
  } else {
    buckets = days.map((d) => ({ key: d, label: dayLabel(d, today, lang), credit: 0, payment: 0 }));
    for (const e of inPeriod) {
      const b = buckets[days.indexOf(e.date.slice(0, 10))];
      if (b && e.kind !== 'writeoff') b[e.kind] += e.amount;
    }
  }

  let credit = 0;
  let payment = 0;
  for (const e of inPeriod) {
    if (e.kind === 'credit') credit += e.amount;
    else if (e.kind === 'payment') payment += e.amount;
  }

  const oldest = entries.reduce<string | null>((min, e) => (min === null || e.date < min ? e.date : min), null);
  const truncated = entries.length >= limit && oldest !== null && oldest.slice(0, 10) >= first;

  return { credit, payment, count: inPeriod.length, buckets, truncated };
}

/** The `n` customers who owe the most (positive balance), highest first; ties by name. */
export function topDues(customers: readonly Customer[], n = 5): Customer[] {
  return customers
    .filter((c) => c.balance > 0)
    .sort((a, b) => b.balance - a.balance || a.display.localeCompare(b.display))
    .slice(0, n);
}

/** Sum of what customers owe (advances are not netted off) and how many owe something. */
export function duesTotal(customers: readonly Customer[]): { total: number; count: number } {
  let total = 0;
  let count = 0;
  for (const c of customers) {
    if (c.balance > 0) {
      total += c.balance;
      count += 1;
    }
  }
  return { total, count };
}

/** Largest bar value, at least 1 so widths never divide by zero. */
export function chartMax(buckets: readonly Bucket[]): number {
  return Math.max(1, ...buckets.map((b) => Math.max(b.credit, b.payment)));
}

/** Bar length in percent of the track; a non-zero value is never shorter than 1.5% so it stays visible. */
export function barPercent(value: number, max: number): number {
  if (value <= 0 || max <= 0) return 0;
  return Math.max(1.5, Math.min(100, (value / max) * 100));
}

const HI_WEEKDAYS = ['Ravivaar', 'Somvaar', 'Mangalvaar', 'Budhvaar', 'Guruvaar', 'Shukravaar', 'Shanivaar'];
const dayMonth = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'long' });
const enWeekday = new Intl.DateTimeFormat('en-IN', { weekday: 'long' });

/** The line under the title, as on the Khata board: "Shanivaar, 21 November" / "Saturday, 21 November". */
export function dateLine(d: Date, lang: Lang): string {
  const weekday = lang === 'en' ? enWeekday.format(d) : HI_WEEKDAYS[d.getDay()];
  return `${weekday}, ${dayMonth.format(d)}`;
}
