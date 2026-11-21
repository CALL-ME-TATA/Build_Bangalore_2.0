// Tap answers for every question type (docs/CONTRACT.md 1.9, 1.14, 3.3, 5.1). Each tap answer must be a word
// the parser accepts for that pending reason.
import { describe, expect, test } from 'vitest';
import { doubtOptions, doubtSpec } from './doubt';
import { numberWords } from './numberWords';
import type { Candidate } from '../services/session/types';

const spec = (reason: string | null, question: string, extra: { candidates?: Candidate[]; confirm?: { type: string }; lang?: 'hi' | 'en' } = {}) =>
  doubtSpec({ reason, question, candidates: extra.candidates, confirm: extra.confirm, lang: extra.lang ?? 'hi' });
const answers = (reason: string | null, q: string, extra = {}) => spec(reason, q, extra).options.map((o) => o.answer);
const labelsOf = (reason: string | null, q: string, extra = {}) => spec(reason, q, extra).options.map((o) => o.label);

describe('choices', () => {
  test('confusable_number: candidates first, sent as plain numbers', () => {
    const s = spec('confusable_number', '₹340 ya ₹740?', { candidates: [340, 740] });
    expect(s.kind).toBe('choice');
    expect(s.options.map((x) => [x.amount, x.answer])).toEqual([
      [340, '340'],
      [740, '740'],
    ]);
  });

  test('confusable_number without candidates reads the ₹ amounts, also after the disclosure prefix', () => {
    expect(answers('confusable_number', '₹1,500 or ₹15,000?', { lang: 'en' })).toEqual(['1500', '15000']);
    expect(answers('confusable_number', 'Namaste! Main KhataVaani hoon, ek AI sahayak. ₹60 ya ₹16?')).toEqual(['60', '16']);
    expect(spec('confusable_number', '₹340?').options).toEqual([]);
  });

  test('same_name: one button per customer; the tag is the answer, else the ordinal', () => {
    const candidates = [
      { id: 'c1', display: 'Ramesh', tags: ['chai wale'] },
      { id: 'c2', display: 'Ramesh', tags: [] },
    ];
    const s = spec('same_name', 'Kaunse Ramesh: chai wale ya pehle wale?', { candidates });
    expect(s.options.map((o) => [o.label, o.sub, o.answer])).toEqual([
      ['Ramesh', 'Chai wale', 'chai wale'],
      ['Ramesh', undefined, 'doosra'],
    ]);
  });

  test('same_name without candidates: the options after the colon', () => {
    expect(answers('same_name', 'Kaunse Ramesh: chai wale ya gali number 3?')).toEqual(['chai wale', 'gali number 3']);
    expect(labelsOf('same_name', 'Kaunse Ramesh: chai wale ya gali number 3?')).toEqual(['Chai wale', 'Gali number 3']);
    expect(answers('same_name', 'Which Ramesh: chai wale or the first one?', { lang: 'en' })).toEqual(['chai wale', 'the first one']);
    expect(spec('same_name', 'Kaunse Ramesh?').options).toEqual([]);
  });

  test('unclear_correction with candidates: one button per entry, answered with the old amount', () => {
    const candidates = [
      { id: 7, kind: 'credit' as const, amount: 340, customer: 'Ramesh' },
      { id: 8, kind: 'payment' as const, amount: 200, customer: { display: 'Sunita' } },
    ];
    const s = spec('unclear_correction', 'Kaunsi entry: ₹340 udhaar ya ₹200 jama?', { candidates });
    expect(s.kind).toBe('choice');
    expect(s.options.map((o) => [o.amount, o.kind, o.sub, o.answer])).toEqual([
      [340, 'credit', 'Ramesh', '340'],
      [200, 'payment', 'Sunita', '200'],
    ]);
  });

  test('unclear_correction with two equal amounts answers pehli / doosri', () => {
    const candidates = [
      { kind: 'credit' as const, amount: 100, customer: 'Ramesh' },
      { kind: 'payment' as const, amount: 100, customer: 'Ramesh' },
    ];
    expect(answers('unclear_correction', 'Kaunsi entry?', { candidates })).toEqual(['pehli', 'doosri']);
  });

  test('unclear_correction without candidates reads "₹a udhaar ya ₹b jama" from the text', () => {
    const s = spec('unclear_correction', 'Kaunsi entry: ₹340 udhaar ya ₹200 jama?');
    expect(s.options.map((o) => [o.amount, o.kind, o.answer])).toEqual([
      [340, 'credit', '340'],
      [200, 'payment', '200'],
    ]);
  });

  test('new_customer with candidates: one button per close customer plus "Naya grahak"', () => {
    const s = spec('new_customer', 'Rakesh naya grahak hai, ya Ramesh?', { candidates: [{ id: 'c1', display: 'Ramesh', tags: ['chai wale'] }] });
    expect(s.kind).toBe('choice');
    expect(s.options.map((o) => [o.label, o.answer])).toEqual([
      ['Ramesh', 'pehla'],
      ['Naya grahak', 'naya'],
    ]);
    const two = spec('new_customer', 'Rakesh naya grahak hai, ya Ramesh ya Rajesh?', {
      candidates: [
        { id: 'c1', display: 'Ramesh' },
        { id: 'c2', display: 'Rajesh' },
      ],
      lang: 'en',
    });
    expect(two.options.map((o) => o.answer)).toEqual(['pehla', 'doosra', 'naya']);
    expect(labelsOf('new_customer', 'Is Rakesh a new customer, or Ramesh?', { candidates: [{ id: 'c1', display: 'Ramesh' }], lang: 'en' })).toEqual([
      'Ramesh',
      'New customer',
    ]);
  });
});

