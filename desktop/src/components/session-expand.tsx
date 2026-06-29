import { useEffect, useState, type ReactNode } from "react";
import type { Session } from "@/lib/bindings/Session";
import type { Port } from "@/lib/bindings/Port";
import { sessionTranscript } from "@/lib/api";
import {
  formatAgo,
  formatCpu,
  formatMem,
  formatPct,
  formatUptime,
  hostAppLabel,
} from "@/lib/format";
import { useMonitorPrefs, type MetricId } from "@/lib/monitor-prefs";
import type { SessionMetric } from "@/lib/session-metrics";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Gauge } from "@/components/ui/gauge";
import { Section } from "@/components/ui/collapsible";
import { StatusBadge } from "@/components/ui/badge";
import { InfoDot } from "@/components/ui/tooltip";
import { Sparkline } from "@/components/ui/sparkline";
import { PortChips } from "@/components/port-chips";

type Prefs = ReturnType<typeof useMonitorPrefs>;

const METRIC_INFO: Record<MetricId, string> = {
  cpu: "CPU use of this process, averaged over recent samples so it doesn't flicker.",
  mem: "Resident memory this process is currently holding.",
  uptime: "How long this process has been running.",
  pid: "Operating-system process id — what a stop signal targets.",
  host: "Where the session runs: CLI, VS Code, or another host app.",
};

const METRIC_LABEL: Record<MetricId, string> = {
  cpu: "CPU",
  mem: "Memory",
  uptime: "Uptime",
  pid: "PID",
  host: "Host",
};

/** A single labeled metric line: label + ⓘ, then a right-aligned value cell. */
function Metric({
  id,
  children,
}: {
  id: MetricId;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <span className="flex w-20 shrink-0 items-center gap-1 text-xs text-ink-muted">
        {METRIC_LABEL[id]}
        <InfoDot label={METRIC_INFO[id]} />
      </span>
      <span className="flex flex-1 items-center gap-2 font-mono text-xs tabular-nums text-ink-soft">
        {children}
      </span>
    </div>
  );
}

/** The gear popover that toggles which Resources metrics are shown. */
function MetricToggles({ prefs }: { prefs: Prefs }) {
  const ids: MetricId[] = ["cpu", "mem", "uptime", "pid", "host"];
  return (
    <details className="relative">
      <summary className="flex cursor-pointer list-none items-center rounded-md px-1.5 py-0.5 text-xs text-ink-faint transition-colors hover:bg-surface-sunken hover:text-ink-muted marker:hidden">
        ⚙ shown
      </summary>
      <div className="absolute right-0 z-20 mt-1 w-44 rounded-lg border border-line bg-overlay p-2 text-xs shadow-lg">
        {ids.map((id) => (
          <label
            key={id}
            className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-ink-soft hover:bg-surface-sunken"
          >
            <input
              type="checkbox"
              checked={!prefs.isHidden(id)}
              onChange={() => prefs.toggleMetric(id)}
              className="accent-[var(--burgundy)]"
            />
            {METRIC_LABEL[id]}
          </label>
        ))}
      </div>
    </details>
  );
}

