// First step of every page load (no board; styled like the conversation it precedes): choose the language and
// unlock audio. Browsers only allow sound after a tap, and the greeting (which carries the AI disclosure) must
// be heard, so this tap starts the session. It sits at the bottom of the conversation area, where the greeting
// will appear, with the disclosure label above it.
import { Volume2 } from 'lucide-react';
import { labels, type Lang } from '../../i18n';
import { startSession, useSession } from '../../state/session';
import { useSettings } from '../../state/settings';
import { setVoiceLang, voiceLang, type VoiceLang } from '../../services/session/voice';

const REGIONAL: { voice: VoiceLang; native: string; name: string }[] = [
  { voice: 'kn', native: 'ಕನ್ನಡ', name: 'Kannada' },
  { voice: 'mr', native: 'मराठी', name: 'Marathi' },
  { voice: 'ta', native: 'தமிழ்', name: 'Tamil' },
];
import { announce } from '../../components/LiveRegion';

export function StartStep() {
  const preferred = useSettings((s) => s.language);
  const remembered = voiceLang(); // Kannada / Marathi / Tamil chosen before: it stays the main choice
  const starting = useSession((s) => s.starting);
  const L = labels(preferred);

  const start = async (lang: Lang, voice: VoiceLang | null = null) => {
    setVoiceLang(voice);
    try {
      await startSession(lang);
    } catch {
      announce(labels(lang).errorGeneric, 'assertive');
    }
  };

  const choices: { lang: Lang; title: string; sub: string }[] = [
    { lang: 'hi', title: L.startHi, sub: L.startHiSub },
    { lang: 'en', title: L.startEn, sub: L.startEnSub },
  ];
  // The preferred language is the one primary action; the other is quiet.
  choices.sort((a, b) => (a.lang === preferred ? -1 : b.lang === preferred ? 1 : 0));

  return (
    <section aria-labelledby="start-title" className="flex flex-col gap-[1.375rem]" id="start-step">
      <div className="flex flex-col gap-1.5">
        <span className="text-meta text-ink-2">{L.aiLabel}</span>
        <h2 id="start-title" className="font-display text-title-md text-ink">
          {L.startTitle}
        </h2>
        <p className="max-w-prose text-body text-ink-2 lg:text-body-lg">{L.startBody}</p>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-meta text-ink-2" id="start-choose">
          {labels('hi').startChoose} · {labels('en').startChoose}
        </p>
        <div role="group" aria-labelledby="start-choose" className="grid gap-3 sm:grid-cols-2">
          {choices.map((c, i) => (
            <button
              key={c.lang}
              type="button"
              id={i === 0 ? 'start-primary' : undefined}
              disabled={starting}
              aria-describedby="start-sound"
              aria-label={`${starting && i === 0 ? L.startBusy : c.title}, ${c.sub}`}
              onClick={() => void start(c.lang)}
              lang={c.lang}
              className={`flex min-h-14 items-center justify-between gap-3 rounded-control px-5 text-start text-label font-medium disabled:opacity-60 ${
                i === 0 && !remembered ? 'bg-accent text-on-accent' : 'border border-line-strong bg-surface text-ink'
              }`}
            >
              <span>{starting && i === 0 ? L.startBusy : c.title}</span>
              <span className="text-meta font-normal opacity-90">{c.sub}</span>
            </button>
          ))}
        </div>
        <div role="group" aria-label="Other languages" className="grid grid-cols-3 gap-2">
          {REGIONAL.map((r) => (
            <button
              key={r.voice}
              type="button"
              disabled={starting}
              lang={r.voice}
              onClick={() => void start('en', r.voice)}
              className={`flex min-h-12 flex-col items-center justify-center rounded-control px-2 py-1 text-label-sm disabled:opacity-60 ${
                r.voice === remembered ? 'bg-accent text-on-accent' : 'border border-line-strong bg-surface text-ink'
              }`}
            >
              <span>{r.native}</span>
              <span className="text-meta text-ink-2">{r.name}</span>
            </button>
          ))}
        </div>
        <p id="start-sound" className="flex items-center gap-2 text-small text-ink-2">
          <Volume2 aria-hidden="true" size={16} strokeWidth={1.8} />
          {L.startSound}
        </p>
      </div>
    </section>
  );
}

/** Moves focus to the start button (used when the disabled mic is pressed before starting). */
export function focusStart(): void {
  document.getElementById('start-primary')?.focus();
}
