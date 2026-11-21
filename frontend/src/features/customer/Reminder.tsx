// The action row of the "Customer" board: "Reminder bhejein" (the screen's one primary action) next to an
// outlined mic link to Bolo, the opt-in line under them, and the opt-in switch.
// - The button is disabled, with the reason written in the line under it, when the customer has not opted in or
//   owes nothing.
// - Pressing it queues reminders (POST /api/reminders/queue), reads the outbox (GET /api/reminders) and shows this
//   customer's prefilled message with the wa.me link the server built. Without a stored phone number the server
//   gives no link, so a number can be added (POST /api/customers/{id}/reminders with the phone).
// - The switch sets the opt-in (same endpoint) and says what it means in plain words.
import { useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Bell, ExternalLink, Mic } from 'lucide-react';
import { useId, useState, type FormEvent } from 'react';
import { Button } from '../../components/Button';
import { Switch } from '../../components/Switch';
import { Amount } from '../../components/Amount';
import { announce } from '../../components/LiveRegion';
import { getReminders, remindCustomer, setReminderOptIn, type Customer, type Reminder } from '../../services/api';
import { queryKeys } from '../../services/query';
import { toast } from '../../lib/toast';
import type { Lang } from '../../i18n';
import { syntheticKey } from '../khata/data';
import { fill } from '../khata/labels';
import { customerLabels } from './labels';
import { normalizePhone, reminderAvailability, reminderFor, safeWaLink } from './logic';

type Outcome =
  | { kind: 'ready'; reminder: Reminder; sms?: boolean } // sms: the server also sends it by SMS
  | { kind: 'none' }
  | { kind: 'quiet' } // outside sending hours: the server queues nothing until 09:00
  | { kind: 'failed' }
  | null;

export function ReminderPanel({ customer, lang, synthetic }: { customer: Customer; lang: Lang; synthetic: boolean }) {
  const C = customerLabels(lang);
  const qc = useQueryClient();
  const lineId = useId();
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const avail = reminderAvailability(customer);

  const send = async () => {
    setBusy(true);
    try {
      // Only this customer is reminded (never every opted-in customer at once).
      const queue = synthetic ? null : await remindCustomer(customer.id);
      if (queue?.quietHours) {
        setOutcome({ kind: 'quiet' });
        announce(C.reminderQuietHours);
        return;
      }
      const found = synthetic ? null : reminderFor(await getReminders(), customer.id);
      const sms = Boolean(queue?.sms && found?.wa_link);
      setOutcome(found ? { kind: 'ready', reminder: found, sms } : { kind: 'none' });
      announce(found ? (sms ? `${C.reminderReady}. ${C.reminderSms}` : C.reminderReady) : C.reminderNone);
    } catch {
      setOutcome({ kind: 'failed' });
      announce(C.reminderFailed, 'assertive');
    } finally {
      setBusy(false);
    }
  };

  const patch = (optIn: boolean) => (list: Customer[] | undefined) =>
    list?.map((c) => (c.id === customer.id ? { ...c, reminders_opt_in: optIn } : c));

  const toggle = async (optIn: boolean) => {
    setSaving(true);
    setOutcome(null);
    if (synthetic) {
      qc.setQueryData<{ customers: Customer[] }>(syntheticKey(), (d) => (d ? { ...d, customers: patch(optIn)(d.customers) ?? [] } : d));
      announce(optIn ? C.optInSavedOn : C.optInSavedOff);
      setSaving(false);
      return;
    }
    const key = queryKeys.customers();
    const before = qc.getQueryData<Customer[]>(key);
    qc.setQueryData<Customer[]>(key, patch(optIn));
    try {
      await setReminderOptIn(customer.id, optIn);
      announce(optIn ? C.optInSavedOn : C.optInSavedOff);
      void qc.invalidateQueries({ queryKey: key });
    } catch {
      qc.setQueryData(key, before);
      announce(C.optInFailed, 'assertive');
      void toast(C.optInFailed);
    } finally {
      setSaving(false);
    }
  };

  const line = avail.enabled ? C.optedIn : C[avail.reason ?? 'reasonNotOptedIn'];
  return (
    <div className="flex flex-col">
      <div className="flex gap-2.5">
        <button
          type="button"
          disabled={!avail.enabled || busy}
          aria-describedby={lineId}
          onClick={() => void send()}
          className="inline-flex min-h-13 min-w-0 flex-1 items-center justify-center gap-2 rounded-control bg-accent px-4 text-[1rem] font-medium text-on-accent hover:brightness-95 active:brightness-90 disabled:opacity-50"
        >
          <Bell aria-hidden="true" size={18} strokeWidth={1.8} className="shrink-0" />
          {busy ? C.reminding : C.remind}
        </button>
        <Link
          to="/"
          aria-label={fill(C.speak, { name: customer.display })}
          className="inline-flex min-h-13 w-13 shrink-0 items-center justify-center rounded-control border border-line-strong text-ink hover:bg-fill"
        >
          <Mic aria-hidden="true" size={20} strokeWidth={1.8} />
        </Link>
      </div>
      <p id={lineId} className="mt-2.5 text-meta text-ink-2">
        {fill(line, { name: customer.display })}
      </p>
      {outcome && avail.enabled ? (
        <ReminderOutcome
          outcome={outcome}
          lang={lang}
          customerId={customer.id}
          saving={saving}
          onSaving={setSaving}
          onReady={(r) => setOutcome({ kind: 'ready', reminder: r })}
        />
      ) : null}

      <div className="mt-5 border-y border-line">
        <Switch
          checked={customer.reminders_opt_in}
          onCheckedChange={(v) => void toggle(v)}
          label={C.optInLabel}
          description={customer.reminders_opt_in ? C.optInOnNote : C.optInOffNote}
          stateWords={[C.optInOn, C.optInOff]}
          disabled={saving}
        />
      </div>
    </div>
  );
}

