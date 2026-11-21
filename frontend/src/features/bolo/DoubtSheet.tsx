// The doubt sheet, as drawn on the Doubt board: one question, its tap answers, nothing else.
//  asking:  "Pakka nahi sun paaya" (14px, ask colour) / the question (`reply_text`) in Spectral 36 / a 16px ink-2
//           context line (what the shopkeeper said) / the answers (lib/doubt.ts) / "Dobara boliye" / a centred hint
//           - choices: amounts (₹340 / teen sau chaalis), customers (name / tag), entries (₹340 / Udhaar · Ramesh),
//             and for a new customer one button per close customer plus "Naya grahak"
//           - yes / no: Haan / Nahi (Yes / No), sending "haan" / "nahi"
//           - open: Udhaar diya / Paise aaye, or Aaj / Kal / Parso; with no buttons, the type box is in the sheet
//  saved:   "Save ho gaya" (payment green) / the amount in Spectral 36 / "Udhaar · Ramesh · Aaj" / "Galat hai? Badlein"
// Answer buttons are min 104px tall with a 1.5px border (ink for the first, line-strong for the rest); yes / no
// and the short open answers sit in one row. Every tap answer equals a spoken one, and "Dobara boliye" is the talk
// control inside the sheet, so voice and tap stay equal. The sheet closes when the server drops the question (any
// later result that is not a question), on Esc / scrim / swipe, and 60 s after asking (the server's expiry).
// Focus moves to the first answer on open and to "Galat hai? Badlein" once saved; on close it returns to the mic.
import { Check, CircleHelp } from 'lucide-react';
import { useEffect, useRef, type Ref, type RefObject } from 'react';
import { labels, type Lang } from '../../i18n';
import { Sheet } from '../../components/Sheet';
import { Amount } from '../../components/Amount';
import { MicTextButton } from '../../components/MicButton';
import { customerName, dayLabel, entryWhen, groupDigits, kindLabel, ymd } from '../../lib/format';
import { numberWords } from '../../lib/numberWords';
import { doubtHeadingKey, type DoubtOption } from '../../lib/doubt';
import { QUESTION_TTL_MS, type SheetState } from '../../lib/doubtSheet';
import { doubtDispatch, useDoubt } from '../../state/doubt';
import { useMicGesture } from '../../state/mic';
import { session, useSession } from '../../state/session';
import { TypeForm } from './TypeBox';

/** The question as shown: a confusable-number question drops the ₹ signs ("340 ya 740?"); the answers carry them. */
function shownQuestion(s: SheetState): string {
  return s.reason === 'confusable_number' ? s.question.replace(/₹\s?/g, '') : s.question;
}

/** The spoken example in the hint: the first answer as it would be said. */
function spokenExample(s: SheetState): string | null {
  const first = s.options[0];
  if (!first) return null;
  if (first.amount != null && s.reason === 'confusable_number') return numberWords(first.amount, s.lang);
  return first.answer;
}

