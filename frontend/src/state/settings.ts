// User settings, persisted in localStorage under "khatavaani.settings".
// Applied to <html> by applySettings() (data attributes read by src/styles/app.css).
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Lang } from '../i18n';
import type { MicMode } from '../lib/mic';

export type TextSize = 'normal' | 'large' | 'xlarge';
export type Theme = 'system' | 'light' | 'dark';

export interface Settings {
  language: Lang;
  textSize: TextSize;
  theme: Theme;
  highContrast: boolean;
  /** Playback rate of the spoken reply, 0.8 to 1.25. */
  voiceSpeed: number;
  shopName: string;
  micMode: MicMode;
  /** Private mode: answers about balances are shown on screen and not spoken (hello.private, contract 3.3). */
  privateMode: boolean;
}

export interface SettingsStore extends Settings {
  set<K extends keyof Settings>(key: K, value: Settings[K]): void;
  reset(): void;
}

export const defaultSettings: Settings = {
  language: 'hi',
  textSize: 'normal',
  theme: 'system',
  highContrast: false,
  voiceSpeed: 1,
  shopName: 'Meri Dukaan',
  micMode: 'hold',
  privateMode: false,
};

export const useSettings = create<SettingsStore>()(
  persist(
    (set) => ({
      ...defaultSettings,
      set: (key, value) => set({ [key]: value } as Partial<Settings>),
      reset: () => set({ ...defaultSettings }),
    }),
    {
      name: 'khatavaani.settings',
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (s): Settings => ({
        language: s.language,
        textSize: s.textSize,
        theme: s.theme,
        highContrast: s.highContrast,
        voiceSpeed: s.voiceSpeed,
        shopName: s.shopName,
        micMode: s.micMode,
        privateMode: s.privateMode,
      }),
    },
  ),
);

/** Writes the display settings onto the root element as data attributes. */
export function applySettings(s: Pick<Settings, 'textSize' | 'theme' | 'highContrast' | 'language'>, root: HTMLElement = document.documentElement): void {
  root.dataset.text = s.textSize;
  root.dataset.theme = s.theme;
  if (s.highContrast) root.dataset.contrast = 'more';
  else delete root.dataset.contrast;
  root.lang = s.language === 'en' ? 'en' : 'hi';
}
