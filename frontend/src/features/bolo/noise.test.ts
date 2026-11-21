// Noise handling on the page (contract 3.5): `timing.noise` reaches the turn, a noisy turn shows
// "Shor zyada hai", the latency panel shows the separation, and its absence changes nothing.
import { describe, expect, test } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { SessionAction } from '../../services/session/types';
import { conversation, initialState, lastLatency, parseNoise, reduce, turnNoise, type SessionState } from '../../state/session-reducer';
import { NoisyLabel } from './Conversation';
import { noiseRow } from './LatencyLine';
import { MockBrain, VOICE_SCRIPT, soundsNoisy } from '../../services/mock/brain';
import { MockLedger } from '../../services/mock/ledger';

const run = (msgs: SessionAction[], s: SessionState = initialState) => msgs.reduce(reduce, s);
const spoken = (noise?: unknown): SessionAction[] => [
  { type: 'local_start' },
  { type: 'local_end', t: 0 },
  { type: 'result', turn_id: 1, status: 'needs_clarification', action: 'none', reason: 'confirm_entry', reply_text: 'Ramesh ke ₹340 udhaar likhun?', confirm: { type: 'unsure', words: [], noise: true } },
  { type: 'timing', turn_id: 1, ms: { end_to_first_audio: 900 }, ...(noise === undefined ? {} : { noise }) } as SessionAction,
];

describe('noise on the turn', () => {
  test('timing.noise is carried to the turn and to the latency figures', () => {
    const s = run(spoken({ separation_db: 8.43, noisy: true, turned_down_ms: 1120 }));
    const turn = conversation(s).at(-1)!;
    expect(turnNoise(turn)).toEqual({ separation_db: 8.43, noisy: true, turned_down_ms: 1120 });
    expect(lastLatency(conversation(s))?.noise).toMatchObject({ noisy: true });
    // It stays with the turn after the next press.
    expect(turnNoise(conversation(reduce(s, { type: 'local_start' })).at(-1)!)).toMatchObject({ separation_db: 8.43 });
  });

  test('absent (typed turns, older servers) or malformed: no noise, silently', () => {
    expect(turnNoise(conversation(run(spoken())).at(-1)!)).toBeNull();
    expect(parseNoise({ noisy: true })).toBeNull();
    expect(parseNoise({ separation_db: 'x', noisy: false })).toBeNull();
    expect(parseNoise(null)).toBeNull();
    expect(parseNoise({ separation_db: 20, noisy: false })).toEqual({ separation_db: 20, noisy: false });
  });
});

describe('what the page shows', () => {
  test('"Shor zyada hai" is a quiet label: no red, no error role, no icon', () => {
    const hi = renderToStaticMarkup(createElement(NoisyLabel, { lang: 'hi' }));
    expect(hi).toContain('Shor zyada hai');
    expect(hi).toContain('text-ink-2');
    expect(hi).not.toMatch(/text-credit|role="alert"|<svg/);
    expect(renderToStaticMarkup(createElement(NoisyLabel, { lang: 'en' }))).toContain('Noisy here');
  });

  test('the latency panel row: separation to one decimal, "(shor zyada)" when noisy, nothing when absent', () => {
    expect(noiseRow({ separation_db: 23.46, noisy: false }, 'hi')).toEqual({ label: 'Awaaz aur shor ka fark', value: '23.5 dB' });
    expect(noiseRow({ separation_db: 8.4, noisy: true }, 'hi')?.value).toBe('8.4 dB (shor zyada)');
    expect(noiseRow({ separation_db: 8.4, noisy: true }, 'en')?.value).toBe('8.4 dB (noisy)');
    expect(noiseRow(null, 'hi')).toBeNull();
  });
});

describe('the mock', () => {
  test('one scripted noisy turn; a noisy save is confirmed first ("… likhun?")', () => {
    expect(VOICE_SCRIPT.hi.filter(soundsNoisy)).toEqual(['Imran ka 60 udhaar, Mohan ka?']);
    expect(VOICE_SCRIPT.en.filter(soundsNoisy)).toHaveLength(1);
    expect(soundsNoisy('Ramesh ka 340 udhaar')).toBe(false);
    const b = new MockBrain(new MockLedger(false));
    b.noisy = true;
    const q = b.respond('Imran ka 60 udhaar, Mohan ka?');
    expect(q).toMatchObject({ reason: 'confirm_entry', reply_text: 'Imran ke ₹60 udhaar likhun?', confirm: { type: 'unsure', noise: true } });
    b.noisy = false;
    expect(b.respond('haan').entries[0]?.amount).toBe(60);
  });
});
