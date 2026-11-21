// Protocol client for /ws/session: hello, reconnect with resume, ping, JSON and binary frames.

export function wsUrl(loc) {
  return `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}/ws/session`;
}

/** Reconnect delay in ms: 500, 1000, 2000, 4000, then 8000. */
export function backoffMs(attempt) {
  return Math.min(8000, 500 * 2 ** attempt);
}

/** The hello message; `resume` is only set when reconnecting an existing session. */
export function helloMessage({ lang = 'hi', resume = null, accessCode = null } = {}) {
  const m = { type: 'hello', lang };
  if (resume) m.resume = resume;
  if (accessCode) m.access_code = accessCode;
  return m;
}

const MAX_BUFFERED = 256 * 1024;

export class SessionClient {
  constructor({ url, lang = 'hi', accessCode = null, onMessage, onAudio, onStatus, WS = globalThis.WebSocket }) {
    Object.assign(this, { url, lang, accessCode, onMessage, onAudio, onStatus, WS });
    this.sessionId = null;
    this.attempt = 0;
    this.closed = false;
    this.ws = null;
  }

  connect() {
    this.closed = false;
    this.onStatus(this.attempt ? 'reconnecting' : 'connecting');
    const ws = new this.WS(this.url);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.onStatus('open');
      ws.send(JSON.stringify(helloMessage({ lang: this.lang, resume: this.sessionId, accessCode: this.accessCode })));
      clearInterval(this.pinger);
      this.pinger = setInterval(() => this.send({ type: 'ping', t: Date.now() }), 20000);
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return this.onAudio(ev.data);
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      if (m.type === 'ready') this.sessionId = m.session_id;
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

  get isOpen() {
    return this.ws !== null && this.ws.readyState === 1;
  }

  send(obj) {
    if (!this.isOpen) return false;
    this.ws.send(JSON.stringify(obj));
    return true;
  }

  /** Send one PCM16 frame; frames are dropped when the socket is not open or is backed up. */
  sendAudio(buf) {
    if (!this.isOpen || this.ws.bufferedAmount > MAX_BUFFERED) return false;
    this.ws.send(buf);
    return true;
  }

  close() {
    this.closed = true;
    clearTimeout(this.timer);
    clearInterval(this.pinger);
    if (this.ws) this.ws.close();
    this.onStatus('closed');
  }
}
