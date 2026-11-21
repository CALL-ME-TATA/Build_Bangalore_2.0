// Search text and filter chip of the Khata list. Kept in a small store so they survive opening a customer and
// coming back (on a phone the list unmounts its rows while the detail is shown).
import { create } from 'zustand';
import type { KhataFilter } from './logic';

interface KhataView {
  query: string;
  filter: KhataFilter;
  setQuery(query: string): void;
  setFilter(filter: KhataFilter): void;
}

export const useKhataView = create<KhataView>()((set) => ({
  query: '',
  filter: 'all',
  setQuery: (query) => set({ query }),
  setFilter: (filter) => set({ filter }),
}));
