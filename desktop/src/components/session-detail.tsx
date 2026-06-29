import { useEffect, useState } from "react";
import type { Session } from "@/lib/bindings/Session";
import type { TranscriptEvent } from "@/lib/bindings/TranscriptEvent";
import { sessionTranscript, workingDiff } from "@/lib/api";
import { Drawer } from "@/components/ui/dialog";
import { Card } from "@/components/ui/card";
import { cx } from "@/components/ui/cx";

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
    <Drawer onClose={onClose} ariaLabel={`Session ${session.id}`}>
      <header className="mb-3 flex items-baseline justify-between">
        <h3 className="font-mono text-sm text-ink">
          {session.model ?? "—"} · {session.branch ?? "—"}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close detail"
          className="rounded-md px-2 py-0.5 text-xs text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink-soft"
        >
          ✕
        </button>
      </header>

      <p className="mb-3 font-mono text-xs text-ink-faint">{session.cwd}</p>

      <nav className="mb-3 flex gap-1 text-xs">
        {(["diff", "transcript"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cx(
              "rounded-md px-2 py-1 transition-colors",
              tab === t
                ? "bg-burgundy text-on-burgundy"
                : "text-ink-muted hover:bg-surface-sunken hover:text-ink-soft",
            )}
          >
            {t === "diff" ? "Working diff" : "Transcript"}
          </button>
        ))}
      </nav>

      {error && <p className="mb-2 text-xs text-danger">{error}</p>}

      {tab === "diff" &&
        (diff == null ? (
          <p className="text-xs text-ink-muted">Loading diff…</p>
        ) : diff.trim() === "" ? (
          <p className="text-xs text-ink-muted">No uncommitted changes.</p>
        ) : (
          <Card tone="sunken" pad="sm" className="max-h-[70vh] overflow-auto">
            <pre className="text-xs leading-relaxed text-ink-soft">{diff}</pre>
          </Card>
        ))}

      {tab === "transcript" &&
        (events == null ? (
          <p className="text-xs text-ink-muted">Loading transcript…</p>
        ) : events.length === 0 ? (
          <p className="text-xs text-ink-muted">No transcript entries.</p>
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
                className="flex-1 accent-[var(--burgundy)]"
              />
              <span className="font-mono text-xs text-ink-muted">
                {pos + 1}/{events.length}
              </span>
            </div>
            <Card tone="sunken" pad="sm">
              <span className="mr-2 rounded-md bg-surface px-1.5 font-mono text-xs text-idle">
                {events[pos].kind}
              </span>
              <span className="text-xs text-ink-soft">{events[pos].summary}</span>
            </Card>
          </div>
        ))}
    </Drawer>
  );
}
