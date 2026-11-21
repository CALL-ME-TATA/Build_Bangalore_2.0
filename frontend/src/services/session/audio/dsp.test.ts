// Ported from web/tests/dsp.test.mjs, plus the level meter and rate clamp.
import { describe, expect, test } from 'vitest';
import { Chunker, Downsampler, PreRoll, Pcm16Decoder, clampRate, floatLevel, floatToPcm16, pcmLevel, scheduleStart } from './dsp';

function sine(freq: number, rate: number, n: number, phase = 0): Float32Array {
  const a = new Float32Array(n);
  for (let i = 0; i < n; i++) a[i] = 0.5 * Math.sin((2 * Math.PI * freq * (i + phase)) / rate);
  return a;
}

describe('Downsampler', () => {
  test('48 kHz to 16 kHz gives one third of the samples', () => {
    expect(new Downsampler(48000).push(new Float32Array(4800)).length).toBe(1600);
  });

  test('44.1 kHz output length tracks the ratio across calls', () => {
    const d = new Downsampler(44100);
    let total = 0;
    for (let i = 0; i < 100; i++) total += d.push(new Float32Array(128)).length;
    expect(Math.abs(total - (100 * 128 * 16000) / 44100)).toBeLessThanOrEqual(1);
  });

  test('a constant signal stays constant', () => {
    const out = new Downsampler(44100).push(new Float32Array(2000).fill(0.25));
    for (const v of out.subarray(1)) expect(Math.abs(v - 0.25)).toBeLessThan(1e-6);
  });

  test('a 440 Hz sine keeps its frequency and amplitude', () => {
    const out = new Downsampler(48000).push(sine(440, 48000, 48000));
    let zc = 0;
    let peak = 0;
    for (let i = 1; i < out.length; i++) {
      if ((out[i - 1] as number) < 0 && (out[i] as number) >= 0) zc++;
      peak = Math.max(peak, Math.abs(out[i] as number));
    }
    expect(Math.abs(zc - 440)).toBeLessThanOrEqual(2);
    expect(peak).toBeGreaterThan(0.45);
    expect(peak).toBeLessThanOrEqual(0.5);
  });

  test('splitting the input into blocks gives the same output', () => {
    const x = sine(300, 44100, 4410);
    const whole = new Downsampler(44100).push(x);
    const d = new Downsampler(44100);
    const parts: number[] = [];
    for (let i = 0; i < x.length; i += 128) parts.push(...d.push(x.subarray(i, i + 128)));
    expect(parts.length).toBe(whole.length);
    for (let i = 0; i < whole.length; i++) expect(Math.abs((parts[i] as number) - (whole[i] as number))).toBeLessThan(1e-5);
  });

  test('16 kHz input passes through unchanged', () => {
    const x = sine(200, 16000, 160);
    const out = new Downsampler(16000).push(x);
    expect(out.length).toBe(160);
    for (let i = 0; i < 160; i++) expect(Math.abs((out[i] as number) - (x[i] as number))).toBeLessThan(1e-6);
  });
});

