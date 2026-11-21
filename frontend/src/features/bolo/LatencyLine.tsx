// The latency of the last turn in small meta text ("Server 840 ms · Phone 910 ms"). Tapping it opens the
// per-stage figures from the `timing` message, in plain words, with the phone's own figure last.
import { ChevronDown } from 'lucide-react';
import { useId, useState } from 'react';
import { labels, type Lang, type LabelKey } from '../../i18n';
import type { TimingKey } from '../../services/session/types';

/** Rows of the breakdown, in pipeline order; stages the server did not report are left out. */
export function latencyRows(ms: Partial<Record<TimingKey, number | null>>, phone: number | null, lang: Lang): { label: string; ms: number }[] {
  const L = labels(lang);
  const order: [TimingKey, LabelKey][] = [
    ['gnani_stt_latency', 'latencyGnani'],
    ['stt_final', 'latencyStt'],
    ['parse', 'latencyParse'],
    ['db', 'latencyDb'],
    ['tts_first_chunk', 'latencyTts'],
    ['end_to_first_audio', 'latencyServerFull'],
  ];
  const rows: { label: string; ms: number }[] = [];
  for (const [k, key] of order) {
    const v = ms[k];
    if (v != null && Number.isFinite(v)) rows.push({ label: L[key], ms: Math.round(v) });
  }
  if (phone != null) rows.push({ label: L.latencyPhoneFull, ms: Math.round(phone) });
  return rows;
}

export function LatencyLine({ server, phone, ms, lang }: { server: number | null; phone: number | null; ms: Partial<Record<TimingKey, number>>; lang: Lang }) {
  const L = labels(lang);
  const [open, setOpen] = useState(false);
  const id = useId();
  const rows = latencyRows(ms, phone, lang);
  const summary = [server != null ? `${L.latencyServer} ${server} ms` : '', phone != null ? `${L.latencyPhone} ${phone} ms` : ''].filter(Boolean).join(' · ');
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex min-h-12 items-center gap-1.5 self-start text-meta text-ink-2 tabular hover:text-ink"
      >
        <span>{summary}</span>
        <ChevronDown aria-hidden="true" size={14} strokeWidth={1.8} className={open ? 'rotate-180' : ''} />
        <span className="sr-only">{L.latencyTitle}</span>
      </button>
      <dl id={id} hidden={!open} className="flex max-w-prose flex-col border-t border-line">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-4 border-b border-line py-2 text-meta">
            <dt className="text-ink-2">{r.label}</dt>
            <dd className="shrink-0 text-ink tabular">
              {r.ms} {L.latencyMs}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
