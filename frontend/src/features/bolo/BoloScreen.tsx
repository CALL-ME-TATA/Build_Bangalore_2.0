// Bolo (talk), the home screen, laid out as on the boards. One hero: the mic.
//  - phone (Main board, 390 x 844): header (shop name h1, lock line, online pill); the conversation anchored to
//    the bottom of the main area with a 40px fade at the top; the wave bar, the 80px mic in an 88px box and its
//    label; the bottom tabs. The screen is exactly one viewport tall and the conversation scrolls inside it.
//  - tablet (>= 640px): today's panel on the left, the phone column on the right
//  - desktop (Desktop board, 1440): rail | main column (Spectral 40 "Bolo" title and the date, the conversation
//    at max 640px with 18px text, the mic bar with the 72px mic and the Space hint) | white right column
// Only one h1 is ever displayed: the shop name below 1024px, "Bolo" above.
import { labels } from '../../i18n';
import { MicButton } from '../../components/MicButton';
import { AppHeader } from '../../layout/AppHeader';
import { TodayPanel } from '../../layout/TodayPanel';
import { longDate } from '../../lib/format';
import { useSession } from '../../state/session';
import { Conversation } from './Conversation';
import { StartStep, focusStart } from './StartStep';
import { TypeForm, TypeToggle, useTypeBox } from './TypeBox';
import { WaveBar } from './WaveBar';

export function BoloScreen() {
  const lang = useSession((s) => s.lang);
  const started = useSession((s) => s.started);
  const L = labels(lang);

  return (
    <div className="h-[calc(100dvh-var(--spacing-tabs)-env(safe-area-inset-bottom))] sm:grid sm:grid-cols-[minmax(16rem,21rem)_minmax(0,1fr)] lg:h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)]">
      <div className="flex h-full min-h-0 min-w-0 flex-col sm:order-2 lg:order-1">
        <AppHeader className="lg:hidden" />
        <main
          id="main"
          tabIndex={-1}
          className="flex min-h-0 flex-1 flex-col outline-none lg:px-[clamp(1.5rem,4vw,4rem)] lg:pt-10 lg:pb-8"
        >
          <header className="hidden flex-wrap items-baseline justify-between gap-2 pb-7 lg:flex">
            <h1 className="font-display text-title-lg text-ink">{L.tabBolo}</h1>
            <span className="text-small text-ink-2">{longDate(new Date(), lang)}</span>
          </header>
          <div className="fade-top min-h-0 flex-1 overflow-y-auto overscroll-contain">
            <div className="flex min-h-full w-full max-w-talk flex-col justify-end px-6 pt-[1.125rem] pb-1 lg:px-0 lg:pb-6">
              {started ? <Conversation /> : <StartStep />}
            </div>
          </div>
          <MicDock />
        </main>
      </div>
      <TodayPanel className="hidden border-line bg-surface px-6 py-8 sm:order-1 sm:flex sm:overflow-y-auto sm:border-e lg:order-2 lg:border-e-0 lg:border-s lg:px-8 lg:pt-10" />
    </div>
  );
}

/** Wave bar, mic and label (phone, tablet); the horizontal mic bar with the Space hint (desktop). */
function MicDock() {
  const lang = useSession((s) => s.lang);
  const L = labels(lang);
  const type = useTypeBox();
  return (
    <div className="flex w-full max-w-talk flex-col items-center gap-3 px-6 pt-3 pb-3.5 lg:items-stretch lg:border-t lg:border-line lg:px-0 lg:pt-5 lg:pb-0">
      <WaveBar />
      {type.open ? <TypeForm onClose={() => type.setOpen(false)} closable={type.closable} /> : null}

      {/* phone and tablet: the mic centred, the keyboard toggle beside it */}
      <div className="relative flex w-full justify-center lg:hidden">
        <MicButton size="hero" id="mic-main" globalSpace onNotStarted={focusStart} />
        {!type.open ? <TypeToggle onOpen={() => type.setOpen(true)} className="absolute start-0 top-5" /> : null}
      </div>

      {/* desktop: the mic bar */}
      <div className="hidden items-center justify-between gap-4 lg:flex">
        <MicButton
          size="desk"
          id="mic-desk"
          onNotStarted={focusStart}
          aside={(label, labelId) => (
            <span className="flex flex-col gap-0.5">
              <span id={labelId} className="text-label font-medium text-ink">
                {label}
              </span>
              <span className="text-small text-ink-2" aria-hidden="true">
                <kbd className="rounded-[0.375rem] border border-line-strong px-1.5 py-px font-sans text-meta">Space</kbd> {L.micSpaceHint}
              </span>
            </span>
          )}
        />
        {!type.open ? <TypeToggle onOpen={() => type.setOpen(true)} /> : null}
      </div>
    </div>
  );
}
