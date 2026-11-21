// Labels: both languages have every key, nothing is empty, and the language switch follows the server rule.
import { expect, test } from 'vitest';
import { LANGS, labels, normalizeLang, t } from './i18n';

test('every label exists and is non-empty in hi and en', () => {
  const hiKeys = Object.keys(labels('hi')).sort();
  const enKeys = Object.keys(labels('en')).sort();
  expect(enKeys).toEqual(hiKeys);
  for (const lang of LANGS) {
    for (const [k, v] of Object.entries(labels(lang))) expect(v.trim(), `${lang}.${k}`).not.toBe('');
  }
});

test('Hindi labels are Hinglish in Latin letters (no Devanagari in fixed labels)', () => {
  for (const v of Object.values(labels('hi'))) expect(/[ऀ-ॿ]/.test(v)).toBe(false);
});

test('the AI disclosure is present in both languages', () => {
  expect(t('hi', 'disclosure')).toMatch(/AI sahayak/);
  expect(t('en', 'disclosure')).toMatch(/AI assistant/);
});

test('normalizeLang: anything but "en" is Hindi / Hinglish', () => {
  expect(normalizeLang('en')).toBe('en');
  expect(normalizeLang('hi')).toBe('hi');
  expect(normalizeLang('kn')).toBe('hi');
  expect(normalizeLang(undefined)).toBe('hi');
});

test('fixed labels never use a dollar sign', () => {
  for (const lang of LANGS) for (const v of Object.values(labels(lang))) expect(v.includes('$')).toBe(false);
});

test('mic labels follow the design board', () => {
  expect(t('hi', 'micIdle')).toBe('Dabaa kar boliye');
  expect(t('hi', 'micListening')).toBe('Sun raha hoon… chhodne par save hoga');
  expect(t('hi', 'micProcessing')).toBe('Samajh raha hoon…');
  expect(t('hi', 'micSpeaking')).toBe('Bol raha hoon…');
  expect(t('hi', 'micAriaIdle')).toBe('Bolna shuru karein');
});
