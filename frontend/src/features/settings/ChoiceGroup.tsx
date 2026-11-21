// A labelled group of native radio buttons drawn as canvas pills (see ../hisaab/ScreenParts.tsx). The legend
// names the setting and says the current choice in words ("Text ka size · Abhi: Bada"); the chosen pill is
// filled ink, the others outlined, so the state never depends on colour. The chosen option's explanation (if
// any) is shown under the pills.
import { useId } from 'react';
import { PILL_BASE, PILL_OFF, PILL_ON } from '../hisaab/ScreenParts';

export interface Choice<T extends string> {
  value: T;
  label: string;
  /** Explanation shown under the group while this option is chosen, e.g. "Chhodte hi bhej dega". */
  sub?: string;
  lang?: string;
}

interface ChoiceGroupProps<T extends string> {
  legend: string;
  currentWord: string;
  value: T;
  options: Choice<T>[];
  onChange: (value: T) => void;
  note?: string;
}

export function ChoiceGroup<T extends string>({ legend, currentWord, value, options, onChange, note }: ChoiceGroupProps<T>) {
  const name = useId();
  const noteId = useId();
  const subId = useId();
  const current = options.find((o) => o.value === value);
  const described = [note ? noteId : '', current?.sub ? subId : ''].filter(Boolean).join(' ') || undefined;
  return (
    <fieldset className="flex min-w-0 flex-col gap-3" aria-describedby={described}>
      <legend className="text-label text-ink">
        {legend}
        {current ? (
          <span className="font-normal text-ink-2">
            {' · '}
            {currentWord}: {current.label}
          </span>
        ) : null}
      </legend>
      {note ? (
        <p id={noteId} className="-mt-1 max-w-prose text-meta text-ink-2">
          {note}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2 py-1">
        {options.map((o) => {
          const checked = o.value === value;
          return (
            <label
              key={o.value}
              lang={o.lang}
              className={`${PILL_BASE} ${checked ? PILL_ON : PILL_OFF} cursor-pointer has-focus-visible:outline-2 has-focus-visible:outline-offset-3 has-focus-visible:outline-accent`}
            >
              <input type="radio" name={name} value={o.value} checked={checked} onChange={() => onChange(o.value)} className="sr-only" />
              {o.label}
            </label>
          );
        })}
      </div>
      {current?.sub ? (
        <p id={subId} className="text-meta text-ink-2">
          {current.sub}
        </p>
      ) : null}
    </fieldset>
  );
}
