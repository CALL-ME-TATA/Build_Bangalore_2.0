// Initial avatar: the first letter of the name on the tint surface. Decorative (the name is always shown next
// to it), so it is hidden from screen readers. Works for Devanagari and Kannada names.
import { initial } from '../lib/format';

export function Avatar({ name, size = 'md' }: { name: string; size?: 'sm' | 'md' | 'lg' }) {
  const dim = size === 'sm' ? 'size-8 text-meta' : size === 'lg' ? 'size-14 text-title-sm' : 'size-10 text-label';
  return (
    <span aria-hidden="true" className={`inline-grid shrink-0 place-items-center rounded-full bg-tint font-medium text-ink ${dim}`}>
      {initial(name)}
    </span>
  );
}