describe('yes / no', () => {
  test('plausibility: Haan / Nahi (Yes / No), always sending haan / nahi', () => {
    expect(spec('plausibility', '₹5,00,000, pakka?').kind).toBe('yesno');
    expect(labelsOf('plausibility', '₹5,00,000, pakka?')).toEqual(['Haan', 'Nahi']);
    expect(labelsOf('plausibility', '₹5,00,000, are you sure?', { lang: 'en' })).toEqual(['Yes', 'No']);
    expect(answers('plausibility', '₹5,00,000, are you sure?', { lang: 'en' })).toEqual(['haan', 'nahi']);
  });

  test.each([
    ['computed', 'Ramesh ke ₹300 udhaar likhun?'],
    ['settle', 'Ramesh ke ₹770 baaki hain. Poore jama likhun?'],
    ['half', 'Aadha yaani ₹385. Ramesh se jama likhun?'],
    ['writeoff', 'Ramesh ke ₹770 baaki hain. Poore maaf karun?'],
    ['roundoff', 'Ramesh ke ₹773 baaki hain. ₹3 chhod doon?'],
    ['overpayment', 'Ramesh ke sirf ₹200 baaki hain. ₹500 hi likhun?'],
    ['duplicate', 'Yeh entry abhi likhi hai. Ek aur likhun?'],
    ['hearsay', 'Ramesh se ₹200 jama likhun?'],
    ['reminder', 'Ramesh ke ₹340 baaki hain, ₹850 nahi. ₹340 ka reminder banaun?'],
  ])('confirm_entry %s: Haan / Nahi', (type, q) => {
    const s = spec('confirm_entry', q, { confirm: { type } });
    expect(s.kind).toBe('yesno');
    expect(s.options.map((o) => o.answer)).toEqual(['haan', 'nahi']);
  });

  test('new_customer without candidates: Haan / Nahi', () => {
    expect(answers('new_customer', 'Rakesh naya grahak hai. Khata banaun?')).toEqual(['haan', 'nahi']);
    expect(answers('new_customer', 'Rakesh is a new customer. Open an account?', { candidates: [], lang: 'en' })).toEqual(['haan', 'nahi']);
  });

  test('yes / no endings without a matching reason', () => {
    expect(answers('unclear_correction', 'Sirf pichli entry hata sakta hoon: Ramesh, ₹20 udhaar. Hata doon?')).toEqual(['haan', 'nahi']);
    expect(answers('unclear_correction', 'Pichli entry hata kar yeh likhoon?')).toEqual(['haan', 'nahi']);
    expect(answers('unclear_correction', 'Replace the last entry with this one?', { lang: 'en' })).toEqual(['haan', 'nahi']);
  });
});

describe('open questions', () => {
  test('ambiguous_direction: Udhaar diya / Paise aaye', () => {
    const s = spec('ambiguous_direction', 'Ramesh ne diye, ya Ramesh ko udhaar?');
    expect(s.options.map((o) => [o.label, o.answer])).toEqual([
      ['Udhaar diya', 'udhaar'],
      ['Paise aaye', 'jama'],
    ]);
    expect(labelsOf('ambiguous_direction', 'Did Ramesh pay, or did Ramesh take credit?', { lang: 'en' })).toEqual(['Gave credit', 'Money received']);
    expect(s.typeBox).toBe(false);
  });

  test('unclear_date: Aaj / Kal / Parso', () => {
    const s = spec('unclear_date', 'Kaunsa din? Aaj, kal ya parso boliye.');
    expect(s.options.map((o) => [o.label, o.answer])).toEqual([
      ['Aaj', 'aaj'],
      ['Kal', 'kal'],
      ['Parso', 'parso'],
    ]);
  });

  test('missing amount, missing customer and unknown reasons: no buttons, the talk control and the type box', () => {
    for (const [reason, q] of [
      ['missing_amount', 'Kitne rupaye?'],
      ['missing_amount', 'Ramesh ka kya likhun?'],
      ['missing_customer', 'Whose account?'],
      ['unclear_correction', 'Sahi amount boliye, ya hata do boliye.'],
      [null, 'Kis baare mein?'],
    ] as const) {
      const s = spec(reason, q);
      expect(s.options).toEqual([]);
      expect(s.typeBox).toBe(true);
    }
  });

  test('doubtOptions is the options list of doubtSpec', () => {
    expect(doubtOptions('plausibility', '₹5,00,000, pakka?', 'hi').map((o) => o.answer)).toEqual(['haan', 'nahi']);
  });
});

