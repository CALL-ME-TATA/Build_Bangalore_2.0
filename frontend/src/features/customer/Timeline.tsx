// One customer's entries grouped by date, as on the "Customer" board: eyebrow date headings (Aaj, Kal · 20 Nov,
// 19 Nov), rows with a hairline above, the amount (Spectral 22, min-width 92), the word Udhaar or Jama, the time.
// A corrected entry shows the old amount struck through in small ink-2 above the new one, labelled
// "Udhaar · sudhaara". A removed entry with nothing in its place (an undo) stays visible, struck through, labelled
// "Udhaar · hataya". History is never hidden. The API has no spoken phrase, so that line is left out.
// With `onEdit`, every active row is one button (44px+ tall, trailing pencil) that opens "Entry badlein";
// removed rows and reversal rows are plain text.
import { Pencil } from 'lucide-react';
import { kindLabel } from '../../lib/format';
import type { Entry } from '../../services/session/types';
import { labels, type Lang } from '../../i18n';
import { Amount } from '../../components/Amount';
import type { TimelineGroup } from './logic';
import { entryTime } from './logic';
import { customerLabels } from './labels';
import { isEditable } from './edit';

interface TimelineProps {
  groups: TimelineGroup[];
  lang: Lang;
  now: Date;
  cut: boolean;
  /** Opens the edit sheet of an active row. Absent: rows are not editable. */
  onEdit?: (entry: Entry) => void;
}

export function Timeline({ groups, lang, now, cut, onEdit }: TimelineProps) {
  const C = customerLabels(lang);
  const L = labels(lang);
  return (
    <section aria-label={C.timeline} className="flex flex-col">
      {groups.length ? (
        groups.map((g) => (
          <section key={g.date} aria-labelledby={`day-${g.date}`} className="flex flex-col">
            <h2 id={`day-${g.date}`} className="eyebrow pt-3.5 pb-2">
              {g.label}
            </h2>
            <ul>
              {g.items.map((it) => {
                const e = it.entry;
                const word = kindLabel(e.kind, lang);
                const label = it.replaced ? `${word} · ${C.corrected}` : e.reversed ? `${word} · ${L.removed}` : word;
                const body = (
                  <>
                    {it.replaced ? (
                      <span className="text-[0.875rem] text-ink-2 line-through decoration-1">
                        <span className="sr-only">{C.oldAmount}: </span>
                        <Amount value={it.replaced.amount} kind={it.replaced.kind} size="inherit" lang={lang} />
                      </span>
                    ) : null}
                    <Line entry={e} label={label} plain={!it.replaced && !e.reversed} lang={lang} now={now} />
                  </>
                );
                return (
                  <li key={String(e.id)} className="border-t border-line">
                    {onEdit && isEditable(e) ? (
                      <button
                        type="button"
                        id={`entry-edit-${e.id}`}
                        onClick={() => onEdit(e)}
                        className="flex min-h-14 w-full items-center gap-3 rounded-control py-3 text-start hover:bg-tint"
                      >
                        <span className="flex min-w-0 flex-1 flex-col gap-1">{body}</span>
                        <Pencil aria-hidden="true" size={18} strokeWidth={1.8} className="shrink-0 text-ink-2" />
                        <span className="sr-only">{C.editEntrySr}</span>
                      </button>
                    ) : (
                      <div className="flex flex-col gap-1 py-3">{body}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      ) : (
        <p className="border-t border-line pt-3 text-body text-ink-2">{C.noEntries}</p>
      )}
      {cut ? <p className="mt-4 max-w-prose text-meta text-ink-2">{C.historyCut}</p> : null}
    </section>
  );
}

function Line({ entry, label, plain, lang, now }: { entry: Entry; label: string; plain: boolean; lang: Lang; now: Date }) {
  const struck = entry.reversed ? 'text-ink-2 line-through decoration-1' : '';
  return (
    <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <span className={`min-w-[5.75rem] text-[1.375rem] leading-[1.2] ${struck}`}>
        <Amount value={entry.amount} kind={entry.kind} size="inherit" tone={!entry.reversed} lang={lang} />
      </span>
      {/* The amount's spoken label already says udhaar / jama; the visible word adds "sudhaara" or "hataya". */}
      <span className={`min-w-0 flex-1 text-[0.9375rem] font-medium ${entry.reversed ? 'text-ink-2' : 'text-ink'}`}>
        <span aria-hidden={plain || undefined}>{label}</span>
      </span>
      <span className="text-meta text-ink-2 tabular">{entryTime(entry, now, lang)}</span>
    </span>
  );
}
