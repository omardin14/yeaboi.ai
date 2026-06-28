import type { Snapshot } from "@/lib/bindings/Snapshot";
import type { Session } from "@/lib/bindings/Session";
import type { Project } from "@/lib/bindings/Project";
import {
  formatCpu,
  formatMem,
  formatPct,
  heatClass,
  statusBadgeClass,
  statusLabel,
} from "@/lib/format";

function StatusBadge({ session }: { session: Session }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium uppercase tracking-wide ring-1 ring-inset ${statusBadgeClass(
        session.status,
      )}`}
    >
      {statusLabel(session.status)}
    </span>
  );
}

function SessionRow({ session }: { session: Session }) {
  const ctx = session.context?.pct ?? null;
  const cpu = session.proc_stats?.cpu_pct ?? null;
  return (
    <tr className="border-b border-zinc-900 last:border-0 hover:bg-zinc-900/40">
      <td className="py-1.5 pr-3">
        <StatusBadge session={session} />
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
      <td className="max-w-md truncate py-1.5 text-zinc-500" title={session.last_prompt ?? ""}>
        {session.last_prompt ?? ""}
      </td>
    </tr>
  );
}

function ProjectGroup({
  project,
  sessions,
}: {
  project: Project;
  sessions: Session[];
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
            <SessionRow key={s.id} session={s} />
          ))}
        </tbody>
      </table>
    </section>
  );
}

/**
 * The monitor view: sessions grouped under their project, rendered purely from
 * the streamed snapshot. Phase 1b-next adds sort/filter, ports, and actions.
 */
export function Monitor({ snapshot }: { snapshot: Snapshot | null }) {
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
          .map((id) => byId.get(id))
          .filter((s): s is Session => s != null);
        return (
          <ProjectGroup
            key={project.id}
            project={project}
            sessions={sessions}
          />
        );
      })}
    </div>
  );
}
