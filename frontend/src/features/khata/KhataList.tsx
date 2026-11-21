// The Khata pane (design board "Khata"): title and date, today's totals as one ruled two-column strip,
// "Kul baaki ₹X · N grahak", the search field, the Sab / Baaki wale / Aaj chips, and the windowed customer list.
// On a phone it is the whole screen; on a tablet or desktop it is the left pane next to the customer detail, where
// its title becomes an h2 (the detail owns the h1).
// Sizes the token scale does not have (32 title, 14 date, 19 balance, 12 state word...) are rem values taken from
// the board, so "Bada text" and browser zoom still scale them.
import { StaleNote } from '../../services/offline/OfflineNotes';
import { Link } from '@tanstack/react-router';
import { CloudOff, Search, X } from 'lucide-react';
import { useEffect, useId, useRef } from 'react';
import { Amount } from '../../components/Amount';
import { Button } from '../../components/Button';
import { announce } from '../../components/LiveRegion';
import { useOnline } from '../../hooks/useOnline';
import { clockTime } from '../../lib/format';
import { useSession } from '../../state/session';
import type { Lang } from '../../i18n';
import { CustomerRow } from './CustomerRow';
import { FilterChip } from './FilterChip';
import { useKhataData } from './data';
import { khataLabels, fill, type KhataLabelKey } from './labels';
import { activeToday, duesSummary, filterCustomers, lastActivity, sortCustomers, todayLine, FILTERS, type KhataFilter } from './logic';
import { useKhataView } from './view';
import { useWindowedList } from './useWindowedList';

const FILTER_LABEL: Record<KhataFilter, KhataLabelKey> = { all: 'filterAll', due: 'filterDue', today: 'filterToday' };

export function KhataList({ titleLevel }: { titleLevel: 'h1' | 'h2' }) {
  const lang = useSession((s) => s.lang);
  const K = khataLabels(lang);
  const data = useKhataData();
  const online = useOnline();
  const now = new Date();
  const Title = titleLevel;
  const totals = data.ledger?.totals;
  const customers = data.customers;
  const dues = duesSummary(customers ?? []);

  return (
    <div className="flex flex-col px-6 pt-7 pb-[calc(var(--spacing-tabs)+var(--spacing-mic-sm)+3rem+env(safe-area-inset-bottom))] lg:px-8 lg:pb-44">
      <div className="flex flex-col gap-1">
        <Title id="khata-title" tabIndex={-1} className="font-display text-[2rem] leading-[1.1] font-medium tracking-[-0.02em] text-ink outline-none">
          {K.title}
        </Title>
        <p className="text-[0.875rem] text-ink-2">{todayLine(now, lang)}</p>
      </div>
      {/* Cached data on screen: when it was last synced (services/offline). */}
      <StaleNote className="mt-3" />

      <section aria-labelledby="khata-totals" className="mt-[1.375rem]">
        <h2 id="khata-totals" className="sr-only">
          {K.todayTotals}
        </h2>
        <dl className="grid grid-cols-2 border-y border-line">
          <TotalCell label={K.creditGiven} value={totals?.credit_today} kind="credit" lang={lang} first />
          <TotalCell label={K.paymentIn} value={totals?.payment_today} kind="payment" lang={lang} />
        </dl>
        {customers ? (
          <p className="mt-2.5 text-[0.875rem] text-ink-2">
            {K.totalDue}{' '}
            <Amount value={dues.total} sign="none" size="inherit" lang={lang} className="text-ink [&_.amount-digits]:font-semibold" />
            {' · '}
            <span className="tabular">{dues.owing}</span> {dues.owing === 1 ? K.customersOne : K.customersMany}
          </p>
        ) : null}
      </section>

      {!online && customers ? (
        <p className="mt-5 flex items-start gap-2 border-y border-line py-3 text-meta text-ink">
          <CloudOff aria-hidden="true" size={16} strokeWidth={1.75} className="mt-0.5 shrink-0" />
          <span>
            {K.offlineStale}
            {data.updatedAt ? <span className="text-ink-2"> {fill(K.updatedAt, { time: clockTime(new Date(data.updatedAt).toISOString()) })}</span> : null}
          </span>
        </p>
      ) : null}

      <ListBody data={data} online={online} lang={lang} now={now} />
    </div>
  );
}

