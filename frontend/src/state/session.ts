// Live voice session state (Zustand) and the single SessionService instance bound to it.
//
// Stage 2 usage:
//   const phase = useSession((s) => s.phase);          // any SessionState field
//   const turns = useSession(useShallow(conversation)); // selectors from ./session-reducer
//   startSession('hi'); session.press(); session.release(); session.sendText('Ramesh ka 340 udhaar');
import { create } from 'zustand';
import type { Lang } from '../i18n';
import { createSessionService } from '../services/session';
import type { MicStatus, SendOptions, SessionAction } from '../services/session/types';
import { useSettings } from './settings';
import { micLevel } from './level';
import { initialState, reduce, type SessionState } from './session-reducer';
import { queueOffline, shouldQueueText, startOutbox } from '../services/offline/status';

export * from './session-reducer';

export interface SessionStore extends SessionState {
  /** True once the start step was completed in this page load (audio unlocked, hello sent). */
  started: boolean;
  starting: boolean;
  dispatch(action: SessionAction): void;
}

export const useSession = create<SessionStore>()((set, get) => ({
  ...initialState,
  lang: useSettings.getState().language,
  started: false,
  starting: false,
  dispatch: (action) => set(reduce(get(), action)),
}));

const service = createSessionService({
  dispatch: (a) => useSession.getState().dispatch(a),
  getState: () => useSession.getState(),
  onLevel: (l) => micLevel.emit(l),
});

// A reply that came as text only (no audio, or a text-to-speech error) gets a short soft beep (N04).
useSession.subscribe((s, prev) => {
  if (s.beepSeq !== prev.beepSeq) service.beep();
});

/**
 * Sends a typed sentence on the socket now, never to the offline outbox (used by the outbox and by undo).
 * A retried sentence passes its first `uttId` (and the time it was typed as `clientTs`).
 */
export function sendTextNow(text: string, opts?: SendOptions): void {
  service.sendText(text, opts);
}

/**
 * The one voice session of the page. A sentence typed while the session is not connected goes to the
 * encrypted offline outbox (services/offline) and is sent, in order, when the connection is back.
 */
export const session: typeof service = {
  ...service,
  sendText(text, opts) {
    const s = useSession.getState();
    if (text.trim() && shouldQueueText(s)) queueOffline(text.trim(), s.lang);
    else service.sendText(text, opts);
  },
};

/**
 * Start step: must run inside a user gesture (tap) so audio can play. Opens the session in `lang`,
 * remembers the language and asks for the microphone.
 */
export async function startSession(lang: Lang): Promise<MicStatus> {
  const st = useSession.getState();
  if (st.starting) return st.mic;
  useSettings.getState().set('language', lang);
  useSession.setState({ starting: true });
  session.setVoiceSpeed(useSettings.getState().voiceSpeed);
  session.setPrivate(useSettings.getState().privateMode);
  try {
    const mic = await session.start(lang);
    useSession.setState({ started: true });
    startOutbox();
    return mic;
  } finally {
    useSession.setState({ starting: false });
  }
}

/** Sends the undo sentence in the current language. */
export function sendUndo(): void {
  sendTextNow(useSession.getState().lang === 'en' ? 'undo' : 'undo karo');
}
