import { renderHook } from "@testing-library/react";
import { useSessionMetrics } from "@/lib/session-metrics";
import type { Snapshot } from "@/lib/bindings/Snapshot";

function snap(frame: number, cpu: number, mem: number, withProc = true): Snapshot {
  return {
    generated_at_ms: frame,
    projects: [],
    sessions: [
      {
        id: "s1",
        pid: 1,
        project_id: "p",
        provider: "Claude",
        host_app: "Cli",
        cwd: "/",
        name: null,
        model: null,
        status: "Busy",
        branch: null,
        started_at_ms: 0,
        updated_at_ms: 0,
        context: null,
        last_prompt: null,
        sub_agent_count: 0,
        awaiting_permission: false,
        proc_stats: withProc
          ? { cpu_pct: cpu, mem_bytes: mem, uptime_secs: 1, ppid: null }
          : null,
        ports: [],
      },
    ],
    orphan_ports: [],
    totals: { session_count: 1, busy_count: 1, project_count: 0 },
    warnings: [],
  };
}

test("smooths cpu across frames and keeps a history for the sparkline", () => {
  const { result, rerender } = renderHook((s: Snapshot) => useSessionMetrics(s), {
    initialProps: snap(1, 100, 1000),
  });
  rerender(snap(2, 0, 1000));
  rerender(snap(3, 0, 1000));

  const m = result.current("s1");
  expect(m).toBeDefined();
  // The EMA sits between the raw samples — not the last (0) nor the first (100).
  expect(m!.cpu.value!).toBeGreaterThan(0);
  expect(m!.cpu.value!).toBeLessThan(100);
  expect(m!.cpu.history).toEqual([100, 0, 0]);
});

test("a process-less session never poisons history with zeros", () => {
  const { result } = renderHook((s: Snapshot) => useSessionMetrics(s), {
    initialProps: snap(1, 0, 0, false),
  });
  expect(result.current("s1")).toBeUndefined();
});

test("a repeated frame stamp is ingested only once", () => {
  const { result, rerender } = renderHook((s: Snapshot) => useSessionMetrics(s), {
    initialProps: snap(7, 50, 1000),
  });
  rerender(snap(7, 50, 1000)); // same stamp → guard drops it
  expect(result.current("s1")!.cpu.history).toEqual([50]);
});
