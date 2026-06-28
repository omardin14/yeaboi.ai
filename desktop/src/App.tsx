import { useEffect, useState } from "react";
import type { UnlistenFn } from "@tauri-apps/api/event";
import type { Snapshot } from "@/lib/bindings/Snapshot";
import {
  getSnapshot,
  subscribeSnapshot,
  subscribeSnapshotError,
} from "@/lib/api";
import { Monitor } from "@/components/monitor";
import { WarningsBanner } from "@/components/warnings-banner";

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

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

        <Monitor snapshot={snapshot} />
      </div>
    </main>
  );
}

export default App;
