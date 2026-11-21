import test from 'node:test';
import assert from 'node:assert/strict';
import { Downsampler, floatToPcm16, Chunker, Pcm16Decoder, scheduleStart } from '../audio/dsp.js';

function sine(freq, rate, n, phase = 0) {
  const a = new Float32Array(n);
  for (let i = 0; i < n; i++) a[i] = 0.5 * Math.sin(2 * Math.PI * freq * (i + phase) / rate);
  return a;
}

test('48 kHz to 16 kHz gives one third of the samples', () => {
  const out = new Downsampler(48000).push(new Float32Array(4800));
  assert.equal(out.length, 1600);
});

test('44.1 kHz output length tracks the ratio across calls', () => {
  const d = new Downsampler(44100);
  let total = 0;
  for (let i = 0; i < 100; i++) total += d.push(new Float32Array(128)).length;
  assert.ok(Math.abs(total - (100 * 128 * 16000) / 44100) <= 1);
});

test('a constant signal stays constant', () => {
  const out = new Downsampler(44100).push(new Float32Array(2000).fill(0.25));
  for (const v of out.subarray(1)) assert.ok(Math.abs(v - 0.25) < 1e-6);
});

test('a 440 Hz sine keeps its frequency and amplitude', () => {
  const out = new Downsampler(48000).push(sine(440, 48000, 48000));
  let zc = 0, peak = 0;
  for (let i = 1; i < out.length; i++) {
    if (out[i - 1] < 0 && out[i] >= 0) zc++;
    peak = Math.max(peak, Math.abs(out[i]));
  }
  assert.ok(Math.abs(zc - 440) <= 2, `zero crossings ${zc}`);
  assert.ok(peak > 0.45 && peak <= 0.5);
});

test('splitting the input into blocks gives the same output', () => {
  const x = sine(300, 44100, 4410);
  const whole = new Downsampler(44100).push(x);
  const d = new Downsampler(44100);
  const parts = [];
  for (let i = 0; i < x.length; i += 128) parts.push(...d.push(x.subarray(i, i + 128)));
  assert.equal(parts.length, whole.length);
  for (let i = 0; i < whole.length; i++) assert.ok(Math.abs(parts[i] - whole[i]) < 1e-5);
});

test('16 kHz input passes through unchanged', () => {
  const x = sine(200, 16000, 160);
  const out = new Downsampler(16000).push(x);
  assert.equal(out.length, 160);
  for (let i = 0; i < 160; i++) assert.ok(Math.abs(out[i] - x[i]) < 1e-6);
});

test('floatToPcm16 maps and clamps', () => {
  const p = floatToPcm16(Float32Array.of(0, 1, -1, 0.5, -0.5, 2, -3));
  assert.deepEqual([...p], [0, 32767, -32768, 16384, -16384, 32767, -32768]);
});

test('PCM16 bytes are little-endian', () => {
  const p = floatToPcm16(Float32Array.of(1));
  const bytes = new Uint8Array(p.buffer);
  if (new Uint8Array(new Uint16Array([1]).buffer)[0] === 1) assert.deepEqual([...bytes], [0xff, 0x7f]);
});

test('Chunker emits 512-sample (1,024-byte) chunks', () => {
  const c = new Chunker();
  assert.equal(c.push(new Int16Array(300)).length, 0);
  const chunks = c.push(new Int16Array(800));
  assert.equal(chunks.length, 2);
  assert.equal(chunks[0].byteLength, 1024);
  assert.equal(c.n, 76);
});

test('Chunker keeps sample order', () => {
  const c = new Chunker(4);
  const a = c.push(Int16Array.of(1, 2, 3));
  const b = c.push(Int16Array.of(4, 5, 6, 7, 8, 9));
  assert.deepEqual([...a], []);
  assert.deepEqual(b.map((x) => [...x]), [[1, 2, 3, 4], [5, 6, 7, 8]]);
});

test('Pcm16Decoder decodes and carries an odd byte across frames', () => {
  const d = new Pcm16Decoder();
  // samples 1, -1, 16384 as little-endian bytes
  const bytes = Uint8Array.of(0x01, 0x00, 0xff, 0xff, 0x00, 0x40);
  const first = d.push(bytes.subarray(0, 3));
  const second = d.push(bytes.subarray(3));
  assert.deepEqual([...first, ...second], [1 / 32768, -1 / 32768, 0.5]);
});

test('Pcm16Decoder accepts an ArrayBuffer and a non-zero byteOffset', () => {
  const buf = Uint8Array.of(9, 0x00, 0x40, 0x00, 0xc0).buffer;
  const out = new Pcm16Decoder().push(new Uint8Array(buf, 1));
  assert.deepEqual([...out], [0.5, -0.5]);
});

test('scheduleStart is gapless while ahead and re-leads after an underrun', () => {
  assert.equal(scheduleStart(1.0, 1.2), 1.2);
  assert.ok(Math.abs(scheduleStart(1.0, 0.5) - 1.03) < 1e-9);
  assert.ok(Math.abs(scheduleStart(1.0, 0) - 1.03) < 1e-9);
});
