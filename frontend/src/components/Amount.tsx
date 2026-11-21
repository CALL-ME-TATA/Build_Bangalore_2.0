// The one way to show money. Spectral with tabular lining figures, Indian grouping, sign first then ₹ then
// digits ("+ ₹340" udhaar, "− ₹200" jama), a real minus sign and a narrow no-break space after the sign.
// The ₹ is 0.75em at weight 400 next to weight-500 digits. Screen readers hear "plus 340 rupees, udhaar".
import type { Lang } from '../i18n';
import { amountParts, kindTone, NNBSP, RUPEE, type AmountKind, type SignMode } from '../lib/format';
import { useLang } from '../hooks/useLabels';

export type AmountSize = 'hero' | 'title' | 'question' | 'total' | 'lg' | 'md' | 'inherit';

const SIZE: Record<AmountSize, string> = {
  hero: 'text-hero',
  title: 'text-title',
  question: 'text-question',
  total: 'text-total',
  lg: 'text-amount-lg',
  md: 'text-amount',
  inherit: '',
};

export interface AmountProps {
  /** Whole rupees. */
  value: number;
  /** credit adds "+" and "udhaar" to the spoken label; payment adds "−" and "jama". */
  kind?: AmountKind;
  /** 'kind' (default with kind), 'auto' (default without: "−" only when negative), 'none'. */
  sign?: SignMode;
  size?: AmountSize;
  /** Colour the amount with the ledger ink of its kind (text still carries the sign and the word). */
  tone?: boolean;
  /** Label language; defaults to the session language. */
  lang?: Lang;
  className?: string;
}

export function Amount({ value, kind, sign, size = 'md', tone = false, lang, className = '' }: AmountProps) {
  const sessionLang = useLang();
  const p = amountParts(value, { kind, sign, lang: lang ?? sessionLang });
  const color = tone && kind ? kindTone(kind) : '';
  return (
    <span className={`amount ${SIZE[size]} ${color} ${className}`}>
      <span aria-hidden="true">
        {p.sign ? p.sign + NNBSP : ''}
        <span className="amount-symbol">{RUPEE}</span>
        <span className="amount-digits">{p.digits}</span>
      </span>
      <span className="sr-only">{p.label}</span>
    </span>
  );
}
