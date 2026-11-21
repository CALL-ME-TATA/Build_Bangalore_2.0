// The offline queue path of the Bolo screen, end to end in mock mode: the real session store, the real outbox
// sync driver and the scripted mock session. Only the encrypted IndexedDB layer is replaced by memory.
// Checks: a sentence typed while disconnected is queued with one utt_id, sent with that id when the connection
// is back, and never saved twice; queued sentences go one at a time, and a question stops the queue until it
// is answered, so a later sentence is never taken as the answer.
import { afterAll, beforeAll, expect, test, vi } from 'vitest';
import type { OutboxRecord } from '../../services/offline/queue';

vi.mock('../../services/offline/outbox', () => {
  let rows: OutboxRecord[] = [];
  let next = 1;
  return {
    loadOutbox: async () => rows.map((r) => ({ ...r })),
    addOutbox: async (text: string, createdAt = new Date().toISOString()) => {
      const { newUttId } = await import('../../lib/ids');
      const rec: OutboxRecord = { id: next++, createdAt, text, state: 'pending', reason: null, attempts: 0, uttId: newUttId() };
      rows.push(rec);
      return { ...rec };
    },
    writeOutbox: async (rec: OutboxRecord) => {
      rows = [...rows.filter((r) => r.id !== rec.id), { ...rec }];
    },
    deleteOutbox: async (id: number) => {
      rows = rows.filter((r) => r.id !== id);
    },
  };
});

type SessionModule = typeof import('../../state/session');
type StatusModule = typeof import('../../services/offline/status');
let S: SessionModule;
let O: StatusModule;

beforeAll(async () => {
  vi.stubEnv('VITE_SESSION', 'mock');
  // The sync driver listens for the browser's "online" event; Node has no window.
  (globalThis as { window?: unknown }).window ??= { addEventListener() {}, removeEventListener() {} };
  // Node's navigator has no onLine; a browser always has it.
  Object.defineProperty(globalThis.navigator, 'onLine', { value: true, configurable: true });
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  S = await import('../../state/session');
  O = await import('../../services/offline/status');
  await S.startSession('hi'); // loads the mock session, which schedules the greeting
  await vi.advanceTimersByTimeAsync(6000); // the greeting plays to its end
  await import('../../services/offline/sync'); // the outbox driver is loaded lazily by startSession
  await vi.advanceTimersByTimeAsync(10);
});

