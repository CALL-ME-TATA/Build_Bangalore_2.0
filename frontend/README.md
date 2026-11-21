# KhataVaani web app (`frontend/`)

Vite + React 19 + TypeScript (strict) + Tailwind CSS 4, TanStack Router (file routes, hash history),
TanStack Query, Zustand, vaul, lucide-react, Fontsource. It talks to the unchanged FastAPI backend
(`docs/CONTRACT.md` section 3). The design brief is `docs/context/FRONTEND_BRIEF.md`.

## Commands (run in `frontend/`)

| | |
|---|---|
| `npm install` | install (exact versions are pinned) |
| `npm run dev` | dev server on :5173, proxies `/api` and `/ws` to `VITE_BACKEND` (default `http://127.0.0.1:8010`) |
| `npm run dev -- --mode mock` or open `/?mock=1` | scripted session, no backend or microphone needed |
| `npm run build` | production build into `dist/` (relative URLs; serve it from any static root) |
| `npm run preview` | serve `dist/` with the same proxy |
| `npm test` | Vitest (pure logic, no browser) |
| `npm run lint` | eslint with jsx-a11y (strict) and the React hooks / compiler rules |
| `npm run typecheck` | TypeScript 7 (`typescript-7` alias); `npx tsc` runs TypeScript 6, which eslint needs |
| `npm run icons` | regenerate the PNG app icons in `public/` |

The access code, when the server needs one, goes in the page URL before the route: `/?code=XXXX#/`.
`?mock=1` and `VITE_SESSION=mock` choose the scripted session (`src/services/session/mode.ts`).

## Layout

| Folder | What lives there |
|---|---|
| `src/routes/` | file routes; `__root.tsx` is the shell (skip link, live regions, header, tabs / rail, mini mic, doubt sheet) |
| `src/features/bolo/` | the Bolo screen: start step, conversation, type box, doubt sheet |
| `src/layout/` | shell pieces: header, today panel, placeholder screen, update prompt |
| `src/components/` | design-system components (Amount, MicButton, Sheet, Button, Chip, Switch, EntryRow, Avatar, StatusBadge, LiveRegion, SkipLink, BottomTabs, SideRail) |
| `src/state/` | Zustand stores: `session` (live voice state + reducer), `settings` (persisted), `mic` (shared gesture), `doubt` (sheet), `level` (mic level bus) |
| `src/services/` | `session/` (SessionService: WebSocket + AudioWorklet + player, and the mock), `api.ts` (REST), `query.ts` (TanStack Query), `db.ts` (Dexie, stage 2), `mock/` (mock ledger and replies) |
| `src/lib/` | pure helpers with tests: money and dates, number words, doubt-sheet answers and state machine, mic states and gestures, motion setup |
| `src/styles/` | `app.css` (every token, themes, type scale, a11y media queries), `fonts.css` |

## Rules for new code

- The design canvas boards in `docs/context/design-canvas/` are the visual source of truth.
- Colours, sizes, radii and shadows come from `src/styles/app.css`: colours `paper surface tint ink ink-2 ink-3
  line line-strong fill avatar highlight muted accent on-accent credit payment ask`; type `text-hero title-lg
  title-md title question total amount-lg amount head body-lg body label label-sm small meta nav eyebrow`;
  `rounded-chip/control/nav/wave/sheet/sheet-lg/full`, `shadow-float`, `shadow-sheet`. The default Tailwind
  palette is removed; no hex in components.
- Every amount goes through `<Amount>`. Credit and payment always show a sign and a word.
- One accent per screen: the mic, plus at most one `Button variant="primary"`.
- Fixed labels live in `src/i18n.ts` (both `hi` and `en`); server reply text is shown as it arrives.
- Keep logic in pure functions under `src/lib/` or `src/state/*-reducer.ts` and test them.
- Each screen renders `<main id="main" tabIndex={-1}>` and exactly one `h1`.
- Heavy or rarely used code is loaded lazily (route files are split automatically; see `lib/motion.tsx`, `services/db.ts`).
