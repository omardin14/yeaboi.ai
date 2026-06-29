import { useEffect, type ReactNode } from "react";
import { cx } from "@/components/ui/cx";

/** Esc-to-close behaviour shared by the overlay primitives. */
function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
}

/**
 * A right-side slide-in drawer over a warm scrim. The caller owns the header
 * and content; the drawer provides the shell + Esc/backdrop dismissal.
 */
export function Drawer({
  onClose,
  ariaLabel,
  className,
  children,
}: {
  onClose: () => void;
  ariaLabel: string;
  className?: string;
  children: ReactNode;
}) {
  useEscape(onClose);
  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-[var(--scrim)]"
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        onClick={(e) => e.stopPropagation()}
        className={cx(
          "h-full w-full overflow-y-auto border-l border-line bg-overlay p-5 shadow-2xl",
          // Default width unless the caller sets its own `max-w-*`.
          !className?.includes("max-w-") && "max-w-xl",
          className,
        )}
      >
        {children}
      </aside>
    </div>
  );
}
