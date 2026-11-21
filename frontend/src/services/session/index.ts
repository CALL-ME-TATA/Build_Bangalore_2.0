// Entry point for the voice session. Both implementations are loaded on demand (preload() warms the
// chunk after first paint), so neither adds to the initial download. The AudioContext is created
// synchronously inside the start tap, before any await, because some browsers only unlock audio there.
import type { Lang } from '../../i18n';
import { sessionMode, type SessionMode } from './mode';
import type { MicStatus, SessionHost, SessionService } from './types';

export type { SessionService, SessionHost, MicStatus } from './types';
export { sessionMode } from './mode';

/**
 * Returns a SessionService for `mode` (default: sessionMode()). Calls made before start() resolves are
 * ignored except setLang and setVoiceSpeed, which are remembered.
 */
export function createSessionService(host: SessionHost, mode: SessionMode = sessionMode()): SessionService & { preload(): void } {
  let impl: SessionService | null = null;
  let lang: Lang | null = null;
  let speed = 1;
  let priv = false;
  const load = () => (mode === 'mock' ? import('./mock-session').then((m) => m.createMockSession) : import('./ws-session').then((m) => m.createWsSession));

  return {
    kind: mode,
    /** Fetches the implementation ahead of the start tap. */
    preload() {
      void load();
    },
    start(startLang: Lang): Promise<MicStatus> {
      const audio = mode === 'ws' && !impl ? unlockAudio() : null; // synchronous, still inside the tap
      return (async () => {
        if (!impl) {
          const create = await load();
          impl = create(host);
          impl.setVoiceSpeed(speed);
          impl.setPrivate(priv);
          if (lang) impl.setLang(lang);
        }
        return impl.start(startLang, audio);
      })();
    },
    press: () => impl?.press(),
    release: () => impl?.release(),
    abort: () => impl?.abort(),
    sendText: (text, opts) => impl?.sendText(text, opts),
    setPrivate(on) {
      priv = on;
      impl?.setPrivate(on);
    },
    beep: () => impl?.beep(),
    setSpoken: (code) => impl?.setSpoken(code),
    setLang(next) {
      lang = next;
      impl?.setLang(next);
    },
    setVoiceSpeed(rate) {
      speed = rate;
      impl?.setVoiceSpeed(rate);
    },
    close: () => impl?.close(),
  };
}

/** Creates and resumes an AudioContext; must be called synchronously from a user gesture. */
function unlockAudio(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const AC: typeof AudioContext | undefined =
    window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  const ctx = new AC({ latencyHint: 'interactive' });
  void ctx.resume();
  return ctx;
}
