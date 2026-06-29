// Small presentational helpers shared across the UI. Pure functions of the
// snapshot data so they're trivially unit-testable. All color output is in
// terms of the design tokens defined in `index.css` (theme-aware).

import type { ActivityStatus } from "@/lib/bindings/ActivityStatus";
import type { HostApp } from "@/lib/bindings/HostApp";
import type { Provider } from "@/lib/bindings/Provider";
import type { Severity } from "@/lib/bindings/Severity";

/** Fill/text/ring token classes for a session status pill. */
export function statusBadgeClass(status: ActivityStatus): string {
  switch (status) {
    case "Busy":
      return "bg-busy-fill text-busy ring-busy-ring";
    case "Idle":
      return "bg-idle-fill text-idle ring-idle-ring";
    case "Dead":
      return "bg-dead-fill text-dead ring-dead-ring";
    default:
      return "bg-needs-fill text-needs ring-needs-ring";
  }
}

/** The status accent color as a CSS var (for the row status rail). */
export function statusRailVar(status: ActivityStatus): string {
  switch (status) {
    case "Busy":
      return "var(--busy)";
    case "Idle":
      return "var(--idle)";
    case "Dead":
      return "var(--dead)";
    default:
      return "var(--needs)";
  }
}

/** Fill/text/ring token classes for a PR state pill. */
export function prStateBadgeClass(state: string): string {
  switch (state) {
    case "OPEN":
      return "bg-busy-fill text-busy ring-busy-ring";
    case "MERGED":
      return "bg-merge-fill text-merge ring-merge-ring";
    case "CLOSED":
      return "bg-danger-fill text-danger ring-danger-ring";
    default:
      return "bg-dead-fill text-dead ring-dead-ring";
  }
}

/** Fill/text/ring token classes for a review-finding severity pill. */
export function severityBadgeClass(severity: Severity): string {
  switch (severity) {
    case "Critical":
      return "bg-danger-fill text-danger ring-danger-ring";
    case "Important":
      return "bg-needs-fill text-needs ring-needs-ring";
    case "Suggestion":
      return "bg-idle-fill text-idle ring-idle-ring";
    default:
      return "bg-dead-fill text-dead ring-dead-ring";
  }
}

/** A small text-color accent for the provider chip on the model cell. */
export function providerAccent(provider: Provider): string {
  return provider === "Codex" ? "text-provider-codex" : "text-provider-claude";
}

/** Format bytes as a compact MB/GB string. */
export function formatMem(bytes: number): string {
  if (bytes <= 0) return "—";
  const mb = bytes / 1_048_576;
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

/** Format a 0–1 fraction as an integer percent, or "—" when missing/non-finite. */
export function formatPct(fraction: number | null | undefined): string {
  if (fraction == null || !Number.isFinite(fraction)) return "—";
  return `${Math.round(fraction * 100)}%`;
}

/** Format CPU usage (already a percent that can exceed 100 across cores). */
export function formatCpu(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return "—";
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

/** Heat bucket (0=low … 3=crit) for a 0–1 intensity, or -1 when unknown. */
function heatBucket(intensity: number | null | undefined): number {
  if (intensity == null || !Number.isFinite(intensity)) return -1;
  if (intensity >= 0.9) return 3;
  if (intensity >= 0.7) return 2;
  if (intensity >= 0.4) return 1;
  return 0;
}

/**
 * Heat text-color token (forest → gold → burnt → brick) for a 0–1 intensity,
 * used on context % and CPU. Unknown intensity renders muted.
 */
export function heatClass(intensity: number | null | undefined): string {
  switch (heatBucket(intensity)) {
    case 3:
      return "text-heat-crit";
    case 2:
      return "text-heat-high";
    case 1:
      return "text-heat-mid";
    case 0:
      return "text-heat-low";
    default:
      return "text-ink-faint";
  }
}

/** The heat color as a CSS var (for SVG strokes like the gauge ring). */
export function heatVar(intensity: number | null | undefined): string {
  switch (heatBucket(intensity)) {
    case 3:
      return "var(--heat-crit)";
    case 2:
      return "var(--heat-high)";
    case 1:
      return "var(--heat-mid)";
    case 0:
      return "var(--heat-low)";
    default:
      return "var(--ink-faint)";
  }
}

/** Short host-app label. */
export function hostAppLabel(host: HostApp): string {
  if (host === "Cli") return "cli";
  if (host === "VsCode") return "vscode";
  if (typeof host === "object" && "Other" in host) return host.Other;
  return "—";
}
