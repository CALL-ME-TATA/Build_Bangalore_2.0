/// <reference types="vitest/config" />
// Build and dev configuration for the KhataVaani web app.
// - Relative asset URLs (base './') so dist/ can be served from any static root.
// - Dev server proxies /api and /ws to the FastAPI backend (VITE_BACKEND, default http://127.0.0.1:8010).
// - File-based TanStack Router routes with automatic route-level code splitting.
// - PWA: offline app shell, update prompt (registerType 'prompt').
import { defineConfig, loadEnv, type Plugin } from 'vite';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import babel from '@rolldown/plugin-babel';
import tailwindcss from '@tailwindcss/vite';
import { tanstackRouter } from '@tanstack/router-plugin/vite';
import { VitePWA } from 'vite-plugin-pwa';

/** Font files preloaded from index.html: the two Latin faces used on first paint. */
const PRELOAD_FONTS = [/spectral-latin-500-normal-[\w-]+\.woff2$/, /ibm-plex-sans-latin-wght-normal-[\w-]+\.woff2$/];

/** Adds <link rel="preload"> for the hashed Latin font files after the bundle is written. */
function preloadFonts(): Plugin {
  return {
    name: 'khatavaani-preload-fonts',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(_html, ctx) {
        if (!ctx.bundle) return [];
        const files = Object.keys(ctx.bundle).filter((f) => PRELOAD_FONTS.some((re) => re.test(f)));
        return files.map((href) => ({
          tag: 'link',
          attrs: { rel: 'preload', as: 'font', type: 'font/woff2', href: `./${href}`, crossorigin: '' },
          injectTo: 'head' as const,
        }));
      },
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backend = env.VITE_BACKEND || 'http://127.0.0.1:8010';
  const testing = Boolean(process.env.VITEST);

  return {
    base: './',
    plugins: [
      tanstackRouter({ target: 'react', autoCodeSplitting: true }),
      react(),
      babel({ presets: [reactCompilerPreset()] }),
      tailwindcss(),
      preloadFonts(),
      !testing &&
        VitePWA({
          registerType: 'prompt',
          injectRegister: false,
          includeAssets: ['icon.svg'],
          manifest: {
            name: 'KhataVaani',
            short_name: 'KhataVaani',
            description: 'Voice udhaar khata for kirana shops. Bolo, aur khata likh jaata hai.',
            lang: 'hi',
            start_url: './',
            scope: './',
            display: 'standalone',
            orientation: 'portrait',
            background_color: '#FAF8F4',
            theme_color: '#FAF8F4',
            icons: [
              { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
              { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
              { src: 'icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
              { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml' },
            ],
          },
          workbox: {
            // Precache the shell and the Latin faces only; Devanagari and Kannada fonts (about 330 kB) are
            // cached the first time a name in those scripts is shown.
            globPatterns: ['**/*.{js,css,html,svg,png}', 'assets/spectral-latin-*.woff2', 'assets/ibm-plex-sans-latin-*.woff2'],
            runtimeCaching: [
              {
                urlPattern: ({ request }) => request.destination === 'font',
                handler: 'CacheFirst',
                options: { cacheName: 'khatavaani-fonts', expiration: { maxEntries: 20 } },
              },
            ],
            navigateFallback: 'index.html',
            navigateFallbackDenylist: [/^\/api\//, /^\/ws\//],
            cleanupOutdatedCaches: true,
          },
        }),
    ],
    server: {
      port: 5173,
      proxy: {
        '/api': { target: backend, changeOrigin: true },
        '/ws': { target: backend.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
      },
    },
    preview: {
      proxy: {
        '/api': { target: backend, changeOrigin: true },
        '/ws': { target: backend.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      target: 'es2022',
      assetsInlineLimit: 0,
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.{ts,tsx}'],
    },
  };
});
