// The four edit sheets of the customer screen (docs/CONTRACT.md section 3.6):
// - "Grahak badlein": name, tag and phone number (the API gives only a hint of the stored number).
// - "Baaki badlein": a new balance; the difference is written as one entry, sent with `if_balance`.
// - "Nayi entry": an entry written by hand.
// - "Entry badlein": amount, kind, date and customer of one active entry, and a second step to remove it.
// Each form mounts when its sheet opens, so it starts from the current values every time. The logic is in edit.ts.
import { Trash2 } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent, type RefObject } from 'react';
import { Button } from '../../components/Button';
import { Sheet } from '../../components/Sheet';
import type { Lang } from '../../i18n';
import { groupDigits, ymd } from '../../lib/format';
import type { Customer } from '../../services/api';
import type { Entry, EntryKind } from '../../services/session/types';
import { fill } from '../khata/labels';
import { balanceState, tagLabel } from '../khata/logic';
import {
  amendBody,
  balanceChange,
  balanceEntry,
  customerPatch,
  dateProblem,
  entryFields,
  MIN_DATE,
  parseAmount,
  type LowerKind,
} from './edit';
import { ErrorLine, Field, INPUT_CLASS, KindPicker, SheetHeading, useFormError, type KindOption } from './EditParts';
import type { EditJob } from './useEdit';
import { customerLabels, type CustomerLabels } from './labels';

export type EditTarget = { type: 'customer' } | { type: 'balance' } | { type: 'new' } | { type: 'entry'; entry: Entry };

/** `open` goes false on close while `target` stays, so the sheet keeps its content while it slides away. */
export interface EditState {
  open: boolean;
  target: EditTarget;
}

interface EditSheetsProps {
  state: EditState | null;
  onClose: () => void;
  customer: Customer;
  customers: readonly Customer[];
  lang: Lang;
  /** Starts a save: the caller updates the cache at once and sends the request in the background. */
  onSave: (job: EditJob) => void;
}

/** The id of the control that opened a sheet, so focus goes back to it and not to the mic. */
export function openerId(t: EditTarget): string {
  return t.type === 'customer' ? 'customer-edit' : t.type === 'balance' ? 'balance-edit' : t.type === 'new' ? 'entry-new' : `entry-edit-${t.entry.id}`;
}

export function EditSheets({ state, onClose, customer, customers, lang, onSave }: EditSheetsProps) {
  const C = customerLabels(lang);
  const first = useRef<HTMLElement>(null);
  if (!state) return null;
  const t = state.target;
  const title = t.type === 'customer' ? C.editCustomer : t.type === 'balance' ? C.editBalance : t.type === 'new' ? C.newEntry : C.editEntry;
  return (
    <Sheet
      open={state.open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
      title={title}
      initialFocus={first}
      returnFocusIds={[openerId(t), 'customer-title']}
    >
      {t.type === 'customer' ? <CustomerForm customer={customer} lang={lang} first={first} onSave={onSave} onDone={onClose} onCancel={onClose} /> : null}
      {t.type === 'balance' ? <BalanceForm customer={customer} lang={lang} first={first} onSave={onSave} onDone={onClose} onCancel={onClose} /> : null}
      {t.type === 'new' || t.type === 'entry' ? (
        <EntryForm
          key={t.type === 'entry' ? String(t.entry.id) : 'new'}
          entry={t.type === 'entry' ? t.entry : null}
          customer={customer}
          customers={customers}
          lang={lang}
          first={first}
          onSave={onSave}
          onDone={onClose}
          onCancel={onClose}
        />
      ) : null}
    </Sheet>
  );
}

interface FormProps {
  lang: Lang;
  first: RefObject<HTMLElement | null>;
  onSave: (job: EditJob) => void;
  onDone: () => void;
  onCancel: () => void;
}

function Actions({ C, canSave, onCancel }: { C: CustomerLabels; canSave: boolean; onCancel: () => void }) {
  return (
    <div className="flex flex-wrap gap-2.5 pt-1">
      <Button type="submit" variant="primary" disabled={!canSave} className="min-w-0 flex-1 basis-36">
        {C.save}
      </Button>
      <Button onClick={onCancel} className="min-w-0 flex-1 basis-36">
        {C.cancel}
      </Button>
    </div>
  );
}

// ---- Grahak badlein ----

function CustomerForm({ customer, lang, first, onSave, onDone, onCancel }: FormProps & { customer: Customer }) {
  const C = customerLabels(lang);
  const { error, setError } = useFormError();
  const [name, setName] = useState(customer.display);
  const [tags, setTags] = useState(customer.tags.join(', '));
  const [phone, setPhone] = useState('');
  const [clearPhone, setClearPhone] = useState(false);
  const hint = customer.phone_hint ?? null;

  const result = customerPatch(customer, { name, tags, phone, clearPhone });
  // Save is offered when something differs; an invalid field is reported on Save.
  const dirty = result.patch !== null || result.error !== null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (result.error) return setError(result.error);
    if (!result.patch) return;
    const patch = result.patch;
    onSave({ type: 'customer', id: customer.id, patch });
    onDone();
  };

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <SheetHeading>{C.editCustomer}</SheetHeading>
      <Field label={C.nameLabel}>
        {({ id }) => (
          <input
            id={id}
            ref={first as RefObject<HTMLInputElement>}
            type="text"
            autoComplete="off"
            maxLength={60}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={INPUT_CLASS}
          />
        )}
      </Field>
      <Field label={C.tagLabel} hint={C.tagHint}>
        {({ id, describedBy }) => (
          <input id={id} type="text" autoComplete="off" value={tags} onChange={(e) => setTags(e.target.value)} aria-describedby={describedBy} className={INPUT_CLASS} />
        )}
      </Field>
      <div className="flex flex-col gap-1.5">
        <p className="text-meta text-ink-2">{hint ? fill(C.phoneSaved, { hint }) : C.phoneNoneSaved}</p>
        <Field label={C.phoneNewLabel} hint={clearPhone ? C.phoneWillClear : undefined}>
          {({ id, describedBy }) => (
            <input
              id={id}
              type="tel"
              inputMode="tel"
              autoComplete="off"
              value={phone}
              disabled={clearPhone}
              onChange={(e) => setPhone(e.target.value)}
              aria-describedby={describedBy}
              className={INPUT_CLASS}
            />
          )}
        </Field>
        {hint ? (
          <Button
            onClick={() => {
              setClearPhone(!clearPhone);
              setPhone('');
            }}
            className="self-start"
          >
            {clearPhone ? C.phoneKeep : C.phoneClear}
          </Button>
        ) : null}
      </div>
      {error ? <ErrorLine>{C[error]}</ErrorLine> : null}
      <Actions C={C} canSave={dirty} onCancel={onCancel} />
    </form>
  );
}

