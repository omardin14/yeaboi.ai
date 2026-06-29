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
    { kind: "user", summary: "do the thing", text: "do the thing" },
    { kind: "assistant", summary: "tool_use: Bash", text: "tool_use: Bash" },
  ]);
});

test("loads and shows the working diff", async () => {
  render(<SessionDetail session={session} onClose={() => {}} />);
  expect(await screen.findByText(/\+added line/)).toBeInTheDocument();
  expect(workingDiffMock).toHaveBeenCalledWith("/repo");
});

test("switches to the transcript and shows the full conversation", async () => {
  render(<SessionDetail session={session} onClose={() => {}} />);
  // Wait for the transcript to load, then open its tab.
  await waitFor(() => expect(transcriptMock).toHaveBeenCalledWith("s1"));
  fireEvent.click(screen.getByRole("button", { name: "Transcript" }));

  // The reader shows every turn's full text at once (no scrubbing).
  expect(await screen.findByText("do the thing")).toBeInTheDocument();
  expect(screen.getByText("tool_use: Bash")).toBeInTheDocument();
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
