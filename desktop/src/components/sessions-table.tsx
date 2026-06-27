import type { Snapshot } from "@/lib/bindings/Snapshot";

const STATUS_STYLES: Record<string, string> = {
  busy: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  idle: "bg-rose-500/15 text-rose-400 ring-rose-500/30",
};

function StatusBadge({ status }: { status: string }) {
  const style =
    STATUS_STYLES[status] ?? "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30";
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
 * trivially testable. Phase 1 replaces this with the grouped project tree.
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
          <th className="py-2 pr-4 font-medium">Project</th>
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
              {session.project}
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
