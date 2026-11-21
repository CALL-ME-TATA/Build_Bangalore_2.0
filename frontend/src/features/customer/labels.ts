// Fixed labels of the Customer detail screen, in the same { hi, en } shape as src/i18n.ts.
// Add a key to both tables; the `CustomerLabels` type makes a missing key a type error.
import type { Lang } from '../../i18n';

const hi = {
  back: 'Khata',
  backSr: 'Khata par wapas',
  balanceDue: 'Baaki',
  balanceAdvance: 'Advance jama',
  balanceClear: 'Hisaab saaf',
  // reminder
  remind: 'Reminder bhejein',
  reminding: 'Reminder ban raha hai…',
  optedIn: '{name} ne reminders ke liye haan kaha hai',
  reasonNotOptedIn: '{name} ne reminders ke liye abhi haan nahi kaha. Neeche switch chalu karein, tabhi bhej sakte hain.',
  reasonNothingDue: '{name} ne reminders ke liye haan kaha hai. Abhi kuch baaki nahi, isliye reminder ki zaroorat nahi.',
  reminderReady: 'Reminder taiyaar hai',
  reminderOpen: 'WhatsApp par bhejein',
  reminderOpenSr: 'WhatsApp mein khulega',
  reminderNoPhone: 'Inka phone number save nahi hai. Number daalein, phir WhatsApp link banega.',
  reminderNone: 'Reminder nahi bana. Thodi der baad dobara koshish karein.',
  reminderFailed: 'Reminder nahi bana. Internet dekhiye aur dobara dabaiye.',
  phoneLabel: 'Mobile number',
  phoneHint: '10 ankon ka number, jaise 98xxxxxx10',
  phoneSave: 'Number save karein',
  phoneSaving: 'Save ho raha hai…',
  phoneInvalid: 'Yeh number sahi nahi lagta. 10 ankon ka mobile number daalein.',
  phoneFailed: 'Number save nahi hua. Dobara koshish karein.',
  // opt-in
  optInLabel: 'WhatsApp reminder',
  optInOnNote: 'Chalu: aap inhe baaki ki yaad WhatsApp par bhej sakte hain. Bina poochhe kuch nahi jaata.',
  optInOffNote: 'Band: inhe koi reminder nahi jaayega. Grahak ne haan kaha ho tabhi chalu karein.',
  optInOn: 'Chalu',
  optInOff: 'Band',
  optInSavedOn: 'Reminder chalu kiya',
  optInSavedOff: 'Reminder band kiya',
  optInFailed: 'Badlav save nahi hua. Internet dekhiye aur dobara koshish karein.',
  // mic
  speak: '{name} ke liye bol kar entry',
  // timeline
  timeline: 'Hisaab ki entries',
  recorded: 'likha',
  corrected: 'sudhaara',
  oldAmount: 'pehle',
  noEntries: 'Haal ki entries mein inka kuch nahi mila.',
  historyCut: 'Sirf haal ki 500 entries dekhi gayi hain; isse purani entries yahan nahi dikhti.',
  // states
  loading: 'Khata khul raha hai…',
  notFoundTitle: 'Yeh grahak nahi mila',
  notFoundBody: 'Shayad link purana hai ya naam badal gaya. Khata se grahak chuniye.',
  errorTitle: 'Grahak ka khata nahi khula',
  errorBody: 'Server se jud nahi paaye. Internet dekhiye, phir dobara koshish karein.',
  retry: 'Dobara koshish karein',
  offlineStale: 'Offline hain. Yeh hisaab purana ho sakta hai.',
};

export type CustomerLabelKey = keyof typeof hi;
export type CustomerLabels = Record<CustomerLabelKey, string>;

const en: CustomerLabels = {
  back: 'Ledger',
  backSr: 'Back to the ledger',
  balanceDue: 'Due',
  balanceAdvance: 'Paid in advance',
  balanceClear: 'Settled',
  remind: 'Send reminder',
  reminding: 'Preparing the reminder…',
  optedIn: '{name} agreed to reminders',
  reasonNotOptedIn: '{name} has not agreed to reminders yet. Turn on the switch below to send one.',
  reasonNothingDue: '{name} agreed to reminders. Nothing is due, so no reminder is needed.',
  reminderReady: 'Reminder ready',
  reminderOpen: 'Send on WhatsApp',
  reminderOpenSr: 'opens WhatsApp',
  reminderNoPhone: 'No phone number is saved. Add one to get the WhatsApp link.',
  reminderNone: 'The reminder was not created. Try again in a moment.',
  reminderFailed: 'The reminder was not created. Check the internet and press again.',
  phoneLabel: 'Mobile number',
  phoneHint: '10 digits, like 98xxxxxx10',
  phoneSave: 'Save number',
  phoneSaving: 'Saving…',
  phoneInvalid: 'This number does not look right. Enter a 10-digit mobile number.',
  phoneFailed: 'The number was not saved. Try again.',
  optInLabel: 'WhatsApp reminders',
  optInOnNote: 'On: you can send them a WhatsApp reminder of what is due. Nothing is sent without you.',
  optInOffNote: 'Off: they get no reminders. Turn on only if the customer agreed.',
  optInOn: 'On',
  optInOff: 'Off',
  optInSavedOn: 'Reminders turned on',
  optInSavedOff: 'Reminders turned off',
  optInFailed: 'The change was not saved. Check the internet and try again.',
  speak: 'Speak an entry for {name}',
  timeline: 'Entries',
  recorded: 'written',
  corrected: 'corrected',
  oldAmount: 'before',
  noEntries: 'No entries for them in the recent ledger.',
  historyCut: 'Only the latest 500 entries are checked; older entries do not show here.',
  loading: 'Opening the ledger…',
  notFoundTitle: 'Customer not found',
  notFoundBody: 'The link may be old or the name changed. Choose the customer from the ledger.',
  errorTitle: "The customer's ledger did not open",
  errorBody: 'Could not reach the server. Check the internet, then try again.',
  retry: 'Try again',
  offlineStale: 'You are offline. These figures may be out of date.',
};

const TABLES: Record<Lang, CustomerLabels> = { hi, en };

export function customerLabels(lang: Lang): CustomerLabels {
  return TABLES[lang];
}

export const CUSTOMER_TABLES = TABLES;
