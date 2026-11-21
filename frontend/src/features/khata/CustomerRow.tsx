// One customer as a ruled ledger line (design board "Khata"): 40px initial avatar, "Ramesh · Chai wale" on one
// line (ellipsis; the full name stays in the accessible name and the title), "Aakhri entry aaj" under it, and at
// the right the balance in Spectral over its state word ("baaki" / "advance jama" / "hisaab saaf"; a zero balance
// shows a dash). The balance ink follows the state, and the word always says it, so colour is never the only cue.
// The whole row links to the customer; on wide screens the open customer's row is highlighted with a bar.
import { Link } from '@tanstack/react-router';
import type { FocusEvent } from 'react';
import type { Customer } from '../../services/api';
import type { Entry } from '../../services/session/types';
import type { Lang } from '../../i18n';
import { Amount } from '../../components/Amount';
import { initial } from '../../lib/format';
import { balanceState, balanceWord, lastEntryText, scriptLang, tagLabel } from './logic';
import { khataLabels } from './labels';

export interface CustomerRowProps {
  customer: Customer;
  last: Entry | undefined;
  lang: Lang;
  now: Date;
  onFocus?: () => void;
  onBlur?: (e: FocusEvent<HTMLElement>) => void;
}

const INK = { due: 'text-credit', advance: 'text-payment', clear: 'text-ink-2' } as const;

export function CustomerRow({ customer, last, lang, now, onFocus, onBlur }: CustomerRowProps) {
  const K = khataLabels(lang);
  const tag = tagLabel(customer.tags);
  const state = balanceState(customer.balance);
  const full = tag ? `${customer.display} · ${tag}` : customer.display;
  return (
    <Link
      to="/khata/$id"
      params={{ id: customer.id }}
      onFocus={onFocus}
      onBlur={onBlur}
      className="relative flex min-h-16 flex-wrap items-center gap-x-3.5 gap-y-1 py-2 text-ink before:absolute before:inset-y-0 before:-start-6 before:w-[3px] before:bg-transparent hover:bg-highlight aria-[current=page]:bg-highlight aria-[current=page]:before:bg-ink"
    >
      <span
        aria-hidden="true"
        className="inline-grid size-10 shrink-0 place-items-center rounded-full bg-avatar text-[0.9375rem] font-semibold text-ink"
        lang={scriptLang(customer.display)}
      >
        {initial(customer.display)}
      </span>
      <span className="flex min-w-[min(100%,7rem)] flex-1 flex-col gap-0.5">
        <span className="truncate text-label" title={full}>
          <span lang={scriptLang(customer.display)}>{customer.display}</span>
          {tag ? (
            <span lang={scriptLang(tag)}>
              {' · '}
              {tag}
            </span>
          ) : null}
        </span>
        <span className="text-meta text-ink-2">{lastEntryText(last, now, lang) ?? K.noActivity}</span>
      </span>
      <span className="ms-auto flex shrink-0 flex-col items-end gap-0.5 text-end">
        <span className={`text-[1.1875rem] leading-[1.2] ${INK[state]}`}>
          {state === 'clear' ? (
            <span className="amount">
              <span aria-hidden="true">—</span>
              <span className="sr-only">{K.zeroSr}</span>
            </span>
          ) : (
            <Amount value={Math.abs(customer.balance)} sign="none" size="inherit" lang={lang} />
          )}
        </span>
        <span className="text-[0.75rem] leading-[1.3] text-ink-2">{balanceWord(customer.balance, lang)}</span>
      </span>
    </Link>
  );
}
