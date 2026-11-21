// Saving an edit without waiting: the sheet calls `save(job)` and closes at once. The job changes the react-query
// cache immediately (customers list and ledger views), is sent in the background, and then
// - on success, the server answer is written over the optimistic data (the temporary ids go away) and "saved" is said;
// - on failure, the cache is restored and only the mapped error is shown, as a toast (never "saved" first).
// Either way the khata queries are refreshed afterwards, once nothing else is in flight.
// Jobs are sent one after another, so a second edit never overtakes the first, and a second Save on the same entry
// or customer while one is in flight is ignored. A temporary id is never sent to the server.
import { useMutation } from '@tanstack/react-query';
import { announce } from '../../components/LiveRegion';
import { ymd } from '../../lib/format';
import { toast } from '../../lib/toast';
import {
  addEntry,
  amendEntry,
  removeEntry,
  updateCustomer,
  type AmendBody,
  type Customer,
  type CustomerPatch,
  type EntryChange,
  type NewEntryBody,
} from '../../services/api';
import { queryClient, queryKeys } from '../../services/query';
import type { Entry } from '../../services/session/types';
import { useSession } from '../../state/session';
import { errorKey, isTempId } from './edit';
import {
  applyChangeToCache,
  applyCustomerToCache,
  optimisticAdd,
  optimisticAmend,
  optimisticRemove,
  patchCustomer,
  restoreKhata,
  snapshotKhata,
  type KhataSnapshot,
} from './editCache';
import { customerLabels, type CustomerLabelKey } from './labels';

export type EditJob =
  | { type: 'add'; body: NewEntryBody; done: Extract<CustomerLabelKey, 'savedEntry' | 'savedBalance'> }
  | { type: 'amend'; entry: Entry; body: AmendBody }
  | { type: 'remove'; entry: Entry }
  | { type: 'customer'; id: string; patch: CustomerPatch };

interface Context {
  snapshot: KhataSnapshot;
  tempIds: (string | number)[];
}

const inflight = new Set<string>();
let active = 0;
let tail: Promise<unknown> = Promise.resolve();

/** Same-target jobs are one at a time: the key of what a job changes, or null for a new entry. */
export function jobKey(job: EditJob): string | null {
  if (job.type === 'add') return null;
  if (job.type === 'customer') return `customer:${job.id}`;
  return `entry:${job.entry.id}`;
}

/** Runs `send` after every earlier job has finished (whether or not it failed). */
function enqueue<T>(send: () => Promise<T>): Promise<T> {
  const run = tail.then(send);
  tail = run.catch(() => undefined);
  return run;
}

function send(job: EditJob): Promise<EntryChange | Customer> {
  if (job.type === 'add') return addEntry(job.body);
  if (job.type === 'customer') return updateCustomer(job.id, job.patch);
  // Entries still waiting for a server id are not editable; this is the last guard.
  if (isTempId(job.entry.id)) return Promise.reject(new Error('unconfirmed entry'));
  return job.type === 'amend' ? amendEntry(job.entry.id, job.body) : removeEntry(job.entry.id);
}

function doneLabel(job: EditJob): CustomerLabelKey {
  return job.type === 'add' ? job.done : job.type === 'amend' ? 'savedAmend' : job.type === 'remove' ? 'savedRemove' : 'savedCustomer';
}

const labelsNow = () => customerLabels(useSession.getState().lang);

export function useEdit(): (job: EditJob) => void {
  const mutation = useMutation<EntryChange | Customer, unknown, EditJob, Context>({
    networkMode: 'always',
    mutationFn: (job) => enqueue(() => send(job)),
    onMutate: async (job) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.all });
      const snapshot = snapshotKhata(queryClient);
      const customers = queryClient.getQueryData<Customer[]>(queryKeys.customers());
      const now = new Date();
      const tempIds: (string | number)[] = [];
      if (job.type === 'customer') {
        applyCustomerToCache(queryClient, job.id, (c) => patchCustomer(c, job.patch));
      } else {
        const change =
          job.type === 'add'
            ? optimisticAdd(job.body, customers, now, ymd(now))
            : job.type === 'amend'
              ? optimisticAmend(job.entry, job.body, customers, now)
              : optimisticRemove(job.entry, customers);
        for (const e of change.entries) if (isTempId(e.id)) tempIds.push(e.id);
        applyChangeToCache(queryClient, change);
      }
      return { snapshot, tempIds };
    },
    onSuccess: (data, job, ctx) => {
      // "Saved" is said only once the server has answered.
      const say = labelsNow()[doneLabel(job)];
      announce(say);
      void toast(say);
      if (job.type === 'customer') {
        applyCustomerToCache(queryClient, job.id, () => data as Customer);
      } else {
        applyChangeToCache(queryClient, data as EntryChange, ctx?.tempIds ?? []);
      }
    },
    onError: (error, _job, ctx) => {
      if (ctx) restoreKhata(queryClient, ctx.snapshot);
      const text = labelsNow()[errorKey(error)];
      announce(text, 'assertive');
      void toast(text);
    },
    onSettled: (_data, _error, job) => {
      const key = jobKey(job);
      if (key) inflight.delete(key);
      active -= 1;
      if (active <= 0) void queryClient.invalidateQueries({ queryKey: queryKeys.all });
    },
  });

  return (job) => {
    const key = jobKey(job);
    if (key && inflight.has(key)) return;
    if ((job.type === 'amend' || job.type === 'remove') && isTempId(job.entry.id)) return;
    if (key) inflight.add(key);
    active += 1;
    mutation.mutate(job);
  };
}
