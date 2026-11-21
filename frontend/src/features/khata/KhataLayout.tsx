// Layout of /khata and /khata/$id. One <main> for both:
//  - phone: the list, or the customer detail on its own (with a way back)
//  - tablet (>= 640px): two panes, the list on the left (scrolling by itself) and the detail on the right
//  - desktop (>= 1024px): the same, with the detail centred in its column (max ~640px)
// Focus and scroll: opening a customer starts the page at the top and the detail moves focus to its h1; coming
// back restores the list's scroll position and puts focus on the row that was opened.
import { Outlet, useParams } from '@tanstack/react-router';
import { useEffect, useLayoutEffect, useRef } from 'react';
import { KhataList } from './KhataList';

const mobile = () => !window.matchMedia('(min-width: 40rem)').matches;

export function KhataLayout() {
  const { id } = useParams({ strict: false }) as { id?: string };
  const detail = id !== undefined;
  const listScroll = useRef(0);
  const prevId = useRef<string | undefined>(undefined);

  // Remember where the list was scrolled while it is the page.
  useEffect(() => {
    if (detail) return;
    const save = () => {
      listScroll.current = window.scrollY;
    };
    window.addEventListener('scroll', save, { passive: true });
    return () => window.removeEventListener('scroll', save);
  }, [detail]);

  useLayoutEffect(() => {
    const from = prevId.current;
    prevId.current = id;
    if (id !== undefined) {
      if (mobile()) window.scrollTo(0, 0);
      return;
    }
    if (from === undefined) return;
    if (mobile()) window.scrollTo(0, listScroll.current);
    // After the rows for the restored position have rendered, focus the row that was opened, else the title.
    const frame = requestAnimationFrame(() => {
      const row = document.querySelector<HTMLElement>(`#khata-list [data-key="${CSS.escape(from)}"] a`);
      (row ?? document.getElementById('khata-title'))?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [id]);

  return (
    <main
      id="main"
      tabIndex={-1}
      className="min-w-0 flex-1 outline-none sm:grid sm:grid-cols-[minmax(17rem,22rem)_minmax(0,1fr)] lg:grid-cols-[minmax(20rem,26rem)_minmax(0,1fr)]"
    >
      <div
        id="khata-list"
        className={`min-w-0 sm:sticky sm:top-0 sm:block sm:h-[calc(100dvh-var(--spacing-tabs)-env(safe-area-inset-bottom))] sm:self-start sm:overflow-y-auto sm:overscroll-contain sm:border-e sm:border-line lg:h-dvh ${
          detail ? 'hidden' : ''
        }`}
      >
        <KhataList titleLevel={detail ? 'h2' : 'h1'} />
      </div>
      <Outlet />
    </main>
  );
}

/** Right pane of /khata on tablet and desktop, before a customer is chosen. Hidden on a phone. */
export function KhataIndexPane({ text }: { text: string }) {
  return (
    <div className="hidden min-w-0 px-8 pt-24 sm:block lg:px-10">
      <p className="mx-auto max-w-prose text-body text-ink-2">{text}</p>
    </div>
  );
}
