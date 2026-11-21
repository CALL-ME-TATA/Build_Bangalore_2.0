// Small form parts shared by the edit sheets: a labelled field, the error line, the segmented choice of an entry
// kind, and the form's validation error state.
import { useId, useState, type ReactNode } from 'react';
import type { FormError } from './edit';

export const INPUT_CLASS =
  'block min-h-12 w-full min-w-0 rounded-control border border-line-strong bg-surface px-3 text-body text-ink tabular disabled:opacity-50';

export function SheetHeading({ children }: { children: ReactNode }) {
  return <h2 className="text-[1.25rem] leading-[1.35] font-semibold text-ink">{children}</h2>;
}

interface FieldProps {
  label: string;
  hint?: string;
  /** Receives the input id and the id of the hint to describe it with. */
  children: (ids: { id: string; describedBy: string | undefined }) => ReactNode;
}

/** A label above a control, with an optional hint line under it. */
export function Field({ label, hint, children }: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-label text-ink">
        {label}
      </label>
      {children({ id, describedBy: hint ? hintId : undefined })}
      {hint ? (
        <p id={hintId} className="text-meta text-ink-2">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** The form's one error line; announced when it appears. */
export function ErrorLine({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-meta font-semibold text-ink">
      {children}
    </p>
  );
}

export interface KindOption<T extends string> {
  value: T;
  label: string;
}

interface KindPickerProps<T extends string> {
  legend: string;
  options: readonly KindOption<T>[];
  value: T | null;
  onChange: (v: T) => void;
  disabled?: boolean;
}

/** Radio buttons drawn as large segments (Udhaar / Jama / Maaf). */
export function KindPicker<T extends string>({ legend, options, value, onChange, disabled }: KindPickerProps<T>) {
  const name = useId();
  return (
    <fieldset className="flex min-w-0 flex-col gap-1.5" disabled={disabled}>
      <legend className="mb-1.5 text-label text-ink">{legend}</legend>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(6rem,1fr))] gap-2">
        {options.map((o) => (
          <label
            key={o.value}
            className="flex min-h-12 cursor-pointer items-center justify-center rounded-control border border-line-strong bg-surface px-2 text-center text-label text-ink has-[:checked]:border-accent has-[:checked]:bg-accent has-[:checked]:text-on-accent has-[:disabled]:opacity-50 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ink"
          >
            <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} className="sr-only" />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** The form's validation error line (a failed save is reported by a toast after the sheet has closed). */
export function useFormError() {
  const [error, setError] = useState<FormError | null>(null);
  return { error, setError };
}
