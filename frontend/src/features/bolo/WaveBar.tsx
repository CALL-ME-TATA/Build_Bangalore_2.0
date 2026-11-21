// Wave bar above the mic whenever the mic is not idle: a dot and a clock on the left, 36 level bars on the
// right. Listening: the microphone level, dark bars, accent dot. Speaking: the reply's playback level,
// ink-2 bars. Processing: flat muted bars. The clock counts while listening or speaking and restarts when
// either begins. Bars are updated through refs every 90 ms, so React does not re-render on each tick.
import { useEffect, useRef } from 'react';
import { labels } from '../../i18n';
import { useMicView } from '../../components/MicButton';
import { micLevel } from '../../state/level';
import { useSession } from '../../state/session';

const BARS = 36;
const TICK_MS = 90;

const BAR_CLASS = { listening: 'bg-ink', speaking: 'bg-ink-2', processing: 'bg-muted' } as const;

function clockText(secs: number): string {
  return `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`;
}

export function WaveBar({ className = '' }: { className?: string }) {
  const { visual } = useMicView();
  const lang = useSession((s) => s.lang);
  const L = labels(lang);
  const bars = useRef<(HTMLSpanElement | null)[]>([]);
  const clock = useRef<HTMLSpanElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const shown = visual === 'listening' || visual === 'speaking' || visual === 'processing';

  useEffect(() => {
    if (!shown) return;
    const moving = visual === 'listening' || visual === 'speaking';
    const levels = new Array<number>(BARS).fill(0);
    let ticks = 0;
    let lastSecs = -1;
    const paint = () => {
      const secs = Math.floor((ticks * TICK_MS) / 1000);
      if (clock.current) clock.current.textContent = clockText(secs);
      if (secs !== lastSecs && box.current) {
        lastSecs = secs;
        const aria = visual === 'listening' ? L.waveRecording.replace('{n}', String(secs)) : visual === 'speaking' ? L.waveSpeaking : L.waveProcessing;
        box.current.setAttribute('aria-label', aria);
      }
      for (let i = 0; i < BARS; i++) {
        const el = bars.current[i];
        if (el) el.style.height = `${moving ? Math.round(4 + (levels[i] ?? 0) * 24) : 4}px`;
      }
    };
    paint();
    if (!moving) return;
    const id = setInterval(() => {
      ticks += 1;
      levels.shift();
      levels.push(micLevel.value);
      paint();
    }, TICK_MS);
    return () => clearInterval(id);
  }, [shown, visual, L]);

  if (!shown) return null;
  const barClass = BAR_CLASS[visual];

  return (
    <div
      ref={box}
      role="img"
      aria-label={visual === 'listening' ? L.waveRecording.replace('{n}', '0') : visual === 'speaking' ? L.waveSpeaking : L.waveProcessing}
      className={`flex h-13 w-full items-center gap-3.5 rounded-wave border border-line bg-surface px-4 ${className}`}
    >
      <span className="flex min-w-[3.625rem] items-center gap-2 text-small text-ink-2 tabular">
        <span aria-hidden="true" className={`size-[7px] shrink-0 rounded-full ${visual === 'listening' ? 'bg-accent' : 'bg-muted'}`} />
        <span ref={clock} aria-hidden="true">
          00:00
        </span>
      </span>
      <span aria-hidden="true" className="flex h-8 min-w-0 flex-1 items-center justify-between overflow-hidden">
        {Array.from({ length: BARS }, (_, i) => (
          <span
            key={i}
            ref={(el) => {
              bars.current[i] = el;
            }}
            className={`h-1 w-[3px] shrink-0 rounded-[2px] motion-safe:transition-[height] motion-safe:duration-[90ms] motion-safe:ease-linear ${barClass}`}
          />
        ))}
      </span>
    </div>
  );
}
