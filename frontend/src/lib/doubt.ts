// Tap answers for the doubt sheet, one per spoken answer the parser accepts (docs/CONTRACT.md 1.9, 1.14, 3.3).
// The question text always comes from `reply_text`; `reason`, `candidates` and `confirm` choose the answers:
//
//   choices   confusable_number    two amounts (candidates [a, b], else the ₹ amounts in the text)  -> "340"
//             same_name            one per customer (candidates, else the names after the colon)    -> its tag, else "pehla"/"doosra"
//             unclear_correction   one per entry (candidates, else "₹a udhaar ya ₹b jama" in the text) -> the old amount
//             new_customer + candidates   one per close customer, plus "Naya grahak"                -> "pehla"/"doosra" / "naya"
//   yes / no  plausibility, confirm_entry (every confirm type), new_customer without candidates, and any
//             question ending "pakka?", "Hata doon?", "likhoon?"…  -> Haan / Nahi (Yes / No), sending "haan" / "nahi"
//   open      ambiguous_direction  Udhaar diya / Paise aaye -> "udhaar" / "jama"
//             unclear_date         Aaj / Kal / Parso        -> "aaj" / "kal" / "parso"
//             missing_amount, missing_customer, anything else: no buttons; the talk control and the type box
// A tap sends {"type":"text","text": option.answer}.
import { labels, type Lang } from '../i18n';
import type { Candidate, CandidateCustomer, CandidateEvent, Confirm, EntryKind } from '../services/session/types';

export interface DoubtOption {
  /** Stable key for React and tests. */
  id: string;
  /** Button text. For amounts this is the plain number; the sheet renders it with <Amount>. */
  label: string;
  /** Text sent to the server when tapped. */
  answer: string;
  /** Set for amount answers. */
  amount?: number;
  /** Set for entry answers (unclear_correction): the entry's kind, shown as its word. */
  kind?: EntryKind;
  /** A secondary line under the label (a customer's tag, an entry's customer). */
  sub?: string;
}

export type DoubtKind = 'choice' | 'yesno' | 'open';

export interface DoubtSpec {
  kind: DoubtKind;
  options: DoubtOption[];
  /** Show the type box in the sheet (open questions without buttons). */
  typeBox: boolean;
}

export interface DoubtInput {
  reason: string | null | undefined;
  /** The question as shown and spoken: `reply_text`. */
  question: string | null | undefined;
  candidates?: Candidate[] | null;
  confirm?: Confirm | null;
  lang: Lang;
}

const YES_NO_ENDINGS = /(pakka|hata doon|likhoon|likhun|banaun|karun|doon|are you sure|remove it|with this one|anyway|advance|another one|all of it off|open an account)\s*\?\s*$/i;

const capFirst = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function amountsIn(question: string): number[] {
  const out: number[] = [];
  for (const m of question.matchAll(/₹\s?(\d[\d,]*)/g)) {
    const n = Number((m[1] ?? '').replace(/,/g, ''));
    if (Number.isFinite(n) && !out.includes(n)) out.push(n);
  }
  return out;
}

function namesAfterColon(question: string): string[] {
  const i = question.lastIndexOf(':');
  if (i < 0) return [];
  const tail = question.slice(i + 1).replace(/[?.!।]+\s*$/u, '').trim();
  if (!tail) return [];
  // "chai wale, gali 3 ya bina tag wale" -> three names.
  return tail
    .split(/\s*,\s*|\s+(?:ya|or)\s+/i)
    .map((s) => s.trim())
    .filter(Boolean);
}

const isCustomer = (c: Candidate): c is CandidateCustomer => typeof c === 'object' && c !== null && 'display' in c && 'id' in c && !('amount' in c);
const isEvent = (c: Candidate): c is CandidateEvent => typeof c === 'object' && c !== null && typeof (c as CandidateEvent).amount === 'number';

function yesNo(lang: Lang): DoubtSpec {
  const L = labels(lang);
  return {
    kind: 'yesno',
    typeBox: false,
    options: [
      { id: 'yes', label: L.yes, answer: 'haan' },
      { id: 'no', label: L.no, answer: 'nahi' },
    ],
  };
}

const ORDINAL = ['pehla', 'doosra', 'teesra'];
const ORDINAL_F = ['pehli', 'doosri', 'teesri'];

function customerOptions(list: CandidateCustomer[], ordinalOnly: boolean, noTagLabel?: string): DoubtOption[] {
  return list.slice(0, 3).map((c, i) => {
    const tag = c.tags?.[0];
    // Three customers (contract 3.4): pehla / doosra / teesra, and a tagless one is labelled "bina tag wale".
    if (list.length >= 3) return { id: `cust-${c.id}`, label: c.display, sub: tag ? capFirst(tag) : noTagLabel, answer: ORDINAL[i] ?? c.display };
    // same_name: a tag identifies the customer; without one, the ordinal does. new_customer: always the ordinal
    // (the parser maps "pehla" / "doosra" to the candidates in order).
    const answer = ordinalOnly ? (ORDINAL[i] ?? c.display) : (tag ?? ORDINAL[i] ?? c.display);
    return { id: `cust-${c.id}`, label: c.display, sub: tag ? capFirst(tag) : undefined, answer };
  });
}

