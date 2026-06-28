import { render, screen, within, fireEvent } from "@testing-library/react";
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
    last_prompt: "alpha task",
    sub_agent_count: 2,
    proc_stats: { cpu_pct: 12, mem_bytes: 524_288_000, uptime_secs: 3600, ppid: 1 },
    ports: [],
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
    session({ id: "s1", project_id: "/repo-a", status: "Busy", last_prompt: "alpha task" }),
    session({
      id: "s2",
      project_id: "/repo-a",
      status: "Idle",
      model: "claude-sonnet-4-6",
      last_prompt: "beta task",
    }),
    // s3: no process and no usage — pid + cpu + mem + ctx all render "—".
    session({
      id: "s3",
      project_id: "/repo-b",
      status: "Idle",
      model: "gpt-5",
      pid: null,
      context: null,
      proc_stats: null,
      last_prompt: "gamma task",
    }),
  ],
  totals: { session_count: 3, busy_count: 1, project_count: 2 },
  warnings: [],
};

/** The `<tr>` that contains the given prompt text. */
function rowWithPrompt(prompt: string): HTMLElement {
  return screen.getByText(prompt).closest("tr") as HTMLElement;
}

test("groups sessions under their project headers with rolled-up counts", () => {
  render(<Monitor snapshot={snapshot} />);
  expect(screen.getByRole("heading", { name: "repo-a" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "repo-b" })).toBeInTheDocument();
  expect(screen.getByText(/1 busy/)).toBeInTheDocument();
});

test("renders a row per session with model, context and prompt", () => {
  render(<Monitor snapshot={snapshot} />);
  expect(screen.getByText("claude-sonnet-4-6")).toBeInTheDocument();
  expect(screen.getByText("gpt-5")).toBeInTheDocument();
  // 90% context is scoped to the busy session's own row.
  expect(within(rowWithPrompt("alpha task")).getByText("90%")).toBeInTheDocument();
});

test("a session without process or usage shows dashes in its own row", () => {
  render(<Monitor snapshot={snapshot} />);
  const row = rowWithPrompt("gamma task");
  // pid, ctx, cpu, mem all unknown → at least the pid dash is present here.
  expect(within(row).getAllByText("—").length).toBeGreaterThanOrEqual(1);
});

test("shows a connecting state for a null snapshot", () => {
  render(<Monitor snapshot={null} />);
  expect(screen.getByText(/connecting/i)).toBeInTheDocument();
});

test("shows an empty state when there are no sessions", () => {
  render(
    <Monitor
      snapshot={{
        ...snapshot,
        projects: [],
        sessions: [],
        totals: { session_count: 0, busy_count: 0, project_count: 0 },
      }}
    />,
  );
  expect(screen.getByText(/no active sessions/i)).toBeInTheDocument();
});

test("only lists a project's own sessions under it", () => {
  render(<Monitor snapshot={snapshot} />);
  const section = screen
    .getByRole("heading", { name: "repo-b" })
    .closest("section") as HTMLElement;
  expect(within(section).getAllByRole("row")).toHaveLength(1);
});

test("renders a chip per listening port", () => {
  const snap: Snapshot = {
    ...snapshot,
    projects: [
      {
        id: "/repo-a",
        name: "repo-a",
        root: "/repo-a",
        remote: null,
        session_ids: ["s1"],
        busy_count: 1,
        session_count: 1,
      },
    ],
    sessions: [
      session({
        id: "s1",
        ports: [
          { number: 1420, pid: 100, state: "LISTEN" },
          { number: 5173, pid: 200, state: "LISTEN" },
        ],
      }),
    ],
    totals: { session_count: 1, busy_count: 1, project_count: 1 },
  };
  render(<Monitor snapshot={snap} />);
  expect(screen.getByText(":1420")).toBeInTheDocument();
  expect(screen.getByText(":5173")).toBeInTheDocument();
});

test("a stop button appears only for killable sessions and calls onKill", () => {
  const onKill = vi.fn();
  render(<Monitor snapshot={snapshot} onKill={onKill} />);
  // s1 has a live pid → killable; s3 has pid null → not killable.
  expect(
    screen.getByRole("button", { name: "Stop session s1" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Stop session s3" }),
  ).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Stop session s1" }));
  expect(onKill).toHaveBeenCalledTimes(1);
  expect(onKill.mock.calls[0][0].id).toBe("s1");
});

test("no stop buttons render without an onKill handler", () => {
  render(<Monitor snapshot={snapshot} />);
  expect(screen.queryByRole("button", { name: /Stop session/ })).toBeNull();
});

test("a Dead session with a (recycled) pid still shows no stop button", () => {
  // drop_dead defaults to false, so a Dead row with a non-null pid is a real
  // shape — signalling it would target a process that's already gone/recycled.
  const dead = session({ id: "s4", pid: 12345, status: "Dead", last_prompt: "dead one" });
  const snap: Snapshot = {
    ...snapshot,
    projects: [
      {
        id: "/repo-d",
        name: "repo-d",
        root: "/repo-d",
        remote: null,
        session_ids: ["s4"],
        busy_count: 0,
        session_count: 1,
      },
    ],
    sessions: [dead],
    totals: { session_count: 1, busy_count: 0, project_count: 1 },
  };
  render(<Monitor snapshot={snap} onKill={vi.fn()} />);
  expect(
    screen.queryByRole("button", { name: "Stop session s4" }),
  ).not.toBeInTheDocument();
});

test("warns and skips a project's dangling session id", () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  const broken: Snapshot = {
    ...snapshot,
    projects: [
      {
        id: "/repo-c",
        name: "repo-c",
        root: "/repo-c",
        remote: null,
        // One real session (so the empty-state guard doesn't short-circuit) plus
        // a dangling id that must be warned about and skipped.
        session_ids: ["s1", "nope"],
        busy_count: 1,
        session_count: 2,
      },
    ],
    sessions: [session({ id: "s1", project_id: "/repo-c", last_prompt: "real one" })],
    totals: { session_count: 1, busy_count: 1, project_count: 1 },
  };
  render(<Monitor snapshot={broken} />);
  expect(warn).toHaveBeenCalledWith(expect.stringContaining("nope"));
  warn.mockRestore();
});