export default function DoubtSheet() {
  const s = useDoubt();
  const L = labels(s.lang);
  const firstRef = useRef<HTMLButtonElement>(null);
  const questionRef = useRef<HTMLHeadingElement>(null);
  const changeRef = useRef<HTMLButtonElement>(null);
  const micOpen = useMicGesture((g) => g.open);
  const phase = useSession((x) => x.phase);
  const open = s.stage !== 'closed';

  // Focus moves when a new question opens (seq), never when the same question is repeated in place.
  const stage = s.stage;
  useEffect(() => {
    if (stage === 'asking') (firstRef.current ?? questionRef.current)?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new question (seq) moves focus
  }, [s.seq]);
  useEffect(() => {
    if (stage === 'saved') changeRef.current?.focus();
    else if (stage === 'correcting') questionRef.current?.focus();
  }, [stage]);

  // The server drops an unanswered question after 60 s; close it then too (unless an answer is on its way).
  const busy = micOpen || phase !== 'idle';
  useEffect(() => {
    if (s.stage !== 'asking' || busy) return;
    const id = setTimeout(() => doubtDispatch({ type: 'dismiss' }), QUESTION_TTL_MS);
    return () => clearTimeout(id);
  }, [s.stage, s.turnId, busy]);

  const pick = (o: DoubtOption) => {
    doubtDispatch({ type: 'pick', option: o });
    session.sendText(o.answer);
  };

  const asking = s.stage === 'asking' || s.stage === 'waiting';
  const example = spokenExample(s);
  // Large amounts get a full-width button each, so "₹5,00,000" fits at 320 px and at the largest text size.
  const wide = s.options.some((o) => o.amount != null && o.amount >= 10000);
  const inRow = !wide && (s.kind !== 'choice' || s.options.length === 2);

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        if (!o) doubtDispatch({ type: 'dismiss' });
      }}
      title={s.stage === 'saved' ? L.doubtSaved : L.doubtTitle}
      description={s.stage === 'saved' ? s.replyText : s.question}
      initialFocus={s.stage === 'saved' ? changeRef : s.options.length ? firstRef : questionRef}
    >
      <div lang={s.lang} className="flex flex-col gap-[1.375rem]">
        {asking ? (
          <>
            <div className="flex flex-col gap-2">
              <span className="flex items-center gap-2 text-small text-ask">
                <CircleHelp aria-hidden="true" size={16} strokeWidth={1.9} />
                {L[doubtHeadingKey(s.reason)]}
              </span>
              <h2
                ref={questionRef}
                tabIndex={-1}
                aria-live="polite"
                className={`font-display text-ink outline-none [overflow-wrap:anywhere] ${longQuestion(s) ? 'text-title-sm' : 'text-question'}`}
              >
                {shownQuestion(s)}
              </h2>
              {s.confirm?.type === 'amend' && s.confirm.old != null && s.confirm.new != null ? (
                <AmendLine old={s.confirm.old} next={s.confirm.new} lang={s.lang} />
              ) : null}
              {s.context ? (
                <p className="text-label font-normal text-ink-2">
                  {L.youSaid}: “{s.context}”
                </p>
              ) : null}
            </div>

            {s.options.length ? (
              <ul
                className={`grid gap-3 ${
                  inRow
                    ? s.options.length === 3
                      ? 'grid-cols-3'
                      : 'grid-cols-2'
                    : wide
                      ? 'grid-cols-1'
                      : 'grid-cols-2 [&>li:last-child:nth-child(odd)]:col-span-2'
                }`}
              >
                {s.options.map((o, i) => (
                  <li key={o.id} className="flex">
                    <AnswerButton
                      option={o}
                      first={i === 0}
                      compact={s.kind !== 'choice'}
                      reason={s.reason}
                      lang={s.lang}
                      buttonRef={i === 0 ? firstRef : undefined}
                      disabled={s.stage === 'waiting'}
                      pressed={s.picked === o.label}
                      onPick={() => pick(o)}
                    />
                  </li>
                ))}
              </ul>
            ) : null}

            {s.stage === 'waiting' ? (
              <p role="status" className="text-small text-ink-2">
                {L.doubtWaiting}
              </p>
            ) : null}

            {s.typeBox ? <TypeForm onClose={() => undefined} closable={false} /> : null}

            <MicTextButton idleLabel={L.doubtSayAgain} id="mic-sheet" />
            <p className="text-center text-small text-ink-2">{example ? `${L.doubtHint} — “${example}”` : L.doubtHintVoice}</p>
          </>
        ) : null}

        {s.stage === 'saved' ? <Saved s={s} changeRef={changeRef} /> : null}

        {s.stage === 'correcting' ? (
          <>
            <div className="flex flex-col gap-2">
              <h2 ref={questionRef} tabIndex={-1} className="font-display text-question text-ink outline-none">
                {L.doubtCorrectTitle}
              </h2>
              <p className="text-label font-normal text-ink-2">{L.doubtCorrectHint}</p>
            </div>
            <MicTextButton idleLabel={L.doubtSayAgain} id="mic-sheet" />
          </>
        ) : null}
      </div>
    </Sheet>
  );
}

/**
 * A question long enough to need a smaller heading (a `review` question lists several entries): it wraps at the
 * 24px title size instead of the 36px question size, so it is never clipped.
 */
export function longQuestion(s: Pick<SheetState, 'question' | 'confirm'>): boolean {
  return s.confirm?.type === 'review' || s.question.length > 48;
}

