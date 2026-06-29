import { useEffect, useRef, useState } from "react";
import type { Session } from "@/lib/bindings/Session";
import type { TranscriptEvent } from "@/lib/bindings/TranscriptEvent";
import { sessionTranscript, workingDiff } from "@/lib/api";
import { formatAgo, formatClock, isoMs } from "@/lib/format";
import { Drawer } from "@/components/ui/dialog";
import { Card } from "@/components/ui/card";
import { cx } from "@/components/ui/cx";

type Meta = { label: string; icon: string; heavy: boolean; rail: string; tone: string };

/** Speaker label, icon, rail color, and whether the entry is collapsed-by-default. */
function kindMeta(kind: string): Meta {
  switch (kind) {
    case "user":
      return { label: "You", icon: "", heavy: false, rail: "border-l-idle", tone: "text-idle" };
    case "assistant":
      return { label: "Assistant", icon: "", heavy: false, rail: "border-l-busy", tone: "text-busy" };
    case "thinking":
      return { label: "Thinking", icon: "💭", heavy: true, rail: "border-l-merge", tone: "text-merge" };
    case "tool_use":
      return { label: "Tool call", icon: "⚙", heavy: true, rail: "border-l-line-strong", tone: "text-ink-muted" };
    case "tool_result":
      return { label: "Tool result", icon: "↩", heavy: true, rail: "border-l-line-strong", tone: "text-ink-muted" };
    default:
      return { label: "System", icon: "·", heavy: true, rail: "border-l-line-strong", tone: "text-ink-faint" };
  }
}

/** One transcript entry: time + speaker, text inline, heavy entries collapsed. */
function TranscriptTurn({ ev }: { ev: TranscriptEvent }) {
  const meta = kindMeta(ev.kind);
  const clock = formatClock(ev.at);
  const ago = formatAgo(isoMs(ev.at));

  const header = (
    <div className="flex items-center gap-2 text-[10px]">
      {clock && (
        <span className="font-mono text-ink-faint" title={ago}>
          {clock}
        </span>
      )}
      <span className={cx("font-semibold uppercase tracking-wide", meta.tone)}>
        {meta.icon && `${meta.icon} `}
        {meta.label}
      </span>
    </div>
  );

  return (
    <div className={cx("border-l-2 pl-2.5", meta.rail)}>
      {meta.heavy ? (
        <details className="group/d">
          <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
            <span className="shrink-0 text-[9px] text-ink-faint transition-transform group-open/d:rotate-90">
              ▶
            </span>
            <div className="min-w-0 flex-1">
              {header}
              <span className="block truncate text-xs text-ink-muted">{ev.summary}</span>
            </div>
          </summary>
          <p className="mt-1 whitespace-pre-wrap break-words pl-4 text-xs leading-relaxed text-ink-soft">
            {ev.text}
          </p>
        </details>
      ) : (
        <>
          {header}
          <p className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-relaxed text-ink-soft">
            {ev.text || ev.summary}
          </p>
        </>
      )}
    </div>
  );
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
              <TranscriptTurn key={i} ev={ev} />
            ))}
            <div ref={readerEndRef} />
          </Card>
        ))}
    </Drawer>
  );
}
