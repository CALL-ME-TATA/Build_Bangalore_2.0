// AudioWorklet: microphone samples at the context rate -> 16 kHz PCM16 chunks of 32 ms.
// Each message posted to the main thread is an ArrayBuffer of 1,024 bytes (little-endian Int16).
// On {flush: true} from the main thread it replies {flush: true, chunk} with the zero-padded tail (or null),
// so the last words before release are not lost.
// Loaded with `?worker&url`, so Vite bundles it (with dsp.ts inlined) into one classic script.
import { Chunker, Downsampler, floatToPcm16 } from './dsp';

// The AudioWorkletGlobalScope is not part of the DOM type library; these are the parts used here.
declare const sampleRate: number;
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
}
declare function registerProcessor(name: string, ctor: new () => AudioWorkletProcessor): void;

class CaptureProcessor extends AudioWorkletProcessor {
  private down = new Downsampler(sampleRate);
  private chunker = new Chunker();

  constructor() {
    super();
    this.port.onmessage = (ev: MessageEvent) => {
      if (!ev.data || !ev.data.flush) return;
      const tail = this.chunker.flush();
      this.port.postMessage({ flush: true, chunk: tail ? tail.buffer : null }, tail ? [tail.buffer] : []);
    };
  }

  process(inputs: Float32Array[][]): boolean {
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
