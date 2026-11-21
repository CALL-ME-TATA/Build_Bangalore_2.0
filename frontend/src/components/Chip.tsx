// Filter chip (Sab / Baaki wale / Aaj). A toggle button with aria-pressed; selected chips use the tint
// surface and a check mark so the state is not shown by colour alone.
import { Check } from 'lucide-react';
import type { ButtonHTMLAttributes } from 'react';

export interface ChipProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'> {
  selected: boolean;
  onSelectedChange?: (selected: boolean) => void;
}

export function Chip({ selected, onSelectedChange, className = '', children, onClick, ...rest }: ChipProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={(e) => {
        onClick?.(e);
        onSelectedChange?.(!selected);
      }}
      className={`inline-flex min-h-12 items-center gap-1.5 rounded-chip border px-4 text-label transition-colors ${
        selected ? 'border-ink bg-tint text-ink' : 'border-line-strong bg-transparent text-ink-2 hover:text-ink'
      } ${className}`}
      {...rest}
    >
      {selected ? <Check aria-hidden="true" size={16} strokeWidth={1.75} /> : null}
      {children}
    </button>
  );
}
