// Why the microphone is not available, from what the browser reports. HTTPS is blamed only when the page really
// is on an insecure origin (window.isSecureContext false); localhost and HTTPS pages get the real reason.
import type { MicStatus } from './types';

/** navigator.mediaDevices.getUserMedia is missing. */
export function micUnavailable(secure: boolean | undefined): MicStatus {
  return secure === false ? 'insecure' : 'nodevice';
}

/** getUserMedia (or the worklet set-up) threw. */
export function micError(err: unknown, secure: boolean | undefined): MicStatus {
  const name = err instanceof Error || (typeof err === 'object' && err !== null && 'name' in err) ? String((err as { name: unknown }).name) : '';
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError' || name === 'SecurityError') return secure === false ? 'insecure' : 'denied';
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || name === 'OverconstrainedError' || name === 'NotReadableError') return 'nodevice';
  return 'failed';
}
