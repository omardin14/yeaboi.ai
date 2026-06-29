import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "@/lib/bindings/Snapshot";
import type { Session } from "@/lib/bindings/Session";
import type { Project } from "@/lib/bindings/Project";
import type { Port } from "@/lib/bindings/Port";
import {
  formatPct,
  heatClass,
  providerAccent,
  statusRailVar,
} from "@/lib/format";
import { useSessionMetrics, type SessionMetric } from "@/lib/session-metrics";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Gauge } from "@/components/ui/gauge";
import { EmptyState } from "@/components/ui/empty-state";
import { PortChips } from "@/components/port-chips";
import { SessionExpand } from "@/components/session-expand";

/** A session can be stopped only if it has a live process. */
function isKillable(session: Session): boolean {
  return session.pid != null && session.status !== "Dead";
}

function SessionRow({
  session,
  expanded,
  onToggleExpand,
  metric,
  onKill,
  onFreePort,
  onSelect,
}: {
  session: Session;
  expanded: boolean;
  onToggleExpand: (session: Session) => void;
  metric: SessionMetric | undefined;
  onKill?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
  onSelect?: (session: Session) => void;
}) {
  const ctx = session.context?.pct ?? null;
  const needs = session.awaiting_permission;
  return (
    <div
      role="row"
      aria-expanded={expanded}
      onClick={() => onToggleExpand(session)}
      className="group relative cursor-pointer rounded-xl px-3 py-2 transition-colors hover:bg-surface-raised"
    >
      {/* Lacquered status rail — status at a glance from the edge. */}
      <span
        aria-hidden
        className={`absolute left-1 top-2 bottom-2 w-[3px] rounded-full ${needs ? "animate-needs" : ""}`}
        style={{ background: statusRailVar(session.status) }}
      />

      {/* Top line: identity on the left, live meta on the right. */}
      <div className="flex items-center gap-2.5 pl-2 text-[13px]">
        <span
          aria-hidden
          className={`w-2 shrink-0 text-[9px] text-ink-faint transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
        >
          ▶
        </span>
        <span
          title={session.status}
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: statusRailVar(session.status) }}
        />
        <span className="flex min-w-0 items-center gap-1.5 font-medium text-ink">
          <span className={`text-[9px] leading-none ${providerAccent(session.provider)}`}>●</span>
          <span className="truncate">{session.model ?? "—"}</span>
        </span>
        {session.branch && (
          <span className="hidden max-w-[13rem] shrink truncate font-mono text-xs text-ink-faint sm:inline">
            {session.branch}
          </span>
        )}

        <span className="ml-auto flex shrink-0 items-center gap-2.5">
          {needs && (
            <span
              title="Waiting on a permission decision"
              className="animate-needs rounded-md bg-needs-fill px-1.5 py-0.5 text-xs text-needs ring-1 ring-inset ring-needs-ring"
            >
              ⏸ needs you
            </span>
          )}
          {session.sub_agent_count > 0 && (
            <span className="font-mono text-xs text-ink-faint" title="sub-agents">
              ⌥{session.sub_agent_count}
            </span>
          )}
          {session.ports.length > 0 && (
            <PortChips ports={session.ports} onFreePort={onFreePort} />
          )}
          <span className="flex items-center gap-1.5" title={`context ${formatPct(ctx)}`}>
            <Gauge value={ctx} />
            <span className={`w-9 text-right font-mono text-xs tabular-nums ${heatClass(ctx)}`}>
              {formatPct(ctx)}
            </span>
          </span>
          <span className="w-8 text-right">
            {onKill && isKillable(session) && (
              <button
                type="button"
                aria-label={`Stop session ${session.id}`}
                title="Stop session (SIGTERM)"
                onClick={(e) => {
                  e.stopPropagation(); // don't also toggle the panel
                  onKill(session);
                }}
                className="rounded-md px-1.5 py-0.5 text-xs text-ink-faint opacity-0 transition hover:bg-danger-fill hover:text-danger group-hover:opacity-100"
              >
                stop
              </button>
            )}
          </span>
        </span>
      </div>

      {/* The current prompt on its own readable line — the "what's happening". */}
      {session.last_prompt && (
        <p
          className="mt-1 truncate pl-[26px] text-[13px] leading-snug text-ink-muted"
          title={session.last_prompt}
        >
          {session.last_prompt}
        </p>
      )}

      {/* Inline expandable detail — calm, labeled sections. */}
      {expanded && (
        <SessionExpand
          session={session}
          metric={metric}
          onSelect={onSelect}
          onFreePort={onFreePort}
        />
      )}
    </div>
  );
}

function ProjectGroup({
  project,
  sessions,
  expandedId,
  onToggleExpand,
  getMetric,
  onKill,
  onFreePort,
  onSelect,
}: {
  project: Project;
  sessions: Session[];
  expandedId: string | null;
  onToggleExpand: (session: Session) => void;
  getMetric: (id: string) => SessionMetric | undefined;
  onKill?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
  onSelect?: (session: Session) => void;
}) {
  const busy = sessions.filter((s) => s.status === "Busy").length;
  return (
    <section className="mb-4">
      <Card pad="none" className="overflow-hidden">
        <header className="flex items-baseline gap-2 px-4 pt-3">
          <span aria-hidden className="text-xs text-burgundy">
            ◆
          </span>
          <h2 className="text-sm font-semibold text-ink">{project.name}</h2>
          <span className="text-xs text-ink-faint">
            {busy > 0 && <span className="text-busy">{busy} busy</span>}
            {busy > 0 && " · "}
            {sessions.length} shown
          </span>
          {project.remote && (
            <span className="ml-auto truncate font-mono text-[11px] text-ink-faint">
              {project.remote}
            </span>
          )}
        </header>
        {/* Ticked divider. */}
        <div className="mx-4 mt-2 mb-1 border-t border-dashed border-line-strong" />
        <div className="space-y-0.5 px-2 pb-2">
          {sessions.map((s) => (
            <SessionRow
              key={s.id}
              session={s}
              expanded={expandedId === s.id}
              onToggleExpand={onToggleExpand}
              metric={getMetric(s.id)}
              onKill={onKill}
              onFreePort={onFreePort}
              onSelect={onSelect}
            />
          ))}
        </div>
      </Card>
    </section>
  );
}

/** Listening ports whose owning process outlived its session — free them here. */
function OrphanPorts({
  ports,
  onFreePort,
}: {
  ports: Port[];
  onFreePort?: (port: Port) => void;
}) {
  if (ports.length === 0) return null;
  return (
    <Card tone="outline" className="mb-4 border-needs-ring bg-needs-fill/40">
      <h2 className="mb-1 text-sm font-semibold text-needs">Orphan ports</h2>
      <p className="mb-2 text-xs text-ink-muted">
        Listeners left by a session that's gone — free a stuck dev-server port.
      </p>
      <PortChips ports={ports} onFreePort={onFreePort} />
    </Card>
  );
}

type SortKey = "recent" | "context" | "cpu" | "status";

const STATUS_ORDER: Record<string, number> = { Busy: 0, Idle: 1, Unknown: 2, Dead: 3 };

function sortSessions(sessions: Session[], key: SortKey): Session[] {
  const sorted = [...sessions];
  sorted.sort((a, b) => {
    switch (key) {
      case "context":
        return (b.context?.pct ?? -1) - (a.context?.pct ?? -1);
      case "cpu":
        return (b.proc_stats?.cpu_pct ?? -1) - (a.proc_stats?.cpu_pct ?? -1);
      case "status":
        return (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
      default:
        return b.updated_at_ms - a.updated_at_ms;
    }
  });
  return sorted;
}

function matchesFilter(s: Session, q: string): boolean {
  if (!q) return true;
  const hay = [s.model, s.branch, s.last_prompt, s.cwd, s.status]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return hay.includes(q.toLowerCase());
}

/**
 * The monitor view: sessions grouped under their project, with a filter box,
 * a sort control, an awaiting-permission inbox filter, and an orphan-port
 * section. Clicking a session expands a calm, labeled detail panel inline.
 */
export function Monitor({
  snapshot,
  onKill,
  onFreePort,
  onSelect,
}: {
  snapshot: Snapshot | null;
  onKill?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
  onSelect?: (session: Session) => void;
}) {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortKey>("recent");
  const [onlyBlocked, setOnlyBlocked] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const filterRef = useRef<HTMLInputElement>(null);
  const getMetric = useSessionMetrics(snapshot);

  // "/" focuses the filter box (a power-user shortcut).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== filterRef.current) {
        e.preventDefault();
        filterRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!snapshot) {
    return <p className="text-sm text-ink-muted">Connecting…</p>;
  }

  const byId = new Map(snapshot.sessions.map((s) => [s.id, s]));
  const blockedCount = snapshot.sessions.filter((s) => s.awaiting_permission).length;
  const toggleExpand = (s: Session) =>
    setExpandedId((cur) => (cur === s.id ? null : s.id));

  const groups = snapshot.projects
    .map((project) => {
      const sessions = sortSessions(
        project.session_ids
          .map((id) => {
            const s = byId.get(id);
            if (s == null) {
              console.warn(
                `monitor: project ${project.id} references unknown session ${id}`,
              );
            }
            return s;
          })
          .filter((s): s is Session => s != null)
          .filter((s) => matchesFilter(s, filter))
          .filter((s) => !onlyBlocked || s.awaiting_permission),
        sort,
      );
      return { project, sessions };
    })
    .filter((g) => g.sessions.length > 0);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          ref={filterRef}
          aria-label="Filter sessions"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter…  ( / )"
          className="w-48"
        />
        <Select
          aria-label="Sort by"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
        >
          <option value="recent">Recent</option>
          <option value="context">Context %</option>
          <option value="cpu">CPU</option>
          <option value="status">Status</option>
        </Select>
        {blockedCount > 0 && (
          <Button
            variant={onlyBlocked ? "primary" : "outline"}
            onClick={() => setOnlyBlocked((v) => !v)}
          >
            ⏸ {blockedCount} need you
          </Button>
        )}
      </div>

      <OrphanPorts ports={snapshot.orphan_ports} onFreePort={onFreePort} />

      {snapshot.sessions.length === 0 ? (
        <EmptyState
          title="No active sessions"
          hint="Start Claude Code or Codex and the session shows up here, live."
        />
      ) : groups.length === 0 ? (
        <EmptyState glyph="⌕" title="No sessions match" hint="Clear the filter to see everything again." />
      ) : (
        groups.map(({ project, sessions }) => (
          <ProjectGroup
            key={project.id}
            project={project}
            sessions={sessions}
            expandedId={expandedId}
            onToggleExpand={toggleExpand}
            getMetric={getMetric}
            onKill={onKill}
            onFreePort={onFreePort}
            onSelect={onSelect}
          />
        ))
      )}
    </div>
  );
}
