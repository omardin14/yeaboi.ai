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

function PortChips({
  ports,
  onFreePort,
}: {
  ports: Port[];
  onFreePort?: (port: Port) => void;
}) {
  return (
    <span className="flex flex-wrap gap-1">
      {ports.map((p) => {
        const label = `:${p.number}`;
        const title = `pid ${p.pid} · ${p.state}`;
        const cls =
          "rounded bg-zinc-800 px-1 font-mono text-xs text-sky-300";
        return onFreePort ? (
          <button
            key={`${p.pid}:${p.number}`}
            type="button"
            aria-label={`Free port ${p.number}`}
            title={`Free ${label} (${title})`}
            onClick={() => onFreePort(p)}
            className={`${cls} hover:bg-rose-500/15 hover:text-rose-300`}
          >
            {label}
          </button>
        ) : (
          <span key={`${p.pid}:${p.number}`} title={title} className={cls}>
            {label}
          </span>
        );
      })}
    </span>
  );
}

function SessionRow({
  session,
  onKill,
  onFreePort,
}: {
  session: Session;
  onKill?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
}) {
  const ctx = session.context?.pct ?? null;
  const cpu = session.proc_stats?.cpu_pct ?? null;
  return (
    <tr className="group border-b border-zinc-900 last:border-0 hover:bg-zinc-900/40">
      <td className="py-1.5 pr-3">
        <StatusBadge status={session.status} />
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
            onClick={() => onKill(session)}
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
}: {
  project: Project;
  sessions: Session[];
  onKill?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
}) {
  return (
    <section className="mb-5">
      <header className="mb-1 flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-zinc-200">{project.name}</h2>
        <span className="text-xs text-zinc-500">
          {project.busy_count > 0 && (
            <span className="text-emerald-400">{project.busy_count} busy</span>
          )}
          {project.busy_count > 0 ? " · " : ""}
          {project.session_count} session{project.session_count === 1 ? "" : "s"}
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
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}

/**
 * The monitor view: sessions grouped under their project, rendered purely from
 * the streamed snapshot. `onKill` (when provided) enables a per-row stop button.
 * Phase 1b-next adds sort/filter and ports.
 */
export function Monitor({
  snapshot,
  onKill,
  onFreePort,
}: {
  snapshot: Snapshot | null;
  onKill?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
}) {
  if (!snapshot) {
    return <p className="text-sm text-zinc-500">Connecting…</p>;
  }
  if (snapshot.sessions.length === 0) {
    return <p className="text-sm text-zinc-500">No active sessions.</p>;
  }

  const byId = new Map(snapshot.sessions.map((s) => [s.id, s]));

  return (
    <div>
      {snapshot.projects.map((project) => {
        const sessions = project.session_ids
          .map((id) => {
            const s = byId.get(id);
            if (s == null) {
              // A project references a session not in the snapshot — surfaces a
              // collector/engine inconsistency instead of silently miscounting.
              console.warn(
                `monitor: project ${project.id} references unknown session ${id}`,
              );
            }
            return s;
          })
          .filter((s): s is Session => s != null);
        return (
          <ProjectGroup
            key={project.id}
            project={project}
            sessions={sessions}
            onKill={onKill}
            onFreePort={onFreePort}
          />
        );
      })}
    </div>
  );
}