afterAll(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

const settle = (ms = 9000) => vi.advanceTimersByTimeAsync(ms);
const outbox = () => O.useOffline.getState().outbox;
const disconnect = () => S.useSession.getState().dispatch({ type: 'conn', status: 'reconnecting' });
const reconnect = () => S.useSession.getState().dispatch({ type: 'conn', status: 'open' });

test('the mock session is up and greeted', () => {
  const s = S.useSession.getState();
  expect(s.started).toBe(true);
  expect(s.greeted).toBe(true);
  expect(s.conn).toBe('open');
});

test('typed while disconnected: queued with one utt_id, sent with it on reconnect, never saved twice', async () => {
  disconnect();
  S.session.sendText('Ramesh ka 340 udhaar');
  await settle(50);
  expect(outbox()).toHaveLength(1);
  const uttId = outbox()[0]?.uttId;
  expect(uttId).toMatch(/^[0-9a-f-]{36}$/);

  reconnect();
  await settle();
  expect(outbox()).toHaveLength(0);
  const saved = S.useSession.getState().saved.filter((e) => e.customer.display === 'Ramesh' && e.amount === 340);
  expect(saved).toHaveLength(1);

  // A retry with the same utt_id (as after a lost result) gets `duplicate: true` and adds nothing.
  const count = S.useSession.getState().saved.length;
  S.sendTextNow('Ramesh ka 340 udhaar', { uttId });
  await settle();
  expect(S.useSession.getState().result?.duplicate).toBe(true);
  expect(S.useSession.getState().saved).toHaveLength(count);
});

test('one at a time, in order; a question holds the rest until it is answered', async () => {
  disconnect();
  S.session.sendText('Geeta ka teen sau chaalis udhaar');
  S.session.sendText('Sunita ne 150 diye');
  await settle(50);
  expect(outbox().map((r) => r.text)).toEqual(['Geeta ka teen sau chaalis udhaar', 'Sunita ne 150 diye']);

  reconnect();
  await settle();
  // The first one asked a question; the second waits instead of being taken as the answer.
  expect(S.useSession.getState().result).toMatchObject({ status: 'needs_clarification', reason: 'confusable_number' });
  expect(outbox().map((r) => r.text)).toEqual(['Sunita ne 150 diye']);
  await settle(15000);
  expect(outbox()).toHaveLength(1);

  // The shopkeeper answers (as a tap on "₹340" would); then the queue carries on.
  S.session.sendText('340');
  await settle();
  await settle();
  const saved = S.useSession.getState().saved;
  expect(saved.some((e) => e.customer.display === 'Geeta' && e.amount === 340)).toBe(true);
  expect(saved.some((e) => e.customer.display === 'Sunita' && e.amount === 150 && e.kind === 'payment')).toBe(true);
  expect(outbox()).toHaveLength(0);
});

test('a question raised by a LIVE turn holds the queue; it resumes after the answer', async () => {
  // Live (connected) sentence that asks a question.
  S.session.sendText('Mohan ka 5 lakh udhaar');
  await settle();
  expect(S.useSession.getState().result).toMatchObject({ status: 'needs_clarification', reason: 'plausibility' });
  // A sentence typed while disconnected must not go out while that question is open.
  disconnect();
  S.session.sendText('Sunita ne 120 diye');
  await settle(50);
  reconnect();
  await settle(15000);
  expect(outbox().map((r) => r.text)).toEqual(['Sunita ne 120 diye']);
  expect(S.useSession.getState().saved.some((e) => e.customer.display === 'Sunita' && e.amount === 120)).toBe(false);
  // The live answer closes it; then the queue carries on.
  S.session.sendText('haan');
  await settle();
  await settle();
  expect(S.useSession.getState().saved.some((e) => e.customer.display === 'Mohan' && e.amount === 500000)).toBe(true);
  expect(S.useSession.getState().saved.some((e) => e.customer.display === 'Sunita' && e.amount === 120)).toBe(true);
  expect(outbox()).toHaveLength(0);
});

test('the queue resumes after the question is cancelled ("Nahi")', async () => {
  S.session.sendText('Mohan ka 7 lakh udhaar');
  await settle();
  disconnect();
  S.session.sendText('Sunita ne 130 diye');
  await settle(50);
  reconnect();
  await settle(10000);
  expect(outbox()).toHaveLength(1);
  S.session.sendText('nahi');
  await settle();
  await settle();
  expect(S.useSession.getState().saved.some((e) => e.amount === 700000)).toBe(false);
  expect(S.useSession.getState().saved.some((e) => e.customer.display === 'Sunita' && e.amount === 130)).toBe(true);
  expect(outbox()).toHaveLength(0);
});

test('the queue resumes when the question expires (60 s), and the sentence is not taken as the answer', async () => {
  S.session.sendText('Mohan ka 9 lakh udhaar');
  await settle();
  disconnect();
  S.session.sendText('Sunita ne 140 diye');
  await settle(50);
  reconnect();
  await settle(30000);
  expect(outbox()).toHaveLength(1);
  await settle(40000); // past the 60 s expiry
  await settle();
  expect(outbox()).toHaveLength(0);
  const saved = S.useSession.getState().saved;
  expect(saved.some((e) => e.amount === 900000)).toBe(false);
  expect(saved.some((e) => e.customer.display === 'Sunita' && e.amount === 140)).toBe(true);
});

test('a stuck sentence (its question is gone, the replay comes back cancelled) is sent once under a new id', async () => {
  // First send: a question; then it is cancelled, so that question is no longer the open one.
  disconnect();
  S.session.sendText('Geeta ka teen sau chaalis udhaar');
  await settle(50);
  const firstId = outbox()[0]?.uttId;
  reconnect();
  await settle();
  expect(S.useSession.getState().result?.reason).toBe('confusable_number');
  S.session.sendText('nahi');
  await settle();
  // As after a page reload where that result was lost: the same record is pending again, same utt_id.
  O.useOffline.setState({
    outbox: [{ id: 99, text: 'Geeta ka teen sau chaalis udhaar', createdAt: new Date().toISOString(), state: 'pending', reason: null, attempts: 1, uttId: firstId }],
  });
  S.useSession.getState().dispatch({ type: 'conn', status: 'open' });
  await settle();
  await settle();
  // The replay got "Theek hai, entry nahi ki."; the renewed send (new id) reached the server and asked again.
  expect(S.useSession.getState().result).toMatchObject({ status: 'needs_clarification', reason: 'confusable_number' });
  expect(S.useSession.getState().result?.duplicate).toBe(false);
  expect(outbox()).toHaveLength(0);
});
