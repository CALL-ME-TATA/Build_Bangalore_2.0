// The live khata column, as drawn on the Desktop board (right column on desktop, left pane on tablet):
//  - "Aaj": credit given and payments received, Spectral 30 in the ledger inks
//  - "Abhi likha gaya": the latest entries, newest first and highlighted; an amended entry shows the replaced
//    amount struck through; the time is "abhi", "N min" or the clock
//  - "Sabse zyada baaki": the three highest dues
//  - "Aaj ka hisaab suniye": sends the daily-summary question to the session, so the answer is spoken
// Updates live: entries of this session come from the session store at once; the ledger and customers are
// refetched after every result. The caller sets the display (e.g. "hidden sm:flex").
import { Volume2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { labels } from '../i18n';
import { Amount } from '../components/Amount';
import { EntryRow } from '../components/EntryRow';
import { customerName } from '../lib/format';
import { useCustomers, useLedger } from '../services/query';
import type { Entry } from '../services/session/types';
import { session, useSession } from '../state/session';

/** Latest entries: the server's recent list with this session's entries (in their latest state) merged in. */
export function recentEntries(server: Entry[], saved: Entry[], amendedFrom: Record<string, Entry>, n = 5): Entry[] {
  const byId = new Map<string, Entry>();
  for (const e of server) byId.set(String(e.id), e);
  for (const e of saved) byId.set(String(e.id), { ...byId.get(String(e.id)), ...e });
  // An entry replaced by an amend is shown on its replacement, not on its own row.
  const replaced = new Set(Object.values(amendedFrom).map((e) => String(e.id)));
  return [...byId.values()]
    .filter((e) => !replaced.has(String(e.id)))
    .sort((a, b) => (Date.parse(b.ts) || 0) - (Date.parse(a.ts) || 0) || Number(b.id) - Number(a.id))
    .slice(0, n);
}

/** Re-renders every 30 s so "abhi" / "N min" stay true. */
function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

const HEAD = 'text-meta font-semibold tracking-[0.08em] text-ink-2 uppercase';

export function TodayPanel({ className = '' }: { className?: string }) {
  const lang = useSession((s) => s.lang);
  const saved = useSession((s) => s.saved);
  const amendedFrom = useSession((s) => s.amendedFrom);
  const greeted = useSession((s) => s.greeted);
  const resultCount = useSession((s) => s.resultCount);
  const L = labels(lang);
  const ledger = useLedger(50);
  const customers = useCustomers();
  const now = useNow();
  const recent = recentEntries(ledger.data?.entries ?? [], saved, amendedFrom);
  const dues = (customers.data ?? [])
    .filter((c) => c.balance > 0)
    .sort((a, b) => b.balance - a.balance)
    .slice(0, 3);
  const totals = ledger.data?.totals;
  const failed = ledger.isError && customers.isError;

  return (
    <aside aria-labelledby="today-title" className={`flex-col gap-7 ${className}`}>
      <section className="flex flex-col gap-3.5">
        <h2 id="today-title" className={HEAD}>
          {L.today}
        </h2>
        <dl className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-0.5">
            <dt className="text-meta text-ink-2">{L.creditGiven}</dt>
            <dd>
              <Amount value={totals?.credit_today ?? 0} kind="credit" size="total" tone lang={lang} />
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-meta text-ink-2">{L.paymentIn}</dt>
            <dd>
              <Amount value={totals?.payment_today ?? 0} kind="payment" size="total" tone lang={lang} />
            </dd>
          </div>
        </dl>
        {failed ? <p className="text-meta text-ink-2">{L.dataUnavailable}</p> : null}
      </section>

      <section aria-labelledby="recent-title" className="flex flex-col">
        <h2 id="recent-title" className={`${HEAD} mb-2`}>
          {L.justWritten}
        </h2>
        {recent.length ? (
          <ul>
            {recent.map((e, i) => (
              <EntryRow
                key={`${String(e.id)}-${i === 0 ? resultCount : 0}`}
                entry={e}
                lang={lang}
                variant="compact"
                highlight={i === 0}
                animate={i === 0}
                now={now}
                replaced={amendedFrom[String(e.id)]}
              />
            ))}
          </ul>
        ) : (
          <p className="text-label-sm text-ink-2">{L.nothingYet}</p>
        )}
      </section>

      <section aria-labelledby="dues-title" className="flex flex-col">
        <h2 id="dues-title" className={`${HEAD} mb-2`}>
          {L.topDues}
        </h2>
        {dues.length ? (
          <ul>
            {dues.map((c) => (
              <li key={c.id} className="flex justify-between gap-3 border-b border-line py-2.5 text-label-sm">
                <span className="min-w-0 text-ink">{customerName(c)}</span>
                <Amount value={c.balance} sign="none" size="inherit" className="font-sans font-medium text-credit" lang={lang} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-label-sm text-ink-2">{customers.isSuccess ? L.nobodyOwes : ''}</p>
        )}
      </section>

      <button
        type="button"
        disabled={!greeted}
        onClick={() => session.sendText(L.summaryText)}
        className="mt-auto flex min-h-12 items-center justify-center gap-2 rounded-control border border-line-strong bg-surface px-4 text-label-sm font-medium text-ink disabled:opacity-50"
      >
        <Volume2 aria-hidden="true" size={18} strokeWidth={1.8} />
        {L.summaryButton}
      </button>
    </aside>
  );
}
