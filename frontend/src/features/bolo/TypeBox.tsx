// "Type karein": type a sentence instead of speaking it. Same pipeline, sent as {"type":"text"}.
// TypeToggle is a small keyboard button beside the mic (the boards leave no room for more); TypeForm opens
// above the mic. The form opens by itself when the microphone is unavailable, when the browser is offline, and
// when the server reports the network or speech service failing (`offerTyping`).
// Offline (session started, no open socket) a sentence still goes out: session.sendText puts it in the encrypted
// outbox, which sends it with its own utt_id when the connection is back (services/offline).
import { Keyboard, Send, X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { labels } from '../../i18n';
import { session, useSession } from '../../state/session';
import { shouldQueueText } from '../../services/offline/status';
import { useOnline } from '../../hooks/useOnline';

export function TypeToggle({ onOpen, className = '' }: { onOpen: () => void; className?: string }) {
  const lang = useSession((s) => s.lang);
  const started = useSession((s) => s.started);
  if (!started) return null;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-expanded="false"
      className={`inline-flex min-h-12 min-w-12 items-center justify-center gap-1.5 rounded-control px-2 text-small text-ink-2 hover:text-ink ${className}`}
    >
      <Keyboard aria-hidden="true" size={18} strokeWidth={1.8} />
      <span>{labels(lang).typeOpen}</span>
    </button>
  );
}

export function TypeForm({ onClose, closable = true, className = '' }: { onClose: () => void; closable?: boolean; className?: string }) {
  const lang = useSession((s) => s.lang);
  const greeted = useSession((s) => s.greeted);
  const conn = useSession((s) => s.conn);
  const started = useSession((s) => s.started);
  useOnline(); // re-render when the connection changes, so the gate below is current
  const L = labels(lang);
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  // Live when connected; queued for later when started but not connected.
  const usable = started && ((greeted && conn === 'open') || shouldQueueText({ started, conn }));

  useEffect(() => {
    if (closable) inputRef.current?.focus();
  }, [closable]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || !usable) return;
    session.sendText(text);
    setText('');
  };

  return (
    <form onSubmit={submit} className={`flex w-full items-end gap-2 ${className}`}>
      <div className="min-w-0 flex-1">
        <label htmlFor={inputId} className="block pb-1 text-meta text-ink-2">
          {L.typeLabel}
        </label>
        <input
          ref={inputRef}
          id={inputId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={L.typePlaceholder}
          autoComplete="off"
          enterKeyHint="send"
          lang={lang}
          className="block min-h-12 w-full rounded-control border border-line bg-surface px-3.5 text-label text-ink placeholder:text-ink-2"
        />
      </div>
      <button
        type="submit"
        disabled={!usable || !text.trim()}
        className="inline-flex min-h-12 items-center gap-2 rounded-control border border-line-strong bg-surface px-4 text-label-sm font-medium text-ink disabled:opacity-50"
      >
        <Send aria-hidden="true" size={18} strokeWidth={1.8} />
        {L.typeSend}
      </button>
      {closable ? (
        <button
          type="button"
          onClick={onClose}
          aria-label={L.typeOpen}
          aria-expanded="true"
          className="inline-flex size-12 items-center justify-center rounded-control text-ink-2 hover:text-ink"
        >
          <X aria-hidden="true" size={18} strokeWidth={1.8} />
        </button>
      ) : null}
    </form>
  );
}

/** Open state of the type form: opened by the user, or forced open when the mic is unavailable. */
export function useTypeBox() {
  const mic = useSession((s) => s.mic);
  const started = useSession((s) => s.started);
  const offerTyping = useSession((s) => s.offerTyping);
  const dispatch = useSession((s) => s.dispatch);
  const online = useOnline();
  const [openByUser, setOpenByUser] = useState(false);
  const micMissing = mic === 'denied' || mic === 'failed' || mic === 'nodevice' || mic === 'insecure';
  const forced = micMissing || !online;
  const setOpen = (open: boolean) => {
    setOpenByUser(open);
    if (!open && offerTyping) dispatch({ type: 'typing_closed' });
  };
  return { open: started && (openByUser || forced || offerTyping), closable: !forced, setOpen };
}
