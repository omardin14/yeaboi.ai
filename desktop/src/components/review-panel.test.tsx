import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ReviewPanel } from "@/components/review-panel";
import type { Finding } from "@/lib/bindings/Finding";
import type { AgentProgress } from "@/lib/bindings/AgentProgress";

const reviewMock = vi.hoisted(() => vi.fn());
const cancelMock = vi.hoisted(() => vi.fn());
const subscribeMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  reviewPr: reviewMock,
  cancelReview: cancelMock,
  subscribeReviewProgress: subscribeMock,
}));

const finding = (over: Partial<Finding> = {}): Finding => ({
  severity: "Critical",
  category: "code",
  file: "a.rs",
  line: 12,
  title: "A bug",
  body: "details",
  provider: "claude",
  ...over,
});

beforeEach(() => {
  reviewMock.mockReset();
  cancelMock.mockReset().mockResolvedValue(undefined);
  // Default: no progress events; the subscription resolves to a no-op unlisten.
  subscribeMock.mockReset().mockResolvedValue(() => {});
});

test("runs a review and groups findings by severity", async () => {
  reviewMock.mockResolvedValue([
    finding({ severity: "Critical", title: "A bug" }),
    finding({ severity: "Suggestion", title: "A nit", category: "comments" }),
  ]);
  render(<ReviewPanel cwd="/repo" number={7} />);
  fireEvent.click(screen.getByRole("button", { name: "Review with agents" }));

  await waitFor(() => expect(reviewMock).toHaveBeenCalledWith("/repo", 7));
  expect(await screen.findByText("A bug")).toBeInTheDocument();
  expect(screen.getByText("A nit")).toBeInTheDocument();
  expect(screen.getByText(/Critical \(1\)/)).toBeInTheDocument();
  expect(screen.getByText(/Suggestion \(1\)/)).toBeInTheDocument();
});

test("shows live per-agent progress", async () => {
  const events: AgentProgress[] = [
    { provider: "claude", category: "code", status: { Done: 2 } },
    { provider: "codex", category: "tests", status: { Failed: "no auth" } },
  ];
  subscribeMock.mockImplementation(
    (cb: (p: AgentProgress) => void) => {
      events.forEach(cb);
      return Promise.resolve(() => {});
    },
  );
  reviewMock.mockResolvedValue([]);
  render(<ReviewPanel cwd="/repo" number={1} />);
  fireEvent.click(screen.getByRole("button", { name: "Review with agents" }));

  expect(await screen.findByText(/claude · code — 2 finding/)).toBeInTheDocument();
  expect(screen.getByText(/codex · tests — failed: no auth/)).toBeInTheDocument();
});

test("a clean review shows the no-findings state", async () => {
  reviewMock.mockResolvedValue([]);
  render(<ReviewPanel cwd="/repo" number={1} />);
  fireEvent.click(screen.getByRole("button", { name: "Review with agents" }));
  expect(await screen.findByText(/looks clean/i)).toBeInTheDocument();
});

test("a failed review surfaces an error", async () => {
  reviewMock.mockRejectedValue("no agent CLI");
  render(<ReviewPanel cwd="/repo" number={1} />);
  fireEvent.click(screen.getByRole("button", { name: "Review with agents" }));
  expect(await screen.findByText(/Review failed/)).toBeInTheDocument();
});
