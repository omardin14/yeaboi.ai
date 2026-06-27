# ai-manager — project tracker

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
- [x] Cargo workspace + crate skeletons (`aim-core`, `aim-proc`, `aim-exec`, `aim-git`, `aim-worktree`, `aim-agent`, `aim-cli`)
- [x] Tauri v2 app under `desktop/` (`src-tauri` Rust shell + React/Vite/TS + Tailwind v4 frontend)
- [x] Shared TS types generated from Rust — **ts-rs** (tauri-specta v2 is still RC; ts-rs is stable). Bindings in `desktop/src/lib/bindings/`, regen via `make gen-bindings`
- [x] CI: `cargo fmt`/`clippy -D warnings`/`test` (macOS) · bindings-freshness · `pnpm typecheck`/`test`/`build`
- Seam proven: `get_snapshot` command + `snapshot-update` event (1s) → typed React table. Tray stub.
- Run the app: `make web-install && make dev`. Headless: `make cli`.
- _Note: shadcn deferred — Tailwind v4 + `@` alias are in place, add components later with `pnpm dlx shadcn@latest add …`._

## Phase 1 — Monitor + worktrees + full PR/git loop (v1)

### aim-core (data + collectors)
- [ ] `model`: `Snapshot{projects,sessions,totals,warnings}`, `Project`, `Session`, `SubAgent`, `Port`, `ProcStats`, `ContextUsage`, enums
- [ ] `model::windows` model→context-window table; `ContextUsage` token math (+ unit tests)
- [ ] `Collector` trait + `Registry` (concurrent collect) + enrichment join (proc subtree + ports by pid)
- [ ] `ClaudeCollector` Tier A — `sessions/*.json` mtime dirty-check → pid/cwd/status
- [ ] `ClaudeCollector` Tier B — `TranscriptCursor` incremental tail; `RawLine` type-tagged enum; sub-agent open/close by tool_use id; `last-prompt`; truncation reset
- [ ] `ProjectResolver` — `git --git-common-dir`/`--show-toplevel` grouping; roll worktrees under repo
- [ ] `CodexCollector` — `rusqlite` read-only; recency-bounded `agent_jobs`/`threads` queries
- [ ] `notify` fs-watch wrapper (dirty-path set)
- [ ] `engine` — 1s tick loop + `watch<Arc<Snapshot>>`; idle skip

### aim-proc
- [ ] `sysinfo` `ProcTable` (cpu+mem+parent) + ppid subtree BFS
- [ ] `lsof -Fpn` parser + 750ms timeout/degrade + orphan-port heuristic
- [ ] `actions::sigterm(pid)` (nix, guards) + `free_port`

### aim-cli (headless — build & validate the data path first)
- [ ] clap args: `--once`, `--json`, `--interval`, `--no-ports`
- [ ] wire collectors → engine → JSON/once output

### desktop — monitor
- [ ] `src-tauri`: stream `Snapshot` as events; commands `kill_session`/`free_port`; menu-bar/tray (busy · $today · blocked)
- [ ] React: project-tree data grid (TanStack Table), detail panel, heat colors, live filter/sort, keyboard shortcuts
- [ ] Confirm dialogs (kill / free-port)
- [ ] Working-diff viewer + transcript replay (detail panel)
- [ ] Native notifications + deep links (finish/blocked)
- [ ] Permission/approval inbox — **detection only (read-only)**

### aim-exec
- [ ] `Cmd::output` / `Cmd::stream(tx,cancel)` / `spawn_detached(log,pid)` + pid files

### aim-git
- [ ] `GitRepo` + `Gh` wrappers; types `PullRequest`/`MergeMethod`/`ReviewFinding`/`Conflict`/`RebaseOutcome`
- [ ] PR ops: `pr_list/view/diff/find_existing/create/merge/comment/review`
- [ ] Git ops: `push/current_branch/pull_rebase/rebase_continue/abort/merged_branches/list_conflicts`
- [ ] Structured `GhError`/`GitError` → UI toasts

### aim-worktree (decentralized, GitHubIssueTriager model)
- [ ] `project.toml` schema (`branch_rules`/`[ports]`/`[lifecycle]`/`[[services]]`/`[env]`) + global repo registry
- [ ] `PortAllocator` — **MD5, byte-compatible with `assign-port.ts`** (+ determinism/range tests)
- [ ] Branch derivation (regex→template) + tests
- [ ] Engine: `create`/`open`/`list`/`start`/`stop`/`remove`/`prune` (discover-on-read from `git worktree list`)
- [ ] `.env` render (parent minus overrides); lifecycle setup/teardown (Neon branch / pg clone); honor Claude Code `WorktreeCreate/Remove` hooks
- [ ] Detached service lifecycle + pid files

