import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PrView } from "@/components/pr-view";
import type { Project } from "@/lib/bindings/Project";
import type { PullRequest } from "@/lib/bindings/PullRequest";

const listPrsMock = vi.hoisted(() => vi.fn());
const prDiffMock = vi.hoisted(() => vi.fn());
const mergePrMock = vi.hoisted(() => vi.fn());
const commentPrMock = vi.hoisted(() => vi.fn());
const openPrMock = vi.hoisted(() => vi.fn());
const syncBranchMock = vi.hoisted(() => vi.fn());
const abortRebaseMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  listPrs: listPrsMock,
  prDiff: prDiffMock,
  mergePr: mergePrMock,
  commentPr: commentPrMock,
  openPr: openPrMock,
  syncBranch: syncBranchMock,
  abortRebase: abortRebaseMock,
}));

const project: Project = {
  id: "/repo",
  name: "repo",
  root: "/repo",
  remote: null,
  session_ids: [],
  busy_count: 0,
  session_count: 0,
};

const pr: PullRequest = {
  number: 42,
  title: "Add a thing",
  state: "OPEN",
  head: "feat/thing",
  base: "main",
  author: "dinho",
  url: "https://example/42",
  is_draft: false,
  updated_at: "now",
};

beforeEach(() => {
  listPrsMock.mockReset().mockResolvedValue([pr]);
  prDiffMock.mockReset().mockResolvedValue("diff --git a b\n+added");
  mergePrMock.mockReset().mockResolvedValue(undefined);
  commentPrMock.mockReset().mockResolvedValue(undefined);
  openPrMock.mockReset().mockResolvedValue("https://example/pr/1");
  syncBranchMock.mockReset().mockResolvedValue("Clean");
  abortRebaseMock.mockReset().mockResolvedValue(undefined);
});

test("lists PRs for the first project on mount", async () => {
  render(<PrView projects={[project]} />);
  expect(await screen.findByText("Add a thing")).toBeInTheDocument();
  expect(screen.getByText("OPEN")).toBeInTheDocument();
  expect(listPrsMock).toHaveBeenCalledWith("/repo");
});

test("clicking a PR loads its diff", async () => {
  render(<PrView projects={[project]} />);
  fireEvent.click(await screen.findByText("Add a thing"));
  expect(await screen.findByText(/\+added/)).toBeInTheDocument();
  expect(prDiffMock).toHaveBeenCalledWith("/repo", 42);
});

test("merge confirms and calls the backend with the chosen method", async () => {
  render(<PrView projects={[project]} />);
  fireEvent.click(await screen.findByText("Add a thing"));
  fireEvent.click(await screen.findByRole("button", { name: "Merge" }));
  // Default method is Squash → confirm label reflects it.
  fireEvent.click(await screen.findByRole("button", { name: "Squash & merge" }));
  await waitFor(() => expect(mergePrMock).toHaveBeenCalledWith("/repo", 42, "Squash"));
});

test("surfaces a list error", async () => {
  listPrsMock.mockRejectedValueOnce("gh not authed");
  render(<PrView projects={[project]} />);
  expect(await screen.findByText(/Could not list PRs/)).toBeInTheDocument();
});

test("merge label reflects the chosen method", async () => {
  render(<PrView projects={[project]} />);
  fireEvent.click(await screen.findByText("Add a thing"));
  fireEvent.change(await screen.findByLabelText("Merge method"), {
    target: { value: "Rebase" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Merge" }));
  expect(
    await screen.findByRole("button", { name: "Rebase & merge" }),
  ).toBeInTheDocument();
});

test("a failed merge surfaces an error", async () => {
  mergePrMock.mockRejectedValueOnce("not mergeable");
  render(<PrView projects={[project]} />);
  fireEvent.click(await screen.findByText("Add a thing"));
  fireEvent.click(await screen.findByRole("button", { name: "Merge" }));
  fireEvent.click(await screen.findByRole("button", { name: "Squash & merge" }));
  expect(await screen.findByText(/Failed to merge #42/)).toBeInTheDocument();
});

test("commenting calls the backend with the body", async () => {
  render(<PrView projects={[project]} />);
  fireEvent.click(await screen.findByText("Add a thing"));
  fireEvent.change(await screen.findByLabelText("Comment"), {
    target: { value: "looks good" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Comment" }));
  await waitFor(() =>
    expect(commentPrMock).toHaveBeenCalledWith("/repo", 42, "looks good"),
  );
});

test("opening a PR confirms then calls the backend", async () => {
  render(<PrView projects={[project]} />);
  await screen.findByText("Add a thing");
  fireEvent.click(screen.getByRole("button", { name: "Open PR" }));
  fireEvent.click(await screen.findByRole("button", { name: "Push & open" }));
  await waitFor(() => expect(openPrMock).toHaveBeenCalledWith("/repo"));
  expect(await screen.findByText(/Opened PR/)).toBeInTheDocument();
});

test("a conflicted sync offers an abort that calls the backend", async () => {
  syncBranchMock.mockResolvedValueOnce({ Conflicts: ["file.txt"] });
  render(<PrView projects={[project]} />);
  await screen.findByText("Add a thing");
  fireEvent.click(screen.getByRole("button", { name: "Sync (rebase)" }));

  expect(await screen.findByText(/Rebase paused on conflicts/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Abort rebase" }));
  await waitFor(() => expect(abortRebaseMock).toHaveBeenCalledWith("/repo"));
  expect(await screen.findByText("Rebase aborted.")).toBeInTheDocument();
});

test("shows an empty state without projects", () => {
  render(<PrView projects={[]} />);
  expect(screen.getByText(/No projects/)).toBeInTheDocument();
});
