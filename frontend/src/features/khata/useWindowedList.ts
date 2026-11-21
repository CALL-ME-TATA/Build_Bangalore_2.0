// A small windowing hook: renders only the rows near the viewport of a long list, so 200+ customers stay smooth
// on a low-end phone. Rows may differ in height (wrapped names, "Bada text"); each rendered row is measured with
// one shared ResizeObserver and unmeasured rows use the mean measured height (windowing.ts).
//
// The list scrolls with whatever scrolls it: the window on a phone, the list pane on a tablet. The scrolling
// ancestor is found from the computed style, and scroll events are caught in the capture phase on window, so
// both cases use the same code. React re-renders only when the visible rows leave the rendered window
// (overscan acts as hysteresis), not on every scroll event. The focused row is always kept rendered so keyboard
// focus is never lost when it scrolls out of view.
import { useEffect, useLayoutEffect, useRef, useState, type FocusEvent } from 'react';
import { buildLayout, estimateHeight, renderedIndices, visibleRange, type Layout } from './windowing';

export interface WindowedRow<T> {
  index: number;
  item: T;
  key: string;
  top: number;
}

export interface WindowedList<T> {
  /** Ref callback for the positioned list element (it gets `height: total`). */
  attachList: (el: HTMLElement | null) => void;
  total: number;
  rows: WindowedRow<T>[];
  /** Ref callback for each rendered row (together with `data-key={row.key}`) so its height is measured. */
  measureRow: (el: HTMLElement | null) => void;
  /** Focus and blur handlers for the focusable control inside a row: keep the focused row rendered. */
  rowFocus: (key: string) => void;
  rowBlur: (e: FocusEvent<HTMLElement>) => void;
}

interface Viewport {
  top: number;
  height: number;
}

function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY;
    if (oy === 'auto' || oy === 'scroll') return p;
  }
  return null;
}

/** The part of the list that is on screen, in list coordinates (0 = top of the list element). */
function readViewport(list: HTMLElement): Viewport {
  const parent = scrollParent(list);
  const rect = list.getBoundingClientRect();
  let vTop = 0;
  let vBottom = window.innerHeight;
  if (parent) {
    const pr = parent.getBoundingClientRect();
    vTop = Math.max(vTop, pr.top);
    vBottom = Math.min(vBottom, pr.bottom);
  }
  return { top: vTop - rect.top, height: Math.max(0, vBottom - vTop) };
}

export function useWindowedList<T>(opts: {
  items: readonly T[];
  getKey: (item: T) => string;
  /** Row height in px to assume before any row was measured. */
  estimate: number;
  overscan?: number;
}): WindowedList<T> {
  const { items, getKey, estimate, overscan = 8 } = opts;
  const [listEl, setListEl] = useState<HTMLElement | null>(null);
  const [heights, setHeights] = useState<ReadonlyMap<string, number>>(() => new Map());
  const [viewport, setViewport] = useState<Viewport>({ top: 0, height: 0 });
  const [focusedKey, setFocusedKey] = useState<string | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  const latest = useRef<{ layout: Layout; viewport: Viewport; overscan: number } | null>(null);

  const keys = items.map(getKey);
  const avg = estimateHeight(heights.values(), estimate);
  const layout = buildLayout(items.length, (i) => heights.get(keys[i] ?? ''), avg);
  const range = visibleRange(layout, viewport.top, viewport.height, overscan);
  const focusedIndex = focusedKey === null ? -1 : keys.indexOf(focusedKey);
  const indices = renderedIndices(range, focusedIndex >= 0 ? focusedIndex : null, items.length);
  const rows: WindowedRow<T>[] = [];
  for (const index of indices) {
    const item = items[index];
    if (item === undefined) continue;
    rows.push({ index, item, key: keys[index] ?? String(index), top: layout.offsets[index] ?? 0 });
  }

  // The scroll handler reads the latest layout without re-subscribing.
  useLayoutEffect(() => {
    latest.current = { layout, viewport, overscan };
  });

  useEffect(() => {
    if (!listEl) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const cur = latest.current;
      const next = readViewport(listEl);
      if (cur) {
        // Re-render only when rows outside the rendered window become visible, or the viewport height changed.
        const rendered = visibleRange(cur.layout, cur.viewport.top, cur.viewport.height, cur.overscan);
        const needed = visibleRange(cur.layout, next.top, next.height, 0);
        const covered = needed.start >= rendered.start && needed.end <= rendered.end;
        if (covered && Math.abs(next.height - cur.viewport.height) < 1 && cur.viewport.height > 0) return;
      }
      setViewport(next);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    window.addEventListener('scroll', schedule, { capture: true, passive: true });
    window.addEventListener('resize', schedule, { passive: true });
    // Content above the list (banners, totals) changing size moves the list without a scroll event.
    const ro = new ResizeObserver(schedule);
    ro.observe(listEl);
    ro.observe(document.documentElement);
    schedule();
    return () => {
      window.removeEventListener('scroll', schedule, { capture: true });
      window.removeEventListener('resize', schedule);
      ro.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [listEl]);

  useEffect(
    () => () => {
      observer.current?.disconnect();
      observer.current = null;
    },
    [],
  );

  const measureRow = (el: HTMLElement | null) => {
    if (!el) return;
    if (!observer.current) {
      observer.current = new ResizeObserver((entries) => {
        const changes: [string, number][] = [];
        for (const entry of entries) {
          const target = entry.target as HTMLElement;
          const key = target.dataset.key;
          if (!key || !target.isConnected) continue;
          const h = entry.borderBoxSize?.[0]?.blockSize ?? target.offsetHeight;
          if (h > 0) changes.push([key, h]);
        }
        if (!changes.length) return;
        setHeights((prev) => {
          if (changes.every(([k, h]) => Math.abs((prev.get(k) ?? -1) - h) < 0.5)) return prev;
          const next = new Map(prev);
          for (const [k, h] of changes) next.set(k, h);
          return next;
        });
      });
    }
    const ro = observer.current;
    ro.observe(el);
    return () => ro.unobserve(el);
  };

  const rowFocus = (key: string) => setFocusedKey(key);
  const rowBlur = (e: FocusEvent<HTMLElement>) => {
    // Focus moving to another row pins that row instead; focus leaving the list unpins.
    const next = e.relatedTarget as Node | null;
    if (!next || !listEl?.contains(next)) setFocusedKey(null);
  };

  return { attachList: setListEl, total: layout.total, rows, measureRow, rowFocus, rowBlur };
}
