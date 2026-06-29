import { useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * A small ⓘ affordance that opens a short explanation on click. The popover is
 * portal-rendered at a fixed position so the collapsible panels' `overflow-hidden`
 * can't clip it (the reason a CSS/hover tooltip didn't show). Click anywhere to
 * dismiss.
 */
export function InfoDot({ label }: { label: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const btnRef = useRef<HTMLButtonElement>(null);

  function toggle(e: React.MouseEvent) {
    e.stopPropagation(); // don't toggle the row/section behind it
    const r = btnRef.current?.getBoundingClientRect();
    if (r) {
      setPos({
        top: r.bottom + 4,
        left: Math.min(r.left, window.innerWidth - 272),
      });
    }
    setOpen((o) => !o);
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={toggle}
        className="inline-flex h-3.5 w-3.5 shrink-0 cursor-pointer items-center justify-center rounded-full border border-line-strong text-[9px] leading-none text-ink-faint transition-colors hover:border-burgundy hover:text-burgundy"
      >
        i
      </button>
      {open &&
        createPortal(
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div
              role="tooltip"
              style={{ position: "fixed", top: pos.top, left: pos.left }}
              className="z-50 max-w-[16rem] rounded-lg border border-line bg-overlay px-2.5 py-1.5 text-[11px] leading-snug text-ink-soft shadow-lg"
            >
              {label}
            </div>
          </>,
          document.body,
        )}
    </>
  );
}
