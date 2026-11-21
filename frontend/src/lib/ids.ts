// Client ids and clocks for the session protocol (contract 3.3).

/**
 * A new utterance id (the idempotency key sent as `utt_id`). crypto.randomUUID only exists on secure origins
 * (HTTPS or localhost), so a page opened over plain HTTP on a LAN falls back to getRandomValues.
 */
export function newUttId(c: Pick<Crypto, 'getRandomValues'> & { randomUUID?: () => string } = globalThis.crypto): string {
  if (typeof c?.randomUUID === 'function') return c.randomUUID();
  const b = new Uint8Array(16);
  c.getRandomValues(b);
  b[6] = ((b[6] ?? 0) & 0x0f) | 0x40; // version 4
  b[8] = ((b[8] ?? 0) & 0x3f) | 0x80; // variant
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** The device clock as sent in `client_ts`. */
export function clientTs(d: Date = new Date()): string {
  return d.toISOString();
}
