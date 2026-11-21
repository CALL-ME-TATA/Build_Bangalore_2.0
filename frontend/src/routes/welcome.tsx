// "#/welcome": the landing page. `?login=not_allowed|failed` comes back from the Google sign-in callback.
import { createFileRoute } from '@tanstack/react-router';
import { WelcomeScreen } from '../features/welcome/WelcomeScreen';

export const Route = createFileRoute('/welcome')({
  validateSearch: (s: Record<string, unknown>): { login?: string } => (typeof s.login === 'string' ? { login: s.login } : {}),
  component: function Welcome() {
    const { login } = Route.useSearch();
    return <WelcomeScreen login={login} />;
  },
});
