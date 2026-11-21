// Ported from web/tests/store.test.mjs (every case), plus the conversation history, saved entries,
// newest-entry and latency selectors added for the new screens.
import { describe, expect, test } from 'vitest';
import type { Entry, SessionAction } from '../services/session/types';
import { conversation, initialState, lastLatency, newestActiveId, reduce, type SessionState } from './session-reducer';

const run = (msgs: SessionAction[], s: SessionState = initialState) => msgs.reduce(reduce, s);
const res = (turn_id: number, extra: Record<string, unknown> = {}): SessionAction =>
  ({ type: 'result', turn_id, status: 'ok', action: 'none', entries: [], reply_text: 'x', ...extra }) as SessionAction;

function entry(id: number, extra: Partial<Entry> = {}): Entry {
  return {
    id,
    kind: 'credit',
    customer: { id: 'c1', display: 'Ramesh', tags: [] },
    amount: 340,
    date: '2026-11-21',
    ts: `2026-11-21T11:4${id}:00+05:30`,
    reversed: false,
    reversal_of: null,
    ...extra,
  };
}

describe('ported reducer behaviour', () => {
  test('state, transcript and result for a turn', () => {
    const s = run([
      { type: 'state', turn_id: 2, state: 'hearing' },
      { type: 'transcript', turn_id: 2, text: 'Ramesh ka 340', segment: 0, final: false },
      { type: 'transcript', turn_id: 2, text: 'Ramesh ka 340 udhaar', segment: 1, final: true },
      res(2, { trace_id: 't1', action: 'append', entries: [entry(1)], reply_text: 'ok' }),
    ]);
    expect(s.turnId).toBe(2);
    expect(s.phase).toBe('hearing');
    expect(s.transcript).toBe('Ramesh ka 340 udhaar');
    expect(s.result?.replyText).toBe('ok');
    expect(s.result?.traceId).toBe('t1');
    expect(s.resultCount).toBe(1);
  });

  test('a newer turn clears the previous turn', () => {
    const s = run([
      res(1, { action: 'greeting', reply_text: 'Namaste' }),
      { type: 'timing', turn_id: 1, trace_id: 'a', ms: { end_to_first_audio: 900 } },
      { type: 'state', turn_id: 2, state: 'listening' },
    ]);
    expect(s.turnId).toBe(2);
    expect(s.result).toBeNull();
    expect(s.timing).toBeNull();
  });

  test('messages for an older turn are ignored', () => {
    const s = run([
      { type: 'state', turn_id: 3, state: 'thinking' },
      res(2, { reply_text: 'old' }),
      { type: 'audio_start', turn_id: 2, sample_rate: 24000 },
    ]);
    expect(s.result).toBeNull();
    expect(s.audioTurn).toBeNull();
  });

  test('barge-in drops the rest of the playing turn until a newer turn arrives', () => {
    let s = run([
      { type: 'state', turn_id: 1, state: 'speaking' },
      { type: 'audio_start', turn_id: 1, sample_rate: 24000 },
    ]);
    expect(s.audioTurn).toBe(1);
    s = reduce(s, { type: 'local_start' });
    expect(s.audioTurn).toBeNull();
    s = run(
      [{ type: 'audio_start', turn_id: 1, sample_rate: 24000 }, res(1, { reply_text: 'stale' }), { type: 'audio_end', turn_id: 1, cancelled: true }],
      s,
    );
    expect(s.audioTurn).toBeNull();
    expect(s.result).toBeNull();
    s = reduce(s, { type: 'state', turn_id: 2, state: 'listening' });
    expect(s.turnId).toBe(2);
    expect(s.barged).toBe(false);
    expect(s.phase).toBe('listening');
  });

  test('audio_start accepts audio and audio_end releases it', () => {
    let s = run([{ type: 'audio_start', turn_id: 1, sample_rate: 24000 }]);
    expect(s.audioTurn).toBe(1);
    expect(s.phase).toBe('speaking');
    s = reduce(s, { type: 'audio_end', turn_id: 1 });
    expect(s.audioTurn).toBeNull();
    expect(s.phase).toBe('idle');
  });

  test('client latency is release to first sound, measured once per turn', () => {
    let s = run([
      { type: 'local_start' },
      { type: 'local_end', t: 1000 },
      { type: 'audio_start', turn_id: 2, sample_rate: 24000 },
      { type: 'first_sound', t: 1850 },
    ]);
    expect(s.clientMs).toBe(850);
    s = reduce(s, { type: 'first_sound', t: 9999 });
    expect(s.clientMs).toBe(850);
  });

  test('first_sound without a release (greeting) records nothing', () => {
    const s = run([{ type: 'audio_start', turn_id: 1, sample_rate: 24000 }, { type: 'first_sound', t: 500 }]);
    expect(s.clientMs).toBeNull();
  });

  test('clientMs survives the new turn message after release', () => {
    const s = run([
      { type: 'local_start' },
      { type: 'local_end', t: 100 },
      { type: 'state', turn_id: 2, state: 'transcribing' },
      { type: 'audio_start', turn_id: 2, sample_rate: 24000 },
      { type: 'first_sound', t: 700 },
    ]);
    expect(s.clientMs).toBe(600);
  });

  test('errors for the current turn are shown, stale ones are not', () => {
    let s = run([{ type: 'state', turn_id: 2, state: 'thinking' }]);
    s = reduce(s, { type: 'error', turn_id: 1, code: 'x', message: 'old' });
    expect(s.error).toBeNull();
    s = reduce(s, { type: 'error', code: 'upstream', message: 'down' });
    expect(s.error).toBe('down');
    expect(s.errorCode).toBe('upstream');
    expect(reduce(s, { type: 'local_start' }).errorCode).toBeNull();
  });

  test('ready stores the session id and conn tracks status', () => {
    const s = run([{ type: 'conn', status: 'open' }, { type: 'ready', session_id: 'abc' }]);
    expect(s.sessionId).toBe('abc');
    expect(s.conn).toBe('open');
  });

  test('transcript text replaces what is shown and final marks the last one', () => {
    let s = run([
      { type: 'transcript', turn_id: 1, text: 'Ramesh', segment: 0, final: false },
      { type: 'transcript', turn_id: 1, text: 'Ramesh ka 340', segment: 0, final: false },
    ]);
    expect(s.transcript).toBe('Ramesh ka 340');
    expect(s.transcriptFinal).toBe(false);
    s = reduce(s, { type: 'transcript', turn_id: 1, text: 'Ramesh ka 340 udhaar', segment: 1, final: true });
    expect(s.transcript).toBe('Ramesh ka 340 udhaar');
    expect(s.transcriptFinal).toBe(true);
    s = reduce(s, { type: 'state', turn_id: 2, state: 'listening' });
    expect(s.transcriptFinal).toBe(false);
  });

  test('a typed sentence is shown as the final transcript, also after the turn starts', () => {
    let s = run([{ type: 'local_start' }, { type: 'local_text', text: 'Ramesh ka 340 udhaar' }]);
    expect(s.transcript).toBe('Ramesh ka 340 udhaar');
    expect(s.transcriptFinal).toBe(true);
    s = reduce(s, { type: 'state', turn_id: 2, state: 'thinking' });
    expect(s.transcript).toBe('Ramesh ka 340 udhaar');
    expect(s.transcriptFinal).toBe(true);
    s = run([{ type: 'local_start' }, { type: 'state', turn_id: 3, state: 'listening' }], s);
    expect(s.transcript).toBe('');
  });

  test('a different session id resets the turn counters', () => {
    let s = run([
      { type: 'ready', session_id: 'A' },
      { type: 'state', turn_id: 5, state: 'speaking' },
      { type: 'audio_start', turn_id: 5, sample_rate: 24000 },
      { type: 'local_start' },
    ]);
    expect(s.turnId).toBe(5);
    s = reduce(s, { type: 'ready', session_id: 'B' });
    expect(s.turnId).toBe(0);
    expect(s.barged).toBe(false);
    expect(s.audioTurn).toBeNull();
    expect(s.greeted).toBe(false);
    s = reduce(s, res(1, { action: 'greeting', reply_text: 'Namaste' }));
    expect(s.result?.replyText).toBe('Namaste');
  });

  test('the same session id on resume keeps the turn counters', () => {
    const s = run([{ type: 'ready', session_id: 'A' }, { type: 'state', turn_id: 4, state: 'idle' }, { type: 'ready', session_id: 'A' }]);
    expect(s.turnId).toBe(4);
  });

  test('greeted turns true on an uncancelled audio_end or on the fallback', () => {
    let s = run([{ type: 'audio_start', turn_id: 1, sample_rate: 24000 }, { type: 'audio_end', turn_id: 1, cancelled: true }]);
    expect(s.greeted).toBe(false);
    expect(reduce(s, { type: 'greeting_timeout' }).greeted).toBe(true);
    s = run([{ type: 'audio_start', turn_id: 1, sample_rate: 24000 }, { type: 'audio_end', turn_id: 1 }]);
    expect(s.greeted).toBe(true);
  });

  test('a notice shows as the error line and a new press clears it', () => {
    let s = reduce(initialState, { type: 'notice' });
    expect(s.error).toBe('Connection nahi hai. Thodi der mein dobara dabaiye.');
    s = reduce(s, { type: 'local_start' });
    expect(s.error).toBeNull();
  });

  test('the chosen language is kept and the notice follows it', () => {
    const s = reduce(initialState, { type: 'set_lang', lang: 'en' });
    expect(s.lang).toBe('en');
    expect(reduce(s, { type: 'notice' }).error).toBe('No connection. Press again in a moment.');
    expect(reduce(initialState, { type: 'set_lang', lang: 'fr' as never }).lang).toBe('hi');
  });

  test('a result with lang switches the label language, one without keeps it', () => {
    let s = run([{ type: 'set_lang', lang: 'hi' }, res(1, { lang: 'en' })]);
    expect(s.lang).toBe('en');
    s = reduce(s, res(2));
    expect(s.lang).toBe('en');
    s = reduce(s, res(3, { lang: 'hi' }));
    expect(s.lang).toBe('hi');
  });

  test('a stale result does not change the language, and a new session keeps it', () => {
    let s = run([{ type: 'set_lang', lang: 'hi' }, { type: 'state', turn_id: 3, state: 'idle' }]);
    s = reduce(s, res(2, { lang: 'en' }));
    expect(s.lang).toBe('hi');
    s = run([{ type: 'ready', session_id: 'A' }, { type: 'set_lang', lang: 'en' }, { type: 'ready', session_id: 'B' }], s);
    expect(s.lang).toBe('en');
  });

  test('mic status is stored', () => {
    expect(reduce(initialState, { type: 'mic', status: 'denied' }).mic).toBe('denied');
  });
});

