// One restrained bar chart of udhaar against jama, in plain SVG. Horizontal bars, one ruled row per bucket,
// so labels stay readable at 320px and 200% text (rows grow downwards instead of squeezing sideways).
// Udhaar is a solid bar, jama a striped (hatched) bar with an outline: told apart by pattern and by the
// legend's words and signs, not by colour alone. The drawing is hidden from screen readers; the same numbers
// are in a data table for screen readers, and shown as wrapping ruled rows after "Table mein dekhein".
import { useId, useState } from 'react';
import type { Lang } from '../../i18n';
import { Amount } from '../../components/Amount';
import { barPercent, chartMax, type Bucket, type Period } from './insights';
import type { HisaabLabels } from './labels';

interface BarChartProps {
  buckets: Bucket[];
  period: Period;
  totals: { credit: number; payment: number };
  L: HisaabLabels;
  lang: Lang;
}

function Swatch({ kind, hatchId }: { kind: 'credit' | 'payment'; hatchId: string }) {
  return (
    <svg aria-hidden="true" className="h-4 w-8 shrink-0" focusable="false">
      {kind === 'credit' ? (
        <rect x="0" y="0" width="100%" height="100%" className="fill-credit" />
      ) : (
        <rect x="0.5" y="0.5" width="31" height="15" fill={`url(#${hatchId})`} className="stroke-payment" strokeWidth="1" />
      )}
    </svg>
  );
}

export function BarChart({ buckets, period, totals, L, lang }: BarChartProps) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const hatchId = `jama-hatch-${uid}`;
  const tableId = `hisaab-table-${uid}`;
  const [showTable, setShowTable] = useState(false);
  const max = chartMax(buckets);

  return (
    <figure className="flex flex-col gap-4">
      <figcaption className="max-w-prose text-meta text-ink-2">{period === 'today' ? L.chartSummaryToday : L.chartSummaryWeek}</figcaption>

      {/* Pattern definition; zero-sized rather than display:none so every browser still paints it. */}
      <svg aria-hidden="true" focusable="false" width="0" height="0" className="absolute">
        <defs>
          <pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect x="0" y="0" width="2.5" height="6" className="fill-payment" />
          </pattern>
        </defs>
      </svg>

      <ul className="flex flex-wrap gap-x-6 gap-y-2 text-meta text-ink">
        <li className="inline-flex items-center gap-2">
          <Swatch kind="credit" hatchId={hatchId} />
          {L.legendCredit}
        </li>
        <li className="inline-flex items-center gap-2">
          <Swatch kind="payment" hatchId={hatchId} />
          {L.legendPayment}
        </li>
      </ul>

      <ul aria-hidden="true" className="ruled border-y border-line">
        {buckets.map((b) => {
          const c = barPercent(b.credit, max);
          const p = barPercent(b.payment, max);
          return (
            <li key={b.key} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3">
              <span className="min-w-[5.5rem] text-meta text-ink-2">{b.label}</span>
              {/* Bars are scaled to 96% of the track so the longest one, its 1px offset and its stroke stay inside. */}
              <svg className="h-7 min-w-[9rem] flex-1 overflow-hidden" focusable="false">
                <line x1="0.5" x2="0.5" y1="0" y2="100%" className="stroke-line-strong" strokeWidth="1" />
                {c > 0 ? <rect x="1" y="0" width={`${c * 0.96}%`} height="42%" className="fill-credit" /> : null}
                {p > 0 ? (
                  <rect x="1.5" y="58%" width={`${p * 0.96}%`} height="40%" fill={`url(#${hatchId})`} className="stroke-payment" strokeWidth="1" />
                ) : null}
              </svg>
            </li>
          );
        })}
      </ul>

      <table className="sr-only">
        <caption>{L.tableCaption}</caption>
        <thead>
          <tr>
            <th scope="col">{L.colWhen}</th>
            <th scope="col">{L.colCredit}</th>
            <th scope="col">{L.colPayment}</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.key}>
              <th scope="row">{b.label}</th>
              <td>
                <Amount value={b.credit} kind="credit" size="inherit" lang={lang} />
              </td>
              <td>
                <Amount value={b.payment} kind="payment" size="inherit" lang={lang} />
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">{L.total}</th>
            <td>
              <Amount value={totals.credit} kind="credit" size="inherit" lang={lang} />
            </td>
            <td>
              <Amount value={totals.payment} kind="payment" size="inherit" lang={lang} />
            </td>
          </tr>
        </tfoot>
      </table>

      <div>
        <button
          type="button"
          aria-expanded={showTable}
          aria-controls={tableId}
          onClick={() => setShowTable((v) => !v)}
          className="inline-flex min-h-12 items-center rounded-control px-1 text-label text-ink underline underline-offset-4 hover:no-underline"
        >
          {showTable ? L.hideTable : L.showTable}
        </button>
      </div>

      {/* The same numbers for sighted readers, as ruled rows that wrap instead of a wide table. */}
      <dl id={tableId} hidden={!showTable} className="ruled border-y border-line">
        {buckets.map((b) => (
          <div key={b.key} className="flex flex-wrap items-baseline gap-x-6 gap-y-1 py-3">
            <dt className="min-w-[5.5rem] text-label text-ink">{b.label}</dt>
            <dd className="flex flex-wrap gap-x-6 gap-y-1">
              <span className="inline-flex items-baseline gap-2">
                <span className="text-meta text-ink-2">{L.colCredit}</span>
                <Amount value={b.credit} kind="credit" size="md" lang={lang} />
              </span>
              <span className="inline-flex items-baseline gap-2">
                <span className="text-meta text-ink-2">{L.colPayment}</span>
                <Amount value={b.payment} kind="payment" size="md" lang={lang} />
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </figure>
  );
}
