// Follow-ups from the first run against the real server: rejection reasons, the settings acknowledgement,
// the sheet headings, microphone failure reasons, write-off entries in every list, and ledger ordering.
import { describe, expect, test } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Entry, SessionAction } from '../../services/session/types';
import { initialState, reduce, type SessionState } from '../../state/session-reducer';
import { doubtHeadingKey } from '../../lib/doubt';
import { micError, micUnavailable } from '../../services/session/micStatus';
import { micView } from '../../lib/mic';
import { amountParts, kindLabel, kindTone, MINUS } from '../../lib/format';
import { EntryRow } from '../../components/EntryRow';
import { customerTimeline } from '../customer/logic';
import { ledgerPath } from '../../services/api';
import { MockLedger } from '../../services/mock/ledger';

const run = (msgs: SessionAction[], s: SessionState = initialState) => msgs.reduce(reduce, s);
const rejected = (turn_id: number, reason: string, reply_text = '') =>
  ({ type: 'result', turn_id, status: 'rejected', action: 'none', reason, entries: [], reply_text }) as SessionAction;

/** An entry exactly as /api/ledger and `result.entries` send it. */
const serverEntry = (over: Partial<Entry> = {}): Entry => ({
  id: 41,
  kind: 'writeoff',
  customer: { id: 'c7', display: 'Ramesh', tags: ['chai wale'] },
  amount: 770,
  date: '2026-11-21',
  ts: '2026-11-21T11:42:00+05:30',
  reversed: false,
  reversal_of: null,
  ...over,
});

describe('rejection reasons end the turn cleanly', () => {
  test.each(['silence', 'too_long', 'empty_transcript', 'internal'])('%s: reply shown, mic back to idle', (reason) => {
    const s = run([{ type: 'local_start' }, { type: 'local_end', t: 1 }, { type: 'state', turn_id: 1, state: 'transcribing' }, rejected(1, reason, 'Kuch sunai nahi diya. Dobara boliye.')]);
    expect(s.phase).toBe('idle');
    expect(s.result?.replyText).toBe('Kuch sunai nahi diya. Dobara boliye.');
    expect(s.error).toBeNull();
    expect(s.released).toBe(false);
  });

  test('too_short: no error, the hold hint; cancelled: nothing at all', () => {
    const short = run([{ type: 'local_start' }, { type: 'local_end', t: 1 }, rejected(1, 'too_short')]);
    expect(short).toMatchObject({ phase: 'idle', error: null, hint: 'micTooShort' });
    expect(micView({ started: true, greeted: true, phase: short.phase, mic: 'ready', error: short.error, conn: 'open', mode: 'hold', hint: short.hint })).toMatchObject({
      visual: 'idle',
      labelKey: 'micTooShort',
    });
    const cancelled = run([{ type: 'local_start' }, { type: 'state', turn_id: 1, state: 'listening' }, rejected(1, 'cancelled')]);
    expect(cancelled).toMatchObject({ phase: 'idle', error: null, beepSeq: 0 });
  });

  test('a spoken silence reply still moves the mic to speaking when its audio starts', () => {
    const s = run([{ type: 'local_start' }, rejected(1, 'silence', 'Kuch sunai nahi diya.'), { type: 'audio_start', turn_id: 1, sample_rate: 24000 }]);
    expect(s.phase).toBe('speaking');
  });

  test('the settings acknowledgement changes nothing and is not an error', () => {
    const before = run([{ type: 'ready', session_id: 'S' }]);
    const after = reduce(before, { type: 'settings', private: true });
    expect(after).toBe(before);
  });
});

describe('sheet headings', () => {
  test('two amounts / confirmations / open questions', () => {
    expect(doubtHeadingKey('confusable_number')).toBe('doubtUnsure');
    for (const r of ['plausibility', 'confirm_entry', 'new_customer']) expect(doubtHeadingKey(r)).toBe('doubtConfirm');
    for (const r of ['missing_amount', 'missing_customer', 'ambiguous_direction', 'unclear_date', 'same_name', 'unclear_correction', null]) {
      expect(doubtHeadingKey(r)).toBe('doubtMore');
    }
  });
});

