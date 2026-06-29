import type { ReactNode } from "react";
import type { Totals } from "@/lib/bindings/Totals";
import { useTheme } from "@/lib/theme";
import { StatBadge } from "@/components/ui/stat";
import { cx } from "@/components/ui/cx";

export type Tab = "monitor" | "prs" | "worktrees";

const NAV: { id: Tab; label: string; glyph: string }[] = [
  { id: "monitor", label: "Monitor", glyph: "◎" },
  { id: "prs", label: "PRs", glyph: "⌥" },
  { id: "worktrees", label: "Worktrees", glyph: "⑂" },
];

/** Concentric-arc logo mark — the same gauge motif as the context rings. */
function LogoMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 36 36" aria-hidden className="-rotate-90">
      <circle cx="18" cy="18" r="15" fill="none" stroke="var(--line-strong)" strokeWidth="3" />
      <circle
        cx="18"
        cy="18"
        r="15"
        fill="none"
        stroke="var(--burgundy)"
        strokeWidth="3"
        strokeLinecap="round"
        pathLength={100}
        strokeDasharray="64 100"
      />
      <circle cx="18" cy="18" r="6" fill="none" stroke="var(--burgundy-soft)" strokeWidth="3" />
    </svg>
  );
}

/**
 * The app frame: a slim left sidebar (logo, nav, theme toggle, live ticker) and
 * a main column with a header strip (view title + rolled-up stats) over the
 * active view. Everything sits on the `.app-bg` instrument-panel motif.
 */
export function AppShell({
  tab,
  onTab,
  totals,
  updatedAt,
  children,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  totals: Totals | null | undefined;
  updatedAt: string;
  children: ReactNode;
}) {
  const { theme, toggle } = useTheme();
  const title = NAV.find((n) => n.id === tab)?.label ?? "";

  return (
    <div className="app-bg flex min-h-screen text-ink">
      <aside className="flex w-44 shrink-0 flex-col border-r border-line bg-surface/70 px-3 py-4 backdrop-blur">
        <div className="mb-6 flex items-center gap-2 px-1">
          <LogoMark />
          <span className="font-display text-lg italic tracking-tight">
            yeaboi<span className="text-burgundy">.ai</span>
          </span>
        </div>

        <nav className="flex flex-col gap-1">
          {NAV.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => onTab(n.id)}
              aria-current={tab === n.id ? "page" : undefined}
              className={cx(
                "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm transition-colors",
                tab === n.id
                  ? "bg-burgundy text-on-burgundy"
                  : "text-ink-muted hover:bg-surface-sunken hover:text-ink-soft",
              )}
            >
              <span className="w-4 text-center text-base leading-none">{n.glyph}</span>
              {n.label}
            </button>
          ))}
        </nav>

        <div className="mt-auto flex flex-col gap-3 px-1">
          <button
            type="button"
            onClick={toggle}
            aria-label="Toggle color theme"
            className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-xs text-ink-muted transition-colors hover:text-ink-soft"
          >
            <span className="text-base leading-none">{theme === "noir" ? "☀" : "☾"}</span>
            {theme === "noir" ? "Parchment" : "Burgundy Noir"}
          </button>
          <div className="font-mono text-[10px] text-ink-faint">updated {updatedAt}</div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-line px-6 py-3">
          <h1 className="font-display text-xl tracking-tight text-ink">{title}</h1>
          <div className="flex items-center gap-5">
            <StatBadge label="sessions" value={totals?.session_count ?? "—"} />
            <StatBadge
              label="busy"
              value={totals?.busy_count ?? "—"}
              accent
              dot={(totals?.busy_count ?? 0) > 0}
            />
            <StatBadge label="projects" value={totals?.project_count ?? "—"} />
          </div>
        </header>

        <div className="min-w-0 flex-1 px-6 py-5">{children}</div>
      </div>
    </div>
  );
}
