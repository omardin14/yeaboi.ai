---
name: rust-tauri
description: |
  Reference for working in ai-manager's Rust + Tauri v2 stack — workspace layout,
  the command/event seam, ts-rs bindings, the async model, clippy/conventions, and
  the build gotchas specific to this machine. Use when implementing or debugging
  Rust engine code, the Tauri shell, or the React frontend.
---

# rust-tauri

ai-manager = a Rust (edition 2024) Cargo workspace + a Tauri v2 desktop app
(React 19 + Vite + Tailwind v4). The engine is presentation-agnostic and also ships the
headless `aim` CLI. See `CLAUDE.md` for the hard rules.

## Workspace layout
- `crates/aim-core` — the `Snapshot` contract + collectors. **No UI/OS deps.**
- `crates/aim-proc` — OS introspection (sysinfo/lsof/signals). `crates/aim-exec` — process runner.
- `crates/aim-git` · `crates/aim-worktree` · `crates/aim-agent` · `crates/aim-cli` (bin `aim`).
- `desktop/src-tauri` — Tauri Rust shell (commands + events; workspace member).
- `desktop/src` — React frontend; `desktop/src/lib/bindings/` is **generated** (ts-rs).

## The Rust↔TS seam
- **Command** (FE→Rust): `#[tauri::command] fn get_snapshot() -> Snapshot`, registered via
  `tauri::generate_handler![...]`. Frontend calls it through the typed wrapper in `src/lib/api.ts`.
- **Event** (Rust→FE): `app.emit("snapshot-update", snapshot)` (needs `use tauri::Emitter`),
  consumed via `listen<Snapshot>("snapshot-update", …)`. This is where Phase 1's
  `tokio::sync::watch<Snapshot>` plugs in.
- **Types**: derive on the model with `#[cfg_attr(feature = "ts", derive(ts_rs::TS))]` +
  `#[ts(export, export_to = "../../../desktop/src/lib/bindings/")]`. Pin wire-number types with
  `#[ts(type = "number")]` (u64 → JSON number, not `bigint`). Regenerate: `make gen-bindings`
  (= `cargo test -p aim-core --features ts`). **CI fails if bindings are stale.**

## Async model
Collectors run in a background task → publish `Arc<Snapshot>` over `tokio::sync::watch`. The Tauri
backend emits each snapshot as an event; the React store renders. Long actions are Tauri commands
that `tokio::spawn` the work + stream progress events; never block a command on sync I/O — use
`tauri::async_runtime::spawn` / `spawn_blocking`.

## Conventions
- `clippy -D warnings` is enforced. No `unwrap/expect/panic!/todo!` in runtime paths → `Result` +
  `thiserror`. Never swallow errors (see `silent-failure-hunter`).
- Ports are deterministic `MD5(path)` (byte-compatible with reference repos).

## Build gotchas (this machine)
- macOS ships GNU make 3.81 whose `export PATH` doesn't reach recipe subshells — the Makefile
  resolves `cargo` to `~/.cargo/bin/cargo` and sets PATH inline for `make dev`.
- pnpm v11 gates build scripts; esbuild is allow-listed in `desktop/pnpm-workspace.yaml`
  (`allowBuilds: { esbuild: true }`). Settings moved out of package.json's `pnpm` field.
- `tauri::generate_context!` tolerates a missing `desktop/dist` in debug, so `cargo build` works
  without a frontend build.
- **tauri-specta v2 is still RC** + heavy; we use **ts-rs** for bindings (stable). The command/event
  seam is identical, so revisit tauri-specta later if desired.

## Docs
- Tauri v2: https://v2.tauri.app (try `…/llms.txt` for markdown). ts-rs: https://github.com/Aleph-Alpha/ts-rs.
- Use the `web-researcher` agent for current crate/API details — these move fast.