function TotalCell({ label, value, kind, lang, first = false }: { label: string; value: number | undefined; kind: 'credit' | 'payment'; lang: Lang; first?: boolean }) {
  return (
    <div className={`@container flex min-w-0 flex-col gap-1 py-4 ${first ? 'border-e border-line pe-4' : 'ps-[1.125rem]'}`}>
      <dt className="text-meta text-ink-2">{label}</dt>
      {/* 30px, shrinking with the column so ₹1,00,000 fits at 320px and with large text. */}
      <dd className="text-total [&_.amount-symbol]:text-[0.7em]" style={{ fontSize: 'min(var(--text-total), 18cqi)' }}>
        {value === undefined ? (
          <span className="amount text-ink-2" aria-hidden="true">
            —
          </span>
        ) : (
          <Amount value={value} kind={kind} size="inherit" tone lang={lang} />
        )}
      </dd>
    </div>
  );
}

interface ListBodyProps {
  data: ReturnType<typeof useKhataData>;
  online: boolean;
  lang: Lang;
  now: Date;
}

function ListBody({ data, online, lang, now }: ListBodyProps) {
  const K = khataLabels(lang);
  const { query, filter, setQuery, setFilter } = useKhataView();
  const searchId = useId();
  const chipsId = useId();
  const inputRef = useRef<HTMLInputElement>(null);

  const customers = data.customers;
  const entries = data.ledger?.entries ?? [];
  const last = lastActivity(entries);
  const today = activeToday(entries, now);
  const sorted = sortCustomers(customers ?? [], last);
  const shown = filterCustomers(sorted, { filter, query, today });

  // Announce how many customers match, once typing pauses.
  const shownCount = shown.length;
  const filtering = query.trim() !== '' || filter !== 'all';
  useEffect(() => {
    if (!filtering || !customers) return;
    const id = setTimeout(() => announce(fill(K.resultCount, { n: shownCount })), 700);
    return () => clearTimeout(id);
  }, [shownCount, filtering, query, filter, customers, K.resultCount]);

  if (!customers) {
    return (
      <div className="mt-6">
        {data.failed ? <ErrorState lang={lang} onRetry={data.retry} /> : !online ? <p className="text-body text-ink">{K.offlineEmpty}</p> : <LoadingState lang={lang} />}
      </div>
    );
  }
  if (!customers.length) return <EmptyState lang={lang} />;

  return (
    <section aria-labelledby="khata-list-title" className="flex flex-col">
      <h2 id="khata-list-title" className="sr-only">
        {K.listLabel}
      </h2>
      {data.failed ? (
        <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-y border-line py-3">
          <p className="min-w-0 flex-1 text-meta text-ink">{K.errorBody}</p>
          <Button onClick={data.retry}>{K.retry}</Button>
        </div>
      ) : null}

      <div className="flex flex-col gap-3 pt-5">
        <label htmlFor={searchId} className="sr-only">
          {K.searchLabel}
        </label>
        <div className="flex min-h-12 items-center gap-2.5 rounded-control border border-line bg-surface ps-3.5 has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-3 has-[input:focus-visible]:outline-accent">
          <Search aria-hidden="true" size={18} strokeWidth={1.8} className="shrink-0 text-ink-2" />
          <input
            ref={inputRef}
            id={searchId}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={K.searchPlaceholder}
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="search"
            className="min-h-12 min-w-0 flex-1 bg-transparent pe-3.5 text-[1rem] text-ink outline-none placeholder:text-ink-2 [&::-webkit-search-cancel-button]:appearance-none"
          />
          {query ? (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                inputRef.current?.focus();
              }}
              aria-label={K.searchClear}
              className="inline-flex size-12 shrink-0 items-center justify-center rounded-control text-ink-2 hover:text-ink"
            >
              <X aria-hidden="true" size={18} strokeWidth={1.75} />
            </button>
          ) : null}
        </div>

        <div role="group" aria-labelledby={chipsId} className="flex flex-wrap gap-2">
          <span id={chipsId} className="sr-only">
            {K.filterLabel}
          </span>
          {FILTERS.map((f) => (
            <FilterChip key={f} selected={filter === f} onSelect={() => setFilter(f)}>
              {K[FILTER_LABEL[f]]}
            </FilterChip>
          ))}
        </div>
      </div>

      <div className="mt-2.5">
        {shown.length ? (
          <CustomerList customers={shown} last={last} lang={lang} now={now} />
        ) : (
          <div className="flex flex-col items-start gap-3 py-6">
            <p className="text-label text-ink">{K.noMatchTitle}</p>
            <p className="max-w-prose text-body text-ink-2">{query.trim() ? fill(K.noMatchSearch, { q: query.trim() }) : K.noMatchFilter}</p>
            <Button
              onClick={() => {
                setQuery('');
                setFilter('all');
              }}
            >
              {K.showAll}
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}

const ROW_ESTIMATE_PX = 65;

function CustomerList({ customers, last, lang, now }: { customers: ReturnType<typeof filterCustomers>; last: ReturnType<typeof lastActivity>; lang: Lang; now: Date }) {
  const K = khataLabels(lang);
  const { attachList, total, rows, measureRow, rowFocus, rowBlur } = useWindowedList({ items: customers, getKey: (c) => c.id, estimate: ROW_ESTIMATE_PX });
  return (
    <ul ref={attachList} aria-label={K.listLabel} className="relative" style={{ height: total }}>
      {rows.map((row) => (
        <li
          key={row.key}
          ref={measureRow}
          data-key={row.key}
          aria-setsize={customers.length}
          aria-posinset={row.index + 1}
          className="absolute inset-x-0 top-0 border-b border-line"
          style={{ transform: `translateY(${row.top}px)` }}
        >
          <CustomerRow
            customer={row.item}
            last={last.get(row.item.id)}
            lang={lang}
            now={now}
            onFocus={() => rowFocus(row.key)}
            onBlur={rowBlur}
          />
        </li>
      ))}
    </ul>
  );
}

function LoadingState({ lang }: { lang: Lang }) {
  const K = khataLabels(lang);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-body text-ink-2">{K.loading}</p>
      <ul aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <li key={i} className="flex min-h-16 items-center gap-3.5 border-b border-line">
            <span className="size-10 rounded-full bg-avatar" />
            <span className="h-3 w-2/5 rounded-chip bg-fill" />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ErrorState({ lang, onRetry }: { lang: Lang; onRetry: () => void }) {
  const K = khataLabels(lang);
  return (
    <div className="flex flex-col items-start gap-3 border-y border-line py-6">
      <p className="text-label text-ink">{K.errorTitle}</p>
      <p className="max-w-prose text-body text-ink-2">{K.errorBody}</p>
      <Button onClick={onRetry}>{K.retry}</Button>
    </div>
  );
}

function EmptyState({ lang }: { lang: Lang }) {
  const K = khataLabels(lang);
  return (
    <div className="mt-6 flex flex-col items-start gap-3 border-y border-line py-8">
      <p className="text-label text-ink">{K.emptyTitle}</p>
      <p className="max-w-prose text-body text-ink-2">{K.emptyBody}</p>
      <p className="text-title-sm text-ink" lang={lang === 'en' ? 'en' : 'hi-Latn'}>
        {K.emptySample}
      </p>
      <Link
        to="/"
        className="mt-2 inline-flex min-h-12 items-center rounded-control border border-line-strong bg-surface px-4 text-label text-ink hover:bg-fill"
      >
        {K.emptyGo}
      </Link>
    </div>
  );
}