// ---- Baaki badlein ----

function BalanceForm({ customer, lang, first, onSave, onDone, onCancel }: FormProps & { customer: Customer }) {
  const C = customerLabels(lang);
  const { error, setError } = useFormError();
  const [text, setText] = useState('');
  const [lower, setLower] = useState<LowerKind | null>(null);
  const current = customer.balance;
  const change = balanceChange(current, text);
  const entry = balanceEntry(change, lower);
  const stateWord = C[balanceState(current) === 'due' ? 'balanceDue' : balanceState(current) === 'advance' ? 'balanceAdvance' : 'balanceClear'];

  const lowerOptions: KindOption<LowerKind>[] = [
    { value: 'payment', label: C.diffPayment },
    { value: 'writeoff', label: C.diffWriteoff },
  ];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (change.type === 'invalid') return setError('errBadAmount');
    if (change.type === 'toolarge') return setError('errBadAmount');
    if (!entry) return;
    onSave({ type: 'add', body: { customer_id: customer.id, kind: entry.kind, amount: entry.amount, if_balance: current }, done: 'savedBalance' });
    onDone();
  };

  let words: string | null = null;
  if (change.type === 'same') words = C.diffSame;
  else if (change.type === 'up') words = fill(C.diffUp, { n: groupDigits(change.amount) });
  else if (change.type === 'down') {
    words = lower ? fill(lower === 'payment' ? C.diffPaymentNote : C.diffWriteoffNote, { n: groupDigits(change.amount) }) : fill(C.diffDown, { n: groupDigits(change.amount) });
  } else if (change.type === 'toolarge') words = C.diffTooLarge;

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <SheetHeading>{C.editBalance}</SheetHeading>
      <p className="text-body text-ink-2">{fill(C.balanceNow, { state: stateWord, amount: `₹${groupDigits(current)}` })}</p>
      <Field label={C.balanceNewLabel} hint={C.balanceHint}>
        {({ id, describedBy }) => (
          <input
            id={id}
            ref={first as RefObject<HTMLInputElement>}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setError(null);
            }}
            aria-describedby={describedBy}
            className={INPUT_CLASS}
          />
        )}
      </Field>
      {words ? (
        <p aria-live="polite" className="text-body text-ink">
          {words}
        </p>
      ) : null}
      {change.type === 'down' ? <KindPicker legend={C.diffLowerLegend} options={lowerOptions} value={lower} onChange={setLower} /> : null}
      {error ? <ErrorLine>{C[error]}</ErrorLine> : null}
      <Actions C={C} canSave={entry !== null} onCancel={onCancel} />
    </form>
  );
}

