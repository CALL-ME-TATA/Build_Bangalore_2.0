// The always-loaded part of the offline layer (no Dexie here): which cached data is on screen and when it was
// last synced, the outbox as shown, and the two entry points the data hooks and the session store call.
// The heavy parts (Dexie, Web Crypto, the sync driver) are imported on first use.
import { create } from 'zustand';
import type { Lang } from '../../i18n';
import { announce } from '../../components/LiveRegion';
import { ApiError } from '../api';
import { sessionMode } from '../session/mode';
import { offlineLabels } from './labels';
import { shouldQueue, type OutboxRecord } from './queue';
import type { ConnStatus } from '../session/types';

export interface OfflineState {
  /** Cache slot -> ISO time of the cached copy now on screen. A slot is absent when its data is fresh. */
  stale: Record<string, string>;
  /** ISO time of the last successful fetch per slot. */
  synced: Record<string, string>;
  /** The outbox as shown, oldest first. Empty until loaded. */
  outbox: OutboxRecord[];
}

export const useOffline = create<OfflineState>()(() => ({ stale: {}, synced: {}, outbox: [] }));

/** Cache slot for a query key: the session mode keeps mock data apart from real data. */
export function cacheSlot(queryKey: readonly unknown[]): string {
  return [sessionMode(), ...queryKey.filter((k) => k !== 'khata')].join(':');
}

const isOffline = () => typeof navigator !== 'undefined' && navigator.onLine === false;

/** True for errors that mean "the server could not be reached", as opposed to a refusal (401, 404). */
export function isUnreachable(e: unknown): boolean {
  if (e instanceof ApiError) return e.status === 0 || e.status >= 500;
  return e instanceof TypeError || (e instanceof DOMException && e.name === 'AbortError');
}

/**
 * Runs `fetcher` and keeps an encrypted copy of what it returns. When offline or the server cannot be
 * reached, returns the last copy instead and marks it stale; with no copy, the original error is thrown.
 * Mock mode is not cached.
 */
export async function withCache<T>(queryKey: readonly unknown[], fetcher: () => Promise<T>): Promise<T> {
  if (sessionMode() === 'mock') return fetcher();
  const slot = cacheSlot(queryKey);
  let failure: unknown = new TypeError('offline');
  if (!isOffline()) {
    try {
      const data = await fetcher();
      const now = new Date().toISOString();
      useOffline.setState((s) => {
        const { [slot]: _gone, ...stale } = s.stale;
        return { stale, synced: { ...s.synced, [slot]: now } };
      });
      void import('./cache').then((m) => m.saveCached(slot, data, now)).catch(() => undefined);
      return data;
    } catch (e) {
      if (!isUnreachable(e)) throw e;
      failure = e;
    }
  }
  const cached = await import('./cache').then((m) => m.loadCached<T>(slot)).catch(() => null);
  if (!cached) throw failure;
  useOffline.setState((s) => ({ stale: { ...s.stale, [slot]: cached.savedAt } }));
  return cached.data;
}

/** Oldest sync time among the cached data now on screen, or null when everything shown is fresh. */
export function staleSince(s: Pick<OfflineState, 'stale'>): string | null {
  const times = Object.values(s.stale).sort();
  return times[0] ?? null;
}

/** For screens: null when fresh, else the ISO time of the last sync of the data shown. */
export function useStaleSince(): string | null {
  return useOffline(staleSince);
}

/** Puts a typed sentence in the encrypted outbox; it is sent when the session is connected again. */
export function queueOffline(text: string, lang: Lang): void {
  announce(offlineLabels(lang).savedOffline);
  void import('./sync').then((m) => m.enqueue(text)).catch(() => announce(offlineLabels(lang).failedFromOutbox, 'assertive'));
}

/** Loads the outbox and starts sending it whenever the session can take it. Safe to call more than once. */
export function startOutbox(): void {
  void import('./sync').then((m) => m.startSync()).catch(() => undefined);
}

/** Whether the session store says a typed sentence should be queued (started, but no open socket or offline). */
export function shouldQueueText(s: { started: boolean; conn: ConnStatus }): boolean {
  return shouldQueue({ started: s.started, conn: s.conn, online: !isOffline() });
}
