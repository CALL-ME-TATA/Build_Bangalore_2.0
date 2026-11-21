// Encrypt / decrypt round trip with the Web Crypto of the test environment.
import { expect, test } from 'vitest';
import { decryptJson, encryptJson, generateKey } from './crypto';

const sample = {
  entries: [{ id: 1, kind: 'credit', customer: { id: 'c1', display: 'रमेश', tags: [] }, amount: 340 }],
  note: 'Ramesh ₹1,25,000',
};

test('round trip returns the same value', async () => {
  const key = await generateKey();
  const sealed = await encryptJson(key, sample, 'ws:ledger:500');
  expect(sealed.iv).toHaveLength(12);
  expect(await decryptJson(key, sealed, 'ws:ledger:500')).toEqual(sample);
});

test('ciphertext does not contain the plain text', async () => {
  const key = await generateKey();
  const sealed = await encryptJson(key, { text: 'Ramesh ka 340 udhaar' });
  expect(new TextDecoder().decode(sealed.blob)).not.toContain('Ramesh');
});

test('every write uses a fresh IV', async () => {
  const key = await generateKey();
  const a = await encryptJson(key, sample);
  const b = await encryptJson(key, sample);
  expect(Array.from(a.iv)).not.toEqual(Array.from(b.iv));
});

test('wrong slot, wrong key or tampered data fail to decrypt', async () => {
  const key = await generateKey();
  const sealed = await encryptJson(key, sample, 'slot-a');
  await expect(decryptJson(key, sealed, 'slot-b')).rejects.toThrow();
  await expect(decryptJson(await generateKey(), sealed, 'slot-a')).rejects.toThrow();
  const bad = new Uint8Array(sealed.blob.slice(0));
  bad[0] = (bad[0] ?? 0) ^ 1;
  await expect(decryptJson(key, { blob: bad.buffer, iv: sealed.iv }, 'slot-a')).rejects.toThrow();
});

test('the key cannot be exported', async () => {
  const key = await generateKey();
  expect(key.extractable).toBe(false);
  await expect(crypto.subtle.exportKey('raw', key)).rejects.toThrow();
});
