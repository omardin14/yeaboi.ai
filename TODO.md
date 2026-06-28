# yeaboi.ai — project tracker

A fast **desktop app (Tauri: Rust engine + React/Tailwind/shadcn UI)** that is the single pane of
glass for your whole AI coding setup. Two halves:

1. **Monitor** (read-only, local, à la `cctop`) — every Claude/Codex session + sub-agent in one live
   view, grouped by project/repo: busy/idle, context left, model, branch, last prompt; kill a
   runaway session or free a stuck port.
2. **Drive the work** — git worktrees ("workstreams") + the full PR/git loop (review, cross-PR,
   cross-provider, open, merge, rebase) with multi-agent reviews via your local `claude`/`codex`.

The Rust engine is presentation-agnostic: the Tauri app and a headless CLI (`--json`/`--once`) share
it. Full design + rationale: `~/.claude/plans/i-want-to-create-groovy-flurry.md`.

**References:** Archon = harness/workflow engineering · GitHubIssueTriager = multi-workspace model
(decentralized, MD5-port, `w <name> [open|rm]`, Neon branch) · planning-platform = multi-service
worktree variant · scrum-planning-ai-agent = v4 planning sidecar.

---

## Phase 0 — Scaffolding ✅
- [x] Cargo workspace + crate skeletons (`yb-core`, `yb-proc`, `yb-exec`, `yb-git`, `yb-worktree`, `yb-agent`, `yb-cli`)
- [x] Tauri v2 app under `desktop/` (`src-tauri` Rust shell + React/Vite/TS + Tailwind v4 frontend)
- [x] Shared TS types generated from Rust — **ts-rs** (tauri-specta v2 is still RC; ts-rs is stable). Bindings in `desktop/src/lib/bindings/`, regen via `make gen-bindings`
- [x] CI: `cargo fmt`/`clippy -D warnings`/`test` (macOS) · bindings-freshness · `pnpm typecheck`/`test`/`build`
- Seam proven: `get_snapshot` command + `snapshot-update` event (1s) → typed React table. Tray stub.
- Run the app: `make web-install && make dev`. Headless: `make cli`.
- _Note: shadcn deferred — Tailwind v4 + `@` alias are in place, add components later with `pnpm dlx shadcn@latest add …`._

## Phase 1 — Monitor + worktrees + full PR/git loop (v1)

> **Phase 1a (data path, headless) — DONE.** `make cli --json/--once/--interval`
> shows real live sessions grouped by project with context %, model, CPU/MEM.
> Deferred from 1a: `notify` fs-watch, `watch<Arc<Snapshot>>` stream, lsof ports,
> sigterm/free-port (these land with the desktop monitor in 1b).

### yb-core (data + collectors)
- [x] `model`: `Snapshot{projects,sessions,totals,warnings}`, `Project`, `Session`, `ProcStats`, `ContextUsage`, enums (`SubAgent`→`sub_agent_count`; `Port` deferred to 1b)
- [x] `model::windows` model→context-window table; `ContextUsage` token math (+ unit tests)
- [x] `Collector` trait + `Registry` + enrichment join (proc by pid); dedup-by-id, project rollup
- [x] `ClaudeCollector` Tier A — `sessions/*.json` → pid/cwd/status (status optional)
- [x] `ClaudeCollector` Tier B — `TranscriptCursor` incremental tail; `RawLine` type-tagged enum; `last-prompt`; truncation reset; sub-agent count via tool_use
- [x] `ProjectResolver` — pure-filesystem `.git`/worktree common-dir grouping; roll worktrees under repo
- [x] `CodexCollector` — `rusqlite` read-only; recency-bounded `threads` query
- [x] `notify` fs-watch wrapper (`DirtyWatcher`) — wakes the collector early on a change
- [x] `engine` tick loop + `watch<Snapshot>` channel (desktop) + idle-skip via fs-watch

### yb-proc
- [x] `sysinfo` `ProcTable` (cpu+mem+parent) + ppid subtree BFS
- [x] `lsof -Fpn` parser + 750ms timeout/degrade; ports attached by subtree (orphan heuristic deferred)
- [ ] `actions::sigterm(pid)` (nix, guards) + `free_port` — *1b*

