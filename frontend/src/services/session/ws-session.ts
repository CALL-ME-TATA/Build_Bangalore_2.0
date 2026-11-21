// The real SessionService: WebSocket to /ws/session, microphone capture through the AudioWorklet, PCM playback
// of the reply. Ported from web/controller.js and extended for contract 3.3 and edge cases L, M, N and R.
//
// Kept from the first app:
// - the greeting gate (press and text are refused until the greeting audio ended, 6 s fallback)
// - barge-in (press stops playback at once and sends `start`)
// - binary frames are played only while a non-stale audio_start is open
// Recording rules that protect the first and last word:
// - M04 pre-roll: after the first permission grant the stream and worklet stay open while the page is visible,
//   and the last 300 ms are kept in a rolling buffer; on press that buffer is sent first, then live audio.
//   The stream is closed when the page is hidden and reopened when it is visible again.
// - M05 tail: after release audio keeps flowing for 300 ms, then the worklet's zero-padded last chunk is sent
//   and then `end`. The screen shows "Samajh raha hoon…" from the release (local_end), and the phone latency
//   counts from the release.
// - M03 accidental press: abort() sends `cancel` (the gesture layer decides what is too short).
// Ids and clocks: `start` and `text` carry `utt_id`; `text` and `end` carry `client_ts`. A retried sentence
// passes its first utt_id. Sessions: every page load starts a new session (hello without resume, so the greeting
// with the AI disclosure plays again); only an automatic reconnect inside the page resumes, with keep_pending
// (SessionClient). On visibility the socket and mic are restored.
import type { Lang } from '../../i18n';
import { accessCode } from '../accessCode';
import { clientTs, newUttId } from '../../lib/ids';
import { SessionClient, wsUrl } from './protocol';
import { Player, softBeep } from './audio/player';
import { PreRoll, pcmLevel } from './audio/dsp';
import { micError, micUnavailable } from './micStatus';
import type { MicStatus, SessionHost, SessionService } from './types';
import { voiceLang } from './voice';
import workletUrl from './audio/capture-worklet.ts?worker&url';

const GREETING_FALLBACK_MS = 6000;
const TAIL_MS = 300;
const FLUSH_WAIT_MS = 40;
const PRE_ROLL_MS = 300;

interface Finishing {
  tail: ArrayBuffer | null;
  timer?: ReturnType<typeof setTimeout>;
  flushTimer?: ReturnType<typeof setTimeout>;
  done: () => void;
}


