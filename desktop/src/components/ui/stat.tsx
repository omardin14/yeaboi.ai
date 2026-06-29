import type { ReactNode } from "react";
import { cx } from "@/components/ui/cx";

/**
 * A compact header readout: a mono value over a tiny uppercase eyebrow label.
 * `accent` tints the value burgundy; `dot` adds a small pulsing status dot
 * (used for the live busy count).
 */
export function StatBadge({
  label,
  value,
  accent = false,
  dot = false,
}: {
  label: string;
  value: ReactNode;
  accent?: boolean;
  dot?: boolean;
}) {
  return (
    <div className="flex flex-col items-end leading-tight">
      <span
        className={cx(
          "flex items-center gap-1 font-mono text-sm tabular-nums",
          accent ? "text-burgundy" : "text-ink-soft",
        )}
      >
        {dot && (
          <span className="animate-needs inline-block h-1.5 w-1.5 rounded-full bg-busy" />
        )}
        {value}
      </span>
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-faint">
        {label}
      </span>
    </div>
  );
}