### yb-cli (headless — build & validate the data path first)
- [x] clap args: `--once`, `--json`, `--interval`, `--no-ports` (+ `--hide-dead`)
- [x] wire collectors → engine → JSON/once output

### desktop — monitor
> **Phase 1b-1 (live read-only monitor) — DONE.** The app streams the *real*
> `Snapshot` (background collector thread → `snapshot-update` event + shared
> state for `get_snapshot`) and renders a project-grouped grid with heat colors.
- [x] `src-tauri`: stream the real `Snapshot` as events + `get_snapshot` from shared state
- [x] React: project-grouped grid (status/pid/model/ctx%/cpu/mem/branch/sub-agents/prompt) + heat colors
- [x] `src-tauri`: `kill_session` command (SIGTERM via `yb-proc::actions`, snapshot-validated guard)
- [x] Confirm dialog (kill) + per-row stop button
- [x] `src-tauri`: `free_port` command (guarded by `pid_owns_tracked_port`) + clickable port chips → confirm
- [x] `src-tauri`: tray live status (busy · sessions · projects), updated each tick
- [x] React: filter box + sort control + keyboard shortcut + detail panel (hand-rolled grid; TanStack deferred as an impl detail)
- [x] Working-diff viewer + transcript replay (detail panel)
- [x] Native notifications (finish / awaiting-permission transitions)
- [x] Permission/approval inbox — **detection only** (`awaiting_permission` + "needs you" filter)
- [x] Orphan-port detection + free

### yb-exec
- [x] `Cmd::output` (run/wait/capture) + typed `ExecError`
- [x] `Cmd::stream(cancel, on_line)` (cooperative cancel) + `spawn_detached(log, pid_file)` (new process group)

### yb-git
- [x] `GitRepo` (current_branch/toplevel) + `Gh` (pr_list/view/diff); `PullRequest` type
- [x] Structured `GitError`/`GhError` (command/exit/stderr); `yeaboi prs` validates the path live
- [x] PR ops: `find_existing/create/merge/comment`; types `MergeMethod`/`RebaseOutcome` (ts-exported)
- [x] Git ops: `push_current/rebase_onto/rebase_continue/abort/merged_branches/list_conflicts`
- [x] Desktop PR view: project picker + list + diff viewer + merge/comment/open/sync (Monitor|PRs tabs)
- [ ] `review` (agent-driven) — *lands with yb-agent (1e)*

### yb-worktree (decentralized, GitHubIssueTriager model) — DONE (1d)
- [x] `project.toml` schema (`[ports]`/`branch_rules`/`[lifecycle]`/`[[services]]`/`[env]`) with defaults
- [x] `PortConfig::port_for` — **MD5, byte-parity with `assign-port.ts`** (+ determinism/range/parity tests)
- [x] Branch derivation (regex→template, first-match) + tests
- [x] Engine: `create`/`list`/`remove`/`prune_merged`/`start_services`/`stop_services` (discover-on-read)
- [x] `.env` render (parent minus overrides + PORT + `[env]`); lifecycle setup/teardown commands
- [x] Detached service lifecycle + pid files (`Cmd::spawn_detached` → SIGTERM)
- [x] Desktop worktree board (project picker · list · create · remove · start/stop · prune)
- _open = reveal in Finder (desktop opener); Neon/pg DB isolation is just configured lifecycle commands_

### yb-agent — DONE (1e)
- [x] `AgentProvider` trait; `ClaudeProvider` (`claude -p --output-format json`); `CodexProvider` (`codex exec`); tolerant JSON extraction (fenced/balanced/fallback)
- [x] `ReviewOrchestrator` — 5-way fan-out (bounded concurrency), per-agent progress, dedupe (file+line+category+title), local synthesis
- [x] **Cross-provider** (claude + codex) — same diff through both, dups merged
- [x] Shared cancel flag (`AtomicBool`) threaded into providers via `Cmd::stream` (kills the agent)
- [x] Desktop `review_pr`/`cancel_review` commands + `review-progress` events; PrView Review panel (progress rows + findings by severity)

