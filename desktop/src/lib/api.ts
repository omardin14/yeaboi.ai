// Typed bridge to the Rust backend. The `Snapshot` type is generated from Rust
// by ts-rs (see crates/yb-core); these thin wrappers give the command + event
// a typed surface. Phase 1 grows the surface (kill_session, worktree ops, …).

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { Snapshot } from "@/lib/bindings/Snapshot";
import type { PullRequest } from "@/lib/bindings/PullRequest";
import type { MergeMethod } from "@/lib/bindings/MergeMethod";
import type { RebaseOutcome } from "@/lib/bindings/RebaseOutcome";

/** Frontend → Rust: fetch the current snapshot on demand. */
export function getSnapshot(): Promise<Snapshot> {
  return invoke<Snapshot>("get_snapshot");
}

/**
 * Frontend → Rust: SIGTERM a session by pid. Rejects (with the backend's
 * message) if the pid isn't a tracked live session or the signal fails.
 */
export function killSession(pid: number): Promise<void> {
  return invoke<void>("kill_session", { pid });
}

/**
 * Frontend → Rust: free a listening port by SIGTERM-ing the process holding it.
 * Rejects if the pid doesn't hold a tracked port or the signal fails.
 */
export function freePort(pid: number): Promise<void> {
  return invoke<void>("free_port", { pid });
}

// ---- PR loop (operates on a repo by its root path) ----

/** List pull requests for the repo at `cwd`. */
export function listPrs(cwd: string): Promise<PullRequest[]> {
  return invoke<PullRequest[]>("list_prs", { cwd });
}

/** Unified diff for a PR. */
export function prDiff(cwd: string, number: number): Promise<string> {
  return invoke<string>("pr_diff", { cwd, number });
}

/** Merge a PR with the given method. */
export function mergePr(
  cwd: string,
  number: number,
  method: MergeMethod,
): Promise<void> {
  return invoke<void>("merge_pr", { cwd, number, method });
}

/** Comment on a PR. */
export function commentPr(
  cwd: string,
  number: number,
  body: string,
): Promise<void> {
  return invoke<void>("comment_pr", { cwd, number, body });
}

/** Push the current branch and open a PR against `base`; resolves to its URL. */
export function openPr(cwd: string, base: string): Promise<string> {
  return invoke<string>("open_pr", { cwd, base });
}

/** Rebase the repo's current branch onto `origin/<base>`. */
export function syncBranch(cwd: string, base: string): Promise<RebaseOutcome> {
  return invoke<RebaseOutcome>("sync_branch", { cwd, base });
}

/** Subscribe to the Rust-emitted snapshot stream (~every 1.5s). */
export function subscribeSnapshot(
  onSnapshot: (snapshot: Snapshot) => void,
): Promise<UnlistenFn> {
  return listen<Snapshot>("snapshot-update", (event) => onSnapshot(event.payload));
}

/**
 * Subscribe to fatal collector failures. When the collector thread dies the
 * stream stops, so the UI must say so rather than freeze on the last frame.
 */
export function subscribeSnapshotError(
  onError: (message: string) => void,
): Promise<UnlistenFn> {
  return listen<string>("snapshot-error", (event) => onError(event.payload));
}
