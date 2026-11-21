// Pure audio helpers shared by the capture worklet, the player and the unit tests.
// Nothing here touches the DOM or the Web Audio API.

export const TARGET_RATE = 16000;
/** 512 samples at 16 kHz = 32 ms = 1,024 bytes, the frame size the server forwards to speech recognition. */
export const CHUNK_SAMPLES = 512;

/**
 * Streaming box-filter resampler. Each output sample is the average of the
 * input span it covers, which also acts as a cheap anti-alias filter when
 * going from 44.1 or 48 kHz down to 16 kHz. State carries across push() calls.
 */
export class Downsampler {
  constructor(inRate, outRate = TARGET_RATE) {
    this.ratio = inRate / outRate; // input samples per output sample
    this.acc = 0;
    this.filled = 0;
  }

  /** @param {Float32Array} input @returns {Float32Array} */
  push(input) {
    const out = new Float32Array(Math.ceil(input.length / this.ratio) + 1);
    let n = 0;
    const ratio = this.ratio;
    for (let i = 0; i < input.length; i++) {
      const x = input[i];
      let left = 1;
      while (left > 1e-9) {
        const take = Math.min(left, ratio - this.filled);
        this.acc += x * take;
        this.filled += take;
        left -= take;
        if (this.filled >= ratio - 1e-9) {
          out[n++] = this.acc / ratio;
          this.acc = 0;
          this.filled = 0;
        }
      }
    }
    return out.subarray(0, n);
  }
}

/** Float samples in [-1, 1] to signed 16-bit. Out-of-range values are clamped. */
export function floatToPcm16(f32) {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
  }
  return out;
}

/** Collects Int16 samples and hands back fixed-size chunks. */
export class Chunker {
  constructor(size = CHUNK_SAMPLES) {
    this.size = size;
    this.buf = new Int16Array(size);
    this.n = 0;
  }

  /** The buffered tail padded with zeros to a full chunk, or null when nothing is buffered. Resets the buffer. */
  flush() {
    if (this.n === 0) return null;
    this.buf.fill(0, this.n);
    const out = this.buf;
    this.buf = new Int16Array(this.size);
    this.n = 0;
    return out;
  }

  /** @param {Int16Array} samples @returns {Int16Array[]} complete chunks */
  push(samples) {
    const chunks = [];
    let i = 0;
    while (i < samples.length) {
      const k = Math.min(this.size - this.n, samples.length - i);
      this.buf.set(samples.subarray(i, i + k), this.n);
      this.n += k;
      i += k;
      if (this.n === this.size) {
        chunks.push(this.buf);
        this.buf = new Int16Array(this.size);
        this.n = 0;
      }
    }
    return chunks;
  }
}

/**
 * Decodes little-endian PCM16 bytes to floats. A frame may end in the middle of
 * a sample, so a leftover byte is kept for the next call.
 */
export class Pcm16Decoder {
  constructor() {
    this.carry = null;
  }

  /** @param {ArrayBuffer|Uint8Array} data @returns {Float32Array} */
  push(data) {
    let bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    if (this.carry !== null) {
      const joined = new Uint8Array(bytes.length + 1);
      joined[0] = this.carry;
      joined.set(bytes, 1);
      bytes = joined;
      this.carry = null;
    }
    const n = bytes.length >> 1;
    if (bytes.length & 1) this.carry = bytes[bytes.length - 1];
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const out = new Float32Array(n);
    for (let i = 0; i < n; i++) out[i] = view.getInt16(i * 2, true) / 32768;
    return out;
  }
}

/**
 * Start time for the next audio chunk. Chunks follow each other exactly; after an
 * underrun (next is in the past) playback restarts a short lead after `now`.
 */
export function scheduleStart(now, next, lead = 0.03) {
  return next > now ? next : now + lead;
}