### aim-agent
- [ ] `AgentProvider` trait; `ClaudeProvider` (`claude -p --output-format json`); `CodexProvider`; tolerant JSON extraction
- [ ] `ReviewOrchestrator` — 5-way fan-out (`Semaphore`), dedupe, synthesis (local default / opt-in 6th LLM)
- [ ] Cross-PR + **cross-provider** (claude vs codex) variants
- [ ] Per-agent timeout + shared `CancellationToken`

### desktop — PR/worktree views
- [ ] PR list · review-run progress (per-agent rows via events, cancelable) · findings (post to PR) · worktree board · diff/conflict viewers · merge/rebase dialogs

### v1 testing
- [ ] Unit (context math, transcript incremental==oracle, sub-agent matching, branch derivation, port determinism, JSON extraction)
- [ ] Collector fixtures (`tempfile`; trimmed `<pid>.json`, all-line-type `.jsonl`, in-test codex sqlite)
- [ ] `aim-proc` parse tests + subtree + feature-gated sigterm
- [ ] Frontend component tests (Vitest/RTL) + Playwright smoke; Tauri command tests
- [ ] End-to-end manual against the live machine

## Phase 2 — Insights & Suggestions + manager + search + PR/CI dashboard (`aim-insights`, `aim-config`)
- [ ] `model→pricing` table; cost tracking ($/session/project/day/model) + leaderboards
- [ ] Token-waste/context-thrash detection (cache-create vs read, near-full ctx, idle holding ctx, wide re-reads) with $ cost
- [ ] Model-fit (cost): Opus-on-trivial-edits → Sonnet/Haiku + $ delta
- [ ] Capability advisor: `models.toml` matrix (Claude/OpenAI/Perplexity/Gemini); heuristic + optional LLM classifier; on-demand + live triggers; **advise + one-click route** where reachable
- [ ] Prompt effectiveness: heuristics always-on + opt-in LLM judge (key `C`)
- [ ] Delivery: Insights tab + threshold nudges (config thresholds) + charts
- [ ] Cron recommendations (surface only → feeds v5)
- [ ] `aim-config`: view/diff/edit MCP servers, agents, commands, hooks, permissions, model defaults across Claude/Codex/Cursor/Copilot; per-project profiles; **`doctor`** (gh/neonctl/env prereqs)
- [ ] Transcript search: local SQLite FTS index (incremental) + notes + prompt library
- [ ] Cross-repo PR/CI dashboard (`gh pr list`/`checks`) + red/green notify
- [ ] Session attach (embedded xterm.js via `portable-pty`) + **permission approve** (v2)

## Phase 3 — Workflows (harness) + standup/queue (`aim-workflow`)
- [ ] YAML DAG engine: nodes (prompt/command/bash/script), `depends_on`, loops, approval gates; generalize the review fan-out
- [ ] Standup/digest generator (transcripts + stats, optional LLM summary)
- [ ] Task queue + batch ops across a project's worktrees (on workflow engine + `aim-worktree open`)

## Phase 4 — Planning sidecar (`aim-plan` + scrum-planning companion changes)
- [ ] Companion #1: scrum-planning `--engine-mode` (intake JSON stdin → graph → `export_plan_json`)
- [ ] Companion #2: `ChatClaudeCLI` provider (`LLM_PROVIDER=claude-cli`) + structured-output emulation, **verified node-by-node**
- [ ] Companion #3: `--list-questions` JSON (expose the 30 intake questions)
- [ ] `aim-plan`: detect `scrum-agent`; spawn `--engine-mode`; JSON IO contract; graceful degrade
- [ ] Desktop: intake multi-step form + pipeline-progress view
- [ ] Loop closure: tasks/stories → `aim-worktree create`; save plan artifact to `.ai-manager/plans/`

## Phase 5 — Cron + push + mobile remote (`aim-schedule`, `aim-notify`, `aim-remote`)
- [ ] `aim-schedule`: cron execution (incl. v2 recommendations)
- [ ] `aim-notify`: Slack + Telegram adapters; chat subscriptions; push for threshold/finish/blocked events
- [ ] `aim-remote`: local daemon API + tunnel (Tailscale/ngrok); mobile web UI (reuse the React frontend)
- [ ] Remote permission approve from phone (ties to the v2 inbox + attach)
