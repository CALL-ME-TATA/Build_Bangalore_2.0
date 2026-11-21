// Bottom navigation for phones and tablets, as drawn: four columns, each at least 52px tall, 22px icons over
// 12px labels; the active tab in ink at weight 600 (and aria-current="page", set by Link), the others ink-2.
// Height is var(--spacing-tabs) plus the safe-area inset; screens pad their bottom by that amount.
import { Link } from '@tanstack/react-router';
import { labels } from '../i18n';
import { useLang } from '../hooks/useLabels';
import { NAV_ITEMS } from './nav';

export function BottomTabs({ className = '' }: { className?: string }) {
  const L = labels(useLang());
  return (
    <nav aria-label={L.navLabel} className={`fixed inset-x-0 bottom-0 z-30 border-t border-line bg-paper pb-safe ${className}`}>
      <ul className="mx-auto grid h-tabs max-w-xl grid-cols-4 px-2 pt-1.5 pb-2.5">
        {NAV_ITEMS.map(({ to, labelKey, icon: Icon, exact }) => (
          <li key={to} className="flex">
            <Link
              to={to}
              activeOptions={{ exact: Boolean(exact) }}
              className="group flex min-h-13 flex-1 flex-col items-center justify-center gap-1 rounded-control text-nav text-ink-2 aria-[current=page]:font-semibold aria-[current=page]:text-ink"
            >
              <Icon aria-hidden="true" size={22} strokeWidth={1.7} />
              <span>{L[labelKey]}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
