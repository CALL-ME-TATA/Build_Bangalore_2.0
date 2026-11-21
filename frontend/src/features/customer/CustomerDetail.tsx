// Customer detail, as on the "Customer" board: a "Khata" back link (phone), name · tag, "Baaki" and the hero
// balance (Spectral 64, in the ink of its state; the word above says the state too), the action row
// ("Reminder bhejein" + an outlined mic link to Bolo), the opt-in line and switch, and the timeline by date.
// States: loading, error with what to do, offline (figures may be stale), and an unknown id ("not found" with a
// way back). The API gives no opt-in date and no spoken phrase, so neither is shown.
import { Link } from '@tanstack/react-router';
import { ArrowLeft, ChevronLeft, CloudOff, Pencil, Plus } from 'lucide-react';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { Amount } from '../../components/Amount';
import { Button } from '../../components/Button';
import { useOnline } from '../../hooks/useOnline';
import { useSession } from '../../state/session';
import type { Lang } from '../../i18n';
import type { Customer } from '../../services/api';
import { LEDGER_LIMIT, useKhataData } from '../khata/data';
import { useCustomerLedger } from '../../services/query';
import { balanceState, scriptLang, tagLabel } from '../khata/logic';
import { customerLabels, type CustomerLabelKey } from './labels';
import { customerTimeline, historyMayBeCut } from './logic';
import { ReminderPanel } from './Reminder';
import { Timeline } from './Timeline';
import { useEdit } from './useEdit';
import { EditSheets, type EditState, type EditTarget } from './EditSheets';
import { fill } from '../khata/labels';
import { StaleNote } from '../../services/offline/OfflineNotes';

const BALANCE: Record<ReturnType<typeof balanceState>, { label: CustomerLabelKey; ink: string }> = {
  due: { label: 'balanceDue', ink: 'text-credit' },
  advance: { label: 'balanceAdvance', ink: 'text-payment' },
  clear: { label: 'balanceClear', ink: 'text-ink' },
};

