// Pure formatting helpers. Amounts are whole rupees (integers) everywhere in the API.
import { labels, type Lang } from '../i18n';

export const MINUS = '−'; // true minus sign, never a hyphen
export const NNBSP = ' '; // narrow no-break space between sign and ₹
export const RUPEE = '₹';

const grouping = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

/** Indian digit grouping without a symbol: 125000 -> "1,25,000". */
export function groupDigits(n: number): string {
  return grouping.format(Math.abs(Math.round(Number(n) || 0)));
}

/** `writeoff` (v1.2): the customer owes less, but it is not a payment; shown with a minus and "Maaf kiya". */
export type AmountKind = 'credit' | 'payment' | 'writeoff';

/** The word for an entry kind: "Udhaar" / "Jama" / "Maaf kiya" (Credit / Payment / Written off). */
export function kindLabel(kind: AmountKind, lang: Lang = 'hi'): string {
  const L = labels(lang);
  return kind === 'credit' ? L.credit : kind === 'payment' ? L.payment : L.writeoff;
}

/** Ledger ink for a kind: credit and payment have their own; a write-off is neutral ink. */
export function kindTone(kind: AmountKind): string {
  return kind === 'credit' ? 'text-credit' : kind === 'payment' ? 'text-payment' : 'text-ink';
}
export type SignMode = 'kind' | 'auto' | 'none';

export interface AmountParts {
  /** "+", "−" or "" */
  sign: string;
  digits: string;
  /** Whole string as shown, e.g. "+ ₹340" with a narrow no-break space. */
  text: string;
  /** What a screen reader says, e.g. "plus 340 rupees, udhaar". */
  label: string;
}

/**
 * Parts of a displayed amount.
 * - kind 'credit' -> "+ ₹340", label "plus 340 rupees, udhaar"; 'payment' -> "− ₹200", "minus 200 rupees, jama".
 * - sign 'auto' (no kind): a negative value gets "−", a positive value none.
 * - sign 'none': no sign at all, the absolute value.
 */
export function amountParts(value: number, opts: { kind?: AmountKind; sign?: SignMode; lang?: Lang } = {}): AmountParts {
  const L = labels(opts.lang ?? 'hi');
  const v = Math.round(Number(value) || 0);
  const mode: SignMode = opts.sign ?? (opts.kind ? 'kind' : 'auto');
  let sign = '';
  if (mode === 'kind' && opts.kind) sign = opts.kind === 'credit' ? '+' : MINUS;
  else if (mode === 'auto' && v < 0) sign = MINUS;
  const digits = groupDigits(v);
  const text = (sign ? sign + NNBSP : '') + RUPEE + digits;
  const spokenNumber = String(Math.abs(v));
  const signWord = sign === '+' ? L.plus : sign === MINUS ? L.minus : '';
  const kindWord = opts.kind ? (opts.kind === 'credit' ? L.creditSr : opts.kind === 'payment' ? L.paymentSr : L.writeoffSr) : '';
  const label = [signWord, `${spokenNumber} ${L.rupees}`].filter(Boolean).join(' ') + (kindWord ? `, ${kindWord}` : '');
  return { sign, digits, text, label };
}

/** Local calendar date as YYYY-MM-DD. */
export function ymd(d: Date = new Date()): string {
  const p = (x: number) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function dayNumber(s: string): number {
  const [y, m, d] = s.split('-').map(Number);
  return Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1) / 86400000;
}

const shortDate = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' });
const clock = new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });

/** "Aaj", "Kal", "Parso" (or English), else "20 Nov". */
export function dayLabel(date: string, today: string, lang: Lang = 'hi'): string {
  if (!date || !/^\d{4}-\d{2}-\d{2}/.test(date)) return '';
  const L = labels(lang);
  const diff = dayNumber(today) - dayNumber(date.slice(0, 10));
  if (diff === 0) return L.today;
  if (diff === 1) return L.yesterday;
  if (diff === 2) return L.dayBeforeYesterday;
  const [y, m, d] = date.slice(0, 10).split('-').map(Number);
  return shortDate.format(new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1));
}

