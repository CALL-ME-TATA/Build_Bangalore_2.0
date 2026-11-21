// Pure helpers of the Settings screen.
import type { Customer } from '../../services/api';

export const SPEEDS = ['0.9', '1', '1.15'] as const;
export type Speed = (typeof SPEEDS)[number];

/** The stored rate as one of the three choices (anything else snaps to the nearest). */
export function speedChoice(rate: number): Speed {
  let best: Speed = '1';
  for (const s of SPEEDS) if (Math.abs(Number(s) - rate) < Math.abs(Number(best) - rate)) best = s;
  return best;
}

/** Customers whose name or tag contains `q` (case-insensitive), sorted by name. */
export function filterCustomers(list: readonly Customer[], q: string): Customer[] {
  const needle = q.trim().toLocaleLowerCase();
  return list
    .filter((c) => !needle || c.display.toLocaleLowerCase().includes(needle) || c.tags.some((t) => t.toLocaleLowerCase().includes(needle)))
    .sort((a, b) => a.display.localeCompare(b.display));
}