interface OutcomeProps {
  outcome: NonNullable<Outcome>;
  lang: Lang;
  customerId: string;
  saving: boolean;
  onSaving: (v: boolean) => void;
  onReady: (r: Reminder) => void;
}

function ReminderOutcome({ outcome, lang, customerId, saving, onSaving, onReady }: OutcomeProps) {
  const C = customerLabels(lang);
  if (outcome.kind === 'failed') return <p className="text-meta text-ink">{C.reminderFailed}</p>;
  if (outcome.kind === 'none') return <p className="text-meta text-ink">{C.reminderNone}</p>;
  if (outcome.kind === 'quiet') return <p className="text-meta text-ink">{C.reminderQuietHours}</p>;
  const r = outcome.reminder;
  const link = safeWaLink(r.wa_link);
  return (
    <div className="mt-2 flex flex-col gap-3 border-y border-line py-4">
      <p className="flex flex-wrap items-baseline gap-x-2 text-label text-ink">
        {C.reminderReady}
        <Amount value={r.amount} sign="none" size="inherit" lang={lang} className="text-ink-2" />
      </p>
      <blockquote className="max-w-prose text-body text-ink-2" lang="hi-Latn">
        {r.message}
      </blockquote>
      {outcome.sms ? <p className="text-meta text-ink">{C.reminderSms}</p> : null}
      {link ? (
        <a
          href={link}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-12 items-center justify-center gap-2 self-start rounded-control border border-line-strong bg-surface px-4 text-label text-ink hover:bg-tint"
        >
          <ExternalLink aria-hidden="true" size={18} strokeWidth={1.75} />
          {C.reminderOpen}
          <span className="sr-only">({C.reminderOpenSr})</span>
        </a>
      ) : (
        <PhoneForm lang={lang} customerId={customerId} saving={saving} onSaving={onSaving} onReady={onReady} />
      )}
    </div>
  );
}

function PhoneForm({ lang, customerId, saving, onSaving, onReady }: Omit<OutcomeProps, 'outcome'>) {
  const C = customerLabels(lang);
  const inputId = useId();
  const hintId = useId();
  const errId = useId();
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const phone = normalizePhone(value);
    if (!phone) {
      setError(C.phoneInvalid);
      return;
    }
    setError(null);
    onSaving(true);
    try {
      await setReminderOptIn(customerId, true, phone);
      const found = reminderFor(await getReminders(), customerId);
      if (found) {
        onReady(found);
        announce(C.reminderReady);
      }
    } catch {
      setError(C.phoneFailed);
    } finally {
      onSaving(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-2" noValidate>
      <p className="text-meta text-ink">{C.reminderNoPhone}</p>
      <label htmlFor={inputId} className="text-label text-ink">
        {C.phoneLabel}
      </label>
      <div className="flex flex-wrap items-start gap-2">
        <input
          id={inputId}
          type="tel"
          inputMode="tel"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${hintId} ${errId}` : hintId}
          className="block min-h-12 min-w-0 flex-1 basis-48 rounded-control border border-line-strong bg-surface px-3 text-body text-ink tabular"
        />
        <Button type="submit" disabled={saving}>
          {saving ? C.phoneSaving : C.phoneSave}
        </Button>
      </div>
      <p id={hintId} className="text-meta text-ink-2">
        {C.phoneHint}
      </p>
      {error ? (
        <p id={errId} className="text-meta font-semibold text-ink">
          {error}
        </p>
      ) : null}
    </form>
  );
}
