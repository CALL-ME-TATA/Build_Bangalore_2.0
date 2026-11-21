// Fixed labels of the Khata screen, in the same { hi, en } shape as src/i18n.ts.
// Add a key to both tables; the `KhataLabels` type makes a missing key a type error.
import type { Lang } from '../../i18n';

const hi = {
  title: 'Aaj ka khata',
  todayTotals: 'Aaj ka hisaab',
  creditGiven: 'Udhaar diya',
  paymentIn: 'Jama aaya',
  totalDue: 'Kul baaki',
  customersOne: 'grahak',
  customersMany: 'grahak',
  searchLabel: 'Grahak dhundein',
  searchPlaceholder: 'Naam ya “chai wale”…',
  searchClear: 'Search saaf karein',
  filterLabel: 'Filter',
  filterAll: 'Sab',
  filterDue: 'Baaki wale',
  filterToday: 'Aaj',
  listLabel: 'Grahak',
  resultCount: '{n} grahak dikh rahe hain',
  stateDue: 'baaki',
  stateAdvance: 'advance jama',
  stateClear: 'hisaab saaf',
  noActivity: 'Haal mein koi entry nahi',
  lastEntry: 'Aakhri entry',
  zeroSr: '0 rupaye',
  removedShort: 'hataya',
  // states
  loading: 'Khata khul raha hai…',
  errorTitle: 'Khata nahi khula',
  errorBody: 'Server se jud nahi paaye. Internet dekhiye, phir dobara koshish karein.',
  retry: 'Dobara koshish karein',
  offlineStale: 'Offline hain. Yeh khata purana ho sakta hai; internet aane par apne aap update hoga.',
  offlineEmpty: 'Offline hain aur khata abhi tak load nahi hua. Internet aane par yahan dikhega.',
  updatedAt: 'Aakhri update {time}',
  emptyTitle: 'Khata abhi khaali hai',
  emptyBody: 'Mic dabakar ek entry boliye. Jaise:',
  emptySample: '"Ramesh ka 340 udhaar"',
  emptyGo: 'Bolo par jaayein',
  noMatchTitle: 'Koi grahak nahi mila',
  noMatchSearch: '"{q}" se koi naam nahi milta.',
  noMatchFilter: 'Is filter mein abhi koi grahak nahi.',
  showAll: 'Sab grahak dikhaiye',
  pickCustomer: 'Kisi grahak ko chuniye, unka poora khata yahan khulega.',
};

export type KhataLabelKey = keyof typeof hi;
export type KhataLabels = Record<KhataLabelKey, string>;

const en: KhataLabels = {
  title: "Today's ledger",
  todayTotals: "Today's totals",
  creditGiven: 'Credit given',
  paymentIn: 'Payments received',
  totalDue: 'Total due',
  customersOne: 'customer',
  customersMany: 'customers',
  searchLabel: 'Find a customer',
  searchPlaceholder: 'Name or “tea stall”…',
  searchClear: 'Clear search',
  filterLabel: 'Show customers',
  filterAll: 'All',
  filterDue: 'With dues',
  filterToday: 'Today',
  listLabel: 'Customers',
  resultCount: '{n} customers shown',
  stateDue: 'due',
  stateAdvance: 'paid in advance',
  stateClear: 'settled',
  noActivity: 'No recent entries',
  lastEntry: 'Last entry',
  zeroSr: '0 rupees',
  removedShort: 'removed',
  loading: 'Opening the ledger…',
  errorTitle: 'The ledger did not open',
  errorBody: 'Could not reach the server. Check the internet, then try again.',
  retry: 'Try again',
  offlineStale: 'You are offline. This ledger may be out of date; it updates by itself when the internet is back.',
  offlineEmpty: 'You are offline and the ledger has not loaded yet. It will show here when the internet is back.',
  updatedAt: 'Last updated {time}',
  emptyTitle: 'The ledger is empty',
  emptyBody: 'Hold the mic and say an entry. For example:',
  emptySample: '"Ramesh 340 credit"',
  emptyGo: 'Go to Talk',
  noMatchTitle: 'No customer found',
  noMatchSearch: 'No name matches "{q}".',
  noMatchFilter: 'No customer in this filter yet.',
  showAll: 'Show all customers',
  pickCustomer: 'Choose a customer to open their full ledger here.',
};

const TABLES: Record<Lang, KhataLabels> = { hi, en };

export function khataLabels(lang: Lang): KhataLabels {
  return TABLES[lang];
}

/** Fills "{name}" placeholders. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in values ? String(values[k]) : m));
}

export const KHATA_TABLES = TABLES;
