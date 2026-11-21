// The mic. One control hook (useMicControl) drives two looks:
//  - MicButton: the round accent button (80px in an 88px box on phones, 72px in the desktop mic bar)
//  - MicTextButton: a full-width quiet button, the talk control inside the doubt sheet ("Dobara boliye")
//
// States (lib/mic.ts micView): idle -> listening -> processing -> speaking -> error. Every state has a visible
// label and an accessible name saying what pressing does now ("Bolna shuru karein", "Bolna band karein"…).
// State changes are announced once, politely, by useAnnouncements() in the root layout.
//
// Input: hold-to-talk and tap-to-toggle (settings.micMode; in hold mode a short tap also latches the mic
// open). Pointer, Space and Enter on the focused control, Space anywhere for the `globalSpace` instance, and a
// plain click from assistive technology (detail 0) toggles.
import { Mic, MicOff, Volume2, AudioLines } from 'lucide-react';
import { useEffect, useId, useRef, type KeyboardEvent, type MouseEvent, type PointerEvent, type ReactNode } from 'react';
import { labels, type LabelKey } from '../i18n';
import { micView, type MicVisual } from '../lib/mic';
import { micCancel, micDown, micTap, micUp, useMicGesture } from '../state/mic';
import { micLevel } from '../state/level';
import { useSession } from '../state/session';
import { useSettings } from '../state/settings';
import { useOnline } from '../hooks/useOnline';

/** Current mic view from the stores; shared by the controls, the wave bar and the announcer. */
export function useMicView() {
  const started = useSession((s) => s.started);
  const greeted = useSession((s) => s.greeted);
  const phase = useSession((s) => s.phase);
  const mic = useSession((s) => s.mic);
  const error = useSession((s) => s.error);
  const errorCode = useSession((s) => s.errorCode);
  const conn = useSession((s) => s.conn);
  const mode = useSettings((s) => s.micMode);
  const latched = useMicGesture((s) => s.latched);
  const hint = useSession((s) => s.hint);
  const online = useOnline();
  return micView({ started, greeted, phase, mic, error, errorCode, conn, mode, latched, hint, online });
}

function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  if (t.isContentEditable) return true;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return true;
  // Space activates other buttons, links and switches; leave those alone. Inside the question sheet (a dialog)
  // Space still talks, so a question can be answered by holding Space ("Bol kar jawab dijiye").
  if (t.closest('button, a, [role="switch"], [role="button"]') && !t.closest('[data-mic]')) return true;
  return false;
}

interface ControlOptions {
  globalSpace?: boolean;
  onNotStarted?: () => void;
}

/** Event handlers, state and labels for any mic control. */
export function useMicControl({ globalSpace = false, onNotStarted }: ControlOptions = {}) {
  const view = useMicView();
  const started = useSession((s) => s.started);
  const lang = useSession((s) => s.lang);
  const open = useMicGesture((s) => s.open);
  const pointerActive = useRef(false);
  const disabled = view.disabled;
  const L = labels(lang);

  // Hold Space anywhere (desktop). Released on keyup or when the window loses focus.
  useEffect(() => {
    if (!globalSpace) return;
    let held = false;
    const down = (e: globalThis.KeyboardEvent) => {
      if (e.code !== 'Space' || isTypingTarget(e.target)) return;
      e.preventDefault();
      if (e.repeat || held || disabled) return;
      held = true;
      micDown();
    };
    const up = (e: globalThis.KeyboardEvent) => {
      if (e.code !== 'Space' || !held) return;
      e.preventDefault();
      held = false;
      micUp();
    };
    const blur = () => {
      if (!held) return;
      held = false;
      micCancel();
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', blur);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
      window.removeEventListener('blur', blur);
    };
  }, [globalSpace, disabled]);

  const blocked = () => {
    if (!started) onNotStarted?.();
    return disabled;
  };

  const handlers = {
    onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
      if (e.button !== 0 || blocked()) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture?.(e.pointerId);
      pointerActive.current = true;
      micDown();
    },
    onPointerUp: () => {
      if (!pointerActive.current) return;
      pointerActive.current = false;
      micUp();
    },
    onPointerCancel: () => {
      if (!pointerActive.current) return;
      pointerActive.current = false;
      micCancel();
    },
    onLostPointerCapture: () => {
      if (!pointerActive.current) return;
      pointerActive.current = false;
      micUp();
    },
    onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.key !== ' ' && e.key !== 'Enter') return;
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat || blocked()) return;
      micDown();
    },
    onKeyUp: (e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.key !== ' ' && e.key !== 'Enter') return;
      e.preventDefault();
      e.stopPropagation();
      micUp();
    },
    onClick: (e: MouseEvent<HTMLButtonElement>) => {
      // Pointer and keyboard are handled above; a click with detail 0 and no pointer is assistive technology.
      if (e.detail !== 0 || pointerActive.current) return;
      if (blocked()) return;
      micTap();
    },
    onContextMenu: (e: MouseEvent<HTMLButtonElement>) => e.preventDefault(),
  };

  return { view, open, disabled, L, handlers, label: (key: LabelKey) => L[key] };
}

