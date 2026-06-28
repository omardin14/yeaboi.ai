import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { WorktreeBoard } from "@/components/worktree-board";
import type { Project } from "@/lib/bindings/Project";
import type { Worktree } from "@/lib/bindings/Worktree";

const listMock = vi.hoisted(() => vi.fn());
const createMock = vi.hoisted(() => vi.fn());
const removeMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  listWorktrees: listMock,
  createWorktree: createMock,
  removeWorktree: removeMock,
  pruneWorktrees: vi.fn(() => Promise.resolve([])),
  startWorktreeServices: vi.fn(),
  stopWorktreeServices: vi.fn(),
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

function wt(over: Partial<Worktree> = {}): Worktree {
  return {
    name: "feat-x",
    path: "/repo-feat-x",
    branch: "feature/x",
    port: 4123,
    is_main: false,
    ...over,
  };
}

beforeEach(() => {
  listMock.mockReset().mockResolvedValue([
    wt({ name: "(main)", path: "/repo", branch: "main", port: 4000, is_main: true }),
    wt(),
  ]);
  createMock.mockReset().mockResolvedValue(wt());
  removeMock.mockReset().mockResolvedValue(undefined);
});

test("lists worktrees with branch and port", async () => {
  render(<WorktreeBoard projects={[project]} />);
  expect(await screen.findByText("feat-x")).toBeInTheDocument();
  expect(screen.getByText(":4123")).toBeInTheDocument();
  expect(screen.getByText(":4000")).toBeInTheDocument();
  expect(listMock).toHaveBeenCalledWith("/repo");
});

test("the main checkout has no remove button", async () => {
  render(<WorktreeBoard projects={[project]} />);
  await screen.findByText("feat-x");
  expect(
    screen.getByRole("button", { name: "Remove worktree feat-x" }),
  ).toBeInTheDocument();
  // main is the only other row, and it's not removable.
  expect(screen.getAllByRole("button", { name: /Remove worktree/ })).toHaveLength(1);
});

test("creating a worktree calls the backend and refreshes", async () => {
  render(<WorktreeBoard projects={[project]} />);
  await screen.findByText("feat-x");
  fireEvent.change(screen.getByLabelText("New worktree name"), {
    target: { value: "issue-9" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create" }));
  await waitFor(() => expect(createMock).toHaveBeenCalledWith("/repo", "issue-9"));
  expect(await screen.findByText(/Created/)).toBeInTheDocument();
});

test("removing confirms then calls the backend", async () => {
  render(<WorktreeBoard projects={[project]} />);
  await screen.findByText("feat-x");
  fireEvent.click(screen.getByRole("button", { name: "Remove worktree feat-x" }));
  fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
  await waitFor(() => expect(removeMock).toHaveBeenCalledWith("/repo", "feat-x"));
});

test("a list failure surfaces an error", async () => {
  listMock.mockRejectedValueOnce("not a git repo");
  render(<WorktreeBoard projects={[project]} />);
  expect(await screen.findByText(/could not list worktrees/i)).toBeInTheDocument();
});
