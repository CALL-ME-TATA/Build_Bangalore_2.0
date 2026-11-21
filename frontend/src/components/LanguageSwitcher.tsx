// Language picker for the nav: switch the spoken language at any time, also mid-conversation.
// A native <select>, so it is keyboard and screen-reader friendly and stays compact on a phone.
import { Languages } from 'lucide-react';
import { useState } from 'react';
import { switchLanguage } from '../state/session';
import { useSettings } from '../state/settings';
import { voiceLang, type VoiceLang } from '../services/session/voice';

const OPTIONS: { code: 'hi' | 'en' | VoiceLang; label: string }[] = [
  { code: 'hi', label: 'Hindi / Hinglish' },
  { code: 'en', label: 'English' },
  { code: 'kn', label: 'ಕನ್ನಡ Kannada' },
  { code: 'mr', label: 'मराठी Marathi' },
  { code: 'ta', label: 'தமிழ் Tamil' },
];

export function LanguageSwitcher({ className = '' }: { className?: string }) {
  const ui = useSettings((s) => s.language);
  const [code, setCode] = useState<string>(() => voiceLang() ?? ui);
  return (
    <label className={`flex min-h-12 items-center gap-2 rounded-nav px-3 text-label-sm text-ink-2 ${className}`}>
      <Languages aria-hidden="true" size={18} strokeWidth={1.7} className="shrink-0" />
      <span className="sr-only">Bhasha · Language</span>
      <select
        value={voiceLang() ?? code}
        onChange={(e) => {
          const next = e.target.value as 'hi' | 'en' | VoiceLang;
          setCode(next);
          switchLanguage(next);
        }}
        className="min-h-10 min-w-0 flex-1 rounded-control border border-line-strong bg-surface px-2 text-label-sm text-ink"
      >
        {OPTIONS.map((o) => (
          <option key={o.code} value={o.code}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
