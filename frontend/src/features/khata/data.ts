// Server data shared by the Khata list and the Customer detail: GET /api/customers and GET /api/ledger?limit=500
// (the most the server returns), through the stage 1 query hooks so both refresh after every result.
// With `?synthetic=N` in mock mode or on the dev server, a generated khata of N customers is used instead, to
// check the long list in a browser.
import { useQuery } from '@tanstack/react-query';
import type { Customer, LedgerView } from '../../services/api';
import { queryKeys, useCustomers, useLedger } from '../../services/query';
import { sessionMode } from '../../services/session/mode';

export const LEDGER_LIMIT = 500;

/** N from `?synthetic=N` (1..5000) when allowed, else null. */
export function syntheticCount(search: string, allowed: boolean): number | null {
  if (!allowed) return null;
  const raw = new URLSearchParams(search).get('synthetic');
  if (raw === null) return null;
  const n = Math.floor(Number(raw));
  return Number.isFinite(n) && n > 0 ? Math.min(n, 5000) : null;
}

const synthetic = syntheticCount(
  typeof location === 'undefined' ? '' : location.search,
  import.meta.env.DEV || sessionMode() === 'mock',
);

export interface KhataData {
  customers: Customer[] | undefined;
  ledger: LedgerView | undefined;
  /** Nothing to show yet and a request is on its way. */
  loading: boolean;
  /** The last request failed (data, if any, is from before). */
  failed: boolean;
  /** Time of the last successful load, ms since epoch (0 when never loaded). */
  updatedAt: number;
  retry: () => void;
  synthetic: boolean;
}

export function syntheticKey() {
  return [...queryKeys.all, 'synthetic', synthetic ?? 0] as const;
}

export function useKhataData(): KhataData {
  const ledgerQ = useLedger(LEDGER_LIMIT);
  const customersQ = useCustomers();
  const fake = useQuery({
    queryKey: syntheticKey(),
    queryFn: async () => (await import('./synthetic')).syntheticKhata(synthetic ?? 0),
    enabled: synthetic !== null,
    staleTime: Infinity,
  });
  if (synthetic !== null) {
    return {
      customers: fake.data?.customers,
      ledger: fake.data?.ledger,
      loading: fake.isPending,
      failed: fake.isError,
      updatedAt: fake.dataUpdatedAt,
      retry: () => void fake.refetch(),
      synthetic: true,
    };
  }
  return {
    customers: customersQ.data,
    ledger: ledgerQ.data,
    // Paused (offline, never loaded) is not "loading": the offline state explains it instead.
    loading: (customersQ.isPending && customersQ.fetchStatus === 'fetching') || (ledgerQ.isPending && ledgerQ.fetchStatus === 'fetching'),
    failed: customersQ.isError || ledgerQ.isError,
    updatedAt: customersQ.dataUpdatedAt && ledgerQ.dataUpdatedAt ? Math.min(customersQ.dataUpdatedAt, ledgerQ.dataUpdatedAt) : 0,
    retry: () => {
      void customersQ.refetch();
      void ledgerQ.refetch();
    },
    synthetic: false,
  };
}
