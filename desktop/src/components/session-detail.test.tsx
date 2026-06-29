import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SessionDetail } from "@/components/session-detail";
import type { Session } from "@/lib/bindings/Session";

const workingDiffMock = vi.hoisted(() => vi.fn());
const transcriptMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  workingDiff: workingDiffMock,
  sessionTranscript: transcriptMock,
}));

const session: Session = {
  id: "s1",
  pid: 100,
  project_id: "/repo",
  provider: "Claude",
  host_app: "Cli",
  cwd: "/repo",
  name: null,
  model: "claude-opus-4-8",
  status: "Idle",
  branch: "main",
  started_at_ms: 0,
  updated_at_ms: 0,
  context: null,
  last_prompt: null,
  sub_agent_count: 0,
  awaiting_permission: false,
  proc_stats: null,
  ports: [],
};

beforeEach(() => {
  workingDiffMock.mockReset().mockResolvedValue("diff --git a b\n+added line");
  transcriptMock.mockReset().mockResolvedValue([
    { kind: "user", summary: "do the thing", text: "do the thing", at: "2026-06-27T21:42:32.000Z" },
    { kind: "assistant", summary: "on it", text: "on it", at: "2026-06-27T21:42:35.000Z" },
    {
      kind: "tool_result",
      summary: "exit 0",
      text: "3 tests passed",
      at: "2026-06-27T21:43:01.000Z",
    },
  ]);
});

test("loads and shows the working diff", async () => {
  render(<SessionDetail session={session} onClose={() => {}} />);
  expect(await screen.findByText(/\+added line/)).toBeInTheDocument();
  expect(workingDiffMock).toHaveBeenCalledWith("/repo");
});

test("switches to the transcript and shows speakers, times, and turns", async () => {
  render(<SessionDetail session={session} onClose={() => {}} />);
  // Wait for the transcript to load, then open its tab.
  await waitFor(() => expect(transcriptMock).toHaveBeenCalledWith("s1"));
  fireEvent.click(screen.getByRole("button", { name: "Transcript" }));

  // Speaker attribution + the conversation text render (no scrubbing slider).
  expect(await screen.findByText("You")).toBeInTheDocument();
  expect(screen.getByText("Assistant")).toBeInTheDocument();
  expect(screen.getByText("do the thing")).toBeInTheDocument();
  expect(screen.getByText("on it")).toBeInTheDocument();
  // A clock (HH:MM:SS) appears on entries.
  expect(screen.getAllByText(/^\d{2}:\d{2}:\d{2}$/).length).toBeGreaterThan(0);
  // The tool result is a collapsible heavy entry (its summary shows as a label).
  expect(screen.getByText("exit 0")).toBeInTheDocument();
  expect(screen.getByText(/Tool result/)).toBeInTheDocument();
  expect(
    screen.queryByRole("slider", { name: "Transcript position" }),
  ).not.toBeInTheDocument();
});

test("close fires the callback", async () => {
  const onClose = vi.fn();
  render(<SessionDetail session={session} onClose={onClose} />);
  fireEvent.click(screen.getByRole("button", { name: "Close detail" }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("an empty diff shows the no-changes state", async () => {
  workingDiffMock.mockResolvedValueOnce("");
  render(<SessionDetail session={session} onClose={() => {}} />);
  expect(await screen.findByText(/no uncommitted changes/i)).toBeInTheDocument();
});

test("a diff load failure surfaces an error", async () => {
  workingDiffMock.mockRejectedValueOnce("not a git repo");
  render(<SessionDetail session={session} onClose={() => {}} />);
  expect(await screen.findByText(/could not load diff/i)).toBeInTheDocument();
});
