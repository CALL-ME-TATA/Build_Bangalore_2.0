// Deterministic synthetic khata for tests and for checking the long list in a browser
// (`?synthetic=300` in mock mode or on the dev server). Synthetic data only: common Indian first names in
// Latin, Devanagari and Kannada script, a few very long names, and amounts from ₹5 to ₹1,00,000.
import type { Customer, LedgerView } from '../../services/api';
import type { Entry } from '../../services/session/types';
import { ymd } from '../../lib/format';

const NAMES = [
  'Ramesh', 'Sunita', 'Shivu', 'Lakshmi', 'Imran', 'Pooja', 'Arjun', 'Kavya', 'Manoj', 'Fatima', 'Ravi', 'Anita',
  'Suresh', 'Meena', 'Vikram', 'Divya', 'Harish', 'Asha', 'Naveen', 'Rekha', 'Prakash', 'Geeta', 'Kiran', 'Salma',
  'रमेश', 'सुनीता', 'गीता', 'मोहन', 'ರಮೇಶ್', 'ಲಕ್ಷ್ಮಿ', 'ಮಂಜುನಾಥ', 'ಶಿವು',
  'Venkatanarasimharajuvaripeta Srinivasan', 'Annapurna Subramaniam Chandrasekharan',
];
const TAGS = ['chai wale', 'doodh wale', 'sabzi wale', 'Sharma ji', 'auto wale', 'naya ghar', 'school ke paas', 'kone wali dukaan'];
const AMOUNTS = [5, 10, 20, 35, 50, 85, 120, 200, 340, 450, 680, 850, 1100, 1250, 2400, 5600, 12500, 48000, 100000];

/** Small seeded PRNG (mulberry32) so every run produces the same khata. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(r: () => number, list: readonly T[]): T {
  return list[Math.floor(r() * list.length)] as T;
}

export interface SyntheticKhata {
  customers: Customer[];
  ledger: LedgerView;
}

/** `count` customers and up to `entryLimit` entries (newest first) over the last two weeks before `now`. */
export function syntheticKhata(count: number, now: Date = new Date(), seed = 7, entryLimit = 500): SyntheticKhata {
  const r = rng(seed);
  const customers: Customer[] = [];
  for (let i = 0; i < count; i++) {
    const base = NAMES[i % NAMES.length] ?? 'Ramesh';
    const round = Math.floor(i / NAMES.length);
    const display = round ? `${base} ${round + 1}` : base;
    const tags = r() < 0.45 ? [pick(r, TAGS)] : [];
    customers.push({ id: `s${i + 1}`, display, tags, balance: 0, reminders_opt_in: r() < 0.3 });
  }
  const entries: Entry[] = [];
  const total = Math.min(entryLimit, count * 3);
  let t = now.getTime() - 14 * 86400000;
  const step = (now.getTime() - t) / Math.max(1, total);
  for (let id = 1; id <= total; id++) {
    t += step * (0.5 + r());
    const when = new Date(Math.min(t, now.getTime() - 60000));
    // Most activity comes from the first customers, like a real shop's regulars.
    const c = customers[Math.floor(Math.pow(r(), 1.6) * customers.length)];
    if (!c) continue;
    entries.push({
      id,
      kind: r() < 0.62 ? 'credit' : 'payment',
      customer: { id: c.id, display: c.display, tags: [...c.tags] },
      amount: pick(r, AMOUNTS),
      date: ymd(when),
      ts: when.toISOString(),
      reversed: r() < 0.04,
      reversal_of: null,
    });
  }
  const balances = new Map<string, number>();
  let credit = 0;
  let payment = 0;
  const today = ymd(now);
  for (const e of entries) {
    if (e.reversed) continue;
    balances.set(e.customer.id, (balances.get(e.customer.id) ?? 0) + (e.kind === 'credit' ? e.amount : -e.amount));
    if (e.date === today) {
      if (e.kind === 'credit') credit += e.amount;
      else payment += e.amount;
    }
  }
  for (const c of customers) c.balance = balances.get(c.id) ?? 0;
  entries.reverse();
  return { customers, ledger: { entries, totals: { credit_today: credit, payment_today: payment } } };
}
