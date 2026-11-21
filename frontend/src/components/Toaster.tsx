// Toasts (sonner), restyled to the tokens. Mounted lazily by the root layout; call `toast()` from
// lib/toast.ts, which loads sonner on first use.
import { Toaster as Sonner } from 'sonner';

export default function Toaster() {
  return (
    <Sonner
      position="top-center"
      offset={16}
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            'flex w-[min(24rem,calc(100vw-2rem))] items-center gap-3 rounded-control border border-line bg-surface px-4 py-3 text-label text-ink shadow-float',
          title: 'flex-1',
          actionButton: 'min-h-12 rounded-control border border-line-strong bg-surface px-3 text-label text-ink',
          cancelButton: 'min-h-12 rounded-control px-3 text-label text-ink-2',
        },
      }}
    />
  );
}
