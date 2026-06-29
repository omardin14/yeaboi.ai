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
import { AppShell, type Tab } from "@/components/app-shell";
import { Monitor } from "@/components/monitor";
import { PrView } from "@/components/pr-view";
import { WorktreeBoard } from "@/components/worktree-board";
import { SessionDetail } from "@/components/session-detail";
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
  const [tab, setTab] = useState<Tab>("monitor");
  const [detailId, setDetailId] = useState<string | null>(null);

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

  // Re-resolved each render so the panel tracks live data and closes itself if
  // the session disappears from the snapshot.
  const detailSession =
    snapshot?.sessions.find((s) => s.id === detailId) ?? null;
  const updatedAt =
    snapshot && snapshot.generated_at_ms > 0
      ? new Date(snapshot.generated_at_ms).toLocaleTimeString()
      : "—";

  return (
    <AppShell
      tab={tab}
      onTab={setTab}
      totals={snapshot?.totals}
      updatedAt={updatedAt}
    >
      {error && (
        <div className="mb-4 rounded-lg border border-danger-ring bg-danger-fill px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {tab === "monitor" ? (
        <div className="mx-auto max-w-6xl">
          <WarningsBanner warnings={snapshot?.warnings ?? []} />
          <Monitor
            snapshot={snapshot}
            onKill={(session) => setPending({ kind: "kill", session })}
            onFreePort={(port) => setPending({ kind: "free", port })}
            onSelect={(session) => setDetailId(session.id)}
          />
          {detailSession && (
            <SessionDetail
              session={detailSession}
              onClose={() => setDetailId(null)}
            />
          )}
        </div>
      ) : tab === "prs" ? (
        <div className="mx-auto max-w-5xl">
          <PrView projects={snapshot?.projects ?? []} />
        </div>
      ) : (
        <div className="mx-auto max-w-5xl">
          <WorktreeBoard projects={snapshot?.projects ?? []} />
        </div>
      )}

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
                <span className="font-mono text-ink">
                  {pending.session.pid}
                </span>
                .
              </p>
              <p className="font-mono text-ink-muted">
                {pending.session.model ?? "—"} · {pending.session.cwd}
              </p>
            </div>
          ) : (
            <p>
              Sends <span className="font-mono">SIGTERM</span> to pid{" "}
              <span className="font-mono text-ink">{pending.port.pid}</span>{" "}
              holding <span className="font-mono">:{pending.port.number}</span>.
            </p>
          )}
        </ConfirmDialog>
      )}
    </AppShell>
  );
}

export default App;
