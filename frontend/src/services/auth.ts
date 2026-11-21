// Google sign-in state (server/app/auth.py). The server does the OAuth flow and keeps the user in an HttpOnly
// cookie; the page only asks who is signed in and links to the login and logout endpoints.
import { useQuery } from '@tanstack/react-query';
import { sessionMode } from './session/mode';

export interface AuthUser {
  email: string;
  name: string;
  picture: string;
}

export interface AuthState {
  /** Google sign-in is configured on the server: the khata needs a signed-in, allowed user. */
  enabled: boolean;
  user: AuthUser | null;
}

export const LOGIN_URL = '/api/auth/google/login';

const OPEN: AuthState = { enabled: false, user: null };

export async function fetchAuth(): Promise<AuthState> {
  if (sessionMode() === 'mock') return OPEN; // the scripted demo has no server
  try {
    const r = await fetch('/api/auth/me', { credentials: 'same-origin' });
    if (!r.ok) return OPEN; // an older server without sign-in
    return (await r.json()) as AuthState;
  } catch {
    return OPEN; // offline: the cached app shell still opens; the server refuses data without a sign-in
  }
}

export function useAuth() {
  return useQuery({ queryKey: ['auth'], queryFn: fetchAuth, staleTime: 60_000 });
}

export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  location.hash = '#/welcome';
  location.reload();
}
