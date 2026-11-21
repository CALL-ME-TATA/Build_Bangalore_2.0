// Pure logic for the Customer detail screen: the timeline grouped by date, the pairing of a removed entry with
// what replaced it, the time line of each entry, and whether a reminder can be sent. Tested in logic.test.ts.
import type { Customer, Reminder } from '../../services/api';
import type { Entry } from '../../services/session/types';
import { clockTime, dayLabel, ymd } from '../../lib/format';
import type { Lang } from '../../i18n';
import { newerFirst } from '../khata/logic';
import { customerLabels, type CustomerLabelKey } from './labels';

export interface TimelineItem {
  entry: Entry;
  /**
   * A removed entry shown struck through just above this one. When the entry carries `replaces`, it is paired with
   * the entry that id names (even on another date). Only when `replaces` is null or absent (an older server) is it
   * paired by position: with the next entry of the same customer recorded after it, when that one is active and
   * dated the same day. A removed entry with no partner (an undo) is listed on its own. Either way nothing is hidden.
   */
  replaced?: Entry;
}

export interface TimelineGroup {
  /** Effective date, YYYY-MM-DD. */
  date: string;
  /** "Aaj", "Kal · 20 Nov", "19 Nov". */
  label: string;
  items: TimelineItem[];
}

const shortDate = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' });
const shortDateYear = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

function parseYmd(s: string): Date {
  const [y, m, d] = s.slice(0, 10).split('-').map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

/** Group heading: "Aaj" today, "Kal · 20 Nov" yesterday, otherwise "19 Nov" (with the year if not this year). */
export function groupLabel(date: string, now: Date, lang: Lang): string {
  const today = ymd(now);
  const rel = dayLabel(date, today, lang);
  const d = parseYmd(date);
  const plain = d.getFullYear() === now.getFullYear() ? shortDate.format(d) : shortDateYear.format(d);
  const yesterday = ymd(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  if (date.slice(0, 10) === today) return rel;
  if (date.slice(0, 10) === yesterday) return `${rel} · ${plain}`;
  return plain;
}

function entryDate(e: Entry): string {
  return /^\d{4}-\d{2}-\d{2}/.test(e.date) ? e.date.slice(0, 10) : ymd(new Date(Date.parse(e.ts) || 0));
}

/**
 * Pairs by `replaces`: replacer -> the entry it corrected, when that entry is in `mine`. Newest first, so in a chain
 * (a corrected to b, b to c) c takes b and b stays hidden under c; a is then listed on its own, never lost.
 */
function pairById(mine: readonly Entry[]): Map<Entry, Entry> {
  const byId = new Map<string, Entry>(mine.map((e) => [String(e.id), e]));
  const pairs = new Map<Entry, Entry>();
  const hidden = new Set<Entry>();
  for (const e of mine) {
    if (e.replaces === null || e.replaces === undefined || hidden.has(e)) continue;
    const target = byId.get(String(e.replaces));
    if (!target || target === e || hidden.has(target)) continue;
    pairs.set(e, target);
    hidden.add(target);
  }
  return pairs;
}

/**
 * One customer's entries grouped by effective date, newest date first, newest entry first in each group. A
 * correction sits with the entry it replaced (by `replaces`; by position when that is null or absent).
 */
export function customerTimeline(entries: readonly Entry[], customerId: string, now: Date, lang: Lang): TimelineGroup[] {
  const mine = entries.filter((e) => e.customer.id === customerId).sort(newerFirst);
  const pairs = pairById(mine);
  const hidden = new Set<Entry>(pairs.values());
  // Entries some entry (of any customer) names in `replaces`: never paired by position.
  const named = new Set<string>();
  for (const e of entries) if (e.replaces !== null && e.replaces !== undefined) named.add(String(e.replaces));

  const byDate = new Map<string, Entry[]>();
  for (const e of mine) {
    if (hidden.has(e)) continue;
    const d = entryDate(e);
    const list = byDate.get(d);
    if (list) list.push(e);
    else byDate.set(d, [e]);
  }
  const dates = [...byDate.keys()].sort((a, b) => (a < b ? 1 : a > b ? -1 : 0));
  return dates.map((date) => {
    const list = byDate.get(date) ?? [];
    const items: TimelineItem[] = [];
    const used = new Set<Entry>();
    // Newest first: the entry just before a removed one in this list is the one recorded right after it.
    for (let i = 0; i < list.length; i++) {
      const e = list[i];
      if (!e || used.has(e)) continue;
      const byReplaces = pairs.get(e);
      const older = list[i + 1];
      if (byReplaces) {
        items.push({ entry: e, replaced: byReplaces });
      } else if (
        (e.replaces === null || e.replaces === undefined) &&
        !e.reversed &&
        older &&
        older.reversed &&
        !used.has(older) &&
        !named.has(String(older.id))
      ) {
        items.push({ entry: e, replaced: older });
        used.add(older);
      } else {
        items.push({ entry: e });
      }
      used.add(e);
    }
    return { date, label: groupLabel(date, now, lang), items };
  });
}

/**
 * The time shown on a timeline row: "11:42" when the entry was recorded on its own date, otherwise when it was
 * written ("likha Aaj, 11:42") for entries said about another day ("kal 200 diya tha").
 */
export function entryTime(entry: Pick<Entry, 'date' | 'ts'>, now: Date, lang: Lang): string {
  const ms = Date.parse(entry.ts);
  if (Number.isNaN(ms)) return '';
  const recordedDay = ymd(new Date(ms));
  const time = clockTime(entry.ts);
  if (recordedDay === entry.date.slice(0, 10)) return time;
  return `${customerLabels(lang).recorded} ${dayLabel(recordedDay, ymd(now), lang)}, ${time}`;
}

/** True when the loaded entries may not reach back to this customer's first entry. */
export function historyMayBeCut(loaded: number, limit: number): boolean {
  return loaded >= limit;
}

export interface ReminderAvailability {
  enabled: boolean;
  /** Visible reason when disabled. */
  reason: CustomerLabelKey | null;
}

/** "Reminder bhejein" needs the customer's opt-in and something owed (the server queues only those). */
export function reminderAvailability(c: Pick<Customer, 'reminders_opt_in' | 'balance'>): ReminderAvailability {
  if (!c.reminders_opt_in) return { enabled: false, reason: 'reasonNotOptedIn' };
  if (c.balance <= 0) return { enabled: false, reason: 'reasonNothingDue' };
  return { enabled: true, reason: null };
}

/** The newest pending reminder for this customer, if any. */
export function reminderFor(reminders: readonly Reminder[], customerId: string): Reminder | null {
  let found: Reminder | null = null;
  for (const r of reminders) {
    if (r.customer.id !== customerId) continue;
    if (!found || Number(r.id) > Number(found.id)) found = r;
  }
  return found;
}

/** Digits of a phone number if it looks like an Indian mobile (10 digits, optionally with 91 / +91 / 0). */
export function normalizePhone(input: string): string | null {
  let d = input.replace(/\D/g, '');
  if (d.length === 11 && d.startsWith('0')) d = d.slice(1);
  if (d.length === 12 && d.startsWith('91')) d = d.slice(2);
  return /^[6-9]\d{9}$/.test(d) ? d : null;
}

/** Only https://wa.me/ links from the server are offered as a link. */
export function safeWaLink(link: string | null | undefined): string | null {
  if (!link) return null;
  try {
    const u = new URL(link);
    return u.protocol === 'https:' && (u.hostname === 'wa.me' || u.hostname === 'api.whatsapp.com') ? u.href : null;
  } catch {
    return null;
  }
}
