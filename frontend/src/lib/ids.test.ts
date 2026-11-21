import { expect, test } from 'vitest';
import { clientTs, newUttId } from './ids';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test('newUttId uses randomUUID when present and a v4 fallback on plain-HTTP pages', () => {
  const real = globalThis.crypto;
  expect(newUttId({ randomUUID: () => 'x-1', getRandomValues: (a) => a })).toBe('x-1');
  const getRandomValues = (<T extends ArrayBufferView | null>(a: T): T => {
    if (a) real.getRandomValues(new Uint8Array(a.buffer as ArrayBuffer, a.byteOffset, a.byteLength));
    return a;
  }) as Crypto['getRandomValues'];
  const fallback = newUttId({ getRandomValues });
  expect(fallback).toMatch(UUID);
  expect(fallback.length).toBeLessThanOrEqual(64);
  expect(newUttId()).not.toBe(newUttId());
});

test('clientTs is ISO 8601', () => {
  expect(clientTs(new Date(Date.UTC(2026, 10, 21, 6, 12)))).toBe('2026-11-21T06:12:00.000Z');
});
