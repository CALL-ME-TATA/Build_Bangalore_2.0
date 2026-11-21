// The quiet conversation of this session, as drawn on the Bolo board, oldest first and anchored to the bottom:
//  - the app's first line carries the disclosure label "KhataVaani · AI sahayak" (13px ink-2) above it
//  - the shopkeeper's words right-aligned in a tint bubble, in curly quotes (max 270px, 17px)
//  - saved entries: a count line ("2 entries likhi gayi") and ruled rows; Undo only on the newest entry
//  - the app's replies as plain text with a small speaker icon; ₹ amounts in weight 600
//  - while speaking, the LIVE box: the partial transcript with its volatile last word in ink-3
//  - the latency of the last turn in small meta text
// Text is 17px on phones and 18px on desktop.
import { Volume2 } from 'lucide-react';
import { useEffect, useMemo, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { labels, type Lang } from '../../i18n';
import { EntryRow } from '../../components/EntryRow';
import { groupDigits, replySegments, splitVolatile } from '../../lib/format';
import { Link } from '@tanstack/react-router';
import { useKhataView } from '../khata/view';
import { OutboxList } from '../../services/offline/OfflineNotes';
import { LatencyLine } from './LatencyLine';
import { conversation, lastLatency, latestEntry, newestActiveId, sendUndo, useSession, type TurnRecord } from '../../state/session';
import type { BalanceInfo, Entry } from '../../services/session/types';

function prefersReducedMotion(): boolean {
  return typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function Conversation() {
  const input = useSession(
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
  const turns = useMemo(() => conversation(input), [input]);
  const latency = useMemo(() => lastLatency(turns), [turns]);
  const historyLength = input.history.length;
  const transcriptFinal = useSession((s) => s.transcriptFinal);
  const phase = useSession((s) => s.phase);
  const barged = useSession((s) => s.barged);
  const saved = useSession((s) => s.saved);
  const greeted = useSession((s) => s.greeted);
  const lang = input.lang;
  const L = labels(lang);
  const endRef = useRef<HTMLDivElement>(null);
  const newest = greeted ? newestActiveId(saved) : null;
  const last = turns[turns.length - 1];

  // The live turn: while its transcript is a partial (or the mic is open with nothing heard yet) it is shown
  // in the LIVE box instead of as a bubble.
  const liveIndex = historyLength < turns.length ? historyLength : -1;
  const listening = phase === 'listening' || phase === 'hearing';
  const livePartial = liveIndex >= 0 && !transcriptFinal && !turns[liveIndex]?.typed && Boolean(turns[liveIndex]?.said);
  const showLiveBox = livePartial || (listening && (barged || liveIndex >= 0) && !transcriptFinal);
  const liveText = livePartial ? (turns[liveIndex]?.said ?? '') : '';

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  }, [turns.length, last?.said, last?.result, showLiveBox]);

  const firstReply = turns.findIndex((t) => t.result?.replyText);
  const empty = turns.every((t) => !t.said);

  return (
    <section aria-labelledby="conversation-title" className="flex flex-col gap-[1.375rem]">
      <h2 id="conversation-title" className="sr-only">
        {L.conversation}
      </h2>
      {turns.map((turn, i) => (
        <Turn
          key={`t${i}`} // the live turn becomes history[i] later, so the key stays the same
          turn={turn}
          hideSaid={i === liveIndex && livePartial}
          disclosure={i === firstReply}
          uiLang={lang}
          newestId={newest}
          entryState={(e) => latestEntry({ saved }, e)}
          live={i === liveIndex}
        />
      ))}

      {empty && !showLiveBox ? (
        <p className="text-small text-ink-2">
          {L.emptyHint} <span className="text-ink">“{L.emptyExample}”</span>
        </p>
      ) : null}

      {showLiveBox ? <LiveBox text={liveText} label={L.live} lang={lang} /> : null}

      {latency ? <LatencyLine server={latency.server} phone={latency.phone} ms={latency.ms} lang={lang} /> : null}
      <OutboxList />
      <div ref={endRef} />
    </section>
  );
}

function LiveBox({ text, label, lang }: { text: string; label: string; lang: Lang }) {
  const [settled, tail] = splitVolatile(text);
  return (
    <div className="rounded-sheet border border-line bg-surface px-4 py-3.5">
      <span className="block pb-1.5 text-eyebrow tracking-[0.06em] text-ink-2 uppercase">{label}</span>
      <p className="text-body leading-[1.45] text-ink lg:text-body-lg" lang={lang}>
        {text ? (
          <>
            {settled}
            <span className="text-ink-3">{tail}…</span>
          </>
        ) : (
          <span className="text-ink-3">…</span>
        )}
      </p>
    </div>
  );
}

interface TurnProps {
  turn: TurnRecord;
  hideSaid: boolean;
  disclosure: boolean;
  live: boolean;
  uiLang: Lang;
  newestId: string | number | null;
  entryState: (e: Entry) => Entry;
}

function Turn({ turn, hideSaid, disclosure, live, uiLang, newestId, entryState }: TurnProps) {
  const L = labels(uiLang);
  const T = labels(turn.lang);
  const r = turn.result;
  const entries = (r?.entries ?? []).map(entryState);
  const added = entries.filter((e) => !e.reversed).length;
  const removed = entries.length - added;
  const count = added
    ? `${added} ${added === 1 ? T.entryOne : T.entryMany}`
    : removed
      ? `${removed} ${T.entryRemovedCount}`
      : '';

  return (
    <>
      {turn.said && !hideSaid ? (
        <p className="bubble ms-auto max-w-bubble animate-row-in bg-tint px-4 py-3 text-body leading-[1.45] text-ink lg:px-[1.125rem] lg:text-body-lg">
          <span className="sr-only">{L.youSaid}: </span>“{turn.said}”
        </p>
      ) : null}

      {entries.length ? (
        <section aria-label={count} className="flex flex-col">
          <span className="pb-2 text-meta text-ink-2" aria-hidden="true">
            {count}
          </span>
          <ul>
            {entries.map((e) => (
              <EntryRow key={String(e.id)} entry={e} lang={turn.lang} animate={live} onUndo={e.id === newestId ? sendUndo : undefined} />
            ))}
          </ul>
          {r?.balances.length ? (
            <p className="pt-2 text-meta text-ink-2">
              {r.balances.map((b) => balanceLine(b, turn.lang)).join(' · ')}
            </p>
          ) : null}
        </section>
      ) : null}

      {r && r.replyText ? (
        disclosure ? (
          <div className="flex flex-col gap-1.5 animate-row-in" lang={turn.lang}>
            <span className="text-meta text-ink-2">{T.aiLabel}</span>
            <p className="text-body text-ink lg:text-body-lg">
              <Reply text={r.replyText} />
            </p>
          </div>
        ) : (
          <p className="flex gap-2.5 text-body text-ink animate-row-in lg:text-body-lg" lang={turn.lang}>
            <Volume2 aria-hidden="true" size={18} strokeWidth={1.8} className="mt-1 shrink-0 text-ink-2" />
            <span className={r.status === 'needs_clarification' ? 'text-ask' : undefined}>
              <span className="sr-only">{T.aiSpeaker}: </span>
              <Reply text={r.replyText} />
            </span>
          </p>
        )
      ) : null}

      {r?.query?.type === 'top_dues' ? <SeeAllDues lang={turn.lang} /> : null}
    </>
  );
}

/** "Ramesh · ab baaki ₹770" (shown, never spoken). */
export function balanceLine(b: BalanceInfo, lang: Lang): string {
  const L = labels(lang);
  const amt = `₹${groupDigits(b.balance)}`;
  if (b.balance > 0) return `${b.display} · ${L.balanceNow} ${amt}`;
  if (b.balance < 0) return `${b.display} · ${amt} ${L.balanceAdvance}`;
  return `${b.display} · ${L.balanceSettled}`;
}

/** For a top-dues answer: the full list of people who owe, on the Khata screen. */
function SeeAllDues({ lang }: { lang: Lang }) {
  const setFilter = useKhataView((s) => s.setFilter);
  return (
    <Link
      to="/khata"
      onClick={() => setFilter('due')}
      className="ms-7 inline-flex min-h-12 items-center gap-1 self-start text-label-sm font-medium text-ink underline underline-offset-4 hover:no-underline"
    >
      {labels(lang).seeAll}
    </Link>
  );
}

function Reply({ text }: { text: string }) {
  return (
    <>
      {replySegments(text).map((seg, i) =>
        seg.amount ? (
          <strong key={i} className="font-semibold tabular">
            {seg.text}
          </strong>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </>
  );
}
