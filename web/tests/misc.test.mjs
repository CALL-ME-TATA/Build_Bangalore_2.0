import test from 'node:test';
import assert from 'node:assert/strict';
import { rupees, dayLabel, entryCard, latencyRows, stateLabel } from '../format.js';
import { wsUrl, backoffMs, helloMessage, SessionClient } from '../ws.js';

test('rupees uses Indian grouping', () => {
  assert.equal(rupees(0), '₹0');
  assert.equal(rupees(340), '₹340');
  assert.equal(rupees(1500), '₹1,500');
  assert.equal(rupees(125000), '₹1,25,000');
  assert.equal(rupees(-560), '-₹560');
});

test('dayLabel', () => {
  assert.equal(dayLabel('2026-11-21', '2026-11-21'), 'Today');
  assert.equal(dayLabel('2026-11-20', '2026-11-21'), 'Yesterday');
  assert.equal(dayLabel('2026-11-18', '2026-11-21'), '3 din pehle');
  assert.equal(dayLabel('2026-10-01', '2026-11-21'), '2026-10-01');
  assert.equal(dayLabel('2026-02-28', '2026-03-01'), 'Yesterday');
});

test('entryCard for credit, payment and reversed entries', () => {
  const e = { id: 1, kind: 'credit', customer: { display: 'Ramesh' }, amount: 340, date: '2026-11-21', reversed: false };
  const c = entryCard(e, '2026-11-21');
  assert.deepEqual([c.cls, c.sign, c.amount, c.kind, c.day, c.name], ['credit', '+', '₹340', 'Credit', 'Today', 'Ramesh']);
  const p = entryCard({ ...e, kind: 'payment', amount: 200, date: '2026-11-20', reversed: true }, '2026-11-21');
  assert.deepEqual([p.cls, p.amount, p.day, p.reversed], ['payment', '₹200', 'Yesterday', true]);
});

test('latencyRows lists server hops and the phone measurement', () => {
  const rows = latencyRows({ ms: { parse: 3.2, end_to_first_audio: 1200 } }, 1310.4);
  assert.deepEqual(rows, [['Parse', 3], ['End to first audio (server)', 1200], ['Release to first sound (phone)', 1310]]);
  assert.deepEqual(latencyRows(null, null), []);
});

test('stateLabel falls back to idle', () => {
  assert.match(stateLabel('speaking'), /Speaking/);
  assert.equal(stateLabel('bogus'), stateLabel('idle'));
});

test('wsUrl follows the page protocol', () => {
  assert.equal(wsUrl({ protocol: 'https:', host: 'a.trycloudflare.com' }), 'wss://a.trycloudflare.com/ws/session');
  assert.equal(wsUrl({ protocol: 'http:', host: 'localhost:8000' }), 'ws://localhost:8000/ws/session');
});

test('backoff doubles and caps', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 9].map(backoffMs), [500, 1000, 2000, 4000, 8000, 8000]);
});

test('hello carries resume and access code only when set', () => {
  assert.deepEqual(helloMessage(), { type: 'hello', lang: 'hi' });
  assert.deepEqual(helloMessage({ resume: 's1', accessCode: 'x' }), { type: 'hello', lang: 'hi', resume: 's1', access_code: 'x' });
});

test('SessionClient sends hello, then resume on reconnect', async () => {
  const sockets = [];
  class FakeWS {
    constructor(url) { this.url = url; this.sent = []; this.readyState = 0; sockets.push(this); }
    send(d) { this.sent.push(d); }
    close() {}
  }
  const seen = [];
  const c = new SessionClient({ url: 'ws://x', WS: FakeWS, onMessage: (m) => seen.push(m), onAudio: () => {}, onStatus: () => {} });
  c.connect();
  const a = sockets[0];
  a.readyState = 1; a.onopen();
  assert.deepEqual(JSON.parse(a.sent[0]), { type: 'hello', lang: 'hi' });
  a.onmessage({ data: JSON.stringify({ type: 'ready', session_id: 'S1' }) });
  assert.equal(seen[0].session_id, 'S1');
  assert.equal(c.send({ type: 'start', mode: 'ptt' }), true);
  a.readyState = 3; a.onclose();
  await new Promise((r) => setTimeout(r, 650));
  const b = sockets[1];
  b.readyState = 1; b.onopen();
  assert.deepEqual(JSON.parse(b.sent[0]), { type: 'hello', lang: 'hi', resume: 'S1' });
  c.close();
});
