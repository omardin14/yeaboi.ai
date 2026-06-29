// Per-user Monitor preferences (which detail sections are collapsed, which
// metrics are hidden), persisted to localStorage like the theme toggle.

import { useEffect, useState } from "react";

const KEY = "yb-monitor-prefs";

/** Section ids in the inline session-detail panel. */
export type SectionId = "activity" | "resources" | "context" | "network" | "agents";
/** Hideable metric ids in the Resources section. */
export type MetricId = "cpu" | "mem" | "uptime" | "pid" | "host";

export type MonitorPrefs = {
  collapsedSections: SectionId[];
  hiddenMetrics: MetricId[];
};

// Default: only "Activity" (the prompt) is open; the rest start collapsed.
const DEFAULT: MonitorPrefs = {
  collapsedSections: ["resources", "context", "network", "agents"],
  hiddenMetrics: [],
};

function read(): MonitorPrefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT;
    const parsed = JSON.parse(raw) as Partial<MonitorPrefs>;
    return {
      collapsedSections: Array.isArray(parsed.collapsedSections)
        ? parsed.collapsedSections
        : DEFAULT.collapsedSections,
      hiddenMetrics: Array.isArray(parsed.hiddenMetrics)
        ? parsed.hiddenMetrics
        : [],
    };
  } catch {
    return DEFAULT;
  }
}

function toggle<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

export function useMonitorPrefs() {
  const [prefs, setPrefs] = useState<MonitorPrefs>(read);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(prefs));
    } catch {
      // Persistence is best-effort; the in-memory choice still applies.
    }
  }, [prefs]);

  return {
    isCollapsed: (id: SectionId) => prefs.collapsedSections.includes(id),
    toggleSection: (id: SectionId) =>
      setPrefs((p) => ({ ...p, collapsedSections: toggle(p.collapsedSections, id) })),
    isHidden: (id: MetricId) => prefs.hiddenMetrics.includes(id),
    toggleMetric: (id: MetricId) =>
      setPrefs((p) => ({ ...p, hiddenMetrics: toggle(p.hiddenMetrics, id) })),
  };
}
