// The offline layer's two pieces of UI, for any screen to drop in:
// - <StaleNote />: "May be out of date · Last synced Aaj, 11:42" when cached data is on screen.
// - <OutboxList />: sentences typed while offline, each "Saved offline · will sync" (or sending / not sent with
//   its reason, Send again and Remove), and the line that explains that speaking needs a connection.
// State is in words and an icon, never colour alone.
import { CloudOff, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { useLang } from '../../hooks/useLabels';
import { useOnline } from '../../hooks/useOnline';
import { clockTime, dayLabel, ymd } from '../../lib/format';
import { useSession } from '../../state/session';
import { offlineLabels, reasonText } from './labels';
import { useOffline, useStaleSince } from './status';

/** "Aaj, 11:42" for an ISO time. */
export function syncedWhen(iso: string, now: Date = new Date(), lang: 'hi' | 'en' = 'hi'): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return '';
  const day = dayLabel(ymd(new Date(ms)), ymd(now), lang);
  return `${day}, ${clockTime(iso)}`;
}

export function StaleNote({ className = '' }: { className?: string }) {
  const since = useStaleSince();
  const lang = useLang();
  if (!since) return null;
  const L = offlineLabels(lang);
  return (
    <p role="status" className={`flex items-start gap-2 text-meta text-ink ${className}`}>
      <CloudOff aria-hidden="true" size={16} strokeWidth={1.75} className="mt-0.5 shrink-0" />
      <span>
        <span className="font-semibold">{L.stale}</span>
        <span className="text-ink-2">
          {' · '}
          {L.lastSync} {syncedWhen(since, new Date(), lang)}
        </span>
      </span>
    </p>
  );
}

function act(fn: 'retry' | 'remove', id: number) {
  void import('./sync').then((m) => m[fn](id));
}

export function OutboxList({ className = '' }: { className?: string }) {
  const lang = useLang();
  const items = useOffline((s) => s.outbox);
  const online = useOnline();
  const started = useSession((s) => s.started);
  const conn = useSession((s) => s.conn);
  const L = offlineLabels(lang);
  const disconnected = started && (!online || (conn !== 'open' && conn !== 'idle'));
  if (!items.length && !disconnected) return null;

  return (
    <section aria-labelledby="outbox-title" className={`flex flex-col gap-3 ${className}`}>
      <h2 id="outbox-title" className="sr-only">
        {L.outboxTitle}
      </h2>
      {disconnected ? (
        <p className="flex max-w-prose items-start gap-2 text-body text-ink">
          <CloudOff aria-hidden="true" size={18} strokeWidth={1.75} className="mt-1 shrink-0" />
          <span>{L.speakNeedsNet}</span>
        </p>
      ) : null}
      {items.length ? (
        <ol className="flex flex-col gap-4">
          {items.map((it) => (
            <li key={it.id} className="ms-auto flex max-w-[85%] flex-col items-end gap-1">
              <p className="rounded-sheet border border-dashed border-line-strong bg-tint px-4 py-3 text-body text-ink">
                <span className="sr-only">{L.youTyped}: </span>
                {it.text}
              </p>
              {it.state === 'failed' ? (
                <div className="flex flex-col items-end gap-1">
                  <p className="text-meta text-ink">
                    <span className="font-semibold">{L.notSent}</span>
                    <span className="text-ink-2"> · {reasonText(it.reason, lang)}</span>
                  </p>
                  <div className="flex flex-wrap justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => act('retry', it.id)}
                      aria-label={`${L.sendAgainLabel}: ${it.text}`}
                      className="inline-flex min-h-12 items-center gap-1.5 rounded-control px-3 text-label text-ink hover:bg-tint"
                    >
                      <RotateCcw aria-hidden="true" size={18} strokeWidth={1.75} />
                      {L.sendAgain}
                    </button>
                    <button
                      type="button"
                      onClick={() => act('remove', it.id)}
                      aria-label={`${L.removeLabel}: ${it.text}`}
                      className="inline-flex min-h-12 items-center gap-1.5 rounded-control px-3 text-label text-ink hover:bg-tint"
                    >
                      <Trash2 aria-hidden="true" size={18} strokeWidth={1.75} />
                      {L.remove}
                    </button>
                  </div>
                </div>
              ) : (
                <p className="inline-flex items-center gap-1.5 text-meta text-ink-2">
                  {it.state === 'sending' ? (
                    <RefreshCw aria-hidden="true" size={14} strokeWidth={1.75} />
                  ) : (
                    <CloudOff aria-hidden="true" size={14} strokeWidth={1.75} />
                  )}
                  {it.state === 'sending' ? L.sending : L.savedOffline}
                </p>
              )}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
