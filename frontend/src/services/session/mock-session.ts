// Scripted SessionService that replays the pitch flow with realistic timing and the same message
// sequence the server sends (docs/CONTRACT.md section 3): ready, state, transcript partials, result,
// audio_start / audio_end, timing. No microphone or network is used. If the browser has speech synthesis,
// the reply text is spoken so the flow can be heard; otherwise the speaking phase is silent.
//
// Each press "hears" the next sentence of VOICE_SCRIPT (or the scripted answer while a question is open).
// Typed text goes through the same small rule set in ../mock/brain.ts.
// Contract 3.3 behaviour mirrored here: a repeated `utt_id` gets the first result back with `duplicate: true`;
// private mode speaks "Jawab screen par hai." for balance answers; `cancel` after an accidental press drops the
// turn; "awaaz band" in a typed sentence makes the reply arrive without audio (a text-to-speech error), and
// "network" makes it the upstream-failure reply, so the beep and the type box can be tried.
import type { Lang } from '../../i18n';
import { MockBrain, VOICE_SCRIPT, scriptedAnswer, soundsNoisy, type BrainResult } from '../mock/brain';
import { mockLedger, type MockLedger } from '../mock/ledger';
import type { MicStatus, ResultMessage, SessionHost, SessionService } from './types';
import { softBeep } from './audio/player';

const jitter = (base: number, spread: number) => Math.round(base + (Math.random() * 2 - 1) * spread);

export interface MockSessionOptions {
  /** Ledger to write to (default: the shared mock ledger). The demo passes a fresh one. */
  ledger?: MockLedger;
  /** What each press "hears", per language (default: VOICE_SCRIPT). */
  script?: Record<Lang, string[]>;
}

