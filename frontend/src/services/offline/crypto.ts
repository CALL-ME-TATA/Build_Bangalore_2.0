// Web Crypto helpers for the offline store: AES-GCM 256 with a non-extractable key, a fresh 96-bit IV per
// write and the record id as additional data, so a ciphertext only decrypts in the slot it was written to.
// No DOM and no IndexedDB here: the key is passed in, which keeps the round trip testable in Node.

export interface Sealed {
  /** AES-GCM ciphertext with its 16-byte tag. */
  blob: ArrayBuffer;
  /** 12 random bytes, unique per write. */
  iv: Uint8Array;
}

const enc = new TextEncoder();
const dec = new TextDecoder();

function subtle(): SubtleCrypto {
  const s = globalThis.crypto?.subtle;
  if (!s) throw new Error('Web Crypto is not available (a secure context is needed)');
  return s;
}

/** A new AES-GCM key that can encrypt and decrypt but can never be exported. */
export function generateKey(): Promise<CryptoKey> {
  return subtle().generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}

/** Encrypts `value` as JSON. `aad` (for example the record id) must be given again to decrypt. */
export async function encryptJson(key: CryptoKey, value: unknown, aad = ''): Promise<Sealed> {
  const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
  const blob = await subtle().encrypt(
    { name: 'AES-GCM', iv, additionalData: enc.encode(aad) },
    key,
    enc.encode(JSON.stringify(value)),
  );
  return { blob, iv };
}

/** Decrypts what encryptJson wrote. Throws when the key, the IV, the data or `aad` do not match. */
export async function decryptJson<T>(key: CryptoKey, sealed: Sealed, aad = ''): Promise<T> {
  const iv = new Uint8Array(sealed.iv); // a copy backed by a plain ArrayBuffer, whatever IndexedDB returned
  const plain = await subtle().decrypt({ name: 'AES-GCM', iv, additionalData: enc.encode(aad) }, key, sealed.blob);
  return JSON.parse(dec.decode(plain)) as T;
}
