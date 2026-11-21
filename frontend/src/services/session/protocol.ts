// Protocol client for /ws/session: hello, reconnect with resume, ping, JSON and binary frames.
// Ported from the first web app (web/ws.js) and extended for contract 3.3:
// - the first connection of a page load sends no `resume`: every page load is a new session, and its greeting
//   (with the AI disclosure) plays again (L05);
// - an automatic reconnect inside the loaded page sends `resume` WITH `keep_pending: true`;
// - `private` is sent in every hello; `ready` is tagged `resumed: true` when it kept the requested session.
import type { ConnStatus, ServerMessage } from './types';

export function wsUrl(loc: { protocol: string; host: string }): string {
  return `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}/ws/session`;
}

/** Reconnect delay in ms: 500, 1000, 2000, 4000, then 8000. */
export function backoffMs(attempt: number): number {
  return Math.min(8000, 500 * 2 ** attempt);
}

export interface HelloOptions {
  lang?: string;
  resume?: string | null;
  accessCode?: string | null;
  /** Only with `resume`, only from an automatic reconnect inside a loaded page. */
  keepPending?: boolean;
  private?: boolean;
}

type Hello = { type: 'hello'; lang: string; resume?: string; access_code?: string; keep_pending?: true; private?: true };

/** The hello message; optional fields are only present when set. */
export function helloMessage({ lang = 'hi', resume = null, accessCode = null, keepPending = false, private: priv = false }: HelloOptions = {}): Hello {
  const m: Hello = { type: 'hello', lang };
  if (resume) m.resume = resume;
  if (resume && keepPending) m.keep_pending = true;
  if (accessCode) m.access_code = accessCode;
  if (priv) m.private = true;
  return m;
}

const MAX_BUFFERED = 256 * 1024;

type WSLike = {
  binaryType: string;
  readyState: number;
  bufferedAmount?: number;
  send(data: string | ArrayBuffer): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
};

export interface SessionClientOptions {
  url: string;
  lang?: string;
  accessCode?: string | null;
  private?: boolean;
  onMessage: (m: ServerMessage) => void;
  onAudio: (buf: ArrayBuffer) => void;
  onStatus: (s: ConnStatus) => void;
  WS?: new (url: string) => WSLike;
}

export class SessionClient {
  url: string;
  lang: string;
  accessCode: string | null;
  private: boolean;
  /** Id of the session this page holds (set by `ready`). */
  sessionId: string | null = null;
  private requested: string | null = null;
  private attempt = 0;
  private closed = false;
  private ws: WSLike | null = null;
  private pinger: ReturnType<typeof setInterval> | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private onMessage: SessionClientOptions['onMessage'];
  private onAudio: SessionClientOptions['onAudio'];
  private onStatus: SessionClientOptions['onStatus'];
  private WS: new (url: string) => WSLike;

  constructor(o: SessionClientOptions) {
    this.url = o.url;
    this.lang = o.lang ?? 'hi';
    this.accessCode = o.accessCode ?? null;
    this.private = o.private ?? false;
    this.onMessage = o.onMessage;
    this.onAudio = o.onAudio;
    this.onStatus = o.onStatus;
    this.WS = o.WS ?? (globalThis.WebSocket as unknown as new (url: string) => WSLike);
  }

  /** The hello for the next connection. */
  hello(): Hello {
    // Only a reconnect inside this page has a session to resume, and it keeps the open question.
    return helloMessage({ lang: this.lang, resume: this.sessionId, accessCode: this.accessCode, keepPending: true, private: this.private });
  }

  connect(): void {
    this.closed = false;
    clearTimeout(this.timer);
    this.onStatus(this.attempt ? 'reconnecting' : 'connecting');
    const ws = new this.WS(this.url);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.onStatus('open');
      const h = this.hello();
      this.requested = h.resume ?? null;
      ws.send(JSON.stringify(h));
      clearInterval(this.pinger);
      this.pinger = setInterval(() => this.send({ type: 'ping', t: Date.now() }), 20000);
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') {
        this.onAudio(ev.data as ArrayBuffer);
        return;
      }
      let m: ServerMessage;
      try {
        m = JSON.parse(ev.data) as ServerMessage;
      } catch {
        return;
      }
      if (m.type === 'ready') {
        m = { ...m, resumed: this.requested != null && this.requested === m.session_id };
        this.sessionId = m.session_id;
      }
      this.onMessage(m);
    };
    ws.onclose = () => {
      clearInterval(this.pinger);
      if (this.ws !== ws || this.closed) return;
      this.onStatus('reconnecting');
      this.timer = setTimeout(() => this.connect(), backoffMs(this.attempt++));
    };
    ws.onerror = () => {};
  }

  get isOpen(): boolean {
    return this.ws !== null && this.ws.readyState === 1;
  }

  /** Page visible again: if the socket is not open (or opening), reconnect now instead of waiting for backoff. */
  reconnectNow(): void {
    if (this.closed || !this.ws) return;
    if (this.ws.readyState === 0 || this.ws.readyState === 1) return;
    this.attempt = Math.max(this.attempt, 1);
    this.connect();
  }

  send(obj: object): boolean {
    if (!this.isOpen || !this.ws) return false;
    this.ws.send(JSON.stringify(obj));
    return true;
  }

  /** Send one PCM16 frame; frames are dropped when the socket is not open or is backed up. */
  sendAudio(buf: ArrayBuffer): boolean {
    if (!this.isOpen || !this.ws || (this.ws.bufferedAmount ?? 0) > MAX_BUFFERED) return false;
    this.ws.send(buf);
    return true;
  }

  close(): void {
    this.closed = true;
    clearTimeout(this.timer);
    clearInterval(this.pinger);
    if (this.ws) this.ws.close();
    this.onStatus('closed');
  }
}
