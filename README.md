# ai-manager

A fast **desktop app** (Tauri: Rust engine + React/Tailwind UI) that is the single pane of
glass for your whole AI coding setup — a live monitor of every Claude/Codex session and sub-agent,
plus git worktrees and the full PR/git loop, without leaving the app. The Rust engine is
presentation-agnostic and also ships a headless CLI.

> Status: **Phase 0 (scaffolding) complete** — the engine, CLI, Tauri shell, typed Rust↔TS
> bindings, and CI are in place and the live snapshot seam works end-to-end (stub data).
> See [`TODO.md`](./TODO.md) for the roadmap.

- Plan & roadmap: `~/.claude/plans/i-want-to-create-groovy-flurry.md`
- Tracker: [`TODO.md`](./TODO.md)

## Layout

```
crates/
  aim-core   domain model (Snapshot/Session), collectors        (no UI/OS deps)
  aim-proc   process table + ports + signals
  aim-exec   external command runner
  aim-git    typed git/gh wrappers
  aim-worktree  worktree engine (decentralized, MD5 ports)
  aim-agent  agent providers + review orchestrator
  aim-cli    headless `aim` binary (--json/--once)
desktop/     Tauri app (src-tauri Rust shell + React/Vite frontend)
```

## Get up and running

Prereqs: **Rust** (via [rustup](https://rustup.rs)), **Node**, and **pnpm**. That's all —
the Makefile finds cargo (even if `~/.cargo/bin` isn't on your PATH) and installs the frontend
deps on first run. Two commands cover everything:

```sh
make dev    # desktop app — installs deps, builds, hot-reloads, opens the window
make cli    # headless — print a live snapshot as JSON
```

The first `make dev` compiles the Tauri backend (~30–60s) and then opens the **ai-manager**
window: a sessions table that updates every second (stub data in Phase 0) plus a tray icon.
Run `make cli` for a quick, GUI-free check that the engine works.

Other tasks — run `make` with no arguments for the full list:

```sh
make test          # all Rust + frontend tests
make lint          # rustfmt --check + clippy -D warnings + tsc
make verify        # everything CI runs
make gen-bindings  # regenerate the Rust -> TS bindings
```
