// A tiny scripted stand-in for the server's parser and replies, used only by the mock session.
// It understands the pitch flow (credit, spoken correction, payment with carry-over, balance, daily summary,
// undo) and raises every question type the doubt sheet handles, with the contract 3.3 result fields
// (`candidates`, `confirm`, `balances`, `query`). Replies follow the templates in docs/CONTRACT.md 3.2, 5 and 5.1.
// This is not the real parser and makes no attempt to be one. Trigger phrases (Hinglish or English):
//   "teen sau chaalis"            confusable_number, candidates [340, 740]
//   amount >= 1 lakh              plausibility
//   no direction word             ambiguous_direction
//   a name close to a known one   new_customer with that customer as a candidate ("Rakesh" when Ramesh exists)
//   a known name alone            missing_amount
//   "nahi" alone after two saves  unclear_correction with the two entries as candidates
//   "bill N, M diya"              confirm_entry computed
//   "maaf" / "write off"          confirm_entry writeoff (then a `writeoff` entry)
//   "pichle saal"                 unclear_date
//   "sabse zyada baaki" / "top"   top_dues answer with query {type: "top_dues"}
//   "awaaz band" / "network"      the client-failure cases (handled by the mock session)
import type { Lang } from '../../i18n';
import type { BalanceInfo, Candidate, Confirm, Entry, EntryKind, QueryInfo } from '../session/types';
import type { MockLedger } from './ledger';

export interface BrainResult {
  status: 'ok' | 'needs_clarification' | 'rejected';
  action: string;
  reason?: string;
  entries: Entry[];
  reply_text: string;
  question?: string;
  lang: Lang;
  candidates?: Candidate[];
  confirm?: Confirm;
  balances?: BalanceInfo[];
  query?: QueryInfo;
  /** What is spoken, when it differs from reply_text (private mode). */
  speak?: string;
}

type Pending =
  | { reason: 'confusable_number'; name: string; kind: EntryKind; a: number; b: number }
  | { reason: 'plausibility'; name: string; kind: EntryKind; amount: number }
  | { reason: 'ambiguous_direction'; name: string; amount: number }
  | { reason: 'new_customer'; name: string; close: string; kind: EntryKind; amount: number }
  | { reason: 'missing_amount'; name: string }
  | { reason: 'unclear_correction'; ids: Entry['id'][] }
  | { reason: 'confirm_entry'; name: string; kind: EntryKind; amount: number }
  | { reason: 'unclear_date'; name: string; kind: EntryKind; amount: number };

const fmt = (n: number) => new Intl.NumberFormat('en-IN').format(n);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const STOP = new Set([
  'aur', 'and', 'ka', 'ke', 'ki', 'ko', 'ne', 'se', 'nahi', 'no', 'haan', 'yes', 'udhaar', 'credit', 'payment',
  'jama', 'mila', 'diye', 'diya', 'tha', 'aaj', 'kal', 'today', 'received', 'paid', 'total', 'baaki', 'hisaab',
  'batao', 'summary', 'rupaye', 'rupees', 'karo', 'undo', 'the', 'from', 'for', 'of', 'is', 'how', 'much', 'owes',
  'teen', 'sau', 'chaalis', 'paanch', 'lakh', 'ya', 'or', 'pakka', "today's", 'bill', 'hai', 'maaf', 'write',
  'off', 'kar', 'do', 'pichle', 'saal', 'sabse', 'zyada', 'top', 'dues', 'kitna', 'naya', 'parso', 'credit.',
]);

