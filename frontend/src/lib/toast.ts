// Shows a toast; sonner is loaded on first use so it stays out of the initial download.
import type { ExternalToast } from 'sonner';

export async function toast(message: string, options?: ExternalToast): Promise<void> {
  const { toast: show } = await import('sonner');
  show(message, options);
}
