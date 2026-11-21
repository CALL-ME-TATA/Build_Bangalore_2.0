// Reminder opt-ins: every customer with a switch ("Chalu" / "Band"). A change is shown at once and sent to
// POST /api/customers/{id}/reminders; on failure it is put back and the reason is said. Offline, the switches
// are disabled with the reason in words. A search box appears for longer lists.
import { useMutation } from '@tanstack/react-query';
import { useId, useMemo, useState } from 'react';
import { Switch } from '../../components/Switch';
import { announce } from '../../components/LiveRegion';
import { useOnline } from '../../hooks/useOnline';
import { customerName, groupDigits, RUPEE } from '../../lib/format';
import { setReminderOptIn, type Customer } from '../../services/api';
import { queryClient, queryKeys, useCustomers } from '../../services/query';
import type { SettingsLabels } from './labels';
import { filterCustomers } from './choices';

const SEARCH_FROM = 8;

function balanceWords(c: Customer, L: SettingsLabels): string {
  if (c.balance > 0) return `${RUPEE}${groupDigits(c.balance)} ${L.baaki}`;
  if (c.balance < 0) return `${RUPEE}${groupDigits(c.balance)} ${L.advance}`;
  return L.settled;
}

export function RemindersList({ L }: { L: SettingsLabels }) {
  const customers = useCustomers();
  const online = useOnline();
  const [q, setQ] = useState('');
  const searchId = useId();
  const all = useMemo(() => customers.data ?? [], [customers.data]);
  const shown = useMemo(() => filterCustomers(all, q), [all, q]);

  const toggle = useMutation({
    mutationFn: ({ id, optIn }: { id: string; optIn: boolean }) => setReminderOptIn(id, optIn),
    onMutate: async ({ id, optIn }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.customers() });
      const before = queryClient.getQueryData<Customer[]>(queryKeys.customers());
      queryClient.setQueryData<Customer[]>(queryKeys.customers(), (old) => old?.map((c) => (c.id === id ? { ...c, reminders_opt_in: optIn } : c)));
      return { before };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.before) queryClient.setQueryData(queryKeys.customers(), ctx.before);
      announce(L.remindersFailed, 'assertive');
    },
    onSuccess: () => announce(L.remindersSaved),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customers() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.reminders() });
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-prose text-body text-ink-2">{L.remindersNote}</p>
      {!online ? <p className="text-label text-ink">{L.remindersOffline}</p> : null}
      {toggle.isError ? <p className="text-label text-ink">{L.remindersFailed}</p> : null}

      {all.length >= SEARCH_FROM ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={searchId} className="text-label text-ink">
            {L.remindersSearch}
          </label>
          <input
            id={searchId}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoComplete="off"
            className="block min-h-12 w-full max-w-md rounded-control border border-line-strong bg-surface px-3 text-body text-ink"
          />
        </div>
      ) : null}

      {customers.isPending ? (
        <p role="status" className="text-body text-ink-2">
          {L.remindersLoading}
        </p>
      ) : customers.isError && !customers.data ? (
        <p className="text-body text-ink">{L.remindersError}</p>
      ) : !all.length ? (
        <p className="text-body text-ink-2">{L.remindersEmpty}</p>
      ) : !shown.length ? (
        <p className="text-body text-ink-2">{L.remindersNoMatch}</p>
      ) : (
        <ul className="ruled border-y border-line">
          {shown.map((c) => (
            <li key={c.id}>
              <Switch
                checked={c.reminders_opt_in}
                onCheckedChange={(optIn) => toggle.mutate({ id: c.id, optIn })}
                label={customerName(c)}
                description={balanceWords(c, L)}
                stateWords={[L.on, L.off]}
                disabled={!online || (toggle.isPending && toggle.variables?.id === c.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
