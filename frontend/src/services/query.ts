// TanStack Query setup: the client, query keys and hooks for server data.
// Ledger and customer queries are invalidated after every `result` (see useRefreshOnResult).
// Both go through the encrypted offline cache (services/offline/status.ts): offline, they return the last
// copy and useStaleSince() tells the screen when it was synced. networkMode 'always' lets them run offline.
import { QueryClient, queryOptions, useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { getCustomers, getLedger, type LedgerOptions } from './api';
import { useSession } from '../state/session';
import { withCache } from './offline/status';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

export const queryKeys = {
  all: ['khata'] as const,
  ledger: (limit = 50, opts: LedgerOptions = {}) => ['khata', 'ledger', limit, opts.order ?? 'created', opts.customerId ?? null] as const,
  customers: () => ['khata', 'customers'] as const,
  reminders: () => ['khata', 'reminders'] as const,
};

/** Creation order by default ("Abhi likha gaya", Khata); `order: 'date'` for a customer's timeline. */
export function ledgerQuery(limit = 50, opts: LedgerOptions = {}) {
  const queryKey = queryKeys.ledger(limit, opts);
  return queryOptions({ queryKey, queryFn: () => withCache(queryKey, () => getLedger(limit, opts)), networkMode: 'always' });
}

export function customersQuery() {
  const queryKey = queryKeys.customers();
  return queryOptions({ queryKey, queryFn: () => withCache(queryKey, getCustomers), networkMode: 'always' });
}

export function useLedger(limit = 50) {
  return useQuery(ledgerQuery(limit));
}

/** One customer's entries by entry date (GET /api/ledger?order=date&customer_id=X). */
export function useCustomerLedger(customerId: string | undefined, limit = 500, enabled = true) {
  return useQuery({ ...ledgerQuery(limit, { order: 'date', customerId }), enabled: enabled && Boolean(customerId) });
}

export function useCustomers() {
  return useQuery(customersQuery());
}

/** Refreshes every khata query when a new `result` arrives. Mount once, in the root layout. */
export function useRefreshOnResult(): void {
  useEffect(
    () =>
      useSession.subscribe((s, prev) => {
        if (s.resultCount !== prev.resultCount) void queryClient.invalidateQueries({ queryKey: queryKeys.all });
      }),
    [],
  );
}