describe('PCM16', () => {
  test('floatToPcm16 maps and clamps', () => {
    const p = floatToPcm16(Float32Array.of(0, 1, -1, 0.5, -0.5, 2, -3));
    expect([...p]).toEqual([0, 32767, -32768, 16384, -16384, 32767, -32768]);
  });

  test('PCM16 bytes are little-endian', () => {
    const p = floatToPcm16(Float32Array.of(1));
    const bytes = new Uint8Array(p.buffer);
    if (new Uint8Array(new Uint16Array([1]).buffer)[0] === 1) expect([...bytes]).toEqual([0xff, 0x7f]);
  });

  test('Chunker emits 512-sample (1,024-byte) chunks', () => {
    const c = new Chunker();
    expect(c.push(new Int16Array(300)).length).toBe(0);
    const chunks = c.push(new Int16Array(800));
    expect(chunks.length).toBe(2);
    expect(chunks[0]?.byteLength).toBe(1024);
    expect((c as unknown as { n: number }).n).toBe(76);
  });

  test('Chunker keeps sample order', () => {
    const c = new Chunker(4);
    const a = c.push(Int16Array.of(1, 2, 3));
    const b = c.push(Int16Array.of(4, 5, 6, 7, 8, 9));
    expect(a).toEqual([]);
    expect(b.map((x) => [...x])).toEqual([
      [1, 2, 3, 4],
      [5, 6, 7, 8],
    ]);
  });

  test('Chunker flush returns the zero-padded tail once (the tail sent on release)', () => {
    const c = new Chunker(4);
    c.push(Int16Array.of(1, 2, 3, 4, 5, 6));
    expect([...(c.flush() ?? [])]).toEqual([5, 6, 0, 0]);
    expect(c.flush()).toBeNull();
  });

  test('Pcm16Decoder decodes and carries an odd byte across frames', () => {
    const d = new Pcm16Decoder();
    const bytes = Uint8Array.of(0x01, 0x00, 0xff, 0xff, 0x00, 0x40);
    const first = d.push(bytes.subarray(0, 3));
    const second = d.push(bytes.subarray(3));
    expect([...first, ...second]).toEqual([1 / 32768, -1 / 32768, 0.5]);
  });

  test('Pcm16Decoder accepts an ArrayBuffer and a non-zero byteOffset', () => {
    const buf = Uint8Array.of(9, 0x00, 0x40, 0x00, 0xc0).buffer;
    expect([...new Pcm16Decoder().push(new Uint8Array(buf, 1))]).toEqual([0.5, -0.5]);
  });
});

describe('scheduling and level', () => {
  test('scheduleStart is gapless while ahead and re-leads after an underrun', () => {
    expect(scheduleStart(1.0, 1.2)).toBe(1.2);
    expect(Math.abs(scheduleStart(1.0, 0.5) - 1.03)).toBeLessThan(1e-9);
    expect(Math.abs(scheduleStart(1.0, 0) - 1.03)).toBeLessThan(1e-9);
  });

  test('pcmLevel is 0 for silence, rises with loudness and stays within [0, 1]', () => {
    expect(pcmLevel(new Int16Array(512))).toBe(0);
    expect(pcmLevel(new Int16Array(0))).toBe(0);
    const quiet = pcmLevel(new Int16Array(512).fill(300));
    const loud = pcmLevel(new Int16Array(512).fill(12000));
    expect(quiet).toBeGreaterThan(0);
    expect(loud).toBeGreaterThan(quiet);
    expect(pcmLevel(new Int16Array(512).fill(32767))).toBe(1);
    expect(floatLevel(new Float32Array(256))).toBe(0);
    expect(Math.abs(floatLevel(new Float32Array(256).fill(12000 / 32768)) - loud)).toBeLessThan(1e-6);
  });

  test('clampRate keeps the voice speed between 0.8 and 1.25', () => {
    expect(clampRate(1)).toBe(1);
    expect(clampRate(3)).toBe(1.25);
    expect(clampRate(0.1)).toBe(0.8);
    expect(clampRate(Number.NaN)).toBe(1);
  });
});

describe('PreRoll', () => {
  const chunk = () => new ArrayBuffer(1024); // 512 samples = 32 ms at 16 kHz

  test('keeps at least 300 ms of whole chunks and drops older ones', () => {
    const p = new PreRoll(300);
    for (let i = 0; i < 40; i++) p.push(chunk());
    expect(p.heldMs).toBeGreaterThanOrEqual(300);
    expect(p.heldMs).toBeLessThan(300 + 32);
    expect(p.take()).toHaveLength(10);
    expect(p.take()).toHaveLength(0);
  });

  test('take returns chunks oldest first; clear empties', () => {
    const p = new PreRoll(300);
    const a = chunk();
    const b = chunk();
    p.push(a);
    p.push(b);
    expect(p.take()).toEqual([a, b]);
    p.push(chunk());
    p.clear();
    expect(p.heldMs).toBe(0);
  });
});
