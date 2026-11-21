// Spoken language of the session when it is not Hindi or English: Kannada, Marathi or Tamil. The server
// translates through the LLM and replies in that language; the page's labels stay English.
// The choice is remembered in this browser until the shopkeeper picks another language (null = Hindi or English,
// which the settings store remembers).
export type VoiceLang = 'kn' | 'mr' | 'ta';

const KEY = 'kv-voice-lang';

function load(): VoiceLang | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'kn' || v === 'mr' || v === 'ta' ? v : null;
  } catch {
    return null; // private window or blocked storage: not remembered, still works
  }
}

let voice: VoiceLang | null = load();

export function setVoiceLang(v: VoiceLang | null): void {
  voice = v;
  try {
    if (v) localStorage.setItem(KEY, v);
    else localStorage.removeItem(KEY);
  } catch {
    /* not remembered */
  }
}

export function voiceLang(): VoiceLang | null {
  return voice;
}
