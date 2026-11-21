// AudioWorklet: microphone samples at the context rate -> 16 kHz PCM16 chunks of 32 ms.
// Each message posted to the main thread is an ArrayBuffer of 1,024 bytes (little-endian Int16).
import { Downsampler, Chunker, floatToPcm16 } from './dsp.js';

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.down = new Downsampler(sampleRate);
    this.chunker = new Chunker();
    // {flush: true} from the main thread: reply with the zero-padded tail (or null) as {flush: true, chunk}.
    this.port.onmessage = (ev) => {
      if (!ev.data || !ev.data.flush) return;
      const tail = this.chunker.flush();
      this.port.postMessage({ flush: true, chunk: tail ? tail.buffer : null }, tail ? [tail.buffer] : []);
    };
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      const pcm = floatToPcm16(this.down.push(ch));
      for (const chunk of this.chunker.push(pcm)) {
        this.port.postMessage(chunk.buffer, [chunk.buffer]);
      }
    }
    return true;
  }
}

registerProcessor('capture', CaptureProcessor);
