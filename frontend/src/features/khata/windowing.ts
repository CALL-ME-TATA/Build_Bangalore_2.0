// Windowing maths for long lists with rows of different heights (wrapped names, large text).
// Rows that were measured use their real height; the rest use the mean of the measured rows (or a fallback
// estimate before anything was measured), so the estimate converges after the first screen.
// Pure functions; the DOM side is in useWindowedList.ts. Tested in windowing.test.ts.

export interface Layout {
  /** offsets[i] = top of row i; offsets[count] = total height. Length count + 1. */
  offsets: Float64Array;
  total: number;
}

/** Height to assume for rows not measured yet. */
export function estimateHeight(measured: Iterable<number>, fallback: number): number {
  let sum = 0;
  let n = 0;
  for (const h of measured) {
    if (h > 0) {
      sum += h;
      n += 1;
    }
  }
  return n ? sum / n : fallback;
}

/** Prefix sums of the row heights. `heightOf(i)` returns the measured height or undefined. */
export function buildLayout(count: number, heightOf: (i: number) => number | undefined, estimate: number): Layout {
  const offsets = new Float64Array(count + 1);
  for (let i = 0; i < count; i++) {
    const h = heightOf(i);
    offsets[i + 1] = (offsets[i] ?? 0) + (h !== undefined && h > 0 ? h : estimate);
  }
  return { offsets, total: offsets[count] ?? 0 };
}

/** Index of the row that contains position `y` (clamped to the list). Binary search over the offsets. */
export function rowAt(layout: Layout, y: number): number {
  const count = layout.offsets.length - 1;
  if (count <= 0) return 0;
  if (y <= 0) return 0;
  if (y >= layout.total) return count - 1;
  let lo = 0;
  let hi = count - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if ((layout.offsets[mid] ?? 0) <= y) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export interface Range {
  /** First rendered index (inclusive). */
  start: number;
  /** Last rendered index (exclusive). */
  end: number;
}

/**
 * Rows to render for a viewport [viewTop, viewTop + viewHeight) in list coordinates (0 = top of the list),
 * with `overscan` extra rows on each side. An empty range when the list is entirely outside the viewport,
 * except that at least one screen is rendered for a list that has not been laid out yet (viewHeight 0).
 */
export function visibleRange(layout: Layout, viewTop: number, viewHeight: number, overscan: number): Range {
  const count = layout.offsets.length - 1;
  if (count <= 0) return { start: 0, end: 0 };
  const height = viewHeight > 0 ? viewHeight : 800;
  const viewBottom = viewTop + height;
  if (viewBottom <= 0 || viewTop >= layout.total) {
    // Off-screen: keep a few rows near the edge so a fast fling does not show a blank band.
    if (viewBottom <= 0) return { start: 0, end: Math.min(count, overscan) };
    return { start: Math.max(0, count - overscan), end: count };
  }
  const first = rowAt(layout, Math.max(0, viewTop));
  const last = rowAt(layout, Math.max(0, viewBottom - 1));
  return { start: Math.max(0, first - overscan), end: Math.min(count, last + 1 + overscan) };
}

/** The rendered indices: the range plus one pinned index (the focused row) so focus is never lost. */
export function renderedIndices(range: Range, pinned: number | null, count: number): number[] {
  const out: number[] = [];
  for (let i = range.start; i < range.end; i++) out.push(i);
  if (pinned !== null && pinned >= 0 && pinned < count && (pinned < range.start || pinned >= range.end)) {
    if (pinned < range.start) out.unshift(pinned);
    else out.push(pinned);
  }
  return out;
}

export function sameRange(a: Range, b: Range): boolean {
  return a.start === b.start && a.end === b.end;
}
