// Plays the spoken reply: PCM16 chunks are queued on one AudioContext and scheduled back to back.
// Ported from web/audio/player.js, with an optional playback rate for the voice-speed setting.
import { Pcm16Decoder, clampRate, floatLevel, scheduleStart } from './dsp';

export class Player {
  private ctx: AudioContext;
  private onFirstSound: (t: number) => void;
  private sources = new Set<AudioBufferSourceNode>();
  private active = false;
  private next = 0;
  private first = false;
  private rate = 24000;
  private decoder = new Pcm16Decoder();
  private speed = 1;
  private analyser: AnalyserNode | null = null;
  private frame: Float32Array<ArrayBuffer> | null = null;

  /** @param onFirstSound called with performance.now() when the first sample of a reply is scheduled */
  constructor(ctx: AudioContext, onFirstSound: (t: number) => void = () => {}) {
    this.ctx = ctx;
    this.onFirstSound = onFirstSound;
    try {
      this.analyser = ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.connect(ctx.destination);
      this.frame = new Float32Array(this.analyser.fftSize);
    } catch {
      this.analyser = null;
    }
  }

  /** True while queued reply audio is still sounding. */
  get playing(): boolean {
    return this.sources.size > 0;
  }

  /** Display level in [0, 1] of what is playing now (for the wave bar). */
  level(): number {
    if (!this.analyser || !this.frame || !this.sources.size) return 0;
    this.analyser.getFloatTimeDomainData(this.frame);
    return floatLevel(this.frame);
  }

  setSpeed(rate: number): void {
    this.speed = clampRate(rate);
  }

  /** Prepare for a new reply (audio_start). Anything still playing is silenced. */
  begin(sampleRate: number): void {
    this.stop();
    this.rate = sampleRate;
    this.decoder = new Pcm16Decoder();
    this.next = 0;
    this.first = true;
    this.active = true;
  }

  /** Queue one binary frame. */
  push(data: ArrayBuffer): void {
    if (!this.active) return;
    const f32 = this.decoder.push(data);
    if (!f32.length) return;
    const ctx = this.ctx;
    const buf = ctx.createBuffer(1, f32.length, this.rate);
    buf.copyToChannel(f32, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = this.speed;
    src.connect(this.analyser ?? ctx.destination);
    const at = scheduleStart(ctx.currentTime, this.next);
    src.start(at);
    this.next = at + buf.duration / this.speed;
    this.sources.add(src);
    src.onended = () => this.sources.delete(src);
    if (this.first) {
      this.first = false;
      this.onFirstSound(performance.now());
    }
  }

  /** audio_end: no more frames; what is already queued keeps playing. */
  end(): void {
    this.active = false;
  }

  /** Silence playback immediately and drop everything queued. */
  stop(): void {
    this.active = false;
    for (const src of this.sources) {
      src.onended = null;
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
      src.disconnect();
    }
    this.sources.clear();
    this.next = 0;
  }
}

/**
 * A short soft beep (N04): played when a reply arrives as text but its audio does not, so the shopkeeper
 * knows to look at the screen. 660 Hz sine, 140 ms, quiet, with a smooth attack and release.
 */
export function softBeep(ctx: AudioContext): void {
  try {
    const t = ctx.currentTime + 0.01;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 660;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.08, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.14);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.16);
  } catch {
    /* audio unavailable: the text is still on screen */
  }
}
