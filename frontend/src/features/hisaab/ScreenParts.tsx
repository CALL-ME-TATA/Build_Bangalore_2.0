// Small pieces in the visual language of the design canvas (Khata and Desktop boards), shared by the Hisaab,
// Settings and Demo screens:
// - ScreenHeader: Spectral 32/500 title (40 on desktop) with a 14px ink-2 line under it (beside it on desktop).
// - Pill: the canvas chip. 40px tall visually (with an invisible 4px extension above and below, so the touch
//   target is 48px), fully rounded, 14px. Selected: ink fill with paper text; unselected: transparent with a
//   line-strong border. Filled versus outlined, so the state is not colour alone; aria-pressed carries it.
import type { ButtonHTMLAttributes, ReactNode } from 'react';

export function ScreenHeader({ title, line, children }: { title: ReactNode; line?: ReactNode; children?: ReactNode }) {
  return (
    <header className="flex flex-col gap-1">
      <div className="flex flex-col gap-1 lg:flex-row lg:flex-wrap lg:items-baseline lg:justify-between lg:gap-x-6">
        <h1 className="font-display text-[2rem] leading-[1.1] font-medium tracking-[-0.02em] text-ink lg:text-[2.5rem]">{title}</h1>
        {line ? <p className="text-[0.875rem] leading-[1.4] text-ink-2">{line}</p> : null}
      </div>
      {children}
    </header>
  );
}

export const PILL_BASE =
  "relative inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full border px-4 py-1.5 text-start text-[0.875rem] leading-[1.3] transition-colors before:absolute before:inset-x-0 before:-inset-y-1 before:content-['']";
export const PILL_ON = 'border-ink bg-ink font-medium text-paper';
export const PILL_OFF = 'border-line-strong bg-transparent text-ink hover:bg-fill';

export interface PillProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected: boolean;
}

/** A toggle pill (aria-pressed). */
export function Pill({ selected, className = '', children, ...rest }: PillProps) {
  return (
    <button type="button" aria-pressed={selected} className={`${PILL_BASE} ${selected ? PILL_ON : PILL_OFF} ${className}`} {...rest}>
      {children}
    </button>
  );
}
