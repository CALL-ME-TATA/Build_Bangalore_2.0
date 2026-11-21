// Encrypted copy of the last ledger and customer responses, so Khata, Customer detail and Hisaab open with
// the last known data when offline. Loaded lazily (it pulls in Dexie); see ./status.ts for the entry point.
import { openDb } from '../db';
import { decryptJson, encryptJson } from './crypto';
import { deviceKey } from './keys';

export interface Cached<T> {
  data: T;
  /** When it was fetched from the server, ISO 8601. */
  savedAt: string;
}

export async function saveCached(slot: string, data: unknown, savedAt = new Date().toISOString()): Promise<void> {
  const [db, key] = await Promise.all([openDb(), deviceKey()]);
  const sealed = await encryptJson(key, data, slot);
  await db.entries.put({ id: slot, blob: sealed.blob, iv: sealed.iv, ts: savedAt });
}

/** The cached value, or null when there is none or it cannot be decrypted (then it is dropped). */
export async function loadCached<T>(slot: string): Promise<Cached<T> | null> {
  const [db, key] = await Promise.all([openDb(), deviceKey()]);
  const row = await db.entries.get(slot);
  if (!row) return null;
  try {
    return { data: await decryptJson<T>(key, row, slot), savedAt: row.ts };
  } catch {
    await db.entries.delete(slot);
    return null;
  }
}
