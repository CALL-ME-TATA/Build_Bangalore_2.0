// Amount formatting (the rules of the <Amount> component), dates and names.
import { describe, expect, test } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import {
  MINUS,
  NNBSP,
  RUPEE,
  amountParts,
  customerName,
  dayLabel,
  entryWhen,
  groupDigits,
  initial,
  longDate,
  replySegments,
  sinceLabel,
  stamp,
  splitVolatile,
} from './format';
import { Amount } from '../components/Amount';

describe('amountParts', () => {
  test('Indian lakh grouping', () => {
    expect(groupDigits(0)).toBe('0');
    expect(groupDigits(5)).toBe('5');
    expect(groupDigits(340)).toBe('340');
    expect(groupDigits(1250)).toBe('1,250');
    expect(groupDigits(125000)).toBe('1,25,000');
    expect(groupDigits(10000000)).toBe('1,00,00,000');
  });

  test('credit: plus, narrow no-break space, ₹, digits; spoken label with udhaar', () => {
    const p = amountParts(340, { kind: 'credit', lang: 'hi' });
    expect(p.text).toBe(`+${NNBSP}${RUPEE}340`);
    expect(p.label).toBe('plus 340 rupaye, udhaar');
    expect(amountParts(340, { kind: 'credit', lang: 'en' }).label).toBe('plus 340 rupees, credit');
  });

  test('payment uses the real minus sign U+2212, never a hyphen', () => {
    const p = amountParts(200, { kind: 'payment', lang: 'hi' });
    expect(p.sign).toBe('−');
    expect(p.text).toBe(`${MINUS}${NNBSP}${RUPEE}200`);
    expect(p.text.includes('-')).toBe(false);
    expect(p.label).toBe('minus 200 rupaye, jama');
  });

  test('no kind: sign only for negative values; sign none shows the absolute value', () => {
    expect(amountParts(18460).text).toBe(`${RUPEE}18,460`);
    expect(amountParts(-560).text).toBe(`${MINUS}${NNBSP}${RUPEE}560`);
    expect(amountParts(-560, { sign: 'none' }).text).toBe(`${RUPEE}560`);
    expect(amountParts(100000, { lang: 'en' }).label).toBe('100000 rupees');
  });

  test('values are rounded to whole rupees', () => {
    expect(amountParts(339.6).digits).toBe('340');
    expect(amountParts(Number.NaN).digits).toBe('0');
  });
});

describe('<Amount>', () => {
  test('renders the visual parts hidden from screen readers and a spoken label', () => {
    const html = renderToStaticMarkup(createElement(Amount, { value: 1250, kind: 'credit', lang: 'hi', size: 'md' }));
    expect(html).toContain('class="amount text-amount');
    expect(html).toContain('<span aria-hidden="true">+ <span class="amount-symbol">₹</span><span class="amount-digits">1,250</span></span>');
    expect(html).toContain('<span class="sr-only">plus 1250 rupaye, udhaar</span>');
  });

  test('tone colours by kind only when asked', () => {
    expect(renderToStaticMarkup(createElement(Amount, { value: 5, kind: 'payment', tone: true, lang: 'en' }))).toContain('text-payment');
    expect(renderToStaticMarkup(createElement(Amount, { value: 5, kind: 'payment', lang: 'en' }))).not.toContain('text-payment');
  });
});

describe('dates and names', () => {
  test('dayLabel', () => {
    expect(dayLabel('2026-11-21', '2026-11-21')).toBe('Aaj');
    expect(dayLabel('2026-11-20', '2026-11-21')).toBe('Kal');
    expect(dayLabel('2026-11-20', '2026-11-21', 'en')).toBe('Yesterday');
    expect(dayLabel('2026-11-19', '2026-11-21')).toBe('Parso');
    expect(dayLabel('2026-02-28', '2026-03-01')).toBe('Kal');
    expect(dayLabel('2026-10-01', '2026-11-21')).toMatch(/1 Oct/);
    expect(dayLabel('', '2026-11-21')).toBe('');
  });

  test('entryWhen: every entry shows its date and the time it was written', () => {
    const now = new Date(2026, 10, 21, 12, 0);
    const at = (d: number, h: number, m = 0) => new Date(2026, 10, d, h, m).toISOString();
    expect(entryWhen({ date: '2026-11-21', ts: at(21, 11, 42) }, now)).toBe('Aaj, 21 Nov · 11:42');
    expect(entryWhen({ date: '2026-11-20', ts: at(20, 18, 5) }, now)).toBe('Kal, 20 Nov · 18:05');
    expect(entryWhen({ date: '2026-11-19', ts: at(19, 9, 3) }, now, 'en')).toBe('Day before, 19 Nov · 09:03');
    expect(entryWhen({ date: '2026-11-10', ts: at(10, 9, 12) }, now)).toBe('10 Nov · 09:12');
    // said today about yesterday ("kal 200 diya tha"): that day, and when it was written
    expect(entryWhen({ date: '2026-11-20', ts: at(21, 11, 42) }, now)).toBe('Kal, 20 Nov · likha Aaj 11:42');
    expect(entryWhen({ date: '2026-11-21', ts: 'bad' }, now, 'en')).toBe('Today, 21 Nov');
  });

  test('stamp: date and time of any moment', () => {
    const now = new Date(2026, 10, 21, 12, 0);
    expect(stamp(new Date(2026, 10, 21, 11, 59, 40).toISOString(), now)).toBe('Aaj, 21 Nov · 11:59');
    expect(stamp(new Date(2026, 10, 2, 7, 5).toISOString(), now, 'en')).toBe('2 Nov · 07:05');
    expect(stamp('bad', now)).toBe('');
  });

  test('sinceLabel and longDate', () => {
    const now = new Date(2026, 10, 21, 12, 0);
    expect(sinceLabel(new Date(2026, 10, 21, 11, 59, 40).toISOString(), now)).toBe('abhi');
    expect(sinceLabel(new Date(2026, 10, 21, 11, 55).toISOString(), now)).toBe('5 min');
    expect(sinceLabel(new Date(2026, 10, 21, 10, 20).toISOString(), now)).toBe('10:20');
    expect(sinceLabel(new Date(2026, 10, 21, 11, 59, 40).toISOString(), now, 'en')).toBe('now');
    expect(longDate(now)).toBe('Shanivaar, 21 November');
    expect(longDate(now, 'en')).toBe('Saturday, 21 November');
  });

  test('splitVolatile keeps the last word apart; replySegments finds ₹ amounts', () => {
    expect(splitVolatile('Sunita ne paanch sau diye')).toEqual(['Sunita ne paanch sau ', 'diye']);
    expect(splitVolatile('Sunita')).toEqual(['', 'Sunita']);
    expect(splitVolatile('')).toEqual(['', '']);
    expect(replySegments('Ramesh ka ab ₹770 baaki hai.')).toEqual([
      { text: 'Ramesh ka ab ', amount: false },
      { text: '₹770', amount: true },
      { text: ' baaki hai.', amount: false },
    ]);
    expect(replySegments('₹1,500 ya ₹15,000?').filter((x) => x.amount).map((x) => x.text)).toEqual(['₹1,500', '₹15,000']);
  });

  test('customerName and initial', () => {
    expect(customerName({ display: 'Ramesh', tags: ['chai wale'] })).toBe('Ramesh · Chai wale');
    expect(customerName({ display: 'Sunita', tags: [] })).toBe('Sunita');
    expect(initial('ramesh')).toBe('R');
    expect(initial('रमेश')).toBe('र');
    expect(initial('ರಮೇಶ್')).toBe('ರ');
    expect(initial('  ')).toBe('?');
  });
});
