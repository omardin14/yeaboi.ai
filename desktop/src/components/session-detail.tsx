import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import type { Session } from "@/lib/bindings/Session";
import type { TranscriptEvent } from "@/lib/bindings/TranscriptEvent";
import { sessionTranscript, workingDiff } from "@/lib/api";
import { formatAgo, formatClock, formatDay, humanTokens, isoMs } from "@/lib/format";
import { Drawer } from "@/components/ui/dialog";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";

const INITIAL_LIMIT = 200;
const PAGE = 400;

/** Drop the `claude-` prefix for a compact model label. */
function shortModel(m: string): string {
  return m.replace(/^claude-/, "");
}

/** `opus-4-8 · 6k→240 tok` metadata for an assistant turn (or ""). */
function metaLine(ev: TranscriptEvent): string {
  const parts: string[] = [];
  if (ev.model) parts.push(shortModel(ev.model));
  if (ev.out_tokens > 0) {
    parts.push(`${humanTokens(ev.in_tokens)}→${humanTokens(ev.out_tokens)} tok`);
  }
  return parts.join(" · ");
}

/** Time + speaker line shared by every entry. */
function EntryHead({
  at,
  align,
  children,
}: {
  at: string;
  align?: "end";
  children: ReactNode;
}) {
  const clock = formatClock(at);
  return (
    <div
      className={cx(
        "mb-0.5 flex items-center gap-2 text-[10px] text-ink-faint",
        align === "end" && "justify-end",
      )}
    >
      {clock && (
        <span className="font-mono" title={formatAgo(isoMs(at))}>
          {clock}
        </span>
      )}
      {children}
    </div>
  );
}

/** One transcript entry, styled by speaker: you (right) / assistant (left) /
 *  tool calls + results (mono cards, expanded) / thinking (collapsible). */
function ChatEntry({ ev }: { ev: TranscriptEvent }) {
  switch (ev.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div className="max-w-[85%]">
            <EntryHead at={ev.at} align="end">
              <span className="font-semibold uppercase tracking-wide text-idle">You</span>
            </EntryHead>
            <div className="whitespace-pre-wrap break-words rounded-2xl rounded-tr-sm bg-burgundy-tint px-3 py-2 text-sm text-ink">
              {ev.text}
            </div>
          </div>
        </div>
      );
    case "assistant": {
      const meta = metaLine(ev);
      return (
        <div className="flex justify-start">
          <div className="max-w-[85%]">
            <EntryHead at={ev.at}>
              <span className="font-semibold uppercase tracking-wide text-busy">Assistant</span>
              {meta && <span className="font-mono normal-case">{meta}</span>}
            </EntryHead>
            <div className="whitespace-pre-wrap break-words rounded-2xl rounded-tl-sm border border-line bg-surface px-3 py-2 text-sm text-ink-soft">
              {ev.text}
            </div>
          </div>
        </div>
      );
    }
    case "thinking":
      return (
        <details className="group/d ml-2">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-[10px] text-ink-faint [&::-webkit-details-marker]:hidden">
            <span className="transition-transform group-open/d:rotate-90">▶</span>
            {formatClock(ev.at) && (
              <span className="font-mono" title={formatAgo(isoMs(ev.at))}>
                {formatClock(ev.at)}
              </span>
            )}
            <span className="font-semibold uppercase tracking-wide text-merge">💭 Thinking</span>
          </summary>
          <p className="mt-1 whitespace-pre-wrap break-words pl-4 text-xs leading-relaxed text-ink-muted">
            {ev.text}
          </p>
        </details>
      );
    case "tool_use":
    case "tool_result": {
      const isCall = ev.kind === "tool_use";
      return (
        <div className="ml-2">
          <EntryHead at={ev.at}>
            <span className="font-semibold uppercase tracking-wide text-ink-muted">
              {isCall ? "⚙ Tool call" : "↩ Tool result"}
            </span>
          </EntryHead>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-line-strong bg-surface-sunken px-2.5 py-1.5 font-mono text-[11px] leading-relaxed text-ink-soft">
            {ev.text}
          </pre>
        </div>
      );
    }
    default:
      return null;
  }
}

function DayDivider({ label }: { label: string }) {
  return (
    <div className="my-1 flex items-center gap-2">
      <div className="h-px flex-1 bg-line" />
      <span className="font-mono text-[10px] uppercase tracking-wide text-ink-faint">{label}</span>
      <div className="h-px flex-1 bg-line" />
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
  const [limit, setLimit] = useState(INITIAL_LIMIT);
  const [reachedStart, setReachedStart] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const readerEndRef = useRef<HTMLDivElement>(null);
  const scrolledRef = useRef(false);

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

  // Reset paging + scroll state when switching sessions.
  useEffect(() => {
    setEvents(null);
    setLimit(INITIAL_LIMIT);
    setReachedStart(false);
    scrolledRef.current = false;
  }, [session.id]);

  // (Re)load the transcript whenever the session or the page size changes.
  useEffect(() => {
    let active = true;
    setLoading(true);
    sessionTranscript(session.id, limit)
      .then((ev) => {
        if (!active) return;
        setEvents(ev);
        setReachedStart(ev.length < limit); // got fewer than asked → at the start
      })
      .catch((e) => active && setError(`Could not load transcript: ${e}`))
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [session.id, limit]);

  // Jump to the latest turn on first load (not when paging in earlier history).
  useEffect(() => {
    if (tab === "transcript" && events && events.length > 0 && !scrolledRef.current) {
      readerEndRef.current?.scrollIntoView?.({ block: "end" });
      scrolledRef.current = true;
    }
  }, [tab, events]);

  let prevDay = "";

  return (
    <Drawer onClose={onClose} ariaLabel={`Session ${session.id}`} className="max-w-3xl">
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
          <Card tone="sunken" pad="sm" className="max-h-[80vh] overflow-auto">
            <pre className="text-xs leading-relaxed text-ink-soft">{diff}</pre>
          </Card>
        ))}

      {tab === "transcript" &&
        (events == null ? (
          <p className="text-xs text-ink-muted">Loading transcript…</p>
        ) : events.length === 0 ? (
          <p className="text-xs text-ink-muted">No transcript entries.</p>
        ) : (
          <Card tone="sunken" pad="sm" className="max-h-[80vh] space-y-2.5 overflow-auto">
            {!reachedStart && (
              <div className="flex justify-center pb-1">
                <Button variant="ghost" size="sm" disabled={loading} onClick={() => setLimit((l) => l + PAGE)}>
                  {loading ? "Loading…" : "△ Load earlier"}
                </Button>
              </div>
            )}
            {events.map((ev, i) => {
              const day = formatDay(ev.at);
              const showDay = day !== "" && day !== prevDay;
              if (day) prevDay = day;
              return (
                <Fragment key={i}>
                  {showDay && <DayDivider label={day} />}
                  <ChatEntry ev={ev} />
                </Fragment>
              );
            })}
            <div ref={readerEndRef} />
          </Card>
        ))}
    </Drawer>
  );
}
