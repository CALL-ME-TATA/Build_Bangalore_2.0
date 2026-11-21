// First focusable element of every page: jumps to the main content.
export function SkipLink({ label, target = 'main' }: { label: string; target?: string }) {
  return (
    <a
      href={`#${target}`}
      onClick={(e) => {
        // Hash routing owns the URL fragment, so move focus by hand instead of navigating.
        e.preventDefault();
        const el = document.getElementById(target);
        el?.focus();
        el?.scrollIntoView({ block: 'start' });
      }}
      className="sr-only-focusable fixed left-3 top-3 z-[60] rounded-control bg-ink px-4 py-3 text-label text-paper"
    >
      {label}
    </a>
  );
}
