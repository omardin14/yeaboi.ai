import { render, screen } from "@testing-library/react";
import { SessionsTable } from "@/components/sessions-table";
import type { Snapshot } from "@/lib/bindings/Snapshot";
import type { Session } from "@/lib/bindings/Session";

function session(over: Partial<Session> = {}): Session {
  return {
    id: "s1",
    pid: 100,
    project_id: "/repo",
    provider: "Claude",
    host_app: "Cli",
    cwd: "/repo",
    name: null,
    model: "claude-opus-4-8",
    status: "Busy",
    branch: "main",
    started_at_ms: 0,
    updated_at_ms: 0,
    context: { used: 100000, window: 200000, pct: 0.5 },
    last_prompt: null,
    sub_agent_count: 0,
    proc_stats: null,
    ...over,
  };
}

const snapshot: Snapshot = {
  generated_at_ms: 0,
  projects: [],
  sessions: [
    session({ id: "s1", model: "claude-opus-4-8", status: "Busy" }),
    session({
      id: "s2",
      model: "claude-sonnet-4-6",
      status: "Idle",
      context: { used: 250000, window: 1000000, pct: 0.25 },
    }),
  ],
  totals: { session_count: 2, busy_count: 1, project_count: 1 },
  warnings: [],
};

test("renders a row per session with model and context", () => {
  render(<SessionsTable snapshot={snapshot} />);
  expect(screen.getByText("s1")).toBeInTheDocument();
  expect(screen.getByText("claude-sonnet-4-6")).toBeInTheDocument();
  expect(screen.getByText("50%")).toBeInTheDocument();
  expect(screen.getByText("25%")).toBeInTheDocument();
});

test("shows a loading state for a null snapshot", () => {
  render(<SessionsTable snapshot={null} />);
  expect(screen.getByText(/loading/i)).toBeInTheDocument();
});

test("shows an empty state when there are no sessions", () => {
  render(<SessionsTable snapshot={{ ...snapshot, sessions: [] }} />);
  expect(screen.getByText(/no active sessions/i)).toBeInTheDocument();
});

test("renders a dash when context is unknown", () => {
  const s = session({ id: "s3", context: null, status: "Unknown" });
  render(
    <SessionsTable
      snapshot={{
        ...snapshot,
        sessions: [s],
        totals: { ...snapshot.totals, session_count: 1 },
      }}
    />,
  );
  expect(screen.getByText("Unknown")).toBeInTheDocument();
});
