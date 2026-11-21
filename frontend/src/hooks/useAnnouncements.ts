// Screen-reader announcements for the session, mounted once in the root layout:
// - each mic state change, politely ("Sun raha hoon…")
// - each saved entry, politely ("Entry likhi: plus 340 rupees, udhaar, Ramesh")
// - errors, assertively
import { useEffect, useRef } from 'react';
import { labels } from '../i18n';
import { announce } from '../components/LiveRegion';
import { useMicView } from '../components/MicButton';
import { amountParts } from '../lib/format';
import { useSession } from '../state/session';

export function useAnnouncements(): void {
  const view = useMicView();
  const lang = useSession((s) => s.lang);
  const prev = useRef<string | null>(null);

  useEffect(() => {
    const L = labels(lang);
    if (view.errorText) {
      if (prev.current !== view.errorText) announce(view.errorText, 'assertive');
      prev.current = view.errorText;
      return;
    }
    const text = L[view.labelKey];
    if (prev.current !== text) {
      if (view.visual === 'error') announce(text, 'assertive');
      else if (prev.current !== null) announce(text);
    }
    prev.current = text;
  }, [view.labelKey, view.errorText, view.visual, lang]);

  useEffect(
    () =>
      useSession.subscribe((s, p) => {
        if (s.resultCount === p.resultCount || !s.result) return;
        const L = labels(s.lang);
        const active = s.result.entries.filter((e) => !e.reversed);
        if (!active.length) return;
        const parts = active.map((e) => `${amountParts(e.amount, { kind: e.kind, lang: s.lang }).label}, ${e.customer.display}`);
        announce(`${L.savedEntry}: ${parts.join('; ')}`);
      }),
    [],
  );
}
