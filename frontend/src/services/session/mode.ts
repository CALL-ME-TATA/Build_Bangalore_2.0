// The one place that decides whether the app talks to the real server or to the scripted mock.
// Order: `?mock=1` / `?mock=0` in the page URL, then VITE_SESSION=mock at build or dev time, else the server.
export type SessionMode = 'ws' | 'mock';

export function resolveMode(search: string, env: string | undefined): SessionMode {
  const q = new URLSearchParams(search).get('mock');
  if (q === '1' || q === 'true') return 'mock';
  if (q === '0' || q === 'false') return 'ws';
  return env === 'mock' ? 'mock' : 'ws';
}

let cached: SessionMode | null = null;

export function sessionMode(): SessionMode {
  if (cached) return cached;
  const search = typeof location === 'undefined' ? '' : location.search;
  cached = resolveMode(search, import.meta.env.VITE_SESSION as string | undefined);
  return cached;
}
