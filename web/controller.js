// Wires the microphone, the player, the WebSocket client and the store together.
import { reduce, initialState } from './store.js';
import { SessionClient, wsUrl } from './ws.js';
import { Player } from './audio/player.js';

export function createController(onChange) {
  let state = initialState;
  let ctx = null;
  let player = null;
  let client = null;
  let talking = false; // button held
  let finishing = null; // pending end-of-stream after release, or null
  let node = null;
  const listeners = new Set();

  const dispatch = (action) => {
    state = reduce(state, action);
    onChange(state, action);
    for (const fn of listeners) fn(state, action);
  };

  const api = {
    get state() { return state; },
    micReady: false,
    micError: null,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },

    /** Called from the Start tap: audio context, microphone, socket, hello. */
    async start() {
      ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
      await ctx.resume();
      player = new Player(ctx, (t) => dispatch({ type: 'first_sound', t }));

      const code = new URLSearchParams(location.search).get('code');
      client = new SessionClient({
        url: wsUrl(location),
        accessCode: code,
        onStatus: (status) => dispatch({ type: 'conn', status }),
        onMessage: (m) => {
          dispatch(m);
          if (m.type === 'audio_start' && state.audioTurn === Number(m.turn_id)) player.begin(m.sample_rate);
          else if (m.type === 'audio_end' && m.turn_id != null && Number(m.turn_id) >= state.turnId) {
            m.cancelled ? player.stop() : player.end();
          }
        },
        // Binary frames carry no turn id: they are played only while a non-stale audio_start is open.
        onAudio: (buf) => { if (state.audioTurn != null) player.push(buf); },
      });
      client.connect();

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: { ideal: true },
            noiseSuppression: { ideal: true },
            autoGainControl: { ideal: true },
          },
        });
        await ctx.audioWorklet.addModule('audio/capture-worklet.js');
        node = new AudioWorkletNode(ctx, 'capture', { numberOfOutputs: 1, outputChannelCount: [1] });
        node.port.onmessage = (ev) => {
          const d = ev.data;
          if (d && d.flush) { if (finishing) finishing.tail = d.chunk; if (finishing) finishing.done(); return; }
          if (talking || finishing) client.sendAudio(d);
        };
        ctx.createMediaStreamSource(stream).connect(node);
        node.connect(ctx.destination); // the node writes silence; the connection keeps it running
        api.micReady = true;
      } catch (err) {
        api.micError = err && err.name === 'NotAllowedError'
          ? 'Microphone ki ijaazat nahi mili. Type karein se bhi test kar sakte hain.'
          : 'Microphone nahi chala (HTTPS chahiye). Type karein se test karein.';
      }
      dispatch({ type: 'mic' });
    },

    /** Button pressed: barge-in, then start streaming. */
    press() {
      if (!api.micReady || talking || !client) return;
      if (finishing) finishing.done(); // a quick re-press: close the previous turn first
      player.stop();
      dispatch({ type: 'local_start' });
      if (client.send({ type: 'start', mode: 'ptt' })) talking = true;
    },

    /**
     * Button released: ask the worklet for the zero-padded tail, send it, then send end.
     * Waits at most 40 ms for the worklet; end is sent regardless.
     */
    release() {
      if (!talking) return;
      talking = false;
      const t = performance.now();
      let sent = false;
      const fin = { tail: null };
      fin.done = () => {
        if (sent) return;
        sent = true;
        clearTimeout(fin.timer);
        finishing = null;
        if (fin.tail) client.sendAudio(fin.tail);
        client.send({ type: 'end' });
        dispatch({ type: 'local_end', t });
      };
      finishing = fin;
      fin.timer = setTimeout(fin.done, 40);
      node.port.postMessage({ flush: true });
    },

    /** Typed input, same pipeline without speech recognition. */
    sendText(text) {
      const t = text.trim();
      if (!t || !client) return;
      player.stop();
      dispatch({ type: 'local_start' });
      dispatch({ type: 'local_text', text: t });
      client.send({ type: 'text', text: t });
      dispatch({ type: 'local_end', t: performance.now() });
    },
  };
  return api;
}
