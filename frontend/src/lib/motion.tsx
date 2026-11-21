// Motion setup for screens that need JS-driven animation (counting amounts, chart bars, list reordering).
// Stage 1 does its motion in CSS (mic ring, row entrance, reduced-motion fades) and vaul animates the sheet,
// so this provider is NOT in the entry bundle (it would add about 10 kB gzipped). Wrap a route's component in
// it inside that route's file, so motion loads with the route chunk:
//   import { MotionProvider, m, enter } from '../lib/motion';
//   <MotionProvider><m.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={enter} /></MotionProvider>
// LazyMotion fetches the animation features in their own chunk; MotionConfig follows the user's
// reduced-motion setting (transforms are dropped, opacity fades stay).
import type { ReactNode } from 'react';
import { LazyMotion, MotionConfig } from 'motion/react';

export * as m from 'motion/react-m';

/** 200 ms ease-out, the house transition. */
export const enter = { duration: 0.2, ease: [0.22, 1, 0.36, 1] as const };

const loadFeatures = () => import('./motion-features').then((r) => r.default);

export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user">
      <LazyMotion features={loadFeatures} strict>
        {children}
      </LazyMotion>
    </MotionConfig>
  );
}
