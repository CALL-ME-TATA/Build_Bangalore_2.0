// The demo script: the greeting, then four spoken sentences, with the same numbers everywhere
// (Ramesh: ₹430 credit after the correction, ₹200 payment, balance ₹230).
import type { Lang } from '../../i18n';

export const DEMO_LINES: Record<Lang, string[]> = {
  hi: ['Ramesh ka 340 udhaar', 'Nahi, 430', 'Aur 200 payment mila', 'Aaj ka hisaab batao'],
  en: ['Ramesh 340 credit', 'No, 430', 'And 200 payment received', "Today's summary"],
};

export const DEMO_EXPECTED = { customer: 'Ramesh', credit: 430, payment: 200, balance: 230 } as const;

/** Progress of a run: before start, the greeting, sentence i (0-based), finished. */
export type DemoStep = { kind: 'idle' } | { kind: 'greeting' } | { kind: 'line'; index: number } | { kind: 'done' };

/** Position of `step` in the list [greeting, ...lines]; -1 before start, lines + 1 when finished. */
export function stepPosition(step: DemoStep, lines: number): number {
  if (step.kind === 'idle') return -1;
  if (step.kind === 'greeting') return 0;
  if (step.kind === 'line') return step.index + 1;
  return lines + 1;
}

/** State word of item `i` of [greeting, ...lines] for the current step. */
export function stepState(i: number, step: DemoStep, lines: number): 'done' | 'now' | 'next' {
  const pos = stepPosition(step, lines);
  if (i < pos) return 'done';
  if (i === pos) return 'now';
  return 'next';
}

/** How long the demo "holds the mic" for a sentence: long enough for the partial words to appear. */
export function holdMs(line: string): number {
  return 900 + line.split(/\s+/).filter(Boolean).length * 300;
}