### desktop — PR/worktree views
- [ ] PR list · review-run progress (per-agent rows via events, cancelable) · findings (post to PR) · worktree board · diff/conflict viewers · merge/rebase dialogs

### v1 testing
- [x] Unit (context math, transcript incremental==oracle, port attribution, rebase outcomes, JSON extraction)
- [x] Collector fixtures (`tempfile`; `<pid>.json`, all-line-type `.jsonl`, in-test codex sqlite)
- [x] `yb-proc` parse tests + subtree + sigterm; `yb-git` against tempfile repos + bare origin
- [x] Frontend component tests (Vitest/RTL) + Playwright smoke (`make e2e`)
- [ ] End-to-end manual against the live machine — **owner: you** (`make dev`; CI can't render the GUI)

## Phase 2 — Insights & Suggestions + manager + search + PR/CI dashboard (`yb-insights`, `yb-config`)
- [ ] `model→pricing` table; cost tracking ($/session/project/day/model) + leaderboards
- [ ] Token-waste/context-thrash detection (cache-create vs read, near-full ctx, idle holding ctx, wide re-reads) with $ cost
- [ ] Model-fit (cost): Opus-on-trivial-edits → Sonnet/Haiku + $ delta
- [ ] Capability advisor: `models.toml` matrix (Claude/OpenAI/Perplexity/Gemini); heuristic + optional LLM classifier; on-demand + live triggers; **advise + one-click route** where reachable
- [ ] Prompt effectiveness: heuristics always-on + opt-in LLM judge (key `C`)
- [ ] Delivery: Insights tab + threshold nudges (config thresholds) + charts
- [ ] Cron recommendations (surface only → feeds v5)
- [ ] `yb-config`: view/diff/edit MCP servers, agents, commands, hooks, permissions, model defaults across Claude/Codex/Cursor/Copilot; per-project profiles; **`doctor`** (gh/neonctl/env prereqs)
- [ ] Transcript search: local SQLite FTS index (incremental) + notes + prompt library
- [ ] Cross-repo PR/CI dashboard (`gh pr list`/`checks`) + red/green notify
- [ ] Session attach (embedded xterm.js via `portable-pty`) + **permission approve** (v2)

## Phase 3 — Workflows (harness) + standup/queue (`yb-workflow`)
- [ ] YAML DAG engine: nodes (prompt/command/bash/script), `depends_on`, loops, approval gates; generalize the review fan-out
- [ ] Standup/digest generator (transcripts + stats, optional LLM summary)
- [ ] Task queue + batch ops across a project's worktrees (on workflow engine + `yb-worktree open`)

## Phase 4 — Planning sidecar (`yb-plan` + scrum-planning companion changes)
- [ ] Companion #1: scrum-planning `--engine-mode` (intake JSON stdin → graph → `export_plan_json`)
- [ ] Companion #2: `ChatClaudeCLI` provider (`LLM_PROVIDER=claude-cli`) + structured-output emulation, **verified node-by-node**
- [ ] Companion #3: `--list-questions` JSON (expose the 30 intake questions)
- [ ] `yb-plan`: detect `scrum-agent`; spawn `--engine-mode`; JSON IO contract; graceful degrade
- [ ] Desktop: intake multi-step form + pipeline-progress view
- [ ] Loop closure: tasks/stories → `yb-worktree create`; save plan artifact to `.yeaboi.ai/plans/`

## Phase 5 — Cron + push + mobile remote (`yb-schedule`, `yb-notify`, `yb-remote`)
- [ ] `yb-schedule`: cron execution (incl. v2 recommendations)
- [ ] `yb-notify`: Slack + Telegram adapters; chat subscriptions; push for threshold/finish/blocked events
- [ ] `yb-remote`: local daemon API + tunnel (Tailscale/ngrok); mobile web UI (reuse the React frontend)
- [ ] Remote permission approve from phone (ties to the v2 inbox + attach)
