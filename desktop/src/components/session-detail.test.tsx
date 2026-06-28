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
    { kind: "user", summary: "do the thing" },
    { kind: "assistant", summary: "tool_use: Bash" },
  ]);
});

test("loads and shows the working diff", async () => {
  render(<SessionDetail session={session} onClose={() => {}} />);
  expect(await screen.findByText(/\+added line/)).toBeInTheDocument();
  expect(workingDiffMock).toHaveBeenCalledWith("/repo");
});

test("switches to the transcript and scrubs", async () => {
  render(<SessionDetail session={session} onClose={() => {}} />);
  // Wait for the transcript to load, then open its tab.
  await waitFor(() => expect(transcriptMock).toHaveBeenCalledWith("s1"));
  fireEvent.click(screen.getByRole("button", { name: "Transcript" }));

  // Starts at the last entry.
  expect(await screen.findByText("tool_use: Bash")).toBeInTheDocument();
  // Scrub back to the first entry.
  fireEvent.change(screen.getByRole("slider", { name: "Transcript position" }), {
    target: { value: "0" },
  });
  expect(screen.getByText("do the thing")).toBeInTheDocument();
});

test("close fires the callback", async () => {
  const onClose = vi.fn();
  render(<SessionDetail session={session} onClose={onClose} />);
  fireEvent.click(screen.getByRole("button", { name: "Close detail" }));
  expect(onClose).toHaveBeenCalledTimes(1);
});
