import { useEffect, useState } from "react";
import type { UnlistenFn } from "@tauri-apps/api/event";
import type { Snapshot } from "@/lib/bindings/Snapshot";
import type { Session } from "@/lib/bindings/Session";
import type { Port } from "@/lib/bindings/Port";
import {
  getSnapshot,
  killSession,
  freePort,
  subscribeSnapshot,
  subscribeSnapshotError,
} from "@/lib/api";
import { Monitor } from "@/components/monitor";
import { WarningsBanner } from "@/components/warnings-banner";
import { ConfirmDialog } from "@/components/confirm-dialog";

/** A destructive action awaiting confirmation. */
type Pending =
  | { kind: "kill"; session: Session }
  | { kind: "free"; port: Port };

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);

  async function confirmPending() {
    const action = pending;
    setPending(null);
    if (action == null) return; // nothing selected — benign

    if (action.kind === "kill") {
      const pid = action.session.pid;
      if (pid == null) {
        // The stop button shouldn't appear for a pid-less session, so reaching
        // here is a bug — surface it, never silently no-op.
        setError("Cannot stop a session with no PID — please report this.");
        return;
      }
      try {
        await killSession(pid);
      } catch (e) {
        setError(`Failed to stop session ${pid}: ${e}`);
      }
    } else {
      try {
        await freePort(action.port.pid);
      } catch (e) {
        setError(`Failed to free port :${action.port.number}: ${e}`);
      }
    }
  }

  useEffect(() => {
    // Outside Tauri (e.g. plain `vite` in a browser) the IPC bridge is absent —
    // stay idle without treating that as an error. Any *other* failure below is
    // a real fault and is surfaced, not swallowed.
    const inTauri =
      typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
    if (!inTauri) return;

    getSnapshot()
      .then(setSnapshot)
      .catch((e) => setError(`Failed to load snapshot: ${e}`));

    const unlisteners: UnlistenFn[] = [];
    subscribeSnapshot((snap) => {
      setSnapshot(snap);
      setError(null); // a fresh frame means the stream recovered
    })
      .then((stop) => unlisteners.push(stop))
      .catch((e) => setError(`Live updates unavailable: ${e}`));
    subscribeSnapshotError((message) =>
      setError(`Live updates stopped: ${message}`),
    )
      .then((stop) => unlisteners.push(stop))
      .catch((e) => setError(`Live updates unavailable: ${e}`));

    return () => unlisteners.forEach((stop) => stop());
  }, []);

  const totals = snapshot?.totals;
  const updatedAt =
    snapshot && snapshot.generated_at_ms > 0
      ? new Date(snapshot.generated_at_ms).toLocaleTimeString()
      : "—";

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <header className="mb-6 flex items-baseline justify-between border-b border-zinc-800 pb-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">yeaboi.ai</h1>
            <p className="text-xs text-zinc-500">live monitor</p>
          </div>
          <div className="text-right text-xs text-zinc-500">
            <div>
              {totals
                ? `${totals.session_count} session(s) · ${totals.busy_count} busy · ${totals.project_count} project(s)`
                : "connecting…"}
            </div>
            <div>updated {updatedAt}</div>
          </div>
        </header>

        {error && (
          <div className="mb-4 rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-400">
            {error}
          </div>
        )}

        <WarningsBanner warnings={snapshot?.warnings ?? []} />

        <Monitor
          snapshot={snapshot}
          onKill={(session) => setPending({ kind: "kill", session })}
          onFreePort={(port) => setPending({ kind: "free", port })}
        />
      </div>

      {pending && (
        <ConfirmDialog
          open
          title={
            pending.kind === "kill"
              ? "Stop this session?"
              : `Free port :${pending.port.number}?`
          }
          confirmLabel={
            pending.kind === "kill" ? "Stop (SIGTERM)" : "Free (SIGTERM)"
          }
          danger
          onConfirm={() => {
            void confirmPending();
          }}
          onCancel={() => setPending(null)}
        >
          {pending.kind === "kill" ? (
            <div className="space-y-1">
              <p>
                Sends <span className="font-mono">SIGTERM</span> to pid{" "}
                <span className="font-mono text-zinc-200">
                  {pending.session.pid}
                </span>
                .
              </p>
              <p className="font-mono text-zinc-400">
                {pending.session.model ?? "—"} · {pending.session.cwd}
              </p>
            </div>
          ) : (
            <p>
              Sends <span className="font-mono">SIGTERM</span> to pid{" "}
              <span className="font-mono text-zinc-200">
                {pending.port.pid}
              </span>{" "}
              holding <span className="font-mono">:{pending.port.number}</span>.
            </p>
          )}
        </ConfirmDialog>
      )}
    </main>
  );
}

export default App;
