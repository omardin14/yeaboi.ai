# yeaboi.ai

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
  yb-core   domain model (Snapshot/Session), collectors        (no UI/OS deps)
  yb-proc   process table + ports + signals
  yb-exec   external command runner
  yb-git    typed git/gh wrappers
  yb-worktree  worktree engine (decentralized, MD5 ports)
  yb-agent  agent providers + review orchestrator
  yb-cli    headless `yeaboi` binary (--json/--once)
desktop/     Tauri app (src-tauri Rust shell + React/Vite frontend)
scripts/     w.sh — git worktree lifecycle
CLAUDE.md    conventions for working on this repo
.claude/     Claude Code harness — agents, commands, skills, settings
.archon/     Archon workflow definitions (needs the Archon CLI)
```

## Get up and running

Prereqs: **Rust** (via [rustup](https://rustup.rs)), **Node**, and **pnpm**. That's all —
the Makefile finds cargo (even if `~/.cargo/bin` isn't on your PATH) and installs the frontend
deps on first run. Two commands cover everything:

```sh
make dev    # desktop app — installs deps, builds, hot-reloads, opens the window
make cli    # headless — print a live snapshot as JSON
```

The first `make dev` compiles the Tauri backend (~30–60s) and then opens the **yeaboi.ai**
window: a sessions table that updates every second (stub data in Phase 0) plus a tray icon.
Run `make cli` for a quick, GUI-free check that the engine works.

Other tasks — run `make` with no arguments for the full list:

```sh
make test          # all Rust + frontend tests
make lint          # rustfmt --check + clippy -D warnings + tsc
make verify        # everything CI runs
make gen-bindings  # regenerate the Rust -> TS bindings
```

## Developing with Claude Code

This repo ships a Claude Code dev harness (adapted from GitHubIssueTriager). Full conventions live
in [`CLAUDE.md`](./CLAUDE.md).

### Parallel worktrees

```sh
./scripts/w.sh <name>        # create ../ai-manager-<name> on branch <name>
./scripts/w.sh <name> open   # create + launch claude inside it
./scripts/w.sh <name> rm     # remove the worktree + branch
```

Each worktree gets a deterministic dev-server port (main `1420`; worktrees `1430–1529`), so you can
run `make dev` in several at once without collisions (`make port` prints the current one).

### Review

- **`/review-pr`** — fresh-context, parallel specialized reviewers on the current PR diff
  (`code-reviewer` always; `silent-failure-hunter` if error handling changed; `pr-test-analyzer` if
  tests changed; then `code-simplifier`). Returns Critical / Important / Suggestions / Verdict.
- **`/cross-review`** — layer Codex (GPT) on top to surface blind spots.
- Reviewer ≠ implementer — run reviews in a fresh session so the reviewer isn't primed.

### Agents & skills

- **Agents** (`.claude/agents/`): code-reviewer · silent-failure-hunter · pr-test-analyzer ·
  code-simplifier · codebase-analyst · codebase-explorer · web-researcher.
- **Skills** (`.claude/skills/`): `archon-dev` (research → plan → implement → commit → pr
  cookbooks) · `rust-tauri` (stack reference) · `agent-browser` (UI automation).
- **Archon** (`.archon/`): `aim-idea-to-pr` + `aim-pr-review` workflows — require the separate Archon
  CLI; use `/review-pr` for the in-session equivalent.

### Conventions (the agents enforce these)

- `yb-core` stays presentation-agnostic; nothing depends on a UI crate.
- No `unwrap`/`expect`/`panic!` in runtime paths; never swallow errors.
- Regenerate ts-rs bindings with `make gen-bindings` (CI fails if stale).
- Conventional Commits; commits and PRs carry the Claude attribution trailers.
