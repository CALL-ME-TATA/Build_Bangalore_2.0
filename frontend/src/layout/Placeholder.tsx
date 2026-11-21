// Placeholder screen for routes not built yet: the main landmark and the screen header as on the Khata
// board (Spectral 32 title, 14px date under it; Spectral 40 on desktop).
import type { ReactNode } from 'react';
import type { LabelKey } from '../i18n';
import { useLabels, useLang } from '../hooks/useLabels';
import { longDate } from '../lib/format';

export function Placeholder({ titleKey, children }: { titleKey: LabelKey; children?: ReactNode }) {
  const L = useLabels();
  const lang = useLang();
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-talk px-6 pt-7 pb-48 outline-none lg:px-10 lg:pt-10">
      <header className="flex flex-col gap-1">
        <h1 className="font-display text-title-md text-ink lg:text-title-lg">{L[titleKey]}</h1>
        <span className="text-small text-ink-2">{longDate(new Date(), lang)}</span>
      </header>
      <p className="mt-6 max-w-prose text-body text-ink-2">{L.comingSoon}</p>
      {children}
    </main>
  );
}
