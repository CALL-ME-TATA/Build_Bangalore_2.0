// /demo: one button auto-plays the pitch flow on the scripted mock session (greeting, "Ramesh ka 340 udhaar",
// "Nahi, 430", "Aur 200 payment mila", "Aaj ka hisaab batao"). It is labelled as a demo throughout; the
// conversation, the demo khata row and the demo hisaab are all read from the run's own mock ledger, so the
// numbers agree everywhere (Ramesh: ₹430 credit, ₹200 payment, ₹230 due). Leaving the route stops the run;
// the page's real session was never touched.
import { Check, Volume2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { useStore } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import type { Lang } from '../../i18n';
import { Amount } from '../../components/Amount';
import { Avatar } from '../../components/Avatar';
import { Button } from '../../components/Button';
import { EntryRow } from '../../components/EntryRow';
import { announce } from '../../components/LiveRegion';
import { useLang } from '../../hooks/useLabels';
import { customerName } from '../../lib/format';
import type { MockLedger } from '../../services/mock/ledger';
import { conversation, latestEntry } from '../../state/session-reducer';
import { computeInsights } from '../hisaab/insights';
import { ScreenHeader } from '../hisaab/ScreenParts';
import { DEMO_LABELS, type DemoLabels } from './labels';
import { createDemoStore, runDemo, type DemoHandle, type DemoStore } from './runner';
import { DEMO_LINES, stepState, type DemoStep } from './script';

type RunStatus = 'idle' | 'running' | 'done' | 'stopped' | 'failed';

export function DemoScreen() {
  const lang = useLang();
  const L = DEMO_LABELS[lang];
  const [store, setStore] = useState<DemoStore | null>(null);
  const [ledger, setLedger] = useState<MockLedger | null>(null);
  const [step, setStep] = useState<DemoStep>({ kind: 'idle' });
  const [status, setStatus] = useState<RunStatus>('idle');
  const [runLang, setRunLang] = useState<Lang>(lang);
  const handle = useRef<DemoHandle | null>(null);

  // Leaving the route stops the run (timers, speech) and drops its store and ledger.
  useEffect(() => () => handle.current?.stop(), []);

  const start = async () => {
    handle.current?.stop();
    const runL = lang;
    const s = createDemoStore(runL);
    setRunLang(runL);
    setStore(s);
    setStatus('running');
    setStep({ kind: 'idle' });
    const T = DEMO_LABELS[runL];
    try {
      const h = await runDemo(s, runL, (st) => {
        setStep(st);
        if (st.kind === 'greeting') announce(`${T.badge}: ${T.stepGreeting}`);
        if (st.kind === 'line') announce(`${T.badge}: ${DEMO_LINES[runL][st.index] ?? ''}`);
      });
      handle.current = h;
      setLedger(h.ledger);
      const result = await h.finished;
      setStatus(result);
      announce(result === 'done' ? T.finished : T.stopped);
    } catch {
      setStatus('failed');
      announce(T.failed, 'assertive');
    }
  };

  const stop = () => {
    handle.current?.stop();
    handle.current = null;
  };

  const lines = DEMO_LINES[runLang];
  const stepsList = [L.stepGreeting, ...lines.map((l) => `“${l}”`)];

  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-talk px-5 pt-6 pb-48 outline-none lg:px-10 lg:pt-12 lg:pb-24">
      <header className="flex flex-col gap-4">
        <p className="eyebrow inline-flex items-center self-start rounded-full border border-ink px-3 py-1 text-ink">
          {L.badge}
        </p>
        <ScreenHeader title={L.title} line={L.subtitle} />
        <div className="flex max-w-prose flex-col gap-1 border-s-2 border-ink ps-4">
          <p className="text-body text-ink">{L.banner}</p>
          <p className="text-meta text-ink-2">{L.leave}</p>
        </div>
        <p className="max-w-prose text-body text-ink-2">{L.intro}</p>
      </header>

      <div className="mt-8 flex flex-wrap gap-3">
        {status === 'running' ? (
          <Button size="lg" onClick={stop}>
            {L.stop}
          </Button>
        ) : (
          <Button variant="primary" size="lg" onClick={() => void start()}>
            {status === 'idle' ? L.run : L.again}
          </Button>
        )}
      </div>
      {status === 'failed' ? <p className="mt-3 text-label text-ink">{L.failed}</p> : null}

      <section aria-labelledby="demo-steps" className="mt-10 flex flex-col gap-3">
        <h2 id="demo-steps" className="eyebrow">
          {L.steps}
        </h2>
        <ol className="ruled border-y border-line">
          {stepsList.map((text, i) => {
            const st = stepState(i, step, lines.length);
            return (
              <li key={text} aria-current={st === 'now' ? 'step' : undefined} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3">
                <span className="w-6 shrink-0 text-meta text-ink-2 tabular">{i + 1}.</span>
                <span className={`min-w-0 flex-1 text-label ${st === 'next' ? 'text-ink-2' : 'text-ink'} ${st === 'now' ? 'font-semibold' : ''}`} lang={runLang}>
                  {text}
                </span>
                <span className={`inline-flex items-center gap-1 text-meta ${st === 'now' ? 'font-semibold text-ink' : 'text-ink-2'}`}>
                  {st === 'done' ? <Check aria-hidden="true" size={14} strokeWidth={1.75} /> : null}
                  {st === 'done' ? L.stateDone : st === 'now' ? L.stateNow : L.stateNext}
                </span>
              </li>
            );
          })}
        </ol>
      </section>

      {store ? <DemoConversation store={store} L={L} /> : null}
      <DemoResults ledger={ledger} lang={runLang} L={L} />
    </main>
  );
}

