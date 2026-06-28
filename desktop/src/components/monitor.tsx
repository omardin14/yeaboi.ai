import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "@/lib/bindings/Snapshot";
import type { Session } from "@/lib/bindings/Session";
import type { Project } from "@/lib/bindings/Project";
import type { Port } from "@/lib/bindings/Port";
import type { ActivityStatus } from "@/lib/bindings/ActivityStatus";
import {
  formatCpu,
  formatMem,
  formatPct,
  heatClass,
  statusBadgeClass,
} from "@/lib/format";

function StatusBadge({ status }: { status: ActivityStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium uppercase tracking-wide ring-1 ring-inset ${statusBadgeClass(
        status,
      )}`}
    >
      {status}
    </span>
  );
}

/** A session can be stopped only if it has a live process. */
function isKillable(session: Session): boolean {
  return session.pid != null && session.status !== "Dead";
}

const CHIP_CLS = "rounded bg-zinc-800 px-1 font-mono text-xs text-sky-300";

function PortChip({
  port,
  onFreePort,
}: {
  port: Port;
  onFreePort?: (port: Port) => void;
}) {
  const label = `:${port.number}`;
  const title = `pid ${port.pid} · ${port.state}`;
  if (!onFreePort) {
    return (
      <span title={title} className={CHIP_CLS}>
        {label}
      </span>
    );
  }
  return (
    <button
      type="button"
      aria-label={`Free port ${port.number}`}
      title={`Free ${label} (${title})`}
      onClick={(e) => {
        e.stopPropagation();
        onFreePort(port);
      }}
      className={`${CHIP_CLS} hover:bg-rose-500/15 hover:text-rose-300`}
    >
      {label}
    </button>
  );
}

function PortChips({
  ports,
  onFreePort,
}: {
  ports: Port[];
  onFreePort?: (port: Port) => void;
}) {
  return (
    <span className="flex flex-wrap gap-1">
      {ports.map((p) => (
        <PortChip key={`${p.pid}:${p.number}`} port={p} onFreePort={onFreePort} />
      ))}
    </span>
  );
}

function SessionRow({
  session,
  onKill,
  onFreePort,
  onSelect,
}: {
  session: Session;
  onKill?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
  onSelect?: (session: Session) => void;
}) {
  const ctx = session.context?.pct ?? null;
  const cpu = session.proc_stats?.cpu_pct ?? null;
  return (
    <tr
      onClick={() => onSelect?.(session)}
      className="group cursor-pointer border-b border-zinc-900 last:border-0 hover:bg-zinc-900/40"
    >
      <td className="py-1.5 pr-3">
        <StatusBadge status={session.status} />
        {session.awaiting_permission && (
          <span
            title="Waiting on a permission decision"
            className="ml-1 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-400 ring-1 ring-inset ring-amber-500/30"
          >
            ⏸ needs you
          </span>
        )}
      </td>
      <td className="py-1.5 pr-3 font-mono text-xs text-zinc-500">
        {session.pid ?? "—"}
      </td>
      <td className="py-1.5 pr-3 text-zinc-300">{session.model ?? "—"}</td>
      <td className={`py-1.5 pr-3 text-right tabular-nums ${heatClass(ctx)}`}>
        {formatPct(ctx)}
      </td>
      <td
        className={`py-1.5 pr-3 text-right tabular-nums ${heatClass(
          cpu == null ? null : cpu / 100,
        )}`}
      >
        {formatCpu(cpu)}
      </td>
      <td className="py-1.5 pr-3 text-right tabular-nums text-zinc-400">
        {formatMem(session.proc_stats?.mem_bytes ?? 0)}
      </td>
      <td className="py-1.5 pr-3 text-zinc-400">{session.branch ?? "—"}</td>
      <td className="py-1.5 pr-3 text-zinc-500">
        {session.sub_agent_count > 0 ? `⌥${session.sub_agent_count}` : ""}
      </td>
      <td className="py-1.5 pr-3">
        <PortChips ports={session.ports} onFreePort={onFreePort} />
      </td>
      <td className="max-w-md truncate py-1.5 pr-3 text-zinc-500" title={session.last_prompt ?? ""}>
        {session.last_prompt ?? ""}
      </td>
      <td className="py-1.5 text-right">
        {onKill && isKillable(session) && (
          <button
            type="button"
            aria-label={`Stop session ${session.id}`}
            title="Stop session (SIGTERM)"
            onClick={(e) => {
              e.stopPropagation(); // don't also open the detail panel
              onKill(session);
            }}
            className="rounded px-1.5 py-0.5 text-xs text-zinc-600 opacity-0 transition hover:bg-rose-500/10 hover:text-rose-400 group-hover:opacity-100"
          >
            stop
          </button>
        )}
      </td>
    </tr>
  );
}

function ProjectGroup({
  project,
  sessions,
  onKill,
  onFreePort,
  onSelect,
}: {
  project: Project;
  sessions: Session[];
  onKill?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
  onSelect?: (session: Session) => void;
}) {
  return (
    <section className="mb-5">
      <header className="mb-1 flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-zinc-200">{project.name}</h2>
        <span className="text-xs text-zinc-500">
          {(() => {
            const busy = sessions.filter((s) => s.status === "Busy").length;
            return busy > 0 ? (
              <>
                <span className="text-emerald-400">{busy} busy</span>
                {" · "}
              </>
            ) : null;
          })()}
          {sessions.length} shown
        </span>
      </header>
      <table className="w-full border-collapse text-sm">
        <tbody>
          {sessions.map((s) => (
            <SessionRow
              key={s.id}
              session={s}
              onKill={onKill}
              onFreePort={onFreePort}
              onSelect={onSelect}
            />
          ))}
        </tbody>
      </table>
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
    <section className="mb-5 rounded border border-amber-500/20 bg-amber-500/5 p-3">
      <h2 className="mb-1 text-sm font-semibold text-amber-300">Orphan ports</h2>
      <p className="mb-2 text-xs text-zinc-500">
        Listeners left by a session that's gone — free a stuck dev-server port.
      </p>
      <PortChips ports={ports} onFreePort={onFreePort} />
    </section>
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
 * section. Rendered purely from the streamed snapshot.
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
  const filterRef = useRef<HTMLInputElement>(null);

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
    return <p className="text-sm text-zinc-500">Connecting…</p>;
  }

  const byId = new Map(snapshot.sessions.map((s) => [s.id, s]));
  const blockedCount = snapshot.sessions.filter((s) => s.awaiting_permission).length;

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
        <input
          ref={filterRef}
          aria-label="Filter sessions"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter…  ( / )"
          className="w-48 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-200"
        />
        <select
          aria-label="Sort by"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200"
        >
          <option value="recent">Recent</option>
          <option value="context">Context %</option>
          <option value="cpu">CPU</option>
          <option value="status">Status</option>
        </select>
        {blockedCount > 0 && (
          <button
            type="button"
            onClick={() => setOnlyBlocked((v) => !v)}
            className={`rounded px-2 py-1 text-xs ${
              onlyBlocked
                ? "bg-amber-500/20 text-amber-300"
                : "border border-zinc-700 text-zinc-400 hover:bg-zinc-800"
            }`}
          >
            ⏸ {blockedCount} need you
          </button>
        )}
      </div>

      <OrphanPorts ports={snapshot.orphan_ports} onFreePort={onFreePort} />

      {snapshot.sessions.length === 0 ? (
        <p className="text-sm text-zinc-500">No active sessions.</p>
      ) : groups.length === 0 ? (
        <p className="text-sm text-zinc-500">No sessions match.</p>
      ) : (
        groups.map(({ project, sessions }) => (
          <ProjectGroup
            key={project.id}
            project={project}
            sessions={sessions}
            onKill={onKill}
            onFreePort={onFreePort}
            onSelect={onSelect}
          />
        ))
      )}
    </div>
  );
}
