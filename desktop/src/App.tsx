import { useEffect, useState } from "react";
import type { Snapshot } from "@/lib/bindings/Snapshot";
import { getSnapshot, subscribeSnapshot } from "@/lib/api";
import { SessionsTable } from "@/components/sessions-table";

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);

  useEffect(() => {
    // Initial fetch (typed command) + live updates (typed event).
    getSnapshot()
      .then(setSnapshot)
      .catch(() => {
        /* not running under Tauri (e.g. plain `vite`) — stay in loading state */
      });

    const unlisten = subscribeSnapshot(setSnapshot);
    return () => {
      unlisten.then((stop) => stop()).catch(() => {});
    };
  }, []);

  const updatedAt =
    snapshot && snapshot.generated_at_ms > 0
      ? new Date(snapshot.generated_at_ms).toLocaleTimeString()
      : "—";

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <header className="mb-6 flex items-baseline justify-between border-b border-zinc-800 pb-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">yeaboi.ai</h1>
            <p className="text-xs text-zinc-500">
              Phase 0 — live snapshot seam (stub data)
            </p>
          </div>
          <div className="text-right text-xs text-zinc-500">
            <div>
              {snapshot ? `${snapshot.sessions.length} session(s)` : "connecting…"}
            </div>
            <div>updated {updatedAt}</div>
          </div>
        </header>

        <SessionsTable snapshot={snapshot} />
      </div>
    </main>
  );
}

export default App;
