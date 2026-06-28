import { render, screen, within } from "@testing-library/react";
import { Monitor } from "@/components/monitor";
import type { Snapshot } from "@/lib/bindings/Snapshot";
import type { Session } from "@/lib/bindings/Session";

function session(over: Partial<Session> = {}): Session {
  return {
    id: "s1",
    pid: 100,
    project_id: "/repo-a",
    provider: "Claude",
    host_app: "Cli",
    cwd: "/repo-a",
    name: null,
    model: "claude-opus-4-8",
    status: "Busy",
    branch: "main",
    started_at_ms: 0,
    updated_at_ms: 0,
    context: { used: 180000, window: 200000, pct: 0.9 },
    last_prompt: "do the thing",
    sub_agent_count: 2,
    proc_stats: { cpu_pct: 12, mem_bytes: 524_288_000, uptime_secs: 3600, ppid: 1 },
    ...over,
  };
}

const snapshot: Snapshot = {
  generated_at_ms: 1,
  projects: [
    {
      id: "/repo-a",
      name: "repo-a",
      root: "/repo-a",
      remote: null,
      session_ids: ["s1", "s2"],
      busy_count: 1,
      session_count: 2,
    },
    {
      id: "/repo-b",
      name: "repo-b",
      root: "/repo-b",
      remote: null,
      session_ids: ["s3"],
      busy_count: 0,
      session_count: 1,
    },
  ],
  sessions: [
    session({ id: "s1", project_id: "/repo-a", status: "Busy" }),
    session({ id: "s2", project_id: "/repo-a", status: "Idle", model: "claude-sonnet-4-6" }),
    session({ id: "s3", project_id: "/repo-b", status: "Idle", model: "gpt-5", pid: null }),
  ],
  totals: { session_count: 3, busy_count: 1, project_count: 2 },
  warnings: [],
};

test("groups sessions under their project headers", () => {
  render(<Monitor snapshot={snapshot} />);
  const a = screen.getByRole("heading", { name: "repo-a" });
  const b = screen.getByRole("heading", { name: "repo-b" });
  expect(a).toBeInTheDocument();
  expect(b).toBeInTheDocument();
  // repo-a header reports its rolled-up counts.
  expect(screen.getByText(/1 busy/)).toBeInTheDocument();
});

test("renders one row per session with model, context and prompt", () => {
  render(<Monitor snapshot={snapshot} />);
  expect(screen.getByText("claude-sonnet-4-6")).toBeInTheDocument();
  expect(screen.getByText("gpt-5")).toBeInTheDocument();
  expect(screen.getAllByText("do the thing").length).toBe(3);
  // 90% context on the busy session.
  expect(screen.getAllByText("90%").length).toBeGreaterThan(0);
});

test("a session without a process shows a dash for pid", () => {
  render(<Monitor snapshot={snapshot} />);
  // s3 has pid null → "—" appears.
  expect(screen.getAllByText("—").length).toBeGreaterThan(0);
});

test("shows a connecting state for a null snapshot", () => {
  render(<Monitor snapshot={null} />);
  expect(screen.getByText(/connecting/i)).toBeInTheDocument();
});

test("shows an empty state when there are no sessions", () => {
  render(
    <Monitor
      snapshot={{ ...snapshot, projects: [], sessions: [], totals: { session_count: 0, busy_count: 0, project_count: 0 } }}
    />,
  );
  expect(screen.getByText(/no active sessions/i)).toBeInTheDocument();
});

test("only lists a project's own sessions under it", () => {
  render(<Monitor snapshot={snapshot} />);
  const repoBHeading = screen.getByRole("heading", { name: "repo-b" });
  const section = repoBHeading.closest("section") as HTMLElement;
  // repo-b has exactly one session row.
  expect(within(section).getAllByRole("row")).toHaveLength(1);
});
