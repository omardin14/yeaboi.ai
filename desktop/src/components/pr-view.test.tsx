import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PrView } from "@/components/pr-view";
import type { Project } from "@/lib/bindings/Project";
import type { PullRequest } from "@/lib/bindings/PullRequest";

const listPrsMock = vi.hoisted(() => vi.fn());
const prDiffMock = vi.hoisted(() => vi.fn());
const mergePrMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  listPrs: listPrsMock,
  prDiff: prDiffMock,
  mergePr: mergePrMock,
  commentPr: vi.fn(),
  openPr: vi.fn(),
  syncBranch: vi.fn(),
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

test("shows an empty state without projects", () => {
  render(<PrView projects={[]} />);
  expect(screen.getByText(/No projects/)).toBeInTheDocument();
});
