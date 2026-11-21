// Fixed labels of the offline cache and outbox, in the same { hi, en } shape as src/i18n.ts.
import type { Lang } from '../../i18n';

const hi = {
  savedOffline: 'Offline save hua · net aate hi jaayega',
  sending: 'Bhej raha hoon…',
  notSent: 'Nahi gaya',
  sendAgain: 'Dobara bhejein',
  remove: 'Hatayein',
  removeLabel: 'Yeh sentence hataiye',
  sendAgainLabel: 'Yeh sentence dobara bhejiye',
  youTyped: 'Aapne likha',
  outboxTitle: 'Bhejna baaki',
  speakNeedsNet: 'Bolne ke liye internet chahiye. Abhi type karke likhiye, connection aate hi bhej dunga.',
  sentFromOutbox: 'Offline wala sentence bhej diya',
  failedFromOutbox: 'Offline wala sentence nahi gaya',
  stale: 'Purana data ho sakta hai',
  lastSync: 'Aakhri sync',
  reasonNoConnection: 'Connection nahi mila',
  reasonTimeout: 'Jawab nahi aaya',
  reasonError: 'Kuch gadbad hui',
};

export type OfflineLabelKey = keyof typeof hi;
export type OfflineLabels = Record<OfflineLabelKey, string>;

const en: OfflineLabels = {
  savedOffline: 'Saved offline · will sync',
  sending: 'Sending…',
  notSent: 'Not sent',
  sendAgain: 'Send again',
  remove: 'Remove',
  removeLabel: 'Remove this sentence',
  sendAgainLabel: 'Send this sentence again',
  youTyped: 'You typed',
  outboxTitle: 'Waiting to send',
  speakNeedsNet: 'Speaking needs a connection. Type for now; I will send it when the connection is back.',
  sentFromOutbox: 'Offline sentence sent',
  failedFromOutbox: 'An offline sentence was not sent',
  stale: 'May be out of date',
  lastSync: 'Last synced',
  reasonNoConnection: 'No connection',
  reasonTimeout: 'No answer came',
  reasonError: 'Something went wrong',
};

export const OFFLINE_LABELS: Record<Lang, OfflineLabels> = { hi, en };

export function offlineLabels(lang: Lang): OfflineLabels {
  return OFFLINE_LABELS[lang];
}

/** A failure reason as shown: short codes become words, server reply text is shown as it came. */
export function reasonText(reason: string | null, lang: Lang): string {
  const L = OFFLINE_LABELS[lang];
  if (!reason) return L.reasonError;
  if (reason === 'no_connection') return L.reasonNoConnection;
  if (reason === 'timeout') return L.reasonTimeout;
  if (reason === 'error' || reason === 'rejected') return L.reasonError;
  return reason;
}
