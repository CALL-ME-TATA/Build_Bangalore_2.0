// Fixed labels of the demo screen, in the same { hi, en } shape as src/i18n.ts.
import type { Lang } from '../../i18n';
import { useLang } from '../../hooks/useLabels';

const hi = {
  title: 'Demo',
  badge: 'Demo',
  subtitle: 'Namoona data · scripted session',
  banner: 'Yeh demo hai: namoona data, scripted session. Asli khata aur server ko nahi chhoota.',
  leave: 'Is screen se jaate hi asli session wapas aa jaata hai.',
  intro: 'Ek button dabaiye. Poora flow apne aap chalega, awaaz ke saath.',
  run: 'Demo chalaiye',
  stop: 'Demo rokiye',
  again: 'Dobara chalaiye',
  steps: 'Kadam',
  stepGreeting: 'Namaste aur AI parichay',
  stateDone: 'Ho gaya',
  stateNow: 'Abhi',
  stateNext: 'Baaki',
  conversation: 'Demo baatcheet',
  youSaid: 'Dukaandaar ne kaha',
  aiSpeaker: 'KhataVaani, AI sahayak',
  aiBadge: 'AI sahayak',
  ledger: 'Demo khata',
  summary: 'Demo hisaab, aaj',
  creditGiven: 'Udhaar diya',
  paymentIn: 'Jama aaya',
  baaki: 'baaki',
  nothingYet: 'Demo shuru hote hi entries yahan dikhengi.',
  finished: 'Demo poora hua.',
  stopped: 'Demo roka gaya.',
  failed: 'Demo nahi chal paaya. Dobara chalaiye.',
};

export type DemoLabelKey = keyof typeof hi;
export type DemoLabels = Record<DemoLabelKey, string>;

const en: DemoLabels = {
  title: 'Demo',
  badge: 'Demo',
  subtitle: 'Sample data · scripted session',
  banner: 'This is a demo: sample data and a scripted session. Your real ledger and the server are not touched.',
  leave: 'Leaving this screen brings the real session back.',
  intro: 'Press one button. The whole flow plays by itself, with voice.',
  run: 'Play the demo',
  stop: 'Stop the demo',
  again: 'Play again',
  steps: 'Steps',
  stepGreeting: 'Greeting and AI disclosure',
  stateDone: 'Done',
  stateNow: 'Now',
  stateNext: 'Next',
  conversation: 'Demo conversation',
  youSaid: 'The shopkeeper said',
  aiSpeaker: 'KhataVaani, AI assistant',
  aiBadge: 'AI assistant',
  ledger: 'Demo ledger',
  summary: 'Demo summary, today',
  creditGiven: 'Credit given',
  paymentIn: 'Payments received',
  baaki: 'due',
  nothingYet: 'Entries appear here once the demo starts.',
  finished: 'The demo is finished.',
  stopped: 'The demo was stopped.',
  failed: 'The demo could not play. Please try again.',
};

export const DEMO_LABELS: Record<Lang, DemoLabels> = { hi, en };

export function useDemoLabels(): DemoLabels {
  return DEMO_LABELS[useLang()];
}
