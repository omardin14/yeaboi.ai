import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import App from "@/App";

// A minimal live snapshot with one killable session.
const { SNAP } = vi.hoisted(() => ({
  SNAP: {
    generated_at_ms: 1,
    projects: [
      {
        id: "/repo",
        name: "repo",
        root: "/repo",
        remote: null,
        session_ids: ["s1"],
        busy_count: 1,
        session_count: 1,
      },
    ],
    sessions: [
      {
        id: "s1",
        pid: 4242,
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
        context: { used: 1, window: 2, pct: 0.5 },
        last_prompt: "hi",
        sub_agent_count: 0,
        awaiting_permission: false,
        proc_stats: { cpu_pct: 1, mem_bytes: 1, uptime_secs: 1, ppid: 1 },
        // Distinct from the session pid (4242) so a test can prove the port's
        // pid — not the session's — is what reaches free_port.
        ports: [{ number: 1420, pid: 9999, state: "LISTEN" }],
      },
    ],
    totals: { session_count: 1, busy_count: 1, project_count: 1 },
    orphan_ports: [],
    warnings: [],
  },
}));

const freePortMock = vi.hoisted(() => vi.fn(() => Promise.resolve()));

vi.mock("@/lib/api", () => ({
  getSnapshot: () => Promise.resolve(SNAP),
  killSession: () => Promise.reject("backend says no"),
  freePort: freePortMock,
  subscribeSnapshot: () => Promise.resolve(() => {}),
  subscribeSnapshotError: () => Promise.resolve(() => {}),
}));

beforeEach(() => {
  // App only talks to the backend when the Tauri bridge is present.
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  freePortMock.mockClear();
  freePortMock.mockResolvedValue(undefined);
});

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});

test("confirming a stop that fails surfaces an error banner", async () => {
  render(<App />);

  // The live snapshot loads and the killable session shows a stop button.
  const stop = await screen.findByRole("button", { name: "Stop session s1" });
  fireEvent.click(stop);

  // Confirm dialog appears; confirm it.
  const confirm = await screen.findByRole("button", { name: "Stop (SIGTERM)" });
  fireEvent.click(confirm);

  // killSession rejects → the failure is surfaced, not swallowed.
  await waitFor(() =>
    expect(screen.getByText(/Failed to stop session 4242/)).toBeInTheDocument(),
  );
});

test("cancelling the stop dialog dismisses it without error", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Stop session s1" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("freeing a port confirms and calls the backend with the port's pid", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Free port 1420" }));
  fireEvent.click(await screen.findByRole("button", { name: "Free (SIGTERM)" }));
  // The port's pid (9999), not the session's (4242), must reach free_port.
  await waitFor(() => expect(freePortMock).toHaveBeenCalledWith(9999));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("a failed free surfaces an error banner", async () => {
  freePortMock.mockRejectedValueOnce("backend says no");
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Free port 1420" }));
  fireEvent.click(await screen.findByRole("button", { name: "Free (SIGTERM)" }));
  await waitFor(() =>
    expect(screen.getByText(/Failed to free port :1420/)).toBeInTheDocument(),
  );
});

test("cancelling the free dialog dismisses it without a backend call", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Free port 1420" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(freePortMock).not.toHaveBeenCalled();
});
