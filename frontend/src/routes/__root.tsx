// Root layout: skip link, live regions, navigation (bottom tabs below 1024px, the rail above), the floating
// mic link to Bolo on the other screens (60px, as on the Khata board), the doubt sheet and the update prompt.
// Each screen renders its own header, <main id="main"> and one h1 (the Bolo header lives in the Bolo screen).
import { createRootRoute, Link, Outlet, useRouterState } from '@tanstack/react-router';
import { Mic } from 'lucide-react';
import { lazy, Suspense, useEffect } from 'react';
import { labels } from '../i18n';
import { SkipLink } from '../components/SkipLink';
import { LiveRegion } from '../components/LiveRegion';
import { BottomTabs } from '../components/BottomTabs';
import { SideRail } from '../components/SideRail';
import { useAnnouncements } from '../hooks/useAnnouncements';
import { useRefreshOnResult } from '../services/query';
import { useDoubtSync } from '../state/doubt';
import { applySettings, useSettings } from '../state/settings';
import { session, useSession } from '../state/session';

const DoubtSheet = lazy(() => import('../features/bolo/DoubtSheet'));
const Toaster = lazy(() => import('../components/Toaster'));
const UpdatePrompt = lazy(() => import('../layout/UpdatePrompt'));

export const Route = createRootRoute({ component: RootLayout });

function useApplySettings() {
  const textSize = useSettings((s) => s.textSize);
  const theme = useSettings((s) => s.theme);
  const highContrast = useSettings((s) => s.highContrast);
  const language = useSettings((s) => s.language);
  const voiceSpeed = useSettings((s) => s.voiceSpeed);
  const privateMode = useSettings((s) => s.privateMode);
  const lang = useSession((s) => s.lang);
  useEffect(() => applySettings({ textSize, theme, highContrast, language: lang }), [textSize, theme, highContrast, lang]);
  useEffect(() => session.setVoiceSpeed(voiceSpeed), [voiceSpeed]);
  // hello.private on the next connection; a `settings` message when changed inside a session.
  useEffect(() => session.setPrivate(privateMode), [privateMode]);
  useEffect(() => {
    // Warm the session chunk after first paint so the start tap does not wait for it.
    const id = setTimeout(() => session.preload(), 1500);
    return () => clearTimeout(id);
  }, []);
  useEffect(() => {
    session.setLang(language);
    if (!useSession.getState().started) useSession.getState().dispatch({ type: 'set_lang', lang: language });
  }, [language]);
}

function RootLayout() {
  useApplySettings();
  useRefreshOnResult();
  useDoubtSync();
  useAnnouncements();
  const lang = useSession((s) => s.lang);
  // The sheet (and vaul) load after the start tap, off the first-paint path, and then stay mounted
  // so its close animation and focus return run.
  const started = useSession((s) => s.started);
  const path = useRouterState({ select: (s) => s.location.pathname });
  const L = labels(lang);
  const onBolo = path === '/';

  return (
    <>
      <SkipLink label={L.skipToContent} />
      <LiveRegion />
      <div className="mx-auto flex min-h-dvh w-full max-w-shell">
        <SideRail className="hidden lg:flex" />
        <div className="flex min-w-0 flex-1 flex-col">
          <Outlet />
        </div>
      </div>
      {!onBolo ? (
        <Link
          to="/"
          id="mic-mini"
          aria-label={L.miniMic}
          className="mic fixed end-5 bottom-[calc(var(--spacing-tabs)+env(safe-area-inset-bottom)+1rem)] z-20 size-mic-sm lg:end-8 lg:bottom-8"
        >
          <Mic aria-hidden="true" size={24} strokeWidth={1.9} />
        </Link>
      ) : null}
      <BottomTabs className="lg:hidden" />
      <Suspense fallback={null}>
        {started ? <DoubtSheet /> : null}
        <Toaster />
        <UpdatePrompt />
      </Suspense>
    </>
  );
}