// ---- Nayi entry / Entry badlein ----

function EntryForm({ entry, customer, customers, lang, first, onSave, onDone, onCancel }: FormProps & { entry: Entry | null; customer: Customer; customers: readonly Customer[] }) {
  const C = customerLabels(lang);
  const { error, setError } = useFormError();
  const today = ymd(new Date());
  const orig = entry ? entryFields(entry) : null;
  const [amountText, setAmountText] = useState(entry ? String(entry.amount) : '');
  const [kind, setKind] = useState<EntryKind | null>(entry ? entry.kind : null);
  const [date, setDate] = useState(orig?.date ?? today);
  const [customerId, setCustomerId] = useState(orig?.customerId ?? customer.id);
  const [confirming, setConfirming] = useState(false);
  const confirmRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
  }, [confirming]);

  const kinds: KindOption<EntryKind>[] = [
    { value: 'credit', label: C.kindCredit },
    { value: 'payment', label: C.kindPayment },
    { value: 'writeoff', label: C.kindWriteoff },
  ];
  const amount = parseAmount(amountText);
  const sorted = [...customers].sort((a, b) => a.display.localeCompare(b.display));
  const moved = orig && customerId !== orig.customerId ? customers.find((c) => c.id === customerId) : undefined;

  // Save stays off while nothing differs (an amend) or while no kind is chosen (a new entry).
  let canSave = kind !== null;
  if (orig && kind) canSave = amount === null ? true : amendBody(orig, { kind, amount, date, customerId }) !== null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!kind) return setError('errBadKind');
    if (amount === null) return setError('errBadAmount');
    if (dateProblem(date, today)) return setError('errBadDate');
    if (orig && entry) {
      const body = amendBody(orig, { kind, amount, date, customerId });
      if (!body) return setError('errNothingChanged');
      onSave({ type: 'amend', entry, body });
    } else {
      onSave({ type: 'add', body: { customer_id: customer.id, kind, amount, date }, done: 'savedEntry' });
    }
    onDone();
  };

  if (confirming && entry) {
    return (
      <div className="flex flex-col gap-4">
        <h2 ref={confirmRef} tabIndex={-1} className="text-[1.25rem] leading-[1.35] font-semibold text-ink outline-none">
          {C.removeAsk}
        </h2>
        <p className="text-body text-ink-2">{C.removeBody}</p>
        {error ? <ErrorLine>{C[error]}</ErrorLine> : null}
        <div className="flex flex-wrap gap-2.5">
          <Button
            variant="primary"
            icon={<Trash2 size={18} strokeWidth={1.8} />}
            onClick={() => {
              onSave({ type: 'remove', entry });
              onDone();
            }}
            className="min-w-0 flex-1 basis-36"
          >
            {C.removeYes}
          </Button>
          <Button
            onClick={() => {
              setConfirming(false);
              setError(null);
            }}
            className="min-w-0 flex-1 basis-36"
          >
            {C.removeNo}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <SheetHeading>{entry ? C.editEntry : C.newEntry}</SheetHeading>
      <Field label={C.amountLabel} hint={C.amountHint}>
        {({ id, describedBy }) => (
          <input
            id={id}
            ref={first as RefObject<HTMLInputElement>}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            value={amountText}
            onChange={(e) => setAmountText(e.target.value)}
            aria-describedby={describedBy}
            className={INPUT_CLASS}
          />
        )}
      </Field>
      <KindPicker legend={C.kindLegend} options={kinds} value={kind} onChange={setKind} />
      <Field label={C.dateLabel} hint={C.dateHint}>
        {({ id, describedBy }) => (
          <input id={id} type="date" min={MIN_DATE} max={today} value={date} onChange={(e) => setDate(e.target.value)} aria-describedby={describedBy} className={INPUT_CLASS} />
        )}
      </Field>
      {entry ? (
        <Field label={C.customerLabel} hint={moved ? fill(C.moveNote, { name: moved.display }) : undefined}>
          {({ id, describedBy }) => (
            <select id={id} value={customerId} onChange={(e) => setCustomerId(e.target.value)} aria-describedby={describedBy} className={INPUT_CLASS}>
              {sorted.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.tags.length ? `${c.display} · ${tagLabel(c.tags)}` : c.display}
                </option>
              ))}
            </select>
          )}
        </Field>
      ) : null}
      {error ? <ErrorLine>{C[error]}</ErrorLine> : null}
      <Actions C={C} canSave={canSave} onCancel={onCancel} />
      {entry ? (
        <Button
          icon={<Trash2 size={18} strokeWidth={1.8} />}
          onClick={() => {
            setError(null);
            setConfirming(true);
          }}
          className="self-start"
        >
          {C.removeEntry}
        </Button>
      ) : null}
    </form>
  );
}
