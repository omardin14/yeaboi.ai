import type { ReactNode } from "react";
import { cx } from "@/components/ui/cx";

/**
 * A calm hover/focus explanation, CSS-only (no portal/positioning deps). Wrap a
 * trigger; the bubble fades in on hover or keyboard focus. Used for the
 * per-metric "what is this?" copy in the Monitor.
 */
export function Tooltip({
  content,
  children,
  className,
}: {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cx("group/tip relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 w-max max-w-[15rem] -translate-x-1/2 translate-y-1 rounded-lg border border-line bg-overlay px-2.5 py-1.5 text-[11px] leading-snug text-ink-soft opacity-0 shadow-lg transition-all duration-200 group-hover/tip:translate-y-0 group-hover/tip:opacity-100 group-focus-within/tip:translate-y-0 group-focus-within/tip:opacity-100"
      >
        {content}
      </span>
    </span>
  );
}

/**
 * A small ⓘ affordance that reveals `label` on hover. Uses a native `title`
 * tooltip — the CSS popover above gets clipped inside the collapsible panels'
 * `overflow-hidden`, whereas `title` always renders.
 */
export function InfoDot({ label }: { label: string }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className="inline-flex h-3.5 w-3.5 shrink-0 cursor-help items-center justify-center rounded-full border border-line-strong text-[9px] leading-none text-ink-faint transition-colors hover:border-burgundy hover:text-burgundy"
    >
      i
    </button>
  );
}