export function createWsSession(host: SessionHost): SessionService {
  let ctx: AudioContext | null = null;
  let player: Player | null = null;
  let client: SessionClient | null = null;
  let node: AudioWorkletNode | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let stream: MediaStream | null = null;
  let workletLoaded = false;
  let micGranted = false; // permission was given once in this page
  let micReady = false; // the stream is open now
  let opening: Promise<MicStatus> | null = null;
  let talking = false; // button held (or latched)
  let finishing: Finishing | null = null; // release tail in progress
  let greetTimer: ReturnType<typeof setTimeout> | undefined;
  let lang: Lang = 'hi';
  let speed = 1;
  let priv = false;
  let outTimer: ReturnType<typeof setInterval> | undefined;
  const preRoll = new PreRoll(PRE_ROLL_MS);
  let lastMic: MicStatus = 'unknown';

  const dispatch = host.dispatch;

  /** Reports the level of the reply audio while it plays, for the wave bar. */
  function watchOutput() {
    clearInterval(outTimer);
    outTimer = setInterval(() => {
      if (talking) return; // the microphone owns the level while the button is held
      const p = player;
      if (!p || (!p.playing && host.getState().audioTurn == null)) {
        clearInterval(outTimer);
        host.onLevel(0);
        return;
      }
      host.onLevel(p.level());
    }, 33);
  }

  function onCapture(ev: MessageEvent) {
    const d = ev.data as ArrayBuffer | { flush: true; chunk: ArrayBuffer | null };
    if (d && typeof d === 'object' && 'flush' in d) {
      if (finishing) {
        finishing.tail = d.chunk;
        finishing.done();
      }
      return;
    }
    const buf = d as ArrayBuffer;
    if (talking || finishing) {
      client?.sendAudio(buf);
      if (talking) host.onLevel(pcmLevel(new Int16Array(buf)));
    } else {
      preRoll.push(buf);
    }
  }

  async function openMicNow(): Promise<MicStatus> {
    if (!ctx) return 'failed';
    if (!navigator.mediaDevices?.getUserMedia) return micUnavailable(window.isSecureContext);
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: { ideal: true },
          noiseSuppression: { ideal: true },
          autoGainControl: { ideal: true },
          channelCount: { ideal: 1 },
        },
      });
      if (!workletLoaded) {
        await ctx.audioWorklet.addModule(workletUrl);
        workletLoaded = true;
      }
      if (!node) {
        node = new AudioWorkletNode(ctx, 'capture', { numberOfOutputs: 1, outputChannelCount: [1] });
        node.port.onmessage = onCapture;
        node.connect(ctx.destination); // the node writes silence; the connection keeps it running
      }
      source = ctx.createMediaStreamSource(stream);
      source.connect(node);
      micGranted = true;
      micReady = true;
      return 'ready';
    } catch (err) {
      return micError(err, window.isSecureContext);
    }
  }

  function openMic(): Promise<MicStatus> {
    opening ??= openMicNow().finally(() => {
      opening = null;
    });
    return opening;
  }

  function closeMic() {
    micReady = false;
    preRoll.clear();
    source?.disconnect();
    source = null;
    stream?.getTracks().forEach((tr) => tr.stop());
    stream = null;
  }

  function onVisibility() {
    if (document.visibilityState === 'hidden') {
      if (talking) service.abort();
      if (finishing) finishing.done();
      closeMic();
      return;
    }
    void ctx?.resume();
    client?.reconnectNow();
    if (micGranted && !micReady) {
      void openMic().then((status) => dispatch({ type: 'mic', status }));
    }
  }

  const service: SessionService = {
    kind: 'ws',

    async start(startLang, audio) {
      lang = startLang;
      dispatch({ type: 'set_lang', lang });
      if (client) return micReady ? 'ready' : lastMic; // already started in this page
      if (audio) ctx = audio;
      else {
        const AC: typeof AudioContext =
          window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        ctx = new AC({ latencyHint: 'interactive' });
      }
      await ctx.resume();
      player = new Player(ctx, (t) => dispatch({ type: 'first_sound', t }));
      player.setSpeed(speed);

      client = new SessionClient({
        url: wsUrl(location),
        lang: voiceLang() ?? lang, // reused by every reconnect; Kannada / Marathi / Tamil when chosen
        accessCode: accessCode(),
        private: priv,
        onStatus: (status) => dispatch({ type: 'conn', status }),
        onMessage: (m) => {
          dispatch(m);
          const s = host.getState();
          // Fallback so a failed greeting cannot lock the page.
          if (m.type === 'ready' && !s.greeted) {
            clearTimeout(greetTimer);
            greetTimer = setTimeout(() => dispatch({ type: 'greeting_timeout' }), GREETING_FALLBACK_MS);
          }
          if (m.type === 'audio_start' && s.audioTurn === Number(m.turn_id)) {
            player?.begin(m.sample_rate);
            watchOutput();
          } else if (m.type === 'audio_end' && m.turn_id != null && Number(m.turn_id) >= s.turnId) {
            if (m.cancelled) player?.stop();
            else player?.end();
          }
        },
        // Binary frames carry no turn id: they are played only while a non-stale audio_start is open.
        onAudio: (buf) => {
          if (host.getState().audioTurn != null) player?.push(buf);
        },
      });
      client.connect();
      document.addEventListener('visibilitychange', onVisibility);

      const mic = await openMic();
      lastMic = mic;
      dispatch({ type: 'mic', status: mic });
      return mic;
    },

    press() {
      if (!micReady || talking || !client || !ctx || !host.getState().greeted) return;
      void ctx.resume(); // a locked screen or a phone call suspends the context
      if (!client.isOpen) {
        dispatch({ type: 'notice' });
        return;
      }
      if (finishing) finishing.done(); // a quick re-press: close the previous turn first
      player?.stop();
      dispatch({ type: 'local_start' });
      if (!client.send({ type: 'start', mode: 'ptt', utt_id: newUttId() })) return;
      talking = true;
      for (const chunk of preRoll.take()) client.sendAudio(chunk); // the 300 ms before the press
    },

    release() {
      if (!talking || !client || !node) return;
      talking = false;
      host.onLevel(0);
      const t = performance.now();
      dispatch({ type: 'local_end', t }); // "Samajh raha hoon…" now; phone latency counts from here
      const c = client;
      const n = node;
      let sent = false;
      const fin: Finishing = {
        tail: null,
        done: () => {
          if (sent) return;
          sent = true;
          clearTimeout(fin.timer);
          clearTimeout(fin.flushTimer);
          finishing = null;
          if (fin.tail) c.sendAudio(fin.tail);
          c.send({ type: 'end', client_ts: clientTs() });
        },
      };
      finishing = fin;
      // Keep streaming for 300 ms, then ask the worklet for its zero-padded tail (waiting at most 40 ms).
      fin.timer = setTimeout(() => {
        fin.flushTimer = setTimeout(fin.done, FLUSH_WAIT_MS);
        n.port.postMessage({ flush: true });
      }, TAIL_MS);
    },

    abort() {
      if (!talking) return;
      talking = false;
      host.onLevel(0);
      preRoll.clear();
      client?.send({ type: 'cancel' });
      dispatch({ type: 'local_abort' });
    },

    sendText(text, opts = {}) {
      const tx = text.trim();
      if (!tx || !client || !host.getState().greeted) return;
      void ctx?.resume();
      if (!client.isOpen) {
        dispatch({ type: 'notice' });
        return;
      }
      player?.stop();
      dispatch({ type: 'local_start' });
      dispatch({ type: 'local_text', text: tx });
      client.send({ type: 'text', text: tx, utt_id: opts.uttId ?? newUttId(), client_ts: opts.clientTs ?? clientTs() });
      dispatch({ type: 'local_end', t: performance.now() });
    },

    setLang(next) {
      lang = next;
      if (client) client.lang = voiceLang() ?? next;
    },

    setSpoken(code) {
      if (!client) return; // not started: the start step sends it in hello
      client.lang = code; // later reconnects keep it
      client.send({ type: 'settings', lang: code });
    },

    setVoiceSpeed(rate) {
      speed = rate;
      player?.setSpeed(rate);
    },

    setPrivate(on) {
      if (priv === on) return;
      priv = on;
      if (!client) return;
      client.private = on; // every later hello carries it
      client.send({ type: 'settings', private: on });
    },

    beep() {
      if (ctx) softBeep(ctx);
    },

    close() {
      clearTimeout(greetTimer);
      clearInterval(outTimer);
      document.removeEventListener('visibilitychange', onVisibility);
      client?.close();
      player?.stop();
      closeMic();
      void ctx?.close();
    },
  };
  return service;
}