export function createMockSession(host: SessionHost, options: MockSessionOptions = {}): SessionService {
  const brain = new MockBrain(options.ledger ?? mockLedger);
  const voiceScript = options.script ?? VOICE_SCRIPT;
  const dispatch = host.dispatch;
  let lang: Lang = 'hi';
  let started = false;
  let turn = 0;
  let scriptIndex = 0;
  let talking = false;
  let heard = '';
  let speakingTurn: number | null = null;
  let speed = 1;
  let timers: ReturnType<typeof setTimeout>[] = [];
  let levelTimer: ReturnType<typeof setInterval> | undefined;
  let speakTimer: ReturnType<typeof setInterval> | undefined;
  /** Results by utt_id, for duplicate detection. */
  const seen = new Map<string, BrainResult>();
  /** When the open question was asked (the server drops it after 60 s). */
  let askedAt = 0;

  /** Answers `text`, dropping a question older than 60 s first, as the server does. */
  function respond(text: string): BrainResult {
    if (brain.pendingReason && Date.now() - askedAt >= 60_000) brain.dropPending();
    const r = brain.respond(text);
    if (r.status === 'needs_clarification') askedAt = Date.now();
    return r;
  }
  let beepCtx: AudioContext | null = null;

  /** A speech-like level while the reply "plays" (word bursts and pauses), for the wave bar. */
  function speakLevels(on: boolean) {
    clearInterval(speakTimer);
    if (!on) {
      host.onLevel(0);
      return;
    }
    let t = 0;
    speakTimer = setInterval(() => {
      t += 1;
      const burst = Math.sin(t / 2.3) > -0.3;
      host.onLevel(burst ? 0.25 + 0.6 * Math.abs(Math.sin(t * 0.9)) * (0.6 + Math.random() * 0.4) : Math.random() * 0.06);
    }, 45);
  }
  let partialTimer: ReturnType<typeof setInterval> | undefined;

  const later = (ms: number, fn: () => void) => {
    timers.push(setTimeout(fn, ms));
  };
  const clearTurnTimers = () => {
    timers.forEach(clearTimeout);
    timers = [];
    clearInterval(partialTimer);
  };

  function speak(text: string) {
    const synth = typeof window !== 'undefined' ? window.speechSynthesis : undefined;
    if (!synth) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang === 'en' ? 'en-IN' : 'hi-IN';
    u.rate = speed;
    synth.speak(u);
  }

  function stopSpeaking() {
    if (typeof window !== 'undefined') window.speechSynthesis?.cancel();
  }

  /** Cancels the reply of the current turn, as the server does on `start` or `cancel`. */
  function bargeIn() {
    clearTurnTimers();
    stopSpeaking();
    speakLevels(false);
    if (speakingTurn != null) {
      dispatch({ type: 'audio_end', turn_id: speakingTurn, cancelled: true });
      speakingTurn = null;
    }
  }

  /** Result, then the spoken reply, then timing, from `t0` ms after the end of input. */
  function deliver(id: number, r: BrainResult, t0: number, opts: { duplicate?: boolean; noAudio?: boolean; noise?: { separation_db: number; noisy: boolean; turned_down_ms: number } } = {}) {
    const { speak: spoken, ...fields } = r;
    const msg: ResultMessage = { type: 'result', turn_id: id, trace_id: `mock-${id}`, ...fields };
    if (opts.duplicate) msg.duplicate = true;
    later(t0, () => dispatch({ type: 'state', turn_id: id, state: 'thinking' }));
    later(t0 + 60, () => dispatch(msg));
    if (opts.noAudio) {
      // The reply's speech failed: an error, then audio_end with no audio (the page beeps, the text stays).
      later(t0 + 400, () => {
        dispatch({ type: 'error', turn_id: id, code: 'tts_upstream', message: 'TimeoutError' });
        dispatch({ type: 'audio_end', turn_id: id });
        dispatch({ type: 'state', turn_id: id, state: 'idle' });
      });
      return;
    }
    if (!r.reply_text) {
      later(t0 + 80, () => dispatch({ type: 'state', turn_id: id, state: 'idle' }));
      return;
    }
    const firstAudio = t0 + jitter(330, 80);
    later(firstAudio, () => {
      speakingTurn = id;
      dispatch({ type: 'state', turn_id: id, state: 'speaking' });
      dispatch({ type: 'audio_start', turn_id: id, sample_rate: 24000, encoding: 'pcm_s16le', channels: 1 });
      speak(spoken ?? r.reply_text);
      speakLevels(true);
    });
    later(firstAudio + 30, () => dispatch({ type: 'first_sound', t: performance.now() }));
    later(firstAudio + 10, () =>
      dispatch({
        type: 'timing',
        turn_id: id,
        trace_id: `mock-${id}`,
        ms: { stt_final: t0, parse: 2, db: 4, tts_first_chunk: firstAudio - t0 - 60, end_to_first_audio: firstAudio + 10, gnani_stt_latency: jitter(180, 40) },
        // Spoken turns only (contract 3.5); typed turns have no noise measurement.
        ...(opts.noise ? { noise: opts.noise } : {}),
      }),
    );
    const duration = Math.max(1400, r.reply_text.length * 62) / speed;
    later(firstAudio + duration, () => {
      speakingTurn = null;
      speakLevels(false);
      dispatch({ type: 'audio_end', turn_id: id });
      dispatch({ type: 'state', turn_id: id, state: 'idle' });
    });
  }

  const service: SessionService = {
    kind: 'mock',

    async start(startLang) {
      lang = startLang;
      brain.lang = startLang;
      dispatch({ type: 'set_lang', lang });
      if (!started) {
        started = true;
        dispatch({ type: 'conn', status: 'connecting' });
        later(220, () => {
          dispatch({ type: 'conn', status: 'open' });
          dispatch({ type: 'ready', session_id: `mock-${Date.now().toString(36)}` });
        });
        deliver(0, brain.greeting(), 300);
      }
      const mic: MicStatus = 'ready';
      dispatch({ type: 'mic', status: mic });
      return mic;
    },

    press() {
      if (talking || !host.getState().greeted) return;
      bargeIn();
      dispatch({ type: 'local_start' });
      talking = true;
      const id = ++turn;
      const answer = scriptedAnswer(brain.pendingReason, lang);
      const script = voiceScript[lang];
      heard = answer ?? script[scriptIndex++ % script.length] ?? '';
      later(40, () => dispatch({ type: 'state', turn_id: id, state: 'listening' }));
      later(450, () => dispatch({ type: 'state', turn_id: id, state: 'hearing' }));
      const words = heard.split(' ');
      let shown = 0;
      later(600, () => {
        partialTimer = setInterval(() => {
          if (shown >= words.length - 1) return; // the last word arrives with the final transcript
          shown += 1;
          dispatch({ type: 'transcript', turn_id: id, text: words.slice(0, shown).join(' '), segment: 0, final: false });
        }, 280);
      });
      let phase = 0;
      levelTimer = setInterval(() => {
        phase += 1;
        host.onLevel(0.35 + 0.3 * Math.abs(Math.sin(phase / 3)) + Math.random() * 0.2);
      }, 33);
    },

    abort() {
      if (!talking) return;
      talking = false;
      clearTurnTimers();
      clearInterval(levelTimer);
      host.onLevel(0);
      dispatch({ type: 'local_abort' });
    },

    release() {
      if (!talking) return;
      talking = false;
      clearInterval(levelTimer);
      clearInterval(partialTimer);
      host.onLevel(0);
      dispatch({ type: 'local_end', t: performance.now() });
      const id = turn;
      later(120, () => dispatch({ type: 'state', turn_id: id, state: 'transcribing' }));
      later(jitter(300, 60), () => dispatch({ type: 'transcript', turn_id: id, text: heard, segment: 1, final: true }));
      // A quiet counter by default; the scripted "…, Mohan ka?" turn has a second voice and counts as noisy.
      const noisy = soundsNoisy(heard);
      brain.noisy = noisy;
      const r = respond(heard);
      brain.noisy = false;
      deliver(id, r, jitter(380, 60), {
        noise: noisy ? { separation_db: 8.4, noisy: true, turned_down_ms: 1120 } : { separation_db: 23.5, noisy: false, turned_down_ms: 420 },
      });
    },

    sendText(text, opts = {}) {
      const tx = text.trim();
      if (!tx || !host.getState().greeted) return;
      bargeIn();
      dispatch({ type: 'local_start' });
      dispatch({ type: 'local_text', text: tx });
      dispatch({ type: 'local_end', t: performance.now() });
      const id = ++turn;
      const first = opts.uttId ? seen.get(opts.uttId) : undefined;
      if (first && first.status === 'needs_clarification' && brain.pendingReason !== first.reason) {
        // A replay whose question is no longer the open one: the server will not put it back (contract 3.4).
        deliver(id, {
          status: 'rejected',
          action: 'none',
          reason: 'cancelled',
          entries: [],
          lang,
          reply_text: lang === 'en' ? 'Okay, nothing was saved.' : 'Theek hai, entry nahi ki.',
        }, 40);
        return;
      }
      if (first) {
        deliver(id, first, 40, { duplicate: true }); // nothing new is saved
        return;
      }
      const low = tx.toLowerCase();
      if (/\bnetwork\b/.test(low)) {
        deliver(id, {
          status: 'rejected',
          action: 'none',
          reason: 'upstream',
          entries: [],
          lang,
          reply_text: lang === 'en' ? 'Network problem, please say it again.' : 'Network mein dikkat hai, dobara boliye.',
        }, 40);
        return;
      }
      const r = respond(tx.replace(/awaaz band/i, '').trim());
      if (opts.uttId) seen.set(opts.uttId, r);
      deliver(id, r, 40, { noAudio: /awaaz band/i.test(low) });
    },

    setPrivate(on) {
      brain.privateMode = on;
    },

    beep() {
      try {
        beepCtx ??= new AudioContext();
        softBeep(beepCtx);
      } catch {
        /* no audio in this environment */
      }
    },

    setLang(next) {
      lang = next;
      brain.lang = next;
    },

    setVoiceSpeed(rate) {
      speed = rate;
    },

    close() {
      clearTurnTimers();
      clearInterval(levelTimer);
      clearInterval(speakTimer);
      stopSpeaking();
      dispatch({ type: 'conn', status: 'closed' });
    },
  };
  return service;
}
