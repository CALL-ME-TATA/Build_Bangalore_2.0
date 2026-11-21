// Mic states and the hold / tap gesture machine.
import { describe, expect, test } from 'vitest';
import { TAP_MS, gestureCancel, gestureDown, gestureIdle, gestureUp, micView, type GestureState, type MicInputs } from './mic';

const base: MicInputs = { started: true, greeted: true, phase: 'idle', mic: 'ready', error: null, conn: 'open', mode: 'hold' };

describe('micView', () => {
  test('the five visual states with their labels', () => {
    expect(micView(base)).toMatchObject({ visual: 'idle', labelKey: 'micIdle', disabled: false });
    expect(micView({ ...base, mode: 'toggle' }).labelKey).toBe('micIdleToggle');
    expect(micView({ ...base, phase: 'listening' })).toMatchObject({ visual: 'listening', labelKey: 'micListening' });
    expect(micView({ ...base, phase: 'hearing' })).toMatchObject({ visual: 'listening', labelKey: 'micListening', ariaKey: 'micAriaListening' });
    expect(micView({ ...base, phase: 'listening', latched: true }).labelKey).toBe('micListeningLatched');
    expect(micView({ ...base, phase: 'transcribing' })).toMatchObject({ visual: 'processing', labelKey: 'micProcessing' });
    expect(micView({ ...base, phase: 'thinking' })).toMatchObject({ visual: 'processing', labelKey: 'micProcessing', ariaKey: 'micAriaProcessing' });
    expect(micView(base).ariaKey).toBe('micAriaIdle');
    expect(micView({ ...base, phase: 'speaking' }).ariaKey).toBe('micAriaSpeaking');
    expect(micView({ ...base, phase: 'speaking' })).toMatchObject({ visual: 'speaking', labelKey: 'micSpeaking', disabled: false });
    expect(micView({ ...base, error: 'down', errorCode: 'upstream' })).toMatchObject({ visual: 'error', labelKey: 'errorGeneric', disabled: false });
    expect(micView({ ...base, error: 'TimeoutError', errorCode: 'tts_upstream' })).toMatchObject({ visual: 'error', labelKey: 'errorVoice' });
    expect(micView({ ...base, error: 'x', errorCode: 'no_connection' })).toMatchObject({ visual: 'error', labelKey: 'noConnection' });
  });

  test('disabled before the start step and until the greeting has played', () => {
    expect(micView({ ...base, started: false })).toMatchObject({ disabled: true, labelKey: 'micNotStarted' });
    expect(micView({ ...base, greeted: false, phase: 'speaking' })).toMatchObject({ disabled: true, visual: 'speaking', labelKey: 'micWaitGreeting' });
  });

  test('a blocked or failed microphone is an error with a way forward', () => {
    expect(micView({ ...base, mic: 'denied' })).toMatchObject({ visual: 'error', labelKey: 'micDenied', disabled: true });
    expect(micView({ ...base, mic: 'failed' })).toMatchObject({ visual: 'error', labelKey: 'micFailed', disabled: true });
  });

  test('reconnecting and offline explain themselves instead of failing silently', () => {
    expect(micView({ ...base, conn: 'reconnecting' })).toMatchObject({ labelKey: 'micReconnecting', disabled: true });
    expect(micView({ ...base, online: false })).toMatchObject({ labelKey: 'micOffline', disabled: true });
  });

  test('an accidental press leaves a hint on the idle label, not an error', () => {
    expect(micView({ ...base, hint: 'micTooShort' })).toMatchObject({ visual: 'idle', labelKey: 'micTooShort' });
  });
});

describe('gesture', () => {
  const play = (steps: [string, number][], mode: 'hold' | 'toggle') => {
    let g: GestureState = gestureIdle;
    const cmds: (string | null)[] = [];
    for (const [ev, t] of steps) {
      const [next, cmd] = ev === 'down' ? gestureDown(g, t, mode) : ev === 'up' ? gestureUp(g, t, mode) : gestureCancel(g);
      g = next;
      cmds.push(cmd);
    }
    return { g, cmds };
  };

  test('hold mode: hold to talk, release to send', () => {
    const { g, cmds } = play([['down', 0], ['up', 1200]], 'hold');
    expect(cmds).toEqual(['press', 'release']);
    expect(g).toEqual(gestureIdle);
  });

  test('hold mode: a press released within 300 ms is accidental and aborts (M03)', () => {
    const { g, cmds } = play([['down', 0], ['up', TAP_MS - 50]], 'hold');
    expect(cmds).toEqual(['press', 'abort']);
    expect(g).toEqual(gestureIdle);
    expect(play([['down', 0], ['up', TAP_MS]], 'hold').cmds).toEqual(['press', 'release']);
  });

  test('toggle mode: each tap flips, holding changes nothing', () => {
    const { cmds } = play([['down', 0], ['up', 2000], ['down', 3000], ['up', 3050]], 'toggle');
    expect(cmds).toEqual(['press', null, 'release', null]);
  });

  test('a repeated down while held is ignored (key repeat, second finger)', () => {
    const { cmds } = play([['down', 0], ['down', 10], ['up', 900]], 'hold');
    expect(cmds).toEqual(['press', null, 'release']);
  });

  test('cancel releases a held mic; in toggle mode it keeps the open mic', () => {
    expect(play([['down', 0], ['cancel', 500]], 'hold').cmds).toEqual(['press', 'release']);
    const t = play([['down', 0], ['cancel', 50]], 'toggle');
    expect(t.cmds).toEqual(['press', null]);
    expect(t.g).toMatchObject({ open: true, latched: true });
  });

  test('up without a down does nothing', () => {
    expect(gestureUp(gestureIdle, 5, 'hold')).toEqual([gestureIdle, null]);
  });
});
