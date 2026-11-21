// Buttons. One `primary` (accent) per screen at most; everything else is `secondary` (hairline) or `quiet`.
// Minimum 48px tall. Size `xl` is for the huge doubt-sheet answers.
import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'quiet';
export type ButtonSize = 'md' | 'lg' | 'xl';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Leading icon (lucide, 20px). Decorative; the text is the name. */
  icon?: ReactNode;
  block?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-on-accent shadow-none hover:brightness-95 active:brightness-90',
  secondary: 'bg-surface text-ink border border-line-strong hover:bg-tint active:bg-tint',
  quiet: 'bg-transparent text-ink underline-offset-4 hover:underline',
};

const SIZE: Record<ButtonSize, string> = {
  md: 'min-h-12 px-4 text-label gap-2',
  lg: 'min-h-14 px-5 text-label gap-3',
  xl: 'min-h-20 px-5 py-3 gap-1 flex-col text-label',
};

export function Button({ variant = 'secondary', size = 'md', icon, block = false, className = '', children, type = 'button', ref, ...rest }: ButtonProps) {
  return (
    <button
      ref={ref}
      type={type}
      className={`inline-flex items-center justify-center rounded-control font-medium transition-colors disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${block ? 'w-full' : ''} ${className}`}
      {...rest}
    >
      {icon ? <span aria-hidden="true" className="inline-flex shrink-0">{icon}</span> : null}
      {children}
    </button>
  );
}