describe('conversation of the session', () => {
  test('greeting, then a spoken turn, then a typed turn are kept in order', () => {
    let s = run([
      { type: 'ready', session_id: 'S' },
      res(0, { action: 'greeting', reply_text: 'Namaste! Main KhataVaani hoon, ek AI sahayak.' }),
      { type: 'audio_start', turn_id: 0, sample_rate: 24000 },
      { type: 'audio_end', turn_id: 0 },
      { type: 'local_start' },
    ]);
    expect(s.history.map((t) => t.result?.action)).toEqual(['greeting']);
    expect(conversation(s)).toHaveLength(1); // the live turn is empty right after the press
    s = run(
      [
        { type: 'local_end', t: 10 },
        { type: 'state', turn_id: 1, state: 'transcribing' },
        { type: 'transcript', turn_id: 1, text: 'Ramesh ka 340 udhaar', final: true },
        res(1, { action: 'append', entries: [entry(1)], reply_text: 'Ramesh ke khate mein ₹340 udhaar likh diya.' }),
      ],
      s,
    );
    const live = conversation(s);
    expect(live).toHaveLength(2);
    expect(live[1]?.said).toBe('Ramesh ka 340 udhaar');
    s = run([{ type: 'local_start' }, { type: 'local_text', text: 'Nahi, 430' }], s);
    const turns = conversation(s);
    expect(turns.map((t) => t.said)).toEqual(['', 'Ramesh ka 340 udhaar', 'Nahi, 430']);
    expect(turns[2]?.typed).toBe(true);
    expect(turns[1]?.result?.entries).toHaveLength(1);
  });

  test('a turn is archived once, even when the next turn id arrives after the press', () => {
    const s = run([
      res(1, { reply_text: 'one' }),
      { type: 'local_start' },
      { type: 'state', turn_id: 2, state: 'listening' },
      res(2, { reply_text: 'two' }),
      { type: 'state', turn_id: 3, state: 'listening' },
    ]);
    expect(s.history.map((t) => t.result?.replyText)).toEqual(['one', 'two']);
  });

  test('a typed sentence never borrows the previous turn reply', () => {
    const s = run([res(1, { reply_text: 'first reply' }), { type: 'local_start' }, { type: 'local_text', text: 'typed' }]);
    const turns = conversation(s);
    expect(turns[0]?.result?.replyText).toBe('first reply');
    expect(turns[1]?.said).toBe('typed');
    expect(turns[1]?.result).toBeNull();
  });

  test('saved keeps every touched entry in its latest state (amend flips the old row)', () => {
    let s = run([res(1, { action: 'append', entries: [entry(1)] })]);
    s = run([{ type: 'local_start' }, res(2, { action: 'amend', entries: [entry(1, { reversed: true }), entry(2, { amount: 430 })] })], s);
    expect(s.saved.map((e) => [e.id, e.amount, e.reversed])).toEqual([
      [1, 340, true],
      [2, 430, false],
    ]);
    expect(newestActiveId(s.saved)).toBe(2);
    expect(s.amendedFrom['2']?.amount).toBe(340);
    s = run([{ type: 'local_start' }, res(3, { action: 'undo', entries: [entry(2, { amount: 430, reversed: true })] })], s);
    expect(newestActiveId(s.saved)).toBeNull();
  });

  test('a stale result does not touch saved entries', () => {
    const s = run([{ type: 'state', turn_id: 4, state: 'idle' }, res(3, { entries: [entry(9)] })]);
    expect(s.saved).toEqual([]);
  });

  test('lastLatency reports the latest turn with server or phone timing', () => {
    let s = run([
      { type: 'local_start' },
      { type: 'local_end', t: 1000 },
      { type: 'audio_start', turn_id: 1, sample_rate: 24000 },
      { type: 'first_sound', t: 1912.4 },
      { type: 'timing', turn_id: 1, ms: { end_to_first_audio: 840.6 } },
    ]);
    expect(lastLatency(conversation(s))).toMatchObject({ server: 841, phone: 912, ms: { end_to_first_audio: 840.6 } });
    s = reduce(s, { type: 'local_start' }); // the next press: the finished turn keeps its numbers
    expect(lastLatency(conversation(s))).toMatchObject({ server: 841, phone: 912 });
    expect(lastLatency([])).toBeNull();
  });
});

