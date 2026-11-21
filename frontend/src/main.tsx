// Entry point: styles, settings on <html> before first paint, TanStack Query, TanStack Router (hash history,
// because the server serves static files only and has no single-page fallback).
// Motion is not loaded here: see src/lib/motion.tsx for adding it inside a route chunk.
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { createHashHistory, createRouter, RouterProvider } from '@tanstack/react-router';
import './styles/app.css';
import { routeTree } from './routeTree.gen';
import { queryClient } from './services/query';
import { applySettings, useSettings } from './state/settings';

applySettings(useSettings.getState());

const router = createRouter({
  routeTree,
  history: createHashHistory(),
  defaultPreload: 'intent',
  scrollRestoration: true,
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}

const root = document.getElementById('root');
if (!root) throw new Error('#root is missing from index.html');

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
