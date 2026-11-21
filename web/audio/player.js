// Plays the spoken reply: PCM16 chunks are queued on one AudioContext and scheduled back to back.
import { Pcm16Decoder, scheduleStart } from './dsp.js';

export class Player {
  /** @param {AudioContext} ctx @param {(t:number)=>void} onFirstSound called with performance.now() when the first sample of a reply is scheduled */
  constructor(ctx, onFirstSound = () => {}) {
    this.ctx = ctx;
    this.onFirstSound = onFirstSound;
    this.sources = new Set();
    this.active = false;
    this.next = 0;
  }

  /** Prepare for a new reply (audio_start). Anything still playing is silenced. */
  begin(sampleRate) {
    this.stop();
    this.rate = sampleRate;
    this.decoder = new Pcm16Decoder();
    this.next = 0;
    this.first = true;
    this.active = true;
  }

  /** Queue one binary frame. */
  push(data) {
    if (!this.active) return;
    const f32 = this.decoder.push(data);
    if (!f32.length) return;
    const ctx = this.ctx;
    const buf = ctx.createBuffer(1, f32.length, this.rate);
    buf.copyToChannel(f32, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const at = scheduleStart(ctx.currentTime, this.next);
    src.start(at);
    this.next = at + buf.duration;
    this.sources.add(src);
    src.onended = () => this.sources.delete(src);
    if (this.first) {
      this.first = false;
      this.onFirstSound(performance.now());
    }
  }

  /** audio_end: no more frames; what is already queued keeps playing. */
  end() {
    this.active = false;
  }

  /** Silence playback immediately and drop everything queued. */
  stop() {
    this.active = false;
    for (const src of this.sources) {
      src.onended = null;
      try { src.stop(); } catch { /* already stopped */ }
      src.disconnect();
    }
    this.sources.clear();
    this.next = 0;
  }
}
