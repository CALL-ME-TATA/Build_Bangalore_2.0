// Service worker registration and the update prompt (vite-plugin-pwa, registerType 'prompt'):
// when a new version is waiting, a toast offers "Reload"; when the app shell is cached, a short toast says so.
import { useEffect } from 'react';
import { useRegisterSW } from 'virtual:pwa-register/react';
import { useLabels } from '../hooks/useLabels';
import { toast } from '../lib/toast';

export default function UpdatePrompt() {
  const L = useLabels();
  const {
    needRefresh: [needRefresh],
    offlineReady: [offlineReady],
    updateServiceWorker,
  } = useRegisterSW();

  useEffect(() => {
    if (!needRefresh) return;
    void toast(L.updateReady, {
      duration: Infinity,
      action: { label: L.updateReload, onClick: () => void updateServiceWorker(true) },
    });
  }, [needRefresh, L, updateServiceWorker]);

  useEffect(() => {
    if (offlineReady) void toast(L.offlineReady);
  }, [offlineReady, L]);

  return null;
}
