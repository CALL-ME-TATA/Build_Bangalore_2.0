import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, reduce } from '../store.js';

const run = (msgs, s = initialState) => msgs.reduce(reduce, s);

test('state, transcript and result for a turn', () => {
  const s = run([
    { type: 'state', turn_id: 2, state: 'hearing' },
    { type: 'transcript', turn_id: 2, text: 'Ramesh ka 340', segment: 0, final: false },
    { type: 'transcript', turn_id: 2, text: 'Ramesh ka 340 udhaar', segment: 1, final: true },
    { type: 'result', turn_id: 2, trace_id: 't1', status: 'ok', action: 'append', entries: [{ id: 1 }], reply_text: 'ok' },
  ]);
  assert.equal(s.turnId, 2);
  assert.equal(s.phase, 'hearing');
  assert.equal(s.transcript, 'Ramesh ka 340 udhaar');
  assert.equal(s.result.replyText, 'ok');
  assert.equal(s.result.traceId, 't1');
  assert.equal(s.resultCount, 1);
});

test('a newer turn clears the previous turn', () => {
  const s = run([
    { type: 'result', turn_id: 1, status: 'ok', action: 'greeting', entries: [], reply_text: 'Namaste' },
    { type: 'timing', turn_id: 1, trace_id: 'a', ms: { end_to_first_audio: 900 } },
    { type: 'state', turn_id: 2, state: 'listening' },
  ]);
  assert.equal(s.turnId, 2);
  assert.equal(s.result, null);
  assert.equal(s.timing, null);
});

test('messages for an older turn are ignored', () => {
  const s = run([
    { type: 'state', turn_id: 3, state: 'thinking' },
    { type: 'result', turn_id: 2, status: 'ok', action: 'none', entries: [], reply_text: 'old' },
    { type: 'audio_start', turn_id: 2, sample_rate: 24000 },
  ]);
  assert.equal(s.result, null);
  assert.equal(s.audioTurn, null);
});

test('barge-in drops the rest of the playing turn until a newer turn arrives', () => {
  let s = run([
    { type: 'state', turn_id: 1, state: 'speaking' },
    { type: 'audio_start', turn_id: 1, sample_rate: 24000 },
  ]);
  assert.equal(s.audioTurn, 1);
  s = reduce(s, { type: 'local_start' });
  assert.equal(s.audioTurn, null);
  s = run([
    { type: 'audio_start', turn_id: 1, sample_rate: 24000 },
    { type: 'result', turn_id: 1, status: 'ok', action: 'none', entries: [], reply_text: 'stale' },
    { type: 'audio_end', turn_id: 1, cancelled: true },
  ], s);
  assert.equal(s.audioTurn, null);
  assert.equal(s.result, null);
  s = reduce(s, { type: 'state', turn_id: 2, state: 'listening' });
  assert.equal(s.turnId, 2);
  assert.equal(s.barged, false);
  assert.equal(s.phase, 'listening');
});

test('audio_start accepts audio and audio_end releases it', () => {
  let s = run([{ type: 'audio_start', turn_id: 1, sample_rate: 24000 }]);
  assert.equal(s.audioTurn, 1);
  assert.equal(s.phase, 'speaking');
  s = reduce(s, { type: 'audio_end', turn_id: 1 });
  assert.equal(s.audioTurn, null);
  assert.equal(s.phase, 'idle');
});

test('client latency is release to first sound, measured once per turn', () => {
  let s = run([
    { type: 'local_start' },
    { type: 'local_end', t: 1000 },
    { type: 'audio_start', turn_id: 2, sample_rate: 24000 },
    { type: 'first_sound', t: 1850 },
  ]);
  assert.equal(s.clientMs, 850);
  s = reduce(s, { type: 'first_sound', t: 9999 });
  assert.equal(s.clientMs, 850);
});

test('first_sound without a release (greeting) records nothing', () => {
  const s = run([
    { type: 'audio_start', turn_id: 1, sample_rate: 24000 },
    { type: 'first_sound', t: 500 },
  ]);
  assert.equal(s.clientMs, null);
});

test('clientMs survives the new turn message after release', () => {
  const s = run([
    { type: 'local_start' },
    { type: 'local_end', t: 100 },
    { type: 'state', turn_id: 2, state: 'transcribing' },
    { type: 'audio_start', turn_id: 2, sample_rate: 24000 },
    { type: 'first_sound', t: 700 },
  ]);
  assert.equal(s.clientMs, 600);
});

test('errors for the current turn are shown, stale ones are not', () => {
  let s = run([{ type: 'state', turn_id: 2, state: 'thinking' }]);
  s = reduce(s, { type: 'error', turn_id: 1, code: 'x', message: 'old' });
  assert.equal(s.error, null);
  s = reduce(s, { type: 'error', code: 'upstream', message: 'down' });
  assert.equal(s.error, 'down');
});

test('ready stores the session id and conn tracks status', () => {
  const s = run([{ type: 'conn', status: 'open' }, { type: 'ready', session_id: 'abc' }]);
  assert.equal(s.sessionId, 'abc');
  assert.equal(s.conn, 'open');
});

test('transcript text replaces what is shown and final marks the last one', () => {
  let s = run([
    { type: 'transcript', turn_id: 1, text: 'Ramesh', segment: 0, final: false },
    { type: 'transcript', turn_id: 1, text: 'Ramesh ka 340', segment: 0, final: false },
  ]);
  assert.equal(s.transcript, 'Ramesh ka 340');
  assert.equal(s.transcriptFinal, false);
  s = reduce(s, { type: 'transcript', turn_id: 1, text: 'Ramesh ka 340 udhaar', segment: 1, final: true });
  assert.equal(s.transcript, 'Ramesh ka 340 udhaar');
  assert.equal(s.transcriptFinal, true);
  s = reduce(s, { type: 'state', turn_id: 2, state: 'listening' });
  assert.equal(s.transcriptFinal, false);
});

test('a typed sentence is shown as the final transcript, also after the turn starts', () => {
  let s = run([{ type: 'local_start' }, { type: 'local_text', text: 'Ramesh ka 340 udhaar' }]);
  assert.equal(s.transcript, 'Ramesh ka 340 udhaar');
  assert.equal(s.transcriptFinal, true);
  s = reduce(s, { type: 'state', turn_id: 2, state: 'thinking' });
  assert.equal(s.transcript, 'Ramesh ka 340 udhaar');
  assert.equal(s.transcriptFinal, true);
  s = run([{ type: 'local_start' }, { type: 'state', turn_id: 3, state: 'listening' }], s);
  assert.equal(s.transcript, '');
});
