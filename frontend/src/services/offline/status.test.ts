// Offline cache entry point: slot names, stale marking and the fallback to the last copy.
import { beforeEach, expect, test, vi } from 'vitest';

const store = new Map<string, { data: unknown; savedAt: string }>();
vi.mock('./cache', () => ({
  saveCached: vi.fn(async (slot: string, data: unknown, savedAt: string) => {
    store.set(slot, { data, savedAt });
  }),
  loadCached: vi.fn(async (slot: string) => store.get(slot) ?? null),
}));

const { cacheSlot, isUnreachable, staleSince, useOffline, withCache } = await import('./status');
const { ApiError } = await import('../api');

beforeEach(() => {
  store.clear();
  useOffline.setState({ stale: {}, synced: {}, outbox: [] });
});

test('slots are namespaced by session mode and drop the common prefix', () => {
  expect(cacheSlot(['khata', 'ledger', 500])).toBe('ws:ledger:500');
  expect(cacheSlot(['khata', 'customers'])).toBe('ws:customers');
});

test('unreachable means network failure or 5xx, not a refusal', () => {
  expect(isUnreachable(new TypeError('Failed to fetch'))).toBe(true);
  expect(isUnreachable(new ApiError('/api/ledger', 502))).toBe(true);
  expect(isUnreachable(new ApiError('/api/ledger', 401))).toBe(false);
  expect(isUnreachable(new Error('x'))).toBe(false);
});

test('a fresh fetch is returned, cached and marked fresh', async () => {
  const data = { entries: [], totals: { credit_today: 430, payment_today: 200 } };
  await expect(withCache(['khata', 'ledger', 500], async () => data)).resolves.toBe(data);
  await vi.waitFor(() => expect(store.get('ws:ledger:500')?.data).toEqual(data));
  expect(useOffline.getState().stale).toEqual({});
  expect(useOffline.getState().synced['ws:ledger:500']).toBeTruthy();
});

test('when the server cannot be reached, the last copy is returned and marked stale', async () => {
  store.set('ws:customers', { data: [{ id: 'c1', display: 'Ramesh', balance: 230 }], savedAt: '2026-11-21T06:12:00.000Z' });
  const out = await withCache(['khata', 'customers'], async () => {
    throw new TypeError('Failed to fetch');
  });
  expect(out).toEqual([{ id: 'c1', display: 'Ramesh', balance: 230 }]);
  expect(staleSince(useOffline.getState())).toBe('2026-11-21T06:12:00.000Z');
});

test('with no copy the original error is thrown; refusals are never hidden', async () => {
  await expect(withCache(['khata', 'customers'], () => Promise.reject(new TypeError('Failed to fetch')))).rejects.toThrow('Failed to fetch');
  store.set('ws:customers', { data: [], savedAt: '2026-11-21T06:12:00.000Z' });
  await expect(withCache(['khata', 'customers'], () => Promise.reject(new ApiError('/api/customers', 401)))).rejects.toThrow('401');
});

test('staleSince is the oldest of the stale slots', () => {
  expect(staleSince({ stale: {} })).toBeNull();
  expect(staleSince({ stale: { a: '2026-11-21T09:00:00.000Z', b: '2026-11-20T18:00:00.000Z' } })).toBe('2026-11-20T18:00:00.000Z');
});