function MicIcon({ visual, size }: { visual: MicVisual; size: number }) {
  const props = { 'aria-hidden': true, size, strokeWidth: 1.9 } as const;
  if (visual === 'error') return <MicOff {...props} />;
  if (visual === 'speaking') return <Volume2 {...props} />;
  if (visual === 'listening') return <AudioLines {...props} />;
  return <Mic {...props} />;
}

export type MicSize = 'hero' | 'desk' | 'sheet' | 'mini';

export interface MicButtonProps {
  /** hero: 80px (phones); desk: 72px (desktop mic bar). 'sheet' and 'mini' are kept as aliases of hero. */
  size?: MicSize;
  /** Show the state label under the button (default true). */
  showLabel?: boolean;
  /** Replaces the idle label. */
  idleLabel?: string;
  /** Hold Space anywhere on the page to talk (one instance per page). */
  globalSpace?: boolean;
  /** Called on press before the start step was completed. */
  onNotStarted?: () => void;
  id?: string;
  className?: string;
  /** Rendered beside the button instead of the label under it (the desktop mic bar). */
  aside?: (label: string, labelId: string) => ReactNode;
}

export function MicButton({ size = 'hero', showLabel = true, idleLabel, globalSpace = false, onNotStarted, id, className = '', aside }: MicButtonProps) {
  const { view, open, disabled, L, handlers } = useMicControl({ globalSpace, onNotStarted });
  const ref = useRef<HTMLButtonElement>(null);
  const labelId = useId();
  const desk = size === 'desk';

  // A thin ring follows the audio level without re-rendering React.
  useEffect(() => {
    if (view.visual !== 'listening') {
      ref.current?.style.setProperty('--level', '0');
      return;
    }
    return micLevel.subscribe((l) => ref.current?.style.setProperty('--level', l.toFixed(3)));
  }, [view.visual]);

  const label = view.visual === 'idle' && idleLabel && view.labelKey !== 'micNotStarted' ? idleLabel : L[view.labelKey];

  const button = (
    <span className={`flex shrink-0 items-center justify-center ${desk ? 'size-mic-desk' : 'size-mic-box'}`}>
      <button
        ref={ref}
        id={id}
        type="button"
        data-mic=""
        data-vaul-no-drag=""
        data-state={view.visual}
        aria-disabled={disabled || undefined}
        aria-pressed={open}
        aria-label={L[view.ariaKey]}
        aria-describedby={showLabel || aside ? labelId : undefined}
        className={`mic ${desk ? 'size-mic-desk' : 'size-mic'}`}
        {...handlers}
      >
        <MicIcon visual={view.visual} size={desk ? 28 : 30} />
      </button>
    </span>
  );

  if (aside) {
    return (
      <div className={`flex items-center gap-5 ${className}`} data-mic="">
        {button}
        {aside(label, labelId)}
      </div>
    );
  }

  return (
    <div className={`flex flex-col items-center gap-3 ${className}`} data-mic="">
      {button}
      {showLabel ? (
        <p id={labelId} className={`min-h-[1.4em] text-center text-small ${view.visual === 'error' ? 'text-credit' : 'text-ink-2'}`}>
          {label}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The talk control as a full-width quiet button (doubt sheet). Press or tap to speak; the visible text
 * shows the listening state ("Dobara boliye" when idle).
 */
export function MicTextButton({ idleLabel, id, className = '' }: { idleLabel: string; id?: string; className?: string }) {
  const { view, open, disabled, L, handlers } = useMicControl();
  const text = view.visual === 'idle' || view.visual === 'error' ? idleLabel : L[view.labelKey];
  return (
    <button
      id={id}
      type="button"
      data-mic=""
      data-vaul-no-drag=""
      data-state={view.visual}
      aria-disabled={disabled || undefined}
      aria-pressed={open}
      className={`flex min-h-13 w-full touch-none items-center justify-center gap-2 rounded-control bg-fill px-4 text-label font-medium text-ink select-none aria-pressed:bg-tint aria-disabled:opacity-60 ${className}`}
      {...handlers}
    >
      <MicIcon visual={view.visual === 'error' ? 'idle' : view.visual} size={18} />
      <span>{text}</span>
    </button>
  );
}
