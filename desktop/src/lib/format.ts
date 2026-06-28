// Small presentational helpers shared by the monitor components. Pure
// functions of the snapshot data so they're trivially unit-testable.

import type { ActivityStatus } from "@/lib/bindings/ActivityStatus";
import type { HostApp } from "@/lib/bindings/HostApp";

/** Human label for an activity status. */
export function statusLabel(status: ActivityStatus): string {
  return status; // "Busy" | "Idle" | "Dead" | "Unknown"
}

/** Tailwind ring/badge classes per status. */
export function statusBadgeClass(status: ActivityStatus): string {
  switch (status) {
    case "Busy":
      return "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30";
    case "Idle":
      return "bg-sky-500/15 text-sky-400 ring-sky-500/30";
    case "Dead":
      return "bg-zinc-600/15 text-zinc-500 ring-zinc-600/30";
    default:
      return "bg-amber-500/15 text-amber-400 ring-amber-500/30";
  }
}

/** Format bytes as a compact MB/GB string. */
export function formatMem(bytes: number): string {
  if (bytes <= 0) return "—";
  const mb = bytes / 1_048_576;
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

/** Format a 0–1 fraction as an integer percent, or "—" when undefined. */
export function formatPct(fraction: number | null | undefined): string {
  if (fraction == null) return "—";
  return `${Math.round(fraction * 100)}%`;
}

/** Format CPU usage (already a percent that can exceed 100 across cores). */
export function formatCpu(pct: number | null | undefined): string {
  if (pct == null) return "—";
  return `${Math.round(pct)}%`;
}

/** Format an uptime in seconds as a compact `1d 2h` / `3h 4m` / `5m` string. */
export function formatUptime(secs: number | null | undefined): string {
  if (secs == null || secs <= 0) return "—";
  const d = Math.floor(secs / 86_400);
  const h = Math.floor((secs % 86_400) / 3_600);
  const m = Math.floor((secs % 3_600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/**
 * Heat color (green → amber → red) for a 0–1 intensity, used on context % and
 * CPU. `null` intensity renders muted.
 */
export function heatClass(intensity: number | null | undefined): string {
  if (intensity == null) return "text-zinc-500";
  if (intensity >= 0.9) return "text-rose-400";
  if (intensity >= 0.7) return "text-amber-400";
  if (intensity >= 0.4) return "text-yellow-400";
  return "text-emerald-400";
}

/** Short host-app label. */
export function hostAppLabel(host: HostApp): string {
  if (host === "Cli") return "cli";
  if (host === "VsCode") return "vscode";
  if (typeof host === "object" && "Other" in host) return host.Other;
  return "—";
}
