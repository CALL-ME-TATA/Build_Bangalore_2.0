// Pure audio helpers shared by the capture worklet, the player and the unit tests.
// Nothing here touches the DOM or the Web Audio API. Ported from web/audio/dsp.js.

export const TARGET_RATE = 16000;
/** 512 samples at 16 kHz = 32 ms = 1,024 bytes, the frame size the server forwards to speech recognition. */
export const CHUNK_SAMPLES = 512;

/**
 * Streaming box-filter resampler. Each output sample is the average of the
 * input span it covers, which also acts as a cheap anti-alias filter when
 * going from 44.1 or 48 kHz down to 16 kHz. State carries across push() calls.
 */
export class Downsampler {
  private ratio: number;
  private acc = 0;
  private filled = 0;

  constructor(inRate: number, outRate = TARGET_RATE) {
    this.ratio = inRate / outRate; // input samples per output sample
  }

  push(input: Float32Array): Float32Array {
    const out = new Float32Array(Math.ceil(input.length / this.ratio) + 1);
    let n = 0;
    const ratio = this.ratio;
    for (let i = 0; i < input.length; i++) {
      const x = input[i] as number;
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
export function floatToPcm16(f32: Float32Array): Int16Array {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i] as number));
    out[i] = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
  }
  return out;
}

/** Collects Int16 samples and hands back fixed-size chunks. */
export class Chunker {
  private size: number;
  private buf: Int16Array;
  private n = 0;

  constructor(size = CHUNK_SAMPLES) {
    this.size = size;
    this.buf = new Int16Array(size);
  }

  /** The buffered tail padded with zeros to a full chunk, or null when nothing is buffered. Resets the buffer. */
  flush(): Int16Array | null {
    if (this.n === 0) return null;
    this.buf.fill(0, this.n);
    const out = this.buf;
    this.buf = new Int16Array(this.size);
    this.n = 0;
    return out;
  }

  push(samples: Int16Array): Int16Array[] {
    const chunks: Int16Array[] = [];
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
  private carry: number | null = null;

  push(data: ArrayBuffer | Uint8Array): Float32Array<ArrayBuffer> {
    let bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    if (this.carry !== null) {
      const joined = new Uint8Array(bytes.length + 1);
      joined[0] = this.carry;
      joined.set(bytes, 1);
      bytes = joined;
      this.carry = null;
    }
    const n = bytes.length >> 1;
    if (bytes.length & 1) this.carry = bytes[bytes.length - 1] as number;
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
export function scheduleStart(now: number, next: number, lead = 0.03): number {
  return next > now ? next : now + lead;
}

/**
 * Display level in [0, 1] for one PCM16 chunk: RMS mapped on a log scale so quiet
 * speech still moves the mic ring. About -50 dBFS maps to 0 and -10 dBFS to 1.
 */
export function pcmLevel(samples: Int16Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = (samples[i] as number) / 32768;
    sum += v * v;
  }
  return rmsToLevel(Math.sqrt(sum / samples.length));
}

/** The same display level for float samples in [-1, 1] (an AnalyserNode's time-domain data). */
export function floatLevel(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = samples[i] as number;
    sum += v * v;
  }
  return rmsToLevel(Math.sqrt(sum / samples.length));
}

function rmsToLevel(rms: number): number {
  if (rms <= 0) return 0;
  const db = 20 * Math.log10(rms);
  return Math.max(0, Math.min(1, (db + 50) / 40));
}

/** Clamp a playback rate to the range the voice-speed setting allows. */
export function clampRate(rate: number): number {
  if (!Number.isFinite(rate)) return 1;
  return Math.max(0.8, Math.min(1.25, rate));
}

/**
 * Rolling buffer of the last `ms` of captured chunks (M04). While the microphone is open but the button is not
 * pressed, chunks go in here; on press they are sent first, so the first word is not clipped.
 */
export class PreRoll {
  private chunks: ArrayBuffer[] = [];
  private bytes = 0;
  private limit: number;

  /** @param ms how much audio to keep; @param rate samples per second of the PCM16 chunks */
  constructor(ms = 300, rate = TARGET_RATE) {
    this.limit = Math.ceil((ms / 1000) * rate) * 2;
  }

  push(chunk: ArrayBuffer): void {
    this.chunks.push(chunk);
    this.bytes += chunk.byteLength;
    // Keep whole chunks, dropping the oldest while what remains still covers the window.
    while (this.chunks.length > 1 && this.bytes - (this.chunks[0]?.byteLength ?? 0) >= this.limit) {
      this.bytes -= this.chunks.shift()?.byteLength ?? 0;
    }
  }

  /** Everything buffered, oldest first; the buffer is emptied. */
  take(): ArrayBuffer[] {
    const out = this.chunks;
    this.chunks = [];
    this.bytes = 0;
    return out;
  }

  clear(): void {
    this.chunks = [];
    this.bytes = 0;
  }

  /** Milliseconds of audio held. */
  get heldMs(): number {
    return (this.bytes / 2 / TARGET_RATE) * 1000;
  }
}
