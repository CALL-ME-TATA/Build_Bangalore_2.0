// On/off switch (role="switch"). The visible label is part of the control, so the whole row is the target.
// State is shown by knob position and an "On/Off" word, not colour alone.
import { useId } from 'react';

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  /** Optional one-line explanation under the label. */
  description?: string;
  /** Words for the state, e.g. ['Chalu', 'Band']. */
  stateWords?: [on: string, off: string];
  disabled?: boolean;
}

export function Switch({ checked, onCheckedChange, label, description, stateWords = ['On', 'Off'], disabled }: SwitchProps) {
  const descId = useId();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-describedby={description ? descId : undefined}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className="flex min-h-14 w-full items-center justify-between gap-4 py-2 text-start disabled:opacity-50"
    >
      <span className="min-w-0">
        <span className="block text-label">{label}</span>
        {description ? (
          <span id={descId} className="block text-meta text-ink-2">
            {description}
          </span>
        ) : null}
      </span>
      <span className="flex shrink-0 items-center gap-2">
        <span className="text-meta text-ink-2" aria-hidden="true">
          {checked ? stateWords[0] : stateWords[1]}
        </span>
        <span
          aria-hidden="true"
          className={`relative h-7 w-12 rounded-full border transition-colors ${checked ? 'border-ink bg-ink' : 'border-line-strong bg-tint'}`}
        >
          <span
            className={`absolute top-0.5 size-5.5 rounded-full transition-[left] ${checked ? 'left-[1.375rem] bg-paper' : 'left-0.5 bg-ink-2'}`}
          />
        </span>
      </span>
    </button>
  );
}
