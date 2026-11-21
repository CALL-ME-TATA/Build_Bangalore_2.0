// Bolo header on phones and tablets (banner landmark): the shop name as the screen's h1 (17px, 600), the lock
// line "Encrypted on device" under it, and the online status pill on the right. Desktop shows the rail and
// the "Bolo" title instead, so this header is hidden there.
import { Lock } from 'lucide-react';
import { useLabels } from '../hooks/useLabels';
import { useSettings } from '../state/settings';
import { StatusBadge } from '../components/StatusBadge';

export function AppHeader({ className = '' }: { className?: string }) {
  const L = useLabels();
  const shopName = useSettings((s) => s.shopName);
  return (
    <header className={`pt-safe ${className}`}>
      <div className="flex items-start justify-between gap-4 px-6 pt-7 pb-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-head text-ink">{shopName}</h1>
          <p className="flex items-center gap-1.5 text-meta text-ink-2">
            <Lock aria-hidden="true" size={13} strokeWidth={1.8} />
            <span>{L.encrypted}</span>
          </p>
        </div>
        <StatusBadge variant="pill" />
      </div>
    </header>
  );
}
