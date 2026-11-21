// Desktop navigation (>= 1024px), as drawn: a 232px rail with the logo in Spectral 22/600, the four
// destinations (15px; the active one on the tint surface at weight 600), and the shop name with
// "Encrypted · Online" at the bottom.
import { Link } from '@tanstack/react-router';
import { labels } from '../i18n';
import { useLang } from '../hooks/useLabels';
import { useSettings } from '../state/settings';
import { StatusBadge } from './StatusBadge';
import { LanguageSwitcher } from './LanguageSwitcher';
import { NAV_ITEMS } from './nav';

export function SideRail({ className = '' }: { className?: string }) {
  const L = labels(useLang());
  const shopName = useSettings((s) => s.shopName);
  return (
    <aside className={`sticky top-0 h-dvh w-rail shrink-0 flex-col gap-8 border-e border-line px-5 py-8 ${className}`}>
      <p className="px-3 font-display text-[1.375rem] leading-tight font-semibold tracking-[-0.01em] text-ink">{L.appName}</p>
      <nav aria-label={L.navLabel}>
        <ul className="flex flex-col gap-1">
          {NAV_ITEMS.map(({ to, labelKey, icon: Icon, exact }) => (
            <li key={to}>
              <Link
                to={to}
                activeOptions={{ exact: Boolean(exact) }}
                className="flex min-h-12 items-center gap-3 rounded-nav px-3 text-label-sm text-ink-2 hover:text-ink aria-[current=page]:bg-tint aria-[current=page]:font-semibold aria-[current=page]:text-ink"
              >
                <Icon aria-hidden="true" size={20} strokeWidth={1.7} />
                <span>{L[labelKey]}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <LanguageSwitcher />
      <div className="mt-auto flex flex-col gap-1 px-3">
        <p className="text-small font-semibold text-ink">{shopName}</p>
        <StatusBadge variant="inline" />
      </div>
    </aside>
  );
}
