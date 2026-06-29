import type { ReactNode } from "react";
import { cx } from "@/components/ui/cx";

/**
 * A labeled, collapsible section with a gentle expand/collapse. Controlled via
 * `open`/`onOpenChange` (persisted by the caller). `action` renders at the right
 * of the header (e.g. a hide/gear control). The body animates with a grid-rows
 * trick so there's no abrupt jump.
 */
export function Section({
  label,
  open,
  onOpenChange,
  action,
  children,
  className,
}: {
  label: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => onOpenChange(!open)}
          className="flex flex-1 items-center gap-1.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-faint transition-colors hover:text-ink-muted"
        >
          <span
            className={cx(
              "inline-block text-[9px] transition-transform duration-200",
              open ? "rotate-90" : "rotate-0",
            )}
          >
            ▶
          </span>
          {label}
        </button>
        {action}
      </div>
      <div
        className={cx(
          "grid transition-all duration-200 ease-out",
          open ? "mt-1.5 grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="overflow-hidden">{children}</div>
      </div>
    </div>
  );
}
