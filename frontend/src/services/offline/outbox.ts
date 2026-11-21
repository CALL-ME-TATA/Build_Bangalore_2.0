// Encrypted storage of the outbox (sentences typed while offline). Only the time typed is kept in clear, for
// ordering; text, state and reason are sealed with the device key. Loaded lazily with Dexie.
import { openDb } from '../db';
import { decryptJson, encryptJson } from './crypto';
import { deviceKey } from './keys';
import type { OutboxRecord } from './queue';
import { newUttId } from '../../lib/ids';

type Payload = Pick<OutboxRecord, 'text' | 'state' | 'reason' | 'attempts' | 'uttId'>;

const aad = (createdAt: string) => `outbox:${createdAt}`;

export async function loadOutbox(): Promise<OutboxRecord[]> {
  const [db, key] = await Promise.all([openDb(), deviceKey()]);
  const rows = await db.outbox.orderBy('createdAt').toArray();
  const out: OutboxRecord[] = [];
  for (const row of rows) {
    if (row.id == null) continue;
    try {
      const p = await decryptJson<Payload>(key, row, aad(row.createdAt));
      out.push({ id: row.id, createdAt: row.createdAt, ...p });
    } catch {
      await db.outbox.delete(row.id); // written with a lost key: unreadable, drop it
    }
  }
  return out;
}

export async function addOutbox(text: string, createdAt = new Date().toISOString()): Promise<OutboxRecord> {
  const [db, key] = await Promise.all([openDb(), deviceKey()]);
  const payload: Payload = { text, state: 'pending', reason: null, attempts: 0, uttId: newUttId() };
  const sealed = await encryptJson(key, payload, aad(createdAt));
  const id = await db.outbox.add({ blob: sealed.blob, iv: sealed.iv, createdAt });
  return { id, createdAt, ...payload };
}

export async function writeOutbox(rec: OutboxRecord): Promise<void> {
  const [db, key] = await Promise.all([openDb(), deviceKey()]);
  const payload: Payload = { text: rec.text, state: rec.state, reason: rec.reason, attempts: rec.attempts, uttId: rec.uttId };
  const sealed = await encryptJson(key, payload, aad(rec.createdAt));
  await db.outbox.put({ id: rec.id, blob: sealed.blob, iv: sealed.iv, createdAt: rec.createdAt });
}

export async function deleteOutbox(id: number): Promise<void> {
  const db = await openDb();
  await db.outbox.delete(id);
}