function DemoConversation({ store, L }: { store: DemoStore; L: DemoLabels }) {
  const input = useStore(
    store,
    useShallow((s) => ({
      history: s.history,
      transcript: s.transcript,
      transcriptTyped: s.transcriptTyped,
      result: s.result,
      turnId: s.turnId,
      lang: s.lang,
      timing: s.timing,
      clientMs: s.clientMs,
      archivedTurn: s.archivedTurn,
    })),
  );
  const transcriptFinal = useStore(store, (s) => s.transcriptFinal);
  const saved = useStore(store, (s) => s.saved);
  const turns = useMemo(() => conversation(input), [input]);
  const historyLength = input.history.length;

  return (
    <section aria-labelledby="demo-conv" className="mt-10 flex flex-col gap-4">
      <h2 id="demo-conv" className="eyebrow">
        {L.conversation}
      </h2>
      <ol className="flex flex-col gap-6">
        {turns.map((turn, i) => {
          const live = i >= historyLength;
          const partial = live && !transcriptFinal;
          const r = turn.result;
          return (
            <li key={`t${i}`} className="flex flex-col gap-3 animate-row-in">
              {turn.said ? (
                <p className={`ms-auto max-w-[85%] rounded-sheet bg-tint px-4 py-3 text-body ${partial ? 'text-ink-2' : 'text-ink'}`} lang={turn.lang}>
                  <span className="sr-only">{L.youSaid}: </span>
                  {turn.said}
                </p>
              ) : null}
              {r?.replyText ? (
                <div className="flex max-w-prose items-start gap-3" lang={turn.lang}>
                  <Volume2 aria-hidden="true" size={18} strokeWidth={1.75} className="mt-1 shrink-0 text-ink-2" />
                  <div className="min-w-0">
                    {r.action === 'greeting' ? <p className="eyebrow mb-1">{DEMO_LABELS[turn.lang].aiBadge}</p> : null}
                    <p className="text-body text-ink">
                      <span className="sr-only">{DEMO_LABELS[turn.lang].aiSpeaker}: </span>
                      {r.replyText}
                    </p>
                  </div>
                </div>
              ) : null}
              {r?.entries.length ? (
                <ul className="ruled ms-7">
                  {r.entries.map((e) => (
                    <EntryRow key={String(e.id)} entry={latestEntry({ saved }, e)} lang={turn.lang} animate={live} />
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** Re-renders when the run's mock ledger changes. */
function useLedgerVersion(ledger: MockLedger | null): number {
  const version = useRef(0);
  return useSyncExternalStore(
    (cb) => {
      if (!ledger) return () => undefined;
      return ledger.subscribe(() => {
        version.current += 1;
        cb();
      });
    },
    () => version.current,
    () => 0,
  );
}

function DemoResults({ ledger, lang, L }: { ledger: MockLedger | null; lang: Lang; L: DemoLabels }) {
  const version = useLedgerVersion(ledger);
  const [now] = useState(() => new Date());
  const data = useMemo(() => {
    void version;
    if (!ledger) return null;
    const entries = ledger.ledgerView(500).entries;
    const customers = ledger.customerSummaries().customers.filter((c) => c.balance !== 0 || entries.some((e) => e.customer.id === c.id));
    return { customers, insights: computeInsights(entries, 'today', now, lang) };
  }, [ledger, version, now, lang]);

  return (
    <div className="mt-12 grid gap-12">
      <section aria-labelledby="demo-ledger" className="flex flex-col gap-2">
        <h2 id="demo-ledger" className="eyebrow">
          {L.ledger}
        </h2>
        {data?.customers.length ? (
          <ul className="ruled border-y border-line">
            {data.customers.map((c) => (
              <li key={c.id} className="flex items-center gap-3 py-3">
                <Avatar name={c.display} size="sm" />
                <span className="min-w-0 flex-1 text-label text-ink">{customerName(c)}</span>
                <span className="flex flex-col items-end">
                  <Amount value={c.balance} sign="auto" size="md" lang={lang} className={c.balance > 0 ? 'text-credit' : ''} />
                  <span className="text-meta text-ink-2">{L.baaki}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body text-ink-2">{L.nothingYet}</p>
        )}
      </section>

      <section aria-labelledby="demo-summary" className="flex flex-col gap-2">
        <h2 id="demo-summary" className="eyebrow">
          {L.summary}
        </h2>
        <dl className="grid grid-cols-1 border-y border-line min-[22rem]:grid-cols-2">
          <div className="flex flex-col gap-1 py-4 min-[22rem]:pe-4">
            <dt className="text-meta text-ink-2">{L.creditGiven}</dt>
            <dd>
              <Amount value={data?.insights.credit ?? 0} kind="credit" size="total" lang={lang} />
            </dd>
          </div>
          <div className="flex flex-col gap-1 border-t border-line py-4 min-[22rem]:border-t-0 min-[22rem]:border-s min-[22rem]:ps-4">
            <dt className="text-meta text-ink-2">{L.paymentIn}</dt>
            <dd>
              <Amount value={data?.insights.payment ?? 0} kind="payment" size="total" lang={lang} />
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
