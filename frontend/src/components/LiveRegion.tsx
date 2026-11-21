// Screen-reader announcements. One polite and one assertive region live in the root layout; anything can
// announce through `announce(text)` (polite: saved entries, mic states) or `announce(text, 'assertive')`
// (errors only). Polite messages are queued and each stays at least MIN_GAP_MS, so a saved entry is not
// overwritten by the mic state that follows it. Repeating the same text re-announces it.
import { useSyncExternalStore } from 'react';

type Politeness = 'polite' | 'assertive';

const MIN_GAP_MS = 1200;
const state = { polite: '', assertive: '', n: 0 };
const listeners = new Set<() => void>();
let snapshot = { ...state };
const queue: string[] = [];
let lastPolite = 0;
let timer: ReturnType<typeof setTimeout> | undefined;

function publish(politeness: Politeness, text: string) {
  state.n += 1;
  // A trailing zero-width space toggles so identical messages still change the DOM and are read again.
  state[politeness] = text + (state.n % 2 ? '​' : '');
  snapshot = { ...state };
  for (const fn of listeners) fn();
}

function drain() {
  timer = undefined;
  const next = queue.shift();
  if (next === undefined) return;
  publish('polite', next);
  lastPolite = Date.now();
  if (queue.length) timer = setTimeout(drain, MIN_GAP_MS);
}

export function announce(text: string, politeness: Politeness = 'polite'): void {
  if (politeness === 'assertive') {
    publish('assertive', text);
    return;
  }
  queue.push(text);
  if (queue.length > 3) queue.splice(0, queue.length - 3); // keep only the latest few
  if (timer) return;
  const wait = Math.max(0, lastPolite + MIN_GAP_MS - Date.now());
  if (wait === 0) drain();
  else timer = setTimeout(drain, wait);
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function LiveRegion() {
  const s = useSyncExternalStore(subscribe, () => snapshot, () => snapshot);
  return (
    <>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {s.polite}
      </div>
      <div className="sr-only" role="alert" aria-live="assertive" aria-atomic="true">
        {s.assertive}
      </div>
    </>
  );
}
