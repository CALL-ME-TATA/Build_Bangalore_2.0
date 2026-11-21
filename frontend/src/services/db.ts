// Offline ledger cache and outbox (IndexedDB through Dexie). Dexie is loaded on first use only, so it is not in
// the initial download. Every value is encrypted with Web Crypto (AES-GCM, see ./offline/crypto.ts) before it is
// written; the key itself is a non-extractable CryptoKey kept in the `keys` table.
import type { Dexie as DexieType, Table } from 'dexie';

export interface CachedEntry {
  /** Cache slot, e.g. "ws:ledger:500" (see ./offline/cache.ts). */
  id: string;
  /** AES-GCM ciphertext of the cached JSON. */
  blob: ArrayBuffer;
  iv: Uint8Array;
  /** When it was saved, ISO 8601. */
  ts: string;
}

export interface OutboxItem {
  id?: number;
  /** AES-GCM ciphertext of { text, state, reason, attempts } (see ./offline/outbox.ts). */
  blob: ArrayBuffer;
  iv: Uint8Array;
  /** When the sentence was typed, ISO 8601 (kept in clear for ordering only). */
  createdAt: string;
}

export interface KeyRecord {
  id: string;
  key: CryptoKey;
}

export type KhataDb = DexieType & {
  entries: Table<CachedEntry, string>;
  outbox: Table<OutboxItem, number>;
  keys: Table<KeyRecord, string>;
};

let dbPromise: Promise<KhataDb> | null = null;

export function openDb(): Promise<KhataDb> {
  dbPromise ??= import('dexie').then(({ Dexie }) => {
    const db = new Dexie('khatavaani') as KhataDb;
    db.version(1).stores({ entries: 'id, ts', outbox: '++id, createdAt' });
    // v2: encrypted outbox rows (v1 never stored any) and the key table.
    db.version(2)
      .stores({ entries: 'id, ts', outbox: '++id, createdAt', keys: 'id' })
      .upgrade((tx) => tx.table('outbox').clear());
    return db;
  });
  return dbPromise;
}
