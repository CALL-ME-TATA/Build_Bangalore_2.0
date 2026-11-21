// Online / offline status with an icon and a word (never colour alone). When the browser is online but the
// session socket is (re)connecting, that is shown instead.
//  - variant "pill" (mobile Bolo header): outlined pill, 13px; "Online" in the payment green
//  - variant "inline" (desktop rail): "Encrypted · Online" with a lock, 13px ink-2
import { Lock, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { useOnline } from '../hooks/useOnline';
import { useLabels } from '../hooks/useLabels';
import { useSession } from '../state/session';

export function useConnectionStatus() {
  const online = useOnline();
  const conn = useSession((s) => s.conn);
  const L = useLabels();
  const reconnecting = online && (conn === 'reconnecting' || conn === 'connecting');
  const state: 'online' | 'offline' | 'connecting' = !online ? 'offline' : reconnecting ? 'connecting' : 'online';
  const text = state === 'offline' ? L.offline : state === 'connecting' ? (conn === 'connecting' ? L.connecting : L.reconnecting) : L.online;
  return { state, text, encrypted: L.encryptedShort };
}

export function StatusBadge({ variant = 'pill', className = '' }: { variant?: 'pill' | 'inline'; className?: string }) {
  const { state, text, encrypted } = useConnectionStatus();
  if (variant === 'inline') {
    return (
      <span className={`flex items-center gap-1.5 text-meta text-ink-2 ${className}`}>
        <Lock aria-hidden="true" size={13} strokeWidth={1.8} />
        <span>
          {encrypted} · {text}
        </span>
      </span>
    );
  }
  const Icon = state === 'offline' ? WifiOff : state === 'connecting' ? RefreshCw : Wifi;
  const tone = state === 'online' ? 'text-payment' : state === 'offline' ? 'font-medium text-ink' : 'text-ink-2';
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2.5 py-1.5 text-meta ${tone} ${className}`}>
      <Icon aria-hidden="true" size={14} strokeWidth={1.8} />
      <span>{text}</span>
    </span>
  );
}