describe('contract 3.3', () => {
  test('a duplicate result shows its reply but never adds its entries again', () => {
    let s = run([res(1, { action: 'append', entries: [entry(1)], reply_text: 'saved' })]);
    expect(s.saved).toHaveLength(1);
    s = run([{ type: 'local_start' }, res(2, { action: 'append', entries: [entry(1)], reply_text: 'saved', duplicate: true })], s);
    expect(s.saved).toHaveLength(1);
    expect(s.result?.entries).toEqual([]);
    expect(s.result?.duplicate).toBe(true);
    expect(s.result?.replyText).toBe('saved');
  });

  test('candidates, confirm, query and balances are kept on the turn', () => {
    const s = run([
      res(1, {
        status: 'needs_clarification',
        reason: 'confirm_entry',
        confirm: { type: 'settle', balance: 770 },
        candidates: [340, 740],
        query: { type: 'top_dues' },
        balances: [{ customer_id: 'c1', display: 'Ramesh', balance: 770 }],
      }),
    ]);
    expect(s.result).toMatchObject({ confirm: { type: 'settle', balance: 770 }, candidates: [340, 740], query: { type: 'top_dues' } });
    expect(s.result?.balances[0]?.balance).toBe(770);
  });

  test('ready alone never marks the session greeted: the greeting (with the disclosure) must play', () => {
    expect(reduce(initialState, { type: 'ready', session_id: 'S', resumed: true }).greeted).toBe(false);
    expect(reduce(initialState, { type: 'ready', session_id: 'S' }).greeted).toBe(false);
  });

  test('waiting for a result when the socket dropped: ready.last_result is shown', () => {
    let s = run([{ type: 'ready', session_id: 'S' }, res(1, { reply_text: 'one' }), { type: 'local_start' }, { type: 'local_end', t: 5 }]);
    expect(s.phase).toBe('transcribing');
    s = reduce(s, { type: 'conn', status: 'reconnecting' });
    s = reduce(s, {
      type: 'ready',
      session_id: 'S',
      resumed: true,
      last_turn_id: 2,
      last_result: { status: 'ok', action: 'append', entries: [entry(9)], reply_text: 'Ramesh ke khate mein ₹340 udhaar likh diya.' },
    });
    expect(s.turnId).toBe(2);
    expect(s.result?.replyText).toMatch(/₹340/);
    expect(s.saved.map((e) => e.id)).toContain(9);
    expect(s.phase).toBe('idle');
  });

  test('the turn never reached the server: the wait ends with the no-connection notice', () => {
    let s = run([{ type: 'ready', session_id: 'S' }, res(1, { reply_text: 'one' }), { type: 'local_start' }, { type: 'local_end', t: 5 }]);
    s = reduce(s, { type: 'ready', session_id: 'S', resumed: true, last_turn_id: 1, last_result: { status: 'ok', action: 'none', reply_text: 'one' } });
    expect(s.result).toBeNull();
    expect(s.phase).toBe('idle');
    expect(s.errorCode).toBe('no_connection');
  });

  test('a fresh ready (not waiting) never replays last_result', () => {
    const s = reduce(initialState, { type: 'ready', session_id: 'S', resumed: true, last_turn_id: 4, last_result: { status: 'needs_clarification', action: 'none', reply_text: '₹340 ya ₹740?' } });
    expect(s.result).toBeNull();
    expect(s.resultCount).toBe(0);
  });

  test('release shows "Samajh raha hoon…" at once, even if the server still says hearing', () => {
    let s = run([{ type: 'local_start' }, { type: 'state', turn_id: 1, state: 'hearing' }, { type: 'local_end', t: 10 }]);
    expect(s.phase).toBe('transcribing');
    s = reduce(s, { type: 'state', turn_id: 1, state: 'hearing' });
    expect(s.phase).toBe('transcribing');
    s = reduce(s, { type: 'state', turn_id: 1, state: 'thinking' });
    expect(s.phase).toBe('thinking');
  });

  test('an accidental press: hint, no error, and the server turn for it is dropped', () => {
    // The server's turn already arrived before the abort.
    let s = run([{ type: 'local_start' }, { type: 'state', turn_id: 1, state: 'listening' }, { type: 'local_abort' }]);
    expect(s).toMatchObject({ phase: 'idle', hint: 'micTooShort', error: null });
    s = run([{ type: 'state', turn_id: 1, state: 'hearing' }, res(1, { reply_text: 'Kuch sunai nahi diya.' })], s);
    expect(s.result).toBeNull();
    expect(s.phase).toBe('idle');
    // The next real press works and clears the hint.
    s = run([{ type: 'local_start' }, { type: 'state', turn_id: 2, state: 'listening' }], s);
    expect(s).toMatchObject({ phase: 'listening', hint: null, turnId: 2 });
  });

  test('an accidental press before the server turn arrives: that turn is dropped when it comes', () => {
    let s = run([res(1, { reply_text: 'old' }), { type: 'local_start' }, { type: 'local_abort' }]);
    s = run([{ type: 'state', turn_id: 2, state: 'listening' }, res(2, { action: 'none', reply_text: '' })], s);
    expect(s.result).toBeNull();
    expect(s.turnId).toBe(2);
    s = run([{ type: 'local_start' }, { type: 'state', turn_id: 3, state: 'listening' }], s);
    expect(s.phase).toBe('listening');
  });

  test('a reply with text but no audio cues one beep; a played reply does not', () => {
    let s = run([res(1, { reply_text: 'Likh diya.' }), { type: 'audio_start', turn_id: 1, sample_rate: 24000 }, { type: 'audio_end', turn_id: 1 }]);
    expect(s.beepSeq).toBe(1);
    s = run([{ type: 'error', turn_id: 1, code: 'tts_upstream', message: 'TimeoutError' }], s);
    expect(s.beepSeq).toBe(1); // once per turn
    s = run(
      [{ type: 'local_start' }, res(2, { reply_text: 'ok' }), { type: 'audio_start', turn_id: 2, sample_rate: 24000 }, { type: 'first_sound', t: 1 }, { type: 'audio_end', turn_id: 2 }],
      s,
    );
    expect(s.beepSeq).toBe(1);
    s = run([{ type: 'local_start' }, res(3, { reply_text: 'Theek hai.' }), { type: 'error', turn_id: 3, code: 'tts_upstream' }], s);
    expect(s.beepSeq).toBe(2);
  });

  test('a cancelled reply or a reply without text never beeps', () => {
    expect(run([res(1, { reply_text: 'x' }), { type: 'audio_end', turn_id: 1, cancelled: true }]).beepSeq).toBe(0);
    expect(run([res(1, { reply_text: '' }), { type: 'audio_end', turn_id: 1 }]).beepSeq).toBe(0);
  });

  test('a network or speech-service failure opens the type box until it is closed or a turn succeeds', () => {
    let s = run([res(1, { status: 'rejected', reason: 'upstream', reply_text: 'Network mein dikkat hai, dobara boliye.' })]);
    expect(s.offerTyping).toBe(true);
    s = reduce(s, { type: 'typing_closed' });
    expect(s.offerTyping).toBe(false);
    s = run([{ type: 'error', turn_id: 1, code: 'stt_upstream', message: 'x' }], s);
    expect(s.offerTyping).toBe(true);
    s = run([{ type: 'local_start' }, res(2, { status: 'ok' })], s);
    expect(s.offerTyping).toBe(false);
  });
});