/**
 * The inline expanded detail for one session: calm, labeled, collapsible
 * sections with per-metric explanations. The heavy stuff (full transcript +
 * working diff) lives behind "Full detail ↗", which opens the side drawer.
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
  const prefs = useMonitorPrefs();
  const [fullPrompt, setFullPrompt] = useState<string | null>(null);

  // Lazily fetch the untruncated current prompt: the latest `user` event. Tool
  // results are now their own `tool_result` kind, so the most recent `user`
  // entry is genuinely what the human typed. Falls back to the (truncated) row
  // prompt while loading or if none is found.
  useEffect(() => {
    let active = true;
    setFullPrompt(null);
    sessionTranscript(session.id)
      .then((events) => {
        if (!active) return;
        const latest = [...events]
          .reverse()
          .find((e) => e.kind === "user" && e.text.trim() !== "");
        if (latest) setFullPrompt(latest.text);
      })
      .catch(() => {
        /* fall back to last_prompt — not worth a toast on the inline panel */
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

  const sec = (id: Parameters<Prefs["isCollapsed"]>[0]) => ({
    open: !prefs.isCollapsed(id),
    onOpenChange: () => prefs.toggleSection(id),
  });

  return (
    <Card
      tone="sunken"
      pad="sm"
      role="region"
      aria-label={`Details for ${session.id}`}
      className="mb-1 ml-[34px] space-y-3"
      onClick={(e) => e.stopPropagation()}
    >
      {/* Activity */}
      <Section label="Activity" {...sec("activity")}>
        <div className="space-y-2">
          <div>
            <div className="mb-0.5 flex items-center gap-1 text-[11px] text-ink-faint">
              Latest prompt
              <InfoDot label="The most recent prompt sent in this session." />
            </div>
            <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-ink-soft">
              {prompt || "—"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-ink-muted">
            <StatusBadge status={session.status} />
            <span>started {formatAgo(session.started_at_ms)}</span>
            <span className="flex items-center gap-1">
              active {formatAgo(session.updated_at_ms)}
              <InfoDot label="Time since the last observed transcript activity." />
            </span>
          </div>
        </div>
      </Section>

      {/* Resources */}
      <Section
        label="Resources"
        {...sec("resources")}
        action={<MetricToggles prefs={prefs} />}
      >
        {!ps && (
          <p className="mb-1 text-[11px] text-ink-faint">
            No live process (e.g. a remote Codex thread).
          </p>
        )}
        {!prefs.isHidden("cpu") && (
          <Metric id="cpu">
            {formatCpu(cpuValue)}
            <Sparkline data={metric?.cpu.history ?? []} />
          </Metric>
        )}
        {!prefs.isHidden("mem") && (
          <Metric id="mem">
            {formatMem(memValue ?? 0)}
            <Sparkline data={metric?.mem.history ?? []} />
          </Metric>
        )}
        {!prefs.isHidden("uptime") && (
          <Metric id="uptime">{formatUptime(ps?.uptime_secs)}</Metric>
        )}
        {!prefs.isHidden("pid") && <Metric id="pid">{session.pid ?? "—"}</Metric>}
        {!prefs.isHidden("host") && (
          <Metric id="host">{hostAppLabel(session.host_app)}</Metric>
        )}
      </Section>

      {/* Context */}
      <Section label="Context" {...sec("context")}>
        <div className="flex items-center gap-3">
          <Gauge value={ctx} size={28} title={`context ${formatPct(ctx)}`} />
          <div className="font-mono text-xs text-ink-soft">
            <div className="flex items-center gap-1">
              {session.context
                ? `${formatTokens(session.context.used)} / ${formatTokens(session.context.window)} tokens`
                : "no reading"}
              <InfoDot label="Input + cached tokens occupying the model's context window right now." />
            </div>
            <div className="text-[11px] text-ink-faint">{formatPct(ctx)} of window used</div>
          </div>
        </div>
      </Section>

      {/* Network */}
      <Section label="Network" {...sec("network")}>
        {session.ports.length > 0 ? (
          <PortChips ports={session.ports} onFreePort={onFreePort} />
        ) : (
          <p className="text-[11px] text-ink-faint">No listening ports.</p>
        )}
      </Section>

      {/* Agents */}
      <Section label="Agents" {...sec("agents")}>
        <div className="flex items-center gap-1 font-mono text-xs text-ink-soft">
          {session.sub_agent_count > 0
            ? `${session.sub_agent_count} sub-agent${session.sub_agent_count === 1 ? "" : "s"}`
            : "none"}
          <InfoDot label="Sidechain / sub-agent activity seen in this session's transcript." />
        </div>
      </Section>

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
