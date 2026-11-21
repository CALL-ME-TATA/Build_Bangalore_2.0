// Filter chip as drawn on the "Khata" board: 40px pill, 14px label; selected is ink with paper text, unselected
// is transparent with a line-strong border. The shared Chip has a different look (tint, check mark, 48px), so the
// Khata screen uses this one. The touch target is still 48px tall (an invisible extension above and below), and
// the state is exposed with aria-pressed and shown by a filled versus outlined shape, not by hue.
import type { ReactNode } from 'react';

export function FilterChip({ selected, onSelect, children }: { selected: boolean; onSelect: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`relative inline-flex min-h-10 items-center rounded-full border px-4 text-[0.875rem] after:absolute after:inset-x-0 after:-inset-y-1 after:content-[''] forced-colors:aria-pressed:underline ${
        selected ? 'border-ink bg-ink font-medium text-paper' : 'border-line-strong bg-transparent text-ink hover:bg-fill'
      }`}
    >
      {children}
    </button>
  );
}