describe('microphone failure reasons', () => {
  const err = (name: string) => Object.assign(new Error(name), { name });
  test('HTTPS is blamed only on an insecure origin', () => {
    expect(micUnavailable(false)).toBe('insecure');
    expect(micUnavailable(true)).toBe('nodevice');
    expect(micError(err('NotAllowedError'), true)).toBe('denied');
    expect(micError(err('NotAllowedError'), false)).toBe('insecure');
    expect(micError(err('NotFoundError'), true)).toBe('nodevice');
    expect(micError(err('NotReadableError'), true)).toBe('nodevice');
    expect(micError(err('AbortError'), true)).toBe('failed');
  });

  test('each reason has its own label', () => {
    const base = { started: true, greeted: true, phase: 'idle' as const, error: null, conn: 'open' as const, mode: 'hold' as const };
    expect(micView({ ...base, mic: 'nodevice' }).labelKey).toBe('micNoDevice');
    expect(micView({ ...base, mic: 'insecure' }).labelKey).toBe('micInsecure');
    expect(micView({ ...base, mic: 'denied' }).labelKey).toBe('micDenied');
  });
});

describe('write-off entries with real data shapes', () => {
  test('minus sign, "Maaf kiya", neutral ink', () => {
    const p = amountParts(770, { kind: 'writeoff', lang: 'hi' });
    expect(p.sign).toBe(MINUS);
    expect(p.label).toBe('minus 770 rupaye, maaf kiya');
    expect(kindLabel('writeoff', 'en')).toBe('Written off');
    expect(kindTone('writeoff')).toBe('text-ink');
  });

  test('conversation rows and the "Abhi likha gaya" rows', () => {
    for (const variant of ['row', 'compact'] as const) {
      const html = renderToStaticMarkup(createElement(EntryRow, { entry: serverEntry(), lang: 'hi', variant, now: new Date('2026-11-21T12:00:00+05:30') }));
      expect(html).toContain('Maaf kiya · Ramesh · Chai wale');
      expect(html).toContain('minus 770 rupaye, maaf kiya');
      expect(html).not.toContain('text-payment');
      expect(html).not.toContain('text-credit');
    }
  });

  test('the customer timeline groups a write-off under its day like any entry', () => {
    const groups = customerTimeline(
      [serverEntry(), serverEntry({ id: 40, kind: 'credit', amount: 770, date: '2026-11-20', ts: '2026-11-20T10:00:00+05:30' })],
      'c7',
      new Date('2026-11-21T12:00:00+05:30'),
      'hi',
    );
    expect(groups.map((g) => [g.date, g.items.map((i) => i.entry.kind)])).toEqual([
      ['2026-11-21', ['writeoff']],
      ['2026-11-20', ['credit']],
    ]);
  });
});

describe('ledger ordering', () => {
  test('query string', () => {
    expect(ledgerPath(50)).toBe('/api/ledger?limit=50');
    expect(ledgerPath(500, { order: 'date', customerId: 'c 7' })).toBe('/api/ledger?limit=500&order=date&customer_id=c+7');
  });

  test('the mock ledger honours order=date and customer_id', () => {
    const l = new MockLedger(false);
    l.add('credit', 'Ramesh', 100, [], new Date('2026-11-21T10:00:00'));
    l.add('payment', 'Ramesh', 50, [], new Date('2026-11-19T10:00:00')); // back-dated, recorded later
    l.add('credit', 'Sunita', 80, [], new Date('2026-11-21T11:00:00'));
    const ramesh = l.find('Ramesh')?.id ?? '';
    expect(l.ledgerView(50).entries.map((e) => e.amount)).toEqual([80, 50, 100]); // creation order
    expect(l.ledgerView(50, { order: 'date', customerId: ramesh }).entries.map((e) => e.amount)).toEqual([100, 50]);
  });
});
