import { useEffect, useState } from "react";
import type { Session } from "@/lib/bindings/Session";
import type { Port } from "@/lib/bindings/Port";
import type { SubAgent } from "@/lib/bindings/SubAgent";
import { sessionSubAgents, sessionTranscript } from "@/lib/api";
import {
  formatAgo,
  formatCpu,
  formatMem,
  formatPct,
  formatUptime,
  heatClass,
  hostAppLabel,
} from "@/lib/format";
import type { SessionMetric } from "@/lib/session-metrics";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Gauge } from "@/components/ui/gauge";
import { StatusBadge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { Tile } from "@/components/ui/tile";
import { PortChips } from "@/components/port-chips";

/** Count sub-agents by type, most frequent first. */
function agentCounts(agents: SubAgent[]): [string, number][] {
  const m = new Map<string, number>();
  for (const a of agents) {
    const k = a.kind || "agent";
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

const EYEBROW = "text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-faint";

/**
 * The inline expanded detail for one session: a strip of raised vitals tiles,
 * the latest prompt as a hero, a compact meta line, and a contained agents
 * panel. Heavy reading (full transcript + diff) lives behind "Full detail ↗".
 */
export function SessionExpand({
  session,
  metric,
  onSelect,
  onFreePort,
}: {
  session: Session;
  metric: SessionMetric | undefined;
  onSelect?: (session: Session) => void;
  onFreePort?: (port: Port) => void;
}) {
  const [fullPrompt, setFullPrompt] = useState<string | null>(null);
  const [subAgents, setSubAgents] = useState<SubAgent[] | null>(null);

  // Lazily fetch the session's sub-agents (Task/Agent calls) — type, task, and
  // whether the result has returned — scanned from the whole transcript.
  useEffect(() => {
    let active = true;
    setSubAgents(null);
    sessionSubAgents(session.id)
      .then((a) => active && setSubAgents(a))
      .catch(() => {
        /* best-effort; the count still shows */
      });
    return () => {
      active = false;
    };
  }, [session.id]);

  // Lazily fetch the untruncated current prompt: the latest `user` event (tool
  // results are their own kind). Falls back to the row prompt while loading.
  useEffect(() => {
    let active = true;
    setFullPrompt(null);
    sessionTranscript(session.id, 80)
      .then((events) => {
        if (!active) return;
        const latest = [...events]
          .reverse()
          .find((e) => e.kind === "user" && e.text.trim() !== "");
        if (latest) setFullPrompt(latest.text);
      })
      .catch(() => {
        /* fall back to last_prompt */
      });
    return () => {
      active = false;
    };
  }, [session.id]);

  const ps = session.proc_stats;
  const cpuValue = metric?.cpu.value ?? ps?.cpu_pct ?? null;
  const memValue = metric?.mem.value ?? ps?.mem_bytes ?? null;
  const prompt = fullPrompt ?? session.last_prompt ?? "";
  const ctx = session.context?.pct ?? null;
  const ctxTokens = session.context
    ? `${formatTokens(session.context.used)} / ${formatTokens(session.context.window)} tokens`
    : undefined;

  const running = subAgents?.filter((a) => !a.done).length ?? 0;
  const done = subAgents?.filter((a) => a.done).length ?? 0;

  return (
    <Card
      tone="sunken"
      pad="md"
      role="region"
      aria-label={`Details for ${session.id}`}
      className="mb-1 ml-[34px] space-y-3"
      onClick={(e) => e.stopPropagation()}
    >
      {/* Vitals — raised tiles floating above the tan. */}
      <div className="flex flex-wrap gap-2">
        <Tile label="Context" title={ctxTokens}>
          <Gauge value={ctx} size={22} />
          <span className={heatClass(ctx)}>{formatPct(ctx)}</span>
        </Tile>
        <Tile label="CPU">
          {formatCpu(cpuValue)}
          {metric && <Sparkline data={metric.cpu.history} width={40} height={14} />}
        </Tile>
        <Tile label="Memory">
          {formatMem(memValue ?? 0)}
          {metric && <Sparkline data={metric.mem.history} width={40} height={14} />}
        </Tile>
        <Tile label="Uptime">{formatUptime(ps?.uptime_secs)}</Tile>
        <Tile label="Status">
          <StatusBadge status={session.status} />
        </Tile>
      </div>

      {/* Latest prompt — the hero. */}
      <div>
        <div className={`mb-1 ${EYEBROW}`}>Latest prompt</div>
        <Card tone="surface" pad="sm">
          <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-ink-soft">
            {prompt || "—"}
          </p>
        </Card>
      </div>

      {/* Meta — one quiet mono line. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-ink-muted">
        <span>started {formatAgo(session.started_at_ms)}</span>
        <span>active {formatAgo(session.updated_at_ms)}</span>
        <span>pid {session.pid ?? "—"}</span>
        <span>{hostAppLabel(session.host_app)}</span>
        {session.ports.length > 0 && (
          <PortChips ports={session.ports} onFreePort={onFreePort} />
        )}
      </div>

      {/* Agents. */}
      {session.sub_agent_count > 0 && (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span className={EYEBROW}>Agents</span>
            {subAgents == null ? (
              <span className="text-ink-faint">loading…</span>
            ) : (
              <>
                <span className="text-ink-muted">
                  <span className="font-mono tabular-nums text-ink">{subAgents.length}</span> launched
                </span>
                {running > 0 && (
                  <span className="animate-needs text-needs">{running} running</span>
                )}
                <span className="text-busy">{done} done</span>
                <span className="ml-auto flex flex-wrap gap-1">
                  {agentCounts(subAgents).map(([kind, n]) => (
                    <span
                      key={kind}
                      className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] text-merge"
                    >
                      {kind} ×{n}
                    </span>
                  ))}
                </span>
              </>
            )}
          </div>
          {subAgents && subAgents.length > 0 && (
            <Card tone="surface" pad="sm" className="max-h-56 overflow-auto">
              <ul className="space-y-1">
                {subAgents.map((a, i) => (
                  <li key={i} className="flex items-baseline gap-2 text-xs">
                    <span
                      title={a.done ? "done" : "running"}
                      className={`shrink-0 text-[10px] leading-none ${a.done ? "text-busy" : "animate-needs text-needs"}`}
                    >
                      {a.done ? "✓" : "●"}
                    </span>
                    <span className="w-24 shrink-0 truncate font-mono text-[11px] text-merge">
                      {a.kind || "agent"}
                    </span>
                    <span className="min-w-0 break-words text-ink-soft">{a.description || "—"}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}

      <div className="flex justify-end border-t border-line pt-2">
        <Button variant="ghost" size="sm" onClick={() => onSelect?.(session)}>
          Full detail ↗
        </Button>
      </div>
    </Card>
  );
}

/** Compact token count (`147k`, `1.2M`). */
function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1000)}k`;
  return `${n}`;
}
