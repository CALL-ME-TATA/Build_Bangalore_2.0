// Spoken language of the session when it is not Hindi or English: Kannada, Marathi or Tamil. The server
// translates through the LLM and replies in that language; the page's labels stay English.
export type VoiceLang = 'kn' | 'mr' | 'ta';

let voice: VoiceLang | null = null;

export function setVoiceLang(v: VoiceLang | null): void {
  voice = v;
}

export function voiceLang(): VoiceLang | null {
  return voice;
}