/** Under an `amend` question: the old amount struck through, then the new one. */
function AmendLine({ old, next, lang }: { old: number; next: number; lang: Lang }) {
  const L = labels(lang);
  return (
    <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="text-ink-2 line-through decoration-1">
        <span className="sr-only">{L.amendOld}: </span>
        <Amount value={old} sign="none" size="lg" lang={lang} />
      </span>
      <span aria-hidden="true" className="text-ink-2">
        →
      </span>
      <span className="text-ink">
        <span className="sr-only">{L.amendNew}: </span>
        <Amount value={next} sign="none" size="lg" lang={lang} />
      </span>
    </p>
  );
}

interface AnswerProps {
  option: DoubtOption;
  first: boolean;
  /** Yes / no and the short open answers: one line, smaller text. */
  compact: boolean;
  reason: string | null;
  lang: Lang;
  buttonRef?: Ref<HTMLButtonElement>;
  disabled: boolean;
  pressed: boolean;
  onPick: () => void;
}

/** One clean accessible name per answer: the visual parts are hidden and the name is set once. */
export function answerName(o: DoubtOption, reason: string | null, lang: Lang): string {
  const L = labels(lang);
  if (o.amount == null) return o.sub ? `${o.label}, ${o.sub}` : o.label;
  const money = `${o.amount} ${L.rupees}`;
  if (reason === 'unclear_correction') return [money, o.kind ? kindLabel(o.kind, lang) : '', o.sub ?? ''].filter(Boolean).join(', ');
  return money;
}

function AnswerButton({ option, first, compact, reason, lang, buttonRef, disabled, pressed, onPick }: AnswerProps) {
  const amount = option.amount;
  const second =
    amount != null
      ? reason === 'confusable_number'
        ? numberWords(amount, lang)
        : [option.kind ? kindLabel(option.kind, lang) : '', option.sub ?? ''].filter(Boolean).join(' · ')
      : option.sub;
  return (
    <button
      ref={buttonRef}
      type="button"
      disabled={disabled}
      aria-pressed={pressed}
      aria-label={answerName(option, reason, lang)}
      onClick={onPick}
      className={`flex w-full flex-col items-center justify-center gap-0.5 rounded-sheet border-[1.5px] bg-surface px-3 py-3 text-ink disabled:opacity-60 aria-pressed:bg-tint ${
        compact ? 'min-h-16' : 'min-h-26'
      } ${first ? 'border-ink' : 'border-line-strong'}`}
    >
      {amount != null ? (
        <span aria-hidden="true" className="amount text-question">
          <span className="amount-symbol text-[0.667em]">₹</span>
          <span className="amount-digits">{groupDigits(amount)}</span>
        </span>
      ) : (
        <span aria-hidden="true" className={compact ? 'text-label font-medium' : 'text-amount font-medium'}>
          {option.label}
        </span>
      )}
      {second ? (
        <span aria-hidden="true" className="text-meta text-ink-2">
          {second}
        </span>
      ) : null}
    </button>
  );
}

function Saved({ s, changeRef }: { s: SheetState; changeRef: RefObject<HTMLButtonElement | null> }) {
  const L = labels(s.lang);
  const e = s.entries.find((x) => !x.reversed) ?? s.entries[0];
  return (
    <div role="status" className="flex flex-col items-start gap-2.5 pt-2 pb-3">
      <span className="flex items-center gap-2 text-small text-payment">
        <Check aria-hidden="true" size={16} strokeWidth={2} />
        {L.doubtSaved}
      </span>
      {e ? (
        <>
          <h2 className="font-display text-question">
            <Amount value={e.amount} kind={e.kind} size="inherit" tone lang={s.lang} />
          </h2>
          <p className="text-label font-normal text-ink-2">
            {kindLabel(e.kind, s.lang)} · {customerName(e.customer)} · {e.ts ? entryWhen(e, new Date(), s.lang) : dayLabel(e.date, ymd(), s.lang)}
          </p>
        </>
      ) : null}
      <button
        ref={changeRef}
        type="button"
        onClick={() => doubtDispatch({ type: 'correct' })}
        className="mt-1.5 min-h-12 rounded-control border border-line-strong bg-surface px-4 text-label-sm text-ink"
      >
        {L.doubtWrong}
      </button>
    </div>
  );
}
