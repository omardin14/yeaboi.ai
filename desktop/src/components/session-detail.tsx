import { useEffect, useState } from "react";
import type { Session } from "@/lib/bindings/Session";
import type { TranscriptEvent } from "@/lib/bindings/TranscriptEvent";
import { sessionTranscript, workingDiff } from "@/lib/api";

/** Detail panel for one session: metadata + working diff + transcript replay. */
export function SessionDetail({
  session,
  onClose,
}: {
  session: Session;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"diff" | "transcript">("diff");
  const [diff, setDiff] = useState<string | null>(null);
  const [events, setEvents] = useState<TranscriptEvent[] | null>(null);
  const [pos, setPos] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setDiff(null);
    setError(null);
    workingDiff(session.cwd)
      .then((d) => active && setDiff(d))
      .catch((e) => active && setError(`Could not load diff: ${e}`));
    return () => {
      active = false;
    };
  }, [session.cwd]);

  useEffect(() => {
    let active = true;
    setEvents(null);
    setPos(0);
    sessionTranscript(session.id)
      .then((ev) => {
        if (!active) return;
        setEvents(ev);
        setPos(ev.length > 0 ? ev.length - 1 : 0);
      })
      .catch((e) => active && setError(`Could not load transcript: ${e}`));
    return () => {
      active = false;
    };
  }, [session.id]);

  return (
    <aside className="mt-5 rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <header className="mb-3 flex items-baseline justify-between">
        <h3 className="font-mono text-sm text-zinc-200">
          {session.model ?? "—"} · {session.branch ?? "—"}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close detail"
          className="rounded px-2 py-0.5 text-xs text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
        >
          ✕
        </button>
      </header>

      <p className="mb-3 font-mono text-xs text-zinc-500">{session.cwd}</p>

      <nav className="mb-3 flex gap-1 text-xs">
        {(["diff", "transcript"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded px-2 py-1 ${
              tab === t ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {t === "diff" ? "Working diff" : "Transcript"}
          </button>
        ))}
      </nav>

      {error && <p className="mb-2 text-xs text-rose-400">{error}</p>}

      {tab === "diff" &&
        (diff == null ? (
          <p className="text-xs text-zinc-500">Loading diff…</p>
        ) : diff.trim() === "" ? (
          <p className="text-xs text-zinc-500">No uncommitted changes.</p>
        ) : (
          <pre className="max-h-80 overflow-auto rounded bg-zinc-900 p-3 text-xs text-zinc-300">
            {diff}
          </pre>
        ))}

      {tab === "transcript" &&
        (events == null ? (
          <p className="text-xs text-zinc-500">Loading transcript…</p>
        ) : events.length === 0 ? (
          <p className="text-xs text-zinc-500">No transcript entries.</p>
        ) : (
          <div>
            <div className="mb-2 flex items-center gap-2">
              <input
                type="range"
                aria-label="Transcript position"
                min={0}
                max={events.length - 1}
                value={pos}
                onChange={(e) => setPos(Number(e.target.value))}
                className="flex-1"
              />
              <span className="font-mono text-xs text-zinc-500">
                {pos + 1}/{events.length}
              </span>
            </div>
            <div className="rounded bg-zinc-900 p-3">
              <span className="mr-2 rounded bg-zinc-800 px-1 font-mono text-xs text-sky-300">
                {events[pos].kind}
              </span>
              <span className="text-xs text-zinc-300">{events[pos].summary}</span>
            </div>
          </div>
        ))}
    </aside>
  );
}
