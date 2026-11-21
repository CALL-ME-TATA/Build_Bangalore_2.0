// Plays the demo on the scripted mock session, never on the real server: its own store (same reducer as
// the real session), its own fresh mock ledger, and its own mock SessionService. Nothing here touches the
// page's real session, so leaving the demo leaves the real session exactly as it was.
import { create } from 'zustand';
import type { Lang } from '../../i18n';
import type { MockLedger } from '../../services/mock/ledger';
import type { SessionAction, SessionService } from '../../services/session/types';
import { initialState, reduce, type SessionState } from '../../state/session-reducer';
import { DEMO_LINES, holdMs, type DemoStep } from './script';

export interface DemoState extends SessionState {
  dispatch(action: SessionAction): void;
}

export function createDemoStore(lang: Lang) {
  return create<DemoState>()((set, get) => ({
    ...initialState,
    lang,
    dispatch: (action) => set(reduce(get(), action)),
  }));
}

export type DemoStore = ReturnType<typeof createDemoStore>;

export interface DemoHandle {
  ledger: MockLedger;
  /** Resolves with 'done' at the end, 'stopped' after stop(); rejects if the run failed. */
  finished: Promise<'done' | 'stopped'>;
  stop(): void;
}

class Stopped extends Error {}

/** Resolves when `pred` holds (or after `timeoutMs`, so a lost message never hangs the demo). */
function waitFor(store: DemoStore, pred: (s: DemoState) => boolean, signal: AbortSignal, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new Stopped());
    if (pred(store.getState())) return resolve();
    const done = () => {
      clearTimeout(timer);
      unsub();
      signal.removeEventListener('abort', abort);
    };
    const abort = () => {
      done();
      reject(new Stopped());
    };
    const timer = setTimeout(() => {
      done();
      resolve();
    }, timeoutMs);
    const unsub = store.subscribe((s) => {
      if (!pred(s)) return;
      done();
      resolve();
    });
    signal.addEventListener('abort', abort);
  });
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new Stopped());
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, ms);
    const abort = () => {
      clearTimeout(timer);
      reject(new Stopped());
    };
    signal.addEventListener('abort', abort, { once: true });
  });
}

const atRest = (s: DemoState) => s.phase === 'idle' && s.audioTurn == null;

/** Starts a run. `onStep` reports progress; `ledger` is a fresh, empty mock ledger owned by this run. */
export async function runDemo(store: DemoStore, lang: Lang, onStep: (step: DemoStep) => void): Promise<DemoHandle> {
  const [{ createMockSession }, { MockLedger }] = await Promise.all([
    import('../../services/session/mock-session'),
    import('../../services/mock/ledger'),
  ]);
  const ledger = new MockLedger(false);
  const ctrl = new AbortController();
  const service: SessionService = createMockSession(
    { dispatch: (a) => store.getState().dispatch(a), getState: () => store.getState(), onLevel: () => undefined },
    { ledger, script: DEMO_LINES },
  );
  const signal = ctrl.signal;
  const lines = DEMO_LINES[lang];

  const play = async (): Promise<'done' | 'stopped'> => {
    try {
      onStep({ kind: 'greeting' });
      await service.start(lang);
      await waitFor(store, (s) => s.greeted && atRest(s), signal, 15_000);
      await sleep(600, signal);
      for (let i = 0; i < lines.length; i++) {
        onStep({ kind: 'line', index: i });
        const before = store.getState().resultCount;
        service.press();
        await sleep(holdMs(lines[i] ?? ''), signal);
        service.release();
        await waitFor(store, (s) => s.resultCount > before && atRest(s), signal, 20_000);
        await sleep(800, signal);
      }
      onStep({ kind: 'done' });
      return 'done';
    } catch (e) {
      if (e instanceof Stopped) return 'stopped';
      throw e;
    }
  };

  const finished = play();
  return {
    ledger,
    finished,
    stop() {
      ctrl.abort();
      service.close();
    },
  };
}