/** 24-hour clock time of an ISO timestamp in local time, e.g. "11:42"; "" when unparseable. */
export function clockTime(ts: string): string {
  const ms = Date.parse(ts);
  if (Number.isNaN(ms)) return '';
  return clock.format(new Date(ms));
}

/**
 * When an entry happened, for its row. Today: "Aaj, 11:42" (time recorded). Yesterday and the day before:
 * "Kal, 20 Nov" / "Parso, 19 Nov". Older: "18 Nov".
 */
export function entryWhen(entry: { date: string; ts: string }, now: Date = new Date(), lang: Lang = 'hi'): string {
  const today = ymd(now);
  if (!entry.date || !/^\d{4}-\d{2}-\d{2}/.test(entry.date)) return '';
  const diff = dayNumber(today) - dayNumber(entry.date.slice(0, 10));
  const day = dayLabel(entry.date, today, lang);
  if (diff === 0) {
    const time = clockTime(entry.ts);
    return time ? `${day}, ${time}` : day;
  }
  if (diff === 1 || diff === 2) {
    const [y, m, d] = entry.date.slice(0, 10).split('-').map(Number);
    return `${day}, ${shortDate.format(new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1))}`;
  }
  return day;
}

/** Side-panel time: "abhi" under a minute, "5 min" under an hour, else the clock time. */
export function sinceLabel(ts: string, now: Date = new Date(), lang: Lang = 'hi'): string {
  const ms = Date.parse(ts);
  if (Number.isNaN(ms)) return '';
  const mins = Math.floor((now.getTime() - ms) / 60000);
  if (mins < 1) return labels(lang).justNow;
  if (mins < 60) return `${mins} min`;
  return clockTime(ts);
}

const HI_DAYS = ['Ravivaar', 'Somvaar', 'Mangalvaar', 'Budhvaar', 'Guruvaar', 'Shukravaar', 'Shanivaar'];
const EN_DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/** Screen-title date: "Shanivaar, 21 November" / "Saturday, 21 November". */
export function longDate(d: Date = new Date(), lang: Lang = 'hi'): string {
  const day = (lang === 'en' ? EN_DAYS : HI_DAYS)[d.getDay()];
  return `${day}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

/**
 * Splits a live (partial) transcript into the settled part and the volatile tail (the last word, which
 * speech recognition may still change). The tail is shown in ink-3 as decoration only.
 */
export function splitVolatile(text: string): [string, string] {
  const t = text.replace(/\s+$/, '');
  const i = t.lastIndexOf(' ');
  if (i < 0) return ['', t];
  return [t.slice(0, i + 1), t.slice(i + 1)];
}

/** Reply text split so ₹ amounts can be set in weight 600 with tabular figures. */
export function replySegments(text: string): { text: string; amount: boolean }[] {
  const out: { text: string; amount: boolean }[] = [];
  let last = 0;
  for (const m of text.matchAll(/₹\s?\d[\d,]*/g)) {
    const i = m.index ?? 0;
    if (i > last) out.push({ text: text.slice(last, i), amount: false });
    out.push({ text: m[0], amount: true });
    last = i + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), amount: false });
  return out;
}

/** Customer name with its first tag: "Ramesh · Chai wale". */
export function customerName(c: { display: string; tags?: string[] }): string {
  const tag = c.tags && c.tags[0];
  return tag ? `${c.display} · ${tag.charAt(0).toUpperCase()}${tag.slice(1)}` : c.display;
}

/** First letter for the avatar, uppercased; works for Devanagari and Kannada names too. */
export function initial(name: string): string {
  const first = Array.from(name.trim())[0];
  return first ? first.toLocaleUpperCase() : '?';
}
