// Typed bridge to the Rust backend. The `Snapshot` type is generated from Rust
// by ts-rs (see crates/yb-core); these thin wrappers give the command + event
// a typed surface. Phase 1 grows the surface (kill_session, worktree ops, …).

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { Snapshot } from "@/lib/bindings/Snapshot";

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
