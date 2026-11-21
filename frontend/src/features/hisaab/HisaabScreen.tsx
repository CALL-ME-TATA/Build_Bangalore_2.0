// Hisaab (insights). One hero: the period's two totals. Then one bar chart of udhaar against jama, the top
// five dues and "Suniye", which asks the running session for the spoken summary. Every number is computed
// here from the ledger (last 500 entries) and the customer list; reversed entries do not count.
// Offline, the last synced data is shown with a "may be out of date" note.
import { Link } from '@tanstack/react-router';
import { Volume2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Amount } from '../../components/Amount';
import { Avatar } from '../../components/Avatar';
import { Button } from '../../components/Button';
import { useLang } from '../../hooks/useLabels';
import { useOnline } from '../../hooks/useOnline';
import { customerName } from '../../lib/format';
import { StaleNote } from '../../services/offline/OfflineNotes';
import { useCustomers, useLedger } from '../../services/query';
import { sendTextNow, useSession } from '../../state/session';
import { BarChart } from './BarChart';
import { Pill, ScreenHeader } from './ScreenParts';
import { LEDGER_LIMIT, computeInsights, dateLine, duesTotal, topDues, type Period } from './insights';
import { useHisaabLabels } from './labels';

export function HisaabScreen() {
  const L = useHisaabLabels();
  const lang = useLang();
  const [period, setPeriod] = useState<Period>('today');
  const [now] = useState(() => new Date());
  const ledger = useLedger(LEDGER_LIMIT);
  const customers = useCustomers();

  const insights = useMemo(() => computeInsights(ledger.data?.entries ?? [], period, now, lang), [ledger.data, period, now, lang]);
  const dues = useMemo(() => topDues(customers.data ?? [], 5), [customers.data]);
  const owed = useMemo(() => duesTotal(customers.data ?? []), [customers.data]);

  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-talk px-5 pt-6 pb-48 outline-none lg:px-10 lg:pt-12 lg:pb-24">
      <ScreenHeader title={L.title} line={dateLine(now, lang)}>
        <StaleNote className="pt-2" />
      </ScreenHeader>

      <div role="group" aria-label={L.periodLabel} className="mt-6 flex flex-wrap gap-2 py-1">
        <Pill selected={period === 'today'} onClick={() => setPeriod('today')}>
          {L.today}
        </Pill>
        <Pill selected={period === 'week'} onClick={() => setPeriod('week')}>
          {L.week}
          <span className="sr-only">, {L.weekSub}</span>
        </Pill>
      </div>

      {ledger.isPending ? (
        <p className="mt-10 text-body text-ink-2" role="status">
          {L.loading}
        </p>
      ) : ledger.isError && !ledger.data ? (
        <p className="mt-10 max-w-prose text-body text-ink">{L.failed}</p>
      ) : (
        <>
          <section aria-labelledby="hisaab-totals" className="mt-8">
            <h2 id="hisaab-totals" className="sr-only">
              {period === 'today' ? L.today : L.week}
            </h2>
            <dl className="grid grid-cols-1 border-y border-line min-[22rem]:grid-cols-2">
              <div className="flex flex-col gap-1 py-4 min-[22rem]:pe-4">
                <dt className="text-meta text-ink-2">{L.creditGiven}</dt>
                <dd>
                  <Amount value={insights.credit} kind="credit" size="total" lang={lang} />
                </dd>
              </div>
              <div className="flex flex-col gap-1 border-t border-line py-4 min-[22rem]:border-t-0 min-[22rem]:border-s min-[22rem]:ps-4">
                <dt className="text-meta text-ink-2">{L.paymentIn}</dt>
                <dd>
                  <Amount value={insights.payment} kind="payment" size="total" lang={lang} />
                </dd>
              </div>
            </dl>
            <p className="mt-2.5 text-[0.875rem] text-ink-2">
              {insights.count} {insights.count === 1 ? L.entriesCount : L.entriesCountMany}
              {customers.data ? (
                <>
                  {' · '}
                  {L.totalDue} <Amount value={owed.total} sign="none" size="inherit" lang={lang} className="font-semibold text-ink" /> · {owed.count}{' '}
                  {L.customersWithDue}
                </>
              ) : null}
            </p>
            {insights.truncated ? <p className="mt-1 text-meta text-ink-2">{L.truncated}</p> : null}
          </section>

          <section aria-labelledby="hisaab-chart" className="mt-12 flex flex-col gap-4">
            <h2 id="hisaab-chart" className="eyebrow">
              {L.chartTitle}
            </h2>
            {insights.count === 0 ? <p className="text-body text-ink-2">{L.noEntries}</p> : null}
            <BarChart buckets={insights.buckets} period={period} totals={insights} L={L} lang={lang} />
          </section>
        </>
      )}

      <section aria-labelledby="hisaab-dues" className="mt-12 flex flex-col gap-2">
        <h2 id="hisaab-dues" className="eyebrow">
          {L.topDues}
        </h2>
        {dues.length ? (
          <ol className="ruled border-b border-line">
            {dues.map((c) => (
              <li key={c.id}>
                <Link
                  to="/khata/$id"
                  params={{ id: c.id }}
                  className="-mx-2 flex min-h-16 items-center gap-3.5 rounded-control px-2 py-2 hover:bg-fill"
                >
                  <Avatar name={c.display} size="sm" />
                  <span className="min-w-0 flex-1 text-label text-ink">{customerName(c)}</span>
                  <span className="flex flex-col items-end">
                    <Amount value={c.balance} sign="none" size="md" lang={lang} className="text-credit" />
                    <span className="text-meta text-ink-2">{L.baaki}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        ) : customers.isSuccess ? (
          <p className="text-body text-ink-2">{L.nobodyOwes}</p>
        ) : null}
      </section>

      <Listen />
    </main>
  );
}

/** "Suniye": sends the summary request as a text turn on the running session and shows the reply text. */
function Listen() {
  const L = useHisaabLabels();
  const started = useSession((s) => s.started);
  const greeted = useSession((s) => s.greeted);
  const conn = useSession((s) => s.conn);
  const online = useOnline();
  const [asked, setAsked] = useState<number | null>(null);
  const [reply, setReply] = useState<{ text: string; lang: string } | null>(null);
  const ready = started && greeted && conn === 'open' && online;
  const reason = !started ? L.listenNotStarted : !online || conn !== 'open' ? L.listenOffline : null;

  useEffect(() => {
    if (asked === null) return;
    return useSession.subscribe((s) => {
      if (s.resultCount > asked && s.result) {
        setReply({ text: s.result.replyText, lang: s.lang });
        setAsked(null);
      }
    });
  }, [asked]);

  const listen = () => {
    if (!ready) return;
    setReply(null);
    setAsked(useSession.getState().resultCount);
    sendTextNow(L.listenText);
  };

  return (
    <section aria-labelledby="hisaab-listen" className="mt-12 flex flex-col items-start gap-3">
      <h2 id="hisaab-listen" className="sr-only">
        {L.listen}
      </h2>
      <Button
        variant="secondary"
        size="md"
        className="w-full sm:w-auto sm:min-w-[16rem]"
        icon={<Volume2 size={20} strokeWidth={1.75} />}
        onClick={listen}
        disabled={!ready}
        aria-describedby="hisaab-listen-note"
      >
        {L.listen}
      </Button>
      <p id="hisaab-listen-note" className="max-w-prose text-meta text-ink-2">
        {reason ?? L.listenHint}
      </p>
      {!started ? (
        <Link to="/" className="inline-flex min-h-12 items-center text-label text-ink underline underline-offset-4 hover:no-underline">
          {L.goBolo}
        </Link>
      ) : null}
      {asked !== null ? (
        <p role="status" className="text-body text-ink-2">
          {L.listenWaiting}
        </p>
      ) : null}
      {reply?.text ? (
        <p className="flex max-w-prose items-start gap-3 text-body text-ink" lang={reply.lang}>
          <Volume2 aria-hidden="true" size={18} strokeWidth={1.75} className="mt-1 shrink-0 text-ink-2" />
          <span>
            <span className="sr-only">{L.reply}: </span>
            {reply.text}
          </span>
        </p>
      ) : null}
    </section>
  );
}