describe('numberWords', () => {
  test('Hindi in Latin letters with Indian place values', () => {
    expect(numberWords(340)).toBe('teen sau chaalis');
    expect(numberWords(740)).toBe('saat sau chaalis');
    expect(numberWords(85)).toBe('pachaasi');
    expect(numberWords(1250)).toBe('ek hazaar do sau pachaas');
    expect(numberWords(100000)).toBe('ek lakh');
    expect(numberWords(500000)).toBe('paanch lakh');
    expect(numberWords(0)).toBe('shunya');
  });

  test('English', () => {
    expect(numberWords(340, 'en')).toBe('three hundred forty');
    expect(numberWords(1250, 'en')).toBe('one thousand two hundred fifty');
    expect(numberWords(125000, 'en')).toBe('one lakh twenty-five thousand');
    expect(numberWords(5, 'en')).toBe('five');
  });
});

describe('contract 3.4 / 1.18 sheet points', () => {
  test('same_name with three customers: three buttons sending pehla / doosra / teesra', () => {
    const candidates = [
      { id: 'c1', display: 'Ramesh', tags: ['chai wale'] },
      { id: 'c2', display: 'Ramesh', tags: ['gali 3'] },
      { id: 'c3', display: 'Ramesh', tags: [] },
    ];
    const s = spec('same_name', 'Kaunse Ramesh: chai wale, gali 3 ya bina tag wale?', { candidates });
    expect(s.options.map((o) => [o.label, o.sub, o.answer])).toEqual([
      ['Ramesh', 'Chai wale', 'pehla'],
      ['Ramesh', 'Gali 3', 'doosra'],
      ['Ramesh', 'Bina tag wale', 'teesra'],
    ]);
    // Without candidates the three names come from the text, and the answers are still the ordinals.
    expect(answers('same_name', 'Kaunse Ramesh: chai wale, gali 3 ya bina tag wale?')).toEqual(['pehla', 'doosra', 'teesra']);
    expect(labelsOf('same_name', 'Kaunse Ramesh: chai wale, gali 3 ya bina tag wale?')).toEqual(['Chai wale', 'Gali 3', 'Bina tag wale']);
  });

  test('same_name with two customers looks and works exactly as before', () => {
    const two = spec('same_name', 'Kaunse Ramesh: chai wale ya pehle wale?', {
      candidates: [
        { id: 'c1', display: 'Ramesh', tags: ['chai wale'] },
        { id: 'c2', display: 'Ramesh', tags: [] },
      ],
    });
    expect(two.options.map((o) => [o.label, o.sub, o.answer])).toEqual([
      ['Ramesh', 'Chai wale', 'chai wale'],
      ['Ramesh', undefined, 'doosra'],
    ]);
    expect(answers('same_name', 'Kaunse Ramesh: chai wale ya gali number 3?')).toEqual(['chai wale', 'gali number 3']);
  });

  test('the longer replace check is still yes / no, and Nahi sends a plain no', () => {
    const s = spec('unclear_correction', 'Pichli entry hata kar Geeta ke ₹500 udhaar likhoon?');
    expect(s.kind).toBe('yesno');
    expect(s.options.map((o) => [o.label, o.answer])).toEqual([
      ['Haan', 'haan'],
      ['Nahi', 'nahi'],
    ]);
    // The ₹ amount in the longer wording must not turn it into an entry choice.
    expect(s.options.some((o) => o.amount != null)).toBe(false);
  });
});

describe('either/or questions keep their answers', () => {
  test('ambiguous_direction with a confirmation attached still offers udhaar / jama, not Haan / Nahi', () => {
    const spec = doubtSpec({ reason: 'ambiguous_direction', question: 'Ramesh ne diye, ya Ramesh ko udhaar?',
      confirm: { type: 'unsure', words: ['phone'] }, lang: 'hi' } as Parameters<typeof doubtSpec>[0]);
    expect(spec.options.map((o) => o.answer)).toEqual(['udhaar', 'jama']);
  });

  test('two customers whose names differ are offered by name', () => {
    const spec = doubtSpec({ reason: 'same_name', question: 'Aap kaunse Diwakar ki baat kar rahe hain: Diwakar, Diwakar Sharma ya koi aur?',
      candidates: [{ id: 5, display: 'Diwakar', tags: [] }, { id: 6, display: 'Diwakar Sharma', tags: [] }],
      lang: 'hi' } as Parameters<typeof doubtSpec>[0]);
    expect(spec.options.map((o) => [o.label, o.answer])).toEqual([['Diwakar', 'pehla'], ['Diwakar Sharma', 'doosra'], ['Koi aur', 'koi aur']]);
  });
});

describe('label for a second customer with the same name', () => {
  test('new_tag: type or say the label, or one tap for none', () => {
    const spec = doubtSpec({ reason: 'new_tag', question: "Naye Diwakar ki pehchaan boliye, jaise 'chai wale' ya 'gali 3 wale'.",
      lang: 'hi' } as Parameters<typeof doubtSpec>[0]);
    expect(spec.typeBox).toBe(true);
    expect(spec.options.map((o) => [o.label, o.answer])).toEqual([['Bina pehchaan', 'bina pehchaan']]);
  });
});
