// The device key: one non-extractable AES-GCM CryptoKey, created on first use and kept in IndexedDB (a
// CryptoKey is stored by structured clone; its raw bytes can never be read back by script).
import { openDb } from '../db';
import { generateKey } from './crypto';

const KEY_ID = 'device';
let keyPromise: Promise<CryptoKey> | null = null;

async function loadOrCreate(): Promise<CryptoKey> {
  const db = await openDb();
  const found = await db.keys.get(KEY_ID);
  if (found) return found.key;
  const fresh = await generateKey(); // outside the transaction: Web Crypto promises would end it early
  return db.transaction('rw', db.keys, async () => {
    const again = await db.keys.get(KEY_ID); // another tab may have written one meanwhile
    if (again) return again.key;
    await db.keys.put({ id: KEY_ID, key: fresh });
    return fresh;
  });
}

export function deviceKey(): Promise<CryptoKey> {
  if (!keyPromise) {
    keyPromise = loadOrCreate();
    keyPromise.catch(() => {
      keyPromise = null;
    });
  }
  return keyPromise;
}