function eventName(e: CandidateEvent): string | undefined {
  if (typeof e.customer === 'string') return e.customer;
  return e.customer?.display ?? e.display;
}

function wordKind(word: string): EntryKind | undefined {
  const w = word.toLowerCase();
  if (/udhaar|credit/.test(w)) return 'credit';
  if (/jama|payment|received/.test(w)) return 'payment';
  return undefined;
}

/** What the doubt sheet shows for a clarification question. */
export function doubtSpec({ reason, question, candidates, confirm, lang }: DoubtInput): DoubtSpec {
  const q = (question ?? '').trim();
  const L = labels(lang);
  const cands = candidates ?? [];
  const none: DoubtSpec = { kind: 'open', options: [], typeBox: true };

  if (reason === 'confusable_number') {
    const fromCands = cands.filter((c): c is number => typeof c === 'number');
    const amounts = (fromCands.length >= 2 ? fromCands : amountsIn(q)).slice(0, 2);
    if (amounts.length < 2) return none;
    return { kind: 'choice', typeBox: false, options: amounts.map((n) => ({ id: `amount-${n}`, label: String(n), answer: String(n), amount: n })) };
  }

  if (reason === 'same_name') {
    const custs = cands.filter(isCustomer);
    if (custs.length >= 2) return { kind: 'choice', typeBox: false, options: customerOptions(custs, false, L.noTag) };
    const names = namesAfterColon(q);
    if (names.length < 2) return none;
    // Two names keep sending the name itself; three send the ordinals, as with candidates.
    return {
      kind: 'choice',
      typeBox: false,
      options: names.slice(0, 3).map((n, i) => ({ id: `name-${i}`, label: capFirst(n), answer: names.length >= 3 ? (ORDINAL[i] ?? n) : n })),
    };
  }

  if (reason === 'new_customer') {
    const custs = cands.filter(isCustomer);
    if (!custs.length) return yesNo(lang);
    return {
      kind: 'choice',
      typeBox: false,
      options: [...customerOptions(custs, true), { id: 'new', label: L.answerNewCustomer, answer: 'naya' }],
    };
  }

  if (reason === 'unclear_correction') {
    const events = cands.filter(isEvent);
    if (events.length >= 2) {
      const amounts = events.map((e) => e.amount);
      const sameAmounts = new Set(amounts).size < amounts.length;
      return {
        kind: 'choice',
        typeBox: false,
        options: events.slice(0, 3).map((e, i) => ({
          id: `entry-${e.id ?? i}`,
          label: String(e.amount),
          amount: e.amount,
          kind: e.kind,
          sub: eventName(e),
          answer: sameAmounts ? (ORDINAL_F[i] ?? String(e.amount)) : String(e.amount),
        })),
      };
    }
    if (YES_NO_ENDINGS.test(q)) return yesNo(lang);
    // "Kaunsi entry: ₹340 udhaar ya ₹200 jama?" without candidates: read the two entries from the text.
    const parts = [...q.matchAll(/₹\s?(\d[\d,]*)\s+([a-z]+)/gi)];
    if (parts.length >= 2) {
      return {
        kind: 'choice',
        typeBox: false,
        options: parts.slice(0, 2).map((m, i) => {
          const n = Number((m[1] ?? '').replace(/,/g, ''));
          return { id: `entry-${i}`, label: String(n), amount: n, kind: wordKind(m[2] ?? ''), answer: String(n) };
        }),
      };
    }
    return none;
  }

  // "Ramesh ka kya likhun?" ends like a yes / no question but is open: the answer is an amount.
  if (reason === 'missing_amount' || reason === 'missing_customer') return none;
  if (reason === 'plausibility' || reason === 'confirm_entry' || confirm) return yesNo(lang);

  if (reason === 'ambiguous_direction') {
    return {
      kind: 'open',
      typeBox: false,
      options: [
        { id: 'credit', label: L.answerCredit, answer: 'udhaar' },
        { id: 'payment', label: L.answerPayment, answer: 'jama' },
      ],
    };
  }

  if (reason === 'unclear_date') {
    return {
      kind: 'open',
      typeBox: false,
      options: [
        { id: 'today', label: L.today, answer: 'aaj' },
        { id: 'yesterday', label: L.yesterday, answer: 'kal' },
        { id: 'daybefore', label: L.dayBeforeYesterday, answer: 'parso' },
      ],
    };
  }

  if (YES_NO_ENDINGS.test(q)) return yesNo(lang);
  return none;
}

/**
 * The small heading above the question: "Pakka nahi sun paaya" only for the two-amounts question (the words were
 * heard unclearly); "Ek baar pakka kar lein" for yes / no confirmations; "Thoda aur bataiye" for open questions.
 */
export function doubtHeadingKey(reason: string | null | undefined): 'doubtUnsure' | 'doubtConfirm' | 'doubtMore' {
  if (reason === 'confusable_number') return 'doubtUnsure';
  if (reason === 'plausibility' || reason === 'confirm_entry' || reason === 'new_customer') return 'doubtConfirm';
  return 'doubtMore';
}

/** Tap answers only (kept for callers that need just the list). */
export function doubtOptions(reason: string | null | undefined, question: string | null | undefined, lang: Lang, candidates?: Candidate[] | null, confirm?: Confirm | null): DoubtOption[] {
  return doubtSpec({ reason, question, candidates, confirm, lang }).options;
}
