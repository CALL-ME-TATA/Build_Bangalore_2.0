// Ported from web/tests/misc.test.mjs (protocol part), plus the session mode switch and the access code.
import { expect, test } from 'vitest';
import { SessionClient, backoffMs, helloMessage, wsUrl } from './protocol';
import { resolveMode } from './mode';
import { accessCode } from '../accessCode';
import type { ServerMessage } from './types';

test('wsUrl follows the page protocol', () => {
  expect(wsUrl({ protocol: 'https:', host: 'a.trycloudflare.com' })).toBe('wss://a.trycloudflare.com/ws/session');
  expect(wsUrl({ protocol: 'http:', host: 'localhost:8000' })).toBe('ws://localhost:8000/ws/session');
});

test('backoff doubles and caps', () => {
  expect([0, 1, 2, 3, 4, 9].map(backoffMs)).toEqual([500, 1000, 2000, 4000, 8000, 8000]);
});

test('hello carries resume and access code only when set', () => {
  expect(helloMessage()).toEqual({ type: 'hello', lang: 'hi' });
  expect(helloMessage({ resume: 's1', accessCode: 'x' })).toEqual({ type: 'hello', lang: 'hi', resume: 's1', access_code: 'x' });
  expect(helloMessage({ lang: 'en' })).toEqual({ type: 'hello', lang: 'en' });
});

test('SessionClient sends hello, then resume on reconnect, with the language set later', async () => {
  const sockets: FakeWS[] = [];
  class FakeWS {
    url: string;
    sent: string[] = [];
    readyState = 0;
    binaryType = '';
    onopen: (() => void) | null = null;
    onmessage: ((ev: { data: unknown }) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(url: string) {
      this.url = url;
      sockets.push(this);
    }
    send(d: string | ArrayBuffer) {
      this.sent.push(String(d));
    }
    close() {}
  }
  const seen: ServerMessage[] = [];
  const c = new SessionClient({ url: 'ws://x', accessCode: 'k', WS: FakeWS, onMessage: (m) => seen.push(m), onAudio: () => {}, onStatus: () => {} });
  c.connect();
  const a = sockets[0] as FakeWS;
  a.readyState = 1;
  a.onopen?.();
  expect(JSON.parse(a.sent[0] as string)).toEqual({ type: 'hello', lang: 'hi', access_code: 'k' });
  a.onmessage?.({ data: JSON.stringify({ type: 'ready', session_id: 'S1' }) });
  expect(seen[0]).toEqual({ type: 'ready', session_id: 'S1', resumed: false });
  expect(c.send({ type: 'start', mode: 'ptt' })).toBe(true);
  c.lang = 'en';
  a.readyState = 3;
  a.onclose?.();
  await new Promise((r) => setTimeout(r, 650));
  const b = sockets[1] as FakeWS;
  b.readyState = 1;
  b.onopen?.();
  // An automatic reconnect inside the page keeps the open question.
  expect(JSON.parse(b.sent[0] as string)).toEqual({ type: 'hello', lang: 'en', resume: 'S1', keep_pending: true, access_code: 'k' });
  b.onmessage?.({ data: JSON.stringify({ type: 'ready', session_id: 'S1' }) });
  expect(seen[1]).toEqual({ type: 'ready', session_id: 'S1', resumed: true });
  c.close();
});

test('binary frames go to onAudio and bad JSON is ignored', () => {
  const made: { onmessage: ((ev: { data: unknown }) => void) | null }[] = [];
  class FakeWS {
    readyState = 1;
    binaryType = '';
    onopen = null;
    onmessage: ((ev: { data: unknown }) => void) | null = null;
    onclose = null;
    onerror = null;
    constructor() {
      made.push(this);
    }
    send() {}
    close() {}
  }
  const audio: ArrayBuffer[] = [];
  const msgs: unknown[] = [];
  const c = new SessionClient({ url: 'ws://x', WS: FakeWS as never, onMessage: (m) => msgs.push(m), onAudio: (b) => audio.push(b), onStatus: () => {} });
  c.connect();
  const buf = new ArrayBuffer(4);
  made[0]?.onmessage?.({ data: buf });
  made[0]?.onmessage?.({ data: '{not json' });
  expect(audio).toEqual([buf]);
  expect(msgs).toEqual([]);
  c.close();
});

test('sendAudio drops frames while the socket is backed up', () => {
  const socks: { bufferedAmount: number; sent: unknown[] }[] = [];
  class FakeWS {
    readyState = 1;
    binaryType = '';
    bufferedAmount = 0;
    sent: unknown[] = [];
    onopen = null;
    onmessage = null;
    onclose = null;
    onerror = null;
    constructor() {
      socks.push(this);
    }
    send(d: unknown) {
      this.sent.push(d);
    }
    close() {}
  }
  const c = new SessionClient({ url: 'ws://x', WS: FakeWS as never, onMessage: () => {}, onAudio: () => {}, onStatus: () => {} });
  c.connect();
  expect(c.sendAudio(new ArrayBuffer(8))).toBe(true);
  (socks[0] as { bufferedAmount: number }).bufferedAmount = 300 * 1024;
  expect(c.sendAudio(new ArrayBuffer(8))).toBe(false);
  c.close();
});

test('mock or real session is chosen by ?mock=, then VITE_SESSION', () => {
  expect(resolveMode('', undefined)).toBe('ws');
  expect(resolveMode('?mock=1', undefined)).toBe('mock');
  expect(resolveMode('?mock=0', 'mock')).toBe('ws');
  expect(resolveMode('', 'mock')).toBe('mock');
  expect(resolveMode('?code=abc&mock=true', undefined)).toBe('mock');
});

test('the access code comes from ?code= in the page URL', () => {
  expect(accessCode('?code=abc')).toBe('abc');
  expect(accessCode('?mock=1')).toBeNull();
  expect(accessCode('')).toBeNull();
});

test('a page load starts a new session (no resume); private goes in every hello', () => {
  const sockets: { sent: string[]; readyState: number; onopen: (() => void) | null; onmessage: ((ev: { data: unknown }) => void) | null }[] = [];
  class FakeWS {
    sent: string[] = [];
    readyState = 0;
    binaryType = '';
    onopen: (() => void) | null = null;
    onmessage: ((ev: { data: unknown }) => void) | null = null;
    onclose = null;
    onerror = null;
    constructor() {
      sockets.push(this);
    }
    send(d: string) {
      this.sent.push(d);
    }
    close() {}
  }
  const seen: ServerMessage[] = [];
  const c = new SessionClient({ url: 'ws://x', private: true, WS: FakeWS as never, onMessage: (m) => seen.push(m), onAudio: () => {}, onStatus: () => {} });
  c.connect();
  const a = sockets[0]!;
  a.readyState = 1;
  a.onopen?.();
  expect(JSON.parse(a.sent[0] as string)).toEqual({ type: 'hello', lang: 'hi', private: true });
  a.onmessage?.({ data: JSON.stringify({ type: 'ready', session_id: 'NEW' }) });
  expect(seen[0]).toMatchObject({ session_id: 'NEW', resumed: false });
  c.close();
});

test('helloMessage leaves keep_pending out without resume', () => {
  expect(helloMessage({ keepPending: true })).toEqual({ type: 'hello', lang: 'hi' });
  expect(helloMessage({ resume: 'S', keepPending: true, private: true })).toEqual({ type: 'hello', lang: 'hi', resume: 'S', keep_pending: true, private: true });
});
