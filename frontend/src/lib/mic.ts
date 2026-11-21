// Pure logic behind the mic button: which of the five visual states to show, the label under it,
// and the gesture state machine that gives both hold-to-talk and tap-to-toggle.
import type { LabelKey } from '../i18n';
import type { ConnStatus, MicStatus, ServerPhase } from '../services/session/types';

/** The five designed states of the mic. */
export type MicVisual = 'idle' | 'listening' | 'processing' | 'speaking' | 'error';

export interface MicView {
  visual: MicVisual;
  /** Label key for the visible state line; `errorText` wins when set. */
  labelKey: LabelKey;
  /** Accessible name of the mic button: what pressing it does now. */
  ariaKey: LabelKey;
  /** Free text to show instead of the label (announced assertively); null when the label says it all. */
  errorText: string | null;
  /** True when pressing does nothing (not started, greeting still playing, mic unavailable). */
  disabled: boolean;
}

export interface MicInputs {
  started: boolean;
  greeted: boolean;
  phase: ServerPhase;
  mic: MicStatus;
  error: string | null;
  /** Server error code, or "no_connection" for the local notice. */
  errorCode?: string | null;
  conn: ConnStatus;
  mode: MicMode;
  /** The mic was opened by a tap and stays open until the next tap. */
  latched?: boolean;
  /** The browser is online (navigator.onLine). Offline, the mic explains that speaking needs a connection. */
  online?: boolean;
  /** A short hint after an accidental press, shown on the idle label. */
  hint?: LabelKey | null;
}

export function micView(s: MicInputs): MicView {
  const v = (visual: MicVisual, labelKey: LabelKey, disabled = false): MicView => ({
    visual,
    labelKey,
    ariaKey:
      visual === 'listening'
        ? 'micAriaListening'
        : visual === 'processing'
          ? 'micAriaProcessing'
          : visual === 'speaking'
            ? 'micAriaSpeaking'
            : 'micAriaIdle',
    errorText: null,
    disabled,
  });
  if (!s.started) return v('idle', 'micNotStarted', true);
  if (s.mic === 'denied') return v('error', 'micDenied', true);
  if (s.mic === 'nodevice') return v('error', 'micNoDevice', true);
  if (s.mic === 'insecure') return v('error', 'micInsecure', true);
  if (s.mic === 'failed') return v('error', 'micFailed', true);
  // Speaking needs a connection (O01): say so instead of failing silently. Typing still works (it is queued).
  if (s.online === false) return v('idle', 'micOffline', true);
  if (!s.greeted) return v(s.phase === 'speaking' ? 'speaking' : 'processing', 'micWaitGreeting', true);
  const listening = s.latched || s.mode === 'toggle' ? 'micListeningLatched' : 'micListening';
  switch (s.phase) {
    case 'listening':
    case 'hearing':
      return v('listening', listening);
    case 'transcribing':
    case 'thinking':
      return v('processing', 'micProcessing');
    case 'speaking':
      return v('speaking', 'micSpeaking');
    default:
      break;
  }
  if (s.error) {
    // Server messages are technical ("TimeoutError"); show what happened and what to do instead.
    if (s.errorCode === 'no_connection') return v('error', 'noConnection');
    if (s.errorCode === 'tts_upstream') return v('error', 'errorVoice');
    return v('error', 'errorGeneric');
  }
  if (s.conn === 'reconnecting' || s.conn === 'connecting') return v('idle', 'micReconnecting', true);
  if (s.hint) return v('idle', s.hint);
  return v('idle', s.mode === 'toggle' ? 'micIdleToggle' : 'micIdle');
}

// ---- gesture ------------------------------------------------------------------------------------------------

export type MicMode = 'hold' | 'toggle';

/** A hold-mode press released sooner than this is accidental (M03). Tap-to-toggle is the "toggle" mode. */
export const TAP_MS = 300;

export interface GestureState {
  /** The mic is streaming (press() was sent and release() not yet). */
  open: boolean;
  /** Open because of a tap; the next down closes it. */
  latched: boolean;
  /** Time of the current down, or null when not held. */
  downAt: number | null;
}

export const gestureIdle: GestureState = { open: false, latched: false, downAt: null };

/** press: open the mic; release: send; abort: an accidental hold-mode press (released within TAP_MS). */
export type GestureCommand = 'press' | 'release' | 'abort' | null;

/**
 * Pointer or key down. Hold mode: opens the mic (or closes a latched one). Toggle mode: each down flips it.
 * A down while already held (key repeat, second finger) is ignored.
 */
export function gestureDown(g: GestureState, now: number, mode: MicMode): [GestureState, GestureCommand] {
  if (g.downAt != null) return [g, null];
  if (g.open) return [{ open: false, latched: false, downAt: now }, 'release'];
  return [{ open: true, latched: mode === 'toggle', downAt: now }, 'press'];
}

/**
 * Pointer or key up. Hold mode: a hold of TAP_MS or more releases (sends); a shorter press is accidental and
 * aborts (M03: `cancel`, a hint, no error). Toggle mode: nothing happens on up; the next down sends.
 */
export function gestureUp(g: GestureState, now: number, mode: MicMode): [GestureState, GestureCommand] {
  if (g.downAt == null) return [g, null];
  const held = now - g.downAt;
  if (!g.open) return [{ ...g, downAt: null }, null]; // the down closed the mic; nothing more to do
  if (mode === 'toggle' || g.latched) return [{ ...g, downAt: null }, null];
  if (held < TAP_MS) return [gestureIdle, 'abort'];
  return [gestureIdle, 'release'];
}

/** Pointer cancelled (scroll, palm, system gesture): close the mic if it was held, keep a latch. */
export function gestureCancel(g: GestureState): [GestureState, GestureCommand] {
  if (g.downAt == null) return [g, null];
  if (g.open && !g.latched) return [gestureIdle, 'release'];
  return [{ ...g, downAt: null }, null];
}

/** The session ended the turn by itself (or was barged by another control): forget the gesture. */
export function gestureReset(): GestureState {
  return gestureIdle;
}
