// Shared gesture state for every mic control (the hero button, the mini mic, the doubt sheet's mic and the
// Space key), so a hold started on one is released by any of them.
import { create } from 'zustand';
import { gestureCancel, gestureDown, gestureIdle, gestureUp, type GestureCommand, type GestureState } from '../lib/mic';
import { session } from './session';
import { useSettings } from './settings';

export const useMicGesture = create<GestureState>()(() => gestureIdle);

function run([next, cmd]: [GestureState, GestureCommand]) {
  useMicGesture.setState(next, true);
  if (cmd === 'press') session.press();
  else if (cmd === 'release') session.release();
  else if (cmd === 'abort') session.abort();
}

export function micDown(now: number = performance.now()): void {
  run(gestureDown(useMicGesture.getState(), now, useSettings.getState().micMode));
}

export function micUp(now: number = performance.now()): void {
  run(gestureUp(useMicGesture.getState(), now, useSettings.getState().micMode));
}

export function micCancel(): void {
  run(gestureCancel(useMicGesture.getState()));
}

/** A complete tap (assistive technology click with no pointer events): flips the mic. */
export function micTap(): void {
  const g = useMicGesture.getState();
  if (g.open) run([gestureIdle, 'release']);
  else run([{ open: true, latched: true, downAt: null }, 'press']);
}