export function CustomerDetail({ id }: { id: string }) {
  const lang = useSession((s) => s.lang);
  const C = customerLabels(lang);
  const data = useKhataData();
  const online = useOnline();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const customer = data.customers?.find((c) => c.id === id);
  const status = customer ? 'ok' : data.customers ? 'missing' : data.failed ? 'error' : !online ? 'offline' : 'loading';

  // A new screen: move focus to its heading (the route remounts this component for every customer).
  useEffect(() => {
    titleRef.current?.focus({ preventScroll: true });
  }, [status]);

  return (
    <section aria-labelledby="customer-title" className="min-w-0 px-6 pb-[calc(var(--spacing-tabs)+var(--spacing-mic-sm)+3rem+env(safe-area-inset-bottom))] sm:px-8 lg:px-10 lg:pb-32">
      <div className="mx-auto flex w-full max-w-talk flex-col">
        <Link
          to="/khata"
          aria-label={C.backSr}
          className="-ms-3 mt-[1.125rem] inline-flex min-h-11 items-center gap-1 self-start rounded-control px-3 text-[0.9375rem] text-ink-2 hover:text-ink sm:hidden"
        >
          <ChevronLeft aria-hidden="true" size={18} strokeWidth={1.8} />
          {C.back}
        </Link>
        <StaleNote className="mt-3" />
        {status === 'ok' && customer ? (
          <Found customer={customer} lang={lang} titleRef={titleRef} data={data} online={online} />
        ) : (
          <div className="flex flex-col items-start gap-3 pt-2 sm:pt-7">
            <h1 id="customer-title" ref={titleRef} tabIndex={-1} className="text-[1.25rem] font-semibold text-ink outline-none">
              {status === 'missing' ? C.notFoundTitle : status === 'error' ? C.errorTitle : C.loading}
            </h1>
            {status === 'missing' ? <p className="max-w-prose text-body text-ink-2">{C.notFoundBody}</p> : null}
            {status === 'error' ? <p className="max-w-prose text-body text-ink-2">{C.errorBody}</p> : null}
            {status === 'offline' ? <p className="max-w-prose text-body text-ink-2">{C.offlineStale}</p> : null}
            {status === 'error' ? <Button onClick={data.retry}>{C.retry}</Button> : null}
            {status === 'missing' ? (
              <Link
                to="/khata"
                className="mt-2 inline-flex min-h-12 items-center gap-2 rounded-control border border-line-strong bg-surface px-4 text-label text-ink hover:bg-tint"
              >
                <ArrowLeft aria-hidden="true" size={18} strokeWidth={1.75} />
                {C.back}
              </Link>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}

interface FoundProps {
  customer: Customer;
  lang: Lang;
  titleRef: RefObject<HTMLHeadingElement | null>;
  data: ReturnType<typeof useKhataData>;
  online: boolean;
}

function Found({ customer, lang, titleRef, data, online }: FoundProps) {
  const C = customerLabels(lang);
  const now = new Date();
  const tag = tagLabel(customer.tags);
  const balance = BALANCE[balanceState(customer.balance)];
  // By entry date for this customer (a back-dated entry sits under its own day); the shared list until it loads.
  const own = useCustomerLedger(customer.id, LEDGER_LIMIT, !data.synthetic);
  const entries = own.data?.entries ?? data.ledger?.entries ?? [];
  const groups = customerTimeline(entries, customer.id, now, lang);
  const [sheet, setSheet] = useState<EditState | null>(null);
  const save = useEdit();
  // Editing needs the server and real data: offline and on the synthetic list the controls are off, with the reason.
  const reason = !online ? C.editOffline : data.synthetic ? C.editSynthetic : null;
  const editable = reason === null;
  const open = (target: EditTarget) => setSheet({ open: true, target });

  return (
    <>
      <div className="flex flex-col gap-0.5 pt-2 sm:pt-7">
        <div className="flex items-start gap-1">
          <h1 id="customer-title" ref={titleRef} tabIndex={-1} className="min-w-0 flex-1 text-[1.25rem] leading-[1.35] font-semibold text-ink outline-none">
            <span lang={scriptLang(customer.display)}>{customer.display}</span>
            {tag ? (
              <span className="font-normal text-ink-2" lang={scriptLang(tag)}>
                {' · '}
                {tag}
              </span>
            ) : null}
          </h1>
          <button
            type="button"
            id="customer-edit"
            disabled={!editable}
            aria-describedby={reason ? 'edit-reason' : undefined}
            aria-label={fill(C.editCustomerSr, { name: customer.display })}
            onClick={() => open({ type: 'customer' })}
            className="-me-2 inline-flex size-11 shrink-0 items-center justify-center rounded-control text-ink-2 hover:bg-tint hover:text-ink disabled:opacity-50"
          >
            <Pencil aria-hidden="true" size={18} strokeWidth={1.8} />
          </button>
        </div>
        <p className="pt-[1.125rem] text-[0.875rem] text-ink-2">{C[balance.label]}</p>
        {/* 64px with the rupee sign at 40px; shrinks with the column so ₹1,00,000 fits at 320px and large text.
            The figure is a button: it opens "Baaki badlein". */}
        <div className="@container">
          <button
            type="button"
            id="balance-edit"
            disabled={!editable}
            aria-describedby={reason ? 'edit-reason' : undefined}
            onClick={() => open({ type: 'balance' })}
            className="flex min-h-11 max-w-full flex-wrap items-center gap-x-3 rounded-control text-start disabled:cursor-default"
          >
            <span className={`block text-hero [&_.amount-symbol]:text-[0.625em] ${balance.ink}`} style={{ fontSize: 'min(var(--text-hero), 17cqi)' }}>
              <Amount value={Math.abs(customer.balance)} sign="none" size="inherit" lang={lang} />
            </span>
            <Pencil aria-hidden="true" size={18} strokeWidth={1.8} className="shrink-0 text-ink-2" />
            <span className="sr-only">{C.editBalance}</span>
          </button>
        </div>
      </div>

      {!online ? (
        <p className="mt-4 flex items-start gap-2 border-y border-line py-3 text-meta text-ink">
          <CloudOff aria-hidden="true" size={16} strokeWidth={1.75} className="mt-0.5 shrink-0" />
          {C.offlineStale}
        </p>
      ) : null}

      <div className="pt-[1.375rem]">
        <ReminderPanel customer={customer} lang={lang} synthetic={data.synthetic} />
      </div>

      <div className="flex flex-col items-start gap-2 pt-[1.625rem]">
        <Button
          id="entry-new"
          icon={<Plus size={18} strokeWidth={1.8} />}
          disabled={!editable}
          aria-describedby={reason ? 'edit-reason' : undefined}
          onClick={() => open({ type: 'new' })}
        >
          {C.newEntry}
        </Button>
        {reason ? (
          <p id="edit-reason" className="text-meta text-ink-2">
            {reason}
          </p>
        ) : null}
      </div>

      <div className="pt-3">
        <Timeline
          groups={groups}
          lang={lang}
          now={now}
          cut={historyMayBeCut(entries.length, LEDGER_LIMIT)}
          onEdit={editable ? (entry) => open({ type: 'entry', entry }) : undefined}
        />
      </div>

      <EditSheets
        state={sheet}
        onClose={() => setSheet((s) => (s ? { ...s, open: false } : s))}
        customer={customer}
        customers={data.customers ?? [customer]}
        lang={lang}
        onSave={save}
      />
    </>
  );
}
