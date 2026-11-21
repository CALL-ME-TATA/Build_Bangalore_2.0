// One ledger entry as a ruled row, as drawn on the boards.
//  - variant "row" (conversation, sheets):  + ₹340 | Udhaar · Ramesh / Aaj, 11:42 | Undo
//    Spectral 24/500 amount (₹ at 18px) in a 92px column, 15/500 label over a 13px date, Undo at the right.
//  - variant "compact" (the "Abhi likha gaya" side list):  − ₹200 | Jama · Ramesh | abhi
//    Spectral 20 amount in an 80px column, 15px label, 13px time on the right; an amended entry shows the
//    replaced amount struck through after the name.
// Credit and payment are told apart by sign AND word (and ink colour as a third cue). A reversed entry
// (corrected or undone) stays visible, struck through, with a "hataya / removed" label: history is never hidden.
// The row wraps on very narrow screens or very large text instead of scrolling sideways.
import { Undo2 } from 'lucide-react';
import type { Entry } from '../services/session/types';
import { labels, type Lang } from '../i18n';
import { amountParts, customerName, entryWhen, kindLabel, stamp } from '../lib/format';
import { Amount } from './Amount';

export interface EntryRowProps {
  entry: Entry;
  lang: Lang;
  /** Shows the Undo button (only on the newest active entry: the server can only undo that one). */
  onUndo?: () => void;
  /** The newest row of the side list, on the highlight surface. */
  highlight?: boolean;
  /** Fades and slides the row in (new entries only). */
  animate?: boolean;
  now?: Date;
  /** Element to render; rows inside a <ul> use 'li'. */
  as?: 'li' | 'div';
  variant?: 'row' | 'compact';
  /** For an amended entry, the entry it replaced (its amount is shown struck through). */
  replaced?: Entry;
}

export function EntryRow({ entry, lang, onUndo, highlight = false, animate = false, now, as: Tag = 'li', variant = 'row', replaced }: EntryRowProps) {
  const L = labels(lang);
  const word = kindLabel(entry.kind, lang);
  const name = customerName(entry.customer);
  const struck = entry.reversed ? 'text-ink-2 line-through decoration-1' : '';
  const enter = animate ? 'animate-row-in' : '';

  if (variant === 'compact') {
    return (
      <Tag
        className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 py-3 ${enter} ${
          highlight ? '-mx-2.5 rounded-nav bg-highlight px-2.5' : 'border-b border-line'
        }`}
      >
        <span className={`min-w-amount-sm ${struck}`}>
          <Amount value={entry.amount} kind={entry.kind} size="md" tone={!entry.reversed} lang={lang} />
        </span>
        <span className="min-w-[7rem] flex-1 text-label-sm text-ink">
          {word} · {name}
          {replaced ? (
            <>
              {' '}
              <span className="text-ink-2 line-through">
                <Amount value={replaced.amount} sign="none" size="inherit" className="font-sans" lang={lang} />
              </span>
            </>
          ) : null}
          {entry.reversed ? <span className="text-ink-2"> · {L.removed}</span> : null}
        </span>
        <span className="text-meta text-ink-2">{stamp(entry.ts, now, lang)}</span>
      </Tag>
    );
  }

  return (
    <Tag className={`flex flex-wrap items-center gap-x-3.5 gap-y-1 border-t border-line py-3 last:border-b ${enter}`}>
      <span className={`min-w-amount ${struck}`}>
        <Amount value={entry.amount} kind={entry.kind} size="lg" tone={!entry.reversed} lang={lang} />
      </span>
      <span className="flex min-w-[8rem] flex-1 flex-col gap-0.5">
        <span className="text-label-sm font-medium text-ink">
          {word} · {name}
        </span>
        <span className="text-meta text-ink-2">
          {entryWhen(entry, now, lang)}
          {entry.reversed ? <span className="font-semibold text-ink"> · {L.removed}</span> : null}
        </span>
      </span>
      {onUndo && !entry.reversed ? (
        <button
          type="button"
          onClick={onUndo}
          aria-label={`${L.undo} ${amountParts(entry.amount, { kind: entry.kind, lang }).label}, ${entry.customer.display}`}
          className="ms-auto inline-flex min-h-12 items-center gap-1.5 rounded-control px-3 text-label-sm text-ink-2 hover:text-ink"
        >
          <Undo2 aria-hidden="true" size={16} strokeWidth={1.8} />
          {L.undo}
        </button>
      ) : null}
    </Tag>
  );
}