function words(text: string): string[] {
  return text.toLowerCase().replace(/[^a-z0-9\s']/g, ' ').split(/\s+/).filter(Boolean);
}

/** Digits, with "lakh" / "hazaar" multipliers and the one spoken form the pitch uses. */
export function findAmount(text: string): number | null {
  const low = text.toLowerCase();
  if (/teen sau chaalis/.test(low)) return 340;
  const m = low.replace(/,/g, '').match(/(\d+)\s*(lakh|hazaar|thousand)?/);
  if (m) {
    const n = Number(m[1]);
    if (m[2] === 'lakh') return n * 100000;
    if (m[2] === 'hazaar' || m[2] === 'thousand') return n * 1000;
    return n;
  }
  if (/paanch lakh/.test(low)) return 500000;
  return null;
}

function allAmounts(text: string): number[] {
  return [...text.replace(/,/g, '').matchAll(/\d+/g)].map((m) => Number(m[0]));
}

function findName(text: string): string | null {
  for (const w of words(text)) {
    if (!STOP.has(w) && !/^\d/.test(w)) return cap(w);
  }
  return null;
}

function direction(text: string): EntryKind | null {
  const low = text.toLowerCase();
  if (/\b(udhaar|credit|liya|le gaya)\b/.test(low)) return 'credit';
  if (/\b(payment|jama|mila|mile|diye|diya|paid|received)\b/.test(low)) return 'payment';
  return null;
}

/** Edit distance, for "a name close to a known one". */
export function distance(a: string, b: string): number {
  const x = a.toLowerCase();
  const y = b.toLowerCase();
  const d = Array.from({ length: x.length + 1 }, (_, i) => [i, ...new Array<number>(y.length).fill(0)]);
  for (let j = 1; j <= y.length; j++) (d[0] as number[])[j] = j;
  for (let i = 1; i <= x.length; i++) {
    for (let j = 1; j <= y.length; j++) {
      const row = d[i] as number[];
      const prev = d[i - 1] as number[];
      row[j] = Math.min((prev[j] as number) + 1, (row[j - 1] as number) + 1, (prev[j - 1] as number) + (x[i - 1] === y[j - 1] ? 0 : 1));
    }
  }
  return (d[x.length] as number[])[y.length] as number;
}

const isYes = (t: string) => /\b(haan|ha|han|yes|pakka|theek|sahi|ji|banao|naya)\b/i.test(t);
const isNo = (t: string) => /\b(nahi|nahin|no|mat)\b/i.test(t);

export class MockBrain {
  private pending: Pending | null = null;
  private lastName: string | null = null;
  /** Entries saved by the last saving turn (for unclear_correction). */
  private lastSaved: Entry[] = [];
  lang: Lang = 'hi';
  privateMode = false;

  constructor(private ledger: MockLedger) {}

  greeting(): BrainResult {
    const reply = this.lang === 'en' ? 'Hello! I am KhataVaani, an AI assistant.' : 'Namaste! Main KhataVaani hoon, ek AI sahayak.';
    return { status: 'ok', action: 'greeting', entries: [], reply_text: reply, lang: this.lang };
  }

  /** Whether a clarification question is waiting for an answer. */
  get pendingReason(): string | null {
    return this.pending?.reason ?? null;
  }

  /** Drops the open question (fresh page load without keep_pending, or the 60 s expiry). */
  dropPending(): void {
    this.pending = null;
  }

  respond(text: string): BrainResult {
    const p = this.pending;
    if (p) {
      this.pending = null;
      return this.answer(p, text);
    }
    const low = text.toLowerCase().trim();
    if (/\bundo\b|hata do|remove/.test(low)) return this.undo();
    const amend = low.match(/^\s*(nahi|no)[,\s]+(\d[\d,]*)/);
    if (amend) return this.amend(Number((amend[2] ?? '0').replace(/,/g, '')));
    if (/^(nahi|no)[.!]?$/.test(low)) {
      const active = this.lastSaved.filter((e) => !e.reversed);
      if (active.length >= 2) {
        const [a, b] = active;
        if (a && b) {
          this.pending = { reason: 'unclear_correction', ids: [a.id, b.id] };
          const q = this.en(
            `Which entry: ₹${fmt(a.amount)} ${a.kind} or ₹${fmt(b.amount)} ${b.kind}?`,
            `Kaunsi entry: ₹${fmt(a.amount)} ${this.word(a.kind)} ya ₹${fmt(b.amount)} ${this.word(b.kind)}?`,
          );
          return this.question('unclear_correction', q, {
            candidates: [a, b].map((e) => ({ id: e.id, kind: e.kind, amount: e.amount, customer: e.customer.display })),
          });
        }
      }
      return { status: 'ok', action: 'none', entries: [], reply_text: this.en('There is no earlier entry.', 'Pehle koi entry nahi hai.'), lang: this.lang };
    }
    if (/sabse zyada baaki|top dues|\btop\b/.test(low)) return this.topDues();
    if (/hisaab|summary/.test(low)) return this.summary();

    const name = findName(text) ?? this.lastName;
    if (/maaf|write off/.test(low) && name) {
      const c = this.ledger.find(name);
      const bal = c ? this.ledger.balance(c.id) : 0;
      if (!c || bal <= 0) return this.balance(name);
      this.pending = { reason: 'confirm_entry', name: c.display, kind: 'writeoff', amount: bal };
      return this.question('confirm_entry', this.en(`${c.display} owes ₹${fmt(bal)}. Write all of it off?`, `${c.display} ke ₹${fmt(bal)} baaki hain. Poore maaf karun?`), {
        confirm: { type: 'writeoff', balance: bal },
      });
    }
    if (/\bbill\b/.test(low) && name) {
      const [bill, paid] = allAmounts(text);
      if (bill != null && paid != null && paid < bill) {
        const amt = bill - paid;
        this.pending = { reason: 'confirm_entry', name, kind: 'credit', amount: amt };
        return this.question('confirm_entry', this.en(`Add ₹${fmt(amt)} credit for ${name}?`, `${name} ke ₹${fmt(amt)} udhaar likhun?`), {
          confirm: { type: 'computed', bill, paid },
        });
      }
    }

    const amount = findAmount(text);
    if (amount == null) {
      if (name && /total|baaki|kitna|owe/.test(low)) return this.balance(name);
      if (name && !this.ledger.isNew(name) && words(text).length === 1) {
        this.pending = { reason: 'missing_amount', name };
        return this.question('missing_amount', this.en(`What should I note for ${name}?`, `${name} ka kya likhun?`));
      }
      return this.rejected();
    }
    if (!name) return this.rejected();
    if (/teen sau chaalis/.test(low)) {
      const kind = direction(text) ?? 'credit';
      this.pending = { reason: 'confusable_number', name, kind, a: 340, b: 740 };
      return this.question('confusable_number', this.en(`₹340 or ₹740?`, `₹340 ya ₹740?`), { candidates: [340, 740] });
    }
    const kind = direction(text);
    if (!kind) {
      this.pending = { reason: 'ambiguous_direction', name, amount };
      return this.question('ambiguous_direction', this.en(`Did ${name} pay, or did ${name} take credit?`, `${name} ne diye, ya ${name} ko udhaar?`));
    }
    if (/pichle saal|last year/.test(low)) {
      this.pending = { reason: 'unclear_date', name, kind, amount };
      return this.question('unclear_date', this.en('Which day? Say today, yesterday or the day before.', 'Kaunsa din? Aaj, kal ya parso boliye.'));
    }
    if (amount >= 100000) {
      this.pending = { reason: 'plausibility', name, kind, amount };
      return this.question('plausibility', this.en(`₹${fmt(amount)}, are you sure?`, `₹${fmt(amount)}, pakka?`));
    }
    if (this.ledger.isNew(name)) {
      const close = this.ledger.customerSummaries().customers.find((c) => distance(c.display, name) <= 2);
      if (close) {
        this.pending = { reason: 'new_customer', name, close: close.display, kind, amount };
        return this.question('new_customer', this.en(`Is ${name} a new customer, or ${close.display}?`, `${name} naya grahak hai, ya ${close.display}?`), {
          candidates: [{ id: close.id, display: close.display, tags: close.tags }],
        });
      }
    }
    return this.append(kind, name, amount);
  }

  private en(en: string, hi: string): string {
    return this.lang === 'en' ? en : hi;
  }

  private word(kind: EntryKind): string {
    if (kind === 'credit') return this.en('credit', 'udhaar');
    if (kind === 'payment') return this.en('payment', 'jama');
    return this.en('written off', 'maaf');
  }

  private question(reason: string, text: string, extra: Pick<BrainResult, 'candidates' | 'confirm'> = {}): BrainResult {
    return { status: 'needs_clarification', action: 'none', reason, entries: [], reply_text: text, question: text, lang: this.lang, ...extra };
  }

  private answer(p: Pending, text: string): BrainResult {
    const low = text.toLowerCase();
    switch (p.reason) {
      case 'confusable_number': {
        const n = findAmount(text);
        if (n === p.a || n === p.b) return this.append(p.kind, p.name, n);
        if (isNo(text)) return this.cancelled();
        return this.rejected();
      }
      case 'plausibility':
      case 'confirm_entry':
        if (isNo(text)) return this.cancelled();
        if (isYes(text)) return this.append(p.kind, p.name, p.amount);
        return this.rejected();
      case 'ambiguous_direction': {
        const kind = direction(text);
        return kind ? this.append(kind, p.name, p.amount) : this.rejected();
      }
      case 'new_customer':
        if (low.includes(p.close.toLowerCase()) || /\b(wahi|purana|pehla)\b/.test(low)) return this.append(p.kind, p.close, p.amount);
        if (isYes(text)) return this.append(p.kind, p.name, p.amount);
        if (isNo(text)) return this.cancelled();
        return this.rejected();
      case 'missing_amount': {
        const n = findAmount(text);
        const kind = direction(text) ?? 'credit';
        return n != null ? this.append(kind, p.name, n) : this.rejected();
      }
      case 'unclear_correction': {
        const n = findAmount(text);
        const target = this.ledger.ledgerView(500).entries.find((e) => p.ids.includes(e.id) && e.amount === n);
        if (!target) return this.rejected();
        // The mock removes the entry that was picked (the real server may ask for the right amount next).
        const old = this.ledger.reverse(target.id);
        const who = target.customer.display;
        return {
          status: 'ok',
          action: 'undo',
          entries: old ? [old] : [],
          reply_text: this.en(`Removed the entry: ${who}, ₹${fmt(target.amount)} ${this.word(target.kind)}.`, `Entry hata di: ${who}, ₹${fmt(target.amount)} ${this.word(target.kind)}.`),
          lang: this.lang,
        };
      }
      case 'unclear_date': {
        const days = /\bparso\b|day before/.test(low) ? 2 : /\bkal\b|yesterday/.test(low) ? 1 : /\baaj\b|today/.test(low) ? 0 : -1;
        if (days < 0) return this.rejected();
        return this.append(p.kind, p.name, p.amount, days);
      }
      default:
        return this.rejected();
    }
  }

  private balancesFor(entries: Entry[]): BalanceInfo[] {
    const seen = new Map<string, BalanceInfo>();
    for (const e of entries) {
      seen.set(e.customer.id, { customer_id: e.customer.id, display: e.customer.display, balance: this.ledger.balance(e.customer.id) });
    }
    return [...seen.values()];
  }

  private append(kind: EntryKind, name: string, amount: number, daysAgo = 0): BrainResult {
    const isNew = this.ledger.isNew(name);
    const when = new Date(this.ledger.now().getTime() - daysAgo * 86400000);
    const e = this.ledger.add(kind, name, amount, [], when);
    this.lastName = e.customer.display;
    this.lastSaved = [e];
    const n = e.customer.display;
    const body =
      kind === 'credit'
        ? this.en(`Added ₹${fmt(amount)} credit for ${n}.`, `${n} ke khate mein ₹${fmt(amount)} udhaar likh diya.`)
        : kind === 'payment'
          ? this.en(`Received ₹${fmt(amount)} from ${n}.`, `${n} se ₹${fmt(amount)} mile, jama kar diya.`)
          : this.en(`Wrote off ₹${fmt(amount)} for ${n}.`, `${n} ke ₹${fmt(amount)} maaf kiye.`);
    const prefix = isNew ? this.en(`New account for ${n}. `, `Naya khata ${n}. `) : '';
    return { status: 'ok', action: 'append', entries: [{ ...e }], reply_text: prefix + body, lang: this.lang, balances: this.balancesFor([e]) };
  }

  private amend(amount: number): BrainResult {
    const last = this.ledger.lastActive();
    if (!last) return this.nothingToChange();
    const old = this.ledger.reverse(last.id);
    const e = this.ledger.add(last.kind, last.customer.display, amount);
    this.lastSaved = [e];
    const word = this.word(last.kind);
    const reply = this.en(`Corrected: ${e.customer.display}, ₹${fmt(amount)} ${word}.`, `Theek kar diya: ${e.customer.display}, ₹${fmt(amount)} ${word}.`);
    return { status: 'ok', action: 'amend', entries: old ? [old, { ...e }] : [{ ...e }], reply_text: reply, lang: this.lang, balances: this.balancesFor([e]) };
  }

  /** For tests: save two entries in one turn (so a bare "nahi" has two candidates). */
  saveTwo(a: { kind: EntryKind; name: string; amount: number }, b: { kind: EntryKind; name: string; amount: number }): Entry[] {
    const x = this.ledger.add(a.kind, a.name, a.amount);
    const y = this.ledger.add(b.kind, b.name, b.amount);
    this.lastSaved = [x, y];
    return [x, y];
  }

  private undo(): BrainResult {
    const last = this.ledger.lastActive();
    if (!last) return { status: 'ok', action: 'none', entries: [], reply_text: this.en('There is nothing to undo.', 'Undo karne ke liye kuch nahi hai.'), lang: this.lang };
    const old = this.ledger.reverse(last.id);
    const word = this.word(last.kind);
    const n = last.customer.display;
    const reply = this.en(`Removed the last entry: ${n}, ₹${fmt(last.amount)} ${word}.`, `Pichli entry hata di: ${n}, ₹${fmt(last.amount)} ${word}.`);
    return { status: 'ok', action: 'undo', entries: old ? [old] : [], reply_text: reply, lang: this.lang };
  }

  /** An answer about balances: in private mode it is shown, and the voice says only that it is on screen. */
  private answerOnScreen(reply: string, query: QueryInfo): BrainResult {
    const r: BrainResult = { status: 'ok', action: 'query', entries: [], reply_text: reply, lang: this.lang, query };
    if (this.privateMode) r.speak = this.en('The answer is on the screen.', 'Jawab screen par hai.');
    return r;
  }

  private balance(name: string): BrainResult {
    const c = this.ledger.find(name);
    if (!c) return { status: 'ok', action: 'query', entries: [], reply_text: this.en(`No account found for ${name}.`, `${name} ka khata nahi mila.`), lang: this.lang };
    const b = this.ledger.balance(c.id);
    const n = c.display;
    const reply =
      b > 0
        ? this.en(`${n} owes ₹${fmt(b)}.`, `${n} ke ₹${fmt(b)} baaki hain.`)
        : b === 0
          ? this.en(`${n}'s account is settled.`, `${n} ka hisaab barabar hai.`)
          : this.en(`${n} has paid ₹${fmt(-b)} extra.`, `${n} ke ₹${fmt(-b)} zyada jama hain.`);
    return this.answerOnScreen(reply, { type: 'balance', customer_id: c.id });
  }

  private summary(): BrainResult {
    const t = this.ledger.totals();
    const top = this.ledger.topDues(1)[0];
    let reply: string;
    if (!t.credit_today && !t.payment_today) reply = this.en('No entries yet today.', 'Aaj abhi tak koi entry nahi.');
    else {
      const head = this.en(`Today: ₹${fmt(t.credit_today)} credit, ₹${fmt(t.payment_today)} received.`, `Aaj ₹${fmt(t.credit_today)} udhaar gaya, ₹${fmt(t.payment_today)} jama hue.`);
      const tail = top ? this.en(` Highest due: ${top.display}, ₹${fmt(top.balance)}.`, ` Sabse zyada baaki: ${top.display}, ₹${fmt(top.balance)}.`) : '';
      reply = head + tail;
    }
    return this.answerOnScreen(reply, { type: 'daily_summary', period: 'today' });
  }

  private topDues(): BrainResult {
    const dues = this.ledger.topDues(3);
    const reply = dues.length
      ? this.en('Highest dues: ', 'Sabse zyada baaki: ') + dues.map((d) => `${d.display} ₹${fmt(d.balance)}`).join(', ') + '.'
      : this.en('Nobody owes anything.', 'Kisi ka kuch baaki nahi.');
    return this.answerOnScreen(reply, { type: 'top_dues' });
  }

  private cancelled(): BrainResult {
    return { status: 'ok', action: 'none', entries: [], reply_text: this.en('Okay, nothing was saved.', 'Theek hai, entry nahi ki.'), lang: this.lang };
  }

  private nothingToChange(): BrainResult {
    return { status: 'ok', action: 'none', entries: [], reply_text: this.en('There is no earlier entry.', 'Pehle koi entry nahi hai.'), lang: this.lang };
  }

  private rejected(): BrainResult {
    return {
      status: 'rejected',
      action: 'none',
      entries: [],
      reply_text: this.en('Sorry, I did not understand. Please say it again.', 'Maaf kijiye, samajh nahi aaya. Dobara boliye.'),
      lang: this.lang,
    };
  }
}

/** What the mock "hears" on each press, in order, per language. Answers to a pending question come first. */
export const VOICE_SCRIPT: Record<Lang, string[]> = {
  hi: [
    'Ramesh ka 340 udhaar',
    'Nahi, 430',
    'Aur 200 payment mila',
    'Aaj ka hisaab batao',
    'Geeta ka teen sau chaalis udhaar',
    'Ramesh ka total kitna hai',
    'Sunita ne 150 diye',
  ],
  en: [
    'Ramesh 340 credit',
    'No, 430',
    'And 200 payment received',
    "Today's summary",
    'Geeta teen sau chaalis credit',
    'How much does Ramesh owe, total',
    'Sunita paid 150',
  ],
};

/** The spoken answer the mock "hears" while a question is open. */
export function scriptedAnswer(reason: string | null, lang: Lang): string | null {
  if (reason === 'confusable_number') return '340';
  if (reason === 'plausibility' || reason === 'confirm_entry' || reason === 'new_customer') return 'haan';
  if (reason === 'ambiguous_direction') return lang === 'en' ? 'credit' : 'udhaar';
  if (reason === 'unclear_date') return 'kal';
  if (reason === 'missing_amount') return '340 udhaar';
  return null;
}
