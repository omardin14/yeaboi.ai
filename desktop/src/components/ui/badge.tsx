import type { ReactNode } from "react";
import type { ActivityStatus } from "@/lib/bindings/ActivityStatus";
import { statusBadgeClass } from "@/lib/format";
import { cx } from "@/components/ui/cx";

/**
 * A small pill. `tone` supplies fill/text/ring utility classes (usually from a
 * token helper in `format.ts`); pass `className` for layout tweaks.
 */
export function Badge({
  tone,
  className,
  children,
}: {
  tone: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        tone,
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Session activity pill (Busy / Idle / Dead / …), uppercase. */
export function StatusBadge({ status }: { status: ActivityStatus }) {
  return (
    <Badge tone={statusBadgeClass(status)} className="uppercase tracking-wide">
      {status}
    </Badge>
  );
}
