import type { ReactNode } from "react";

/**
 * A calm empty/placeholder state — a display-serif glyph over guidance copy.
 * Used when a view has nothing to show yet (no sessions, no PRs, …).
 */
export function EmptyState({
  glyph = "◵",
  title,
  hint,
}: {
  glyph?: ReactNode;
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-16 text-center">
      <div className="font-display text-4xl text-burgundy-soft">{glyph}</div>
      <p className="text-sm font-medium text-ink-soft">{title}</p>
      {hint && <p className="max-w-sm text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}
