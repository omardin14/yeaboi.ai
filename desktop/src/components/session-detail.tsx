import { useEffect, useRef, useState } from "react";
import type { Session } from "@/lib/bindings/Session";
import type { TranscriptEvent } from "@/lib/bindings/TranscriptEvent";
import { sessionTranscript, workingDiff } from "@/lib/api";
import { Drawer } from "@/components/ui/dialog";
import { Card } from "@/components/ui/card";
import { cx } from "@/components/ui/cx";

/** Left-rule color per transcript turn kind, so the reader scans at a glance. */
function kindRail(kind: string): string {
  switch (kind) {
    case "user":
      return "border-l-idle";
    case "assistant":
      return "border-l-busy";
    case "thinking":
      return "border-l-merge";
    default:
      return "border-l-line-strong";
  }
}

/** Detail panel for one session: metadata + working diff + transcript reader. */
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
  const [error, setError] = useState<string | null>(null);
  const readerEndRef = useRef<HTMLDivElement>(null);

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
    sessionTranscript(session.id)
      .then((ev) => active && setEvents(ev))
      .catch((e) => active && setError(`Could not load transcript: ${e}`));
    return () => {
      active = false;
    };
  }, [session.id]);

  // Jump to the latest turn once the transcript renders (most recent is last).
  useEffect(() => {
    if (tab === "transcript" && events && events.length > 0) {
      // Optional-call: jsdom doesn't implement scrollIntoView.
      readerEndRef.current?.scrollIntoView?.({ block: "end" });
    }
  }, [tab, events]);

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
          <Card tone="sunken" pad="sm" className="max-h-[70vh] space-y-3 overflow-auto">
            {events.map((ev, i) => (
              <div key={i} className={cx("border-l-2 pl-2.5", kindRail(ev.kind))}>
                <div className="mb-0.5 font-mono text-[10px] uppercase tracking-wide text-ink-faint">
                  {ev.kind}
                </div>
                <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-ink-soft">
                  {ev.text || ev.summary}
                </p>
              </div>
            ))}
            <div ref={readerEndRef} />
          </Card>
        ))}
    </Drawer>
  );
}
