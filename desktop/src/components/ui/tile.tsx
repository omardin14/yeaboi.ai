import type { ReactNode } from "react";
import { cx } from "@/components/ui/cx";

/**
 * A small raised stat tile — the lightest surface, so it visibly floats above
 * the panel's tan base. A value slot over a quiet uppercase eyebrow label. This
 * is the surface layering the session-detail vitals strip hinges on.
 */
export function Tile({
  label,
  title,
  className,
  children,
}: {
  label: string;
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      title={title}
      className={cx(
        "rounded-xl border border-line bg-surface-raised px-3 py-2 shadow-[0_1px_2px_rgba(42,26,18,0.06)]",
        className,
      )}
    >
      <div className="flex h-6 items-center gap-1.5 font-mono text-sm tabular-nums text-ink">
        {children}
      </div>
      <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-faint">
        {label}
      </div>
    </div>
  );
}
