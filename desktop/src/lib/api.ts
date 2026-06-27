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

/** Subscribe to the Rust-emitted snapshot stream (~1/s in Phase 0). */
export function subscribeSnapshot(
  onSnapshot: (snapshot: Snapshot) => void,
): Promise<UnlistenFn> {
  return listen<Snapshot>("snapshot-update", (event) => onSnapshot(event.payload));
}
