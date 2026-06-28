import type { Snapshot } from "@/lib/bindings/Snapshot";
import type { ActivityStatus } from "@/lib/bindings/ActivityStatus";

const STATUS_STYLES: Record<ActivityStatus, string> = {
  Busy: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  Idle: "bg-sky-500/15 text-sky-400 ring-sky-500/30",
  Dead: "bg-zinc-600/15 text-zinc-500 ring-zinc-600/30",
  Unknown: "bg-amber-500/15 text-amber-400 ring-amber-500/30",
};

function StatusBadge({ status }: { status: ActivityStatus }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.Unknown;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium uppercase tracking-wide ring-1 ring-inset ${style}`}
    >
      {status}
    </span>
  );
}

/**
 * Presentational table for the monitor. Pure function of the snapshot, so it is
 * trivially testable. Phase 1b replaces this with the grouped project tree.
 */
export function SessionsTable({ snapshot }: { snapshot: Snapshot | null }) {
  if (!snapshot) {
    return <p className="text-sm text-zinc-500">Loading sessions…</p>;
  }

  if (snapshot.sessions.length === 0) {
    return <p className="text-sm text-zinc-500">No active sessions.</p>;
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wide text-zinc-500">
          <th className="py-2 pr-4 font-medium">Status</th>
          <th className="py-2 pr-4 font-medium">Model</th>
          <th className="py-2 pr-4 font-medium">Ctx</th>
          <th className="py-2 pr-4 font-medium">Session</th>
        </tr>
      </thead>
      <tbody>
        {snapshot.sessions.map((session) => (
          <tr
            key={session.id}
            className="border-b border-zinc-900 hover:bg-zinc-900/50"
          >
            <td className="py-2 pr-4">
              <StatusBadge status={session.status} />
            </td>
            <td className="py-2 pr-4 font-medium text-zinc-200">
              {session.model ?? "—"}
            </td>
            <td className="py-2 pr-4 tabular-nums text-zinc-400">
              {session.context
                ? `${Math.round(session.context.pct * 100)}%`
                : "—"}
            </td>
            <td className="py-2 pr-4 font-mono text-xs text-zinc-400">
              {session.id}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
