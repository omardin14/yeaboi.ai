---
name: archon-dev
description: |
  The PRIMARY development workflow for ai-manager (Rust + Tauri).
  Routes to 10 specialized cookbooks based on what the user is trying to do:

  RESEARCH    — "how does the ClaudeCollector work?", "where is Snapshot defined?",
                "trace how a snapshot reaches the desktop UI"
  INVESTIGATE — "should we use tauri-specta or ts-rs?", "best way to watch ~/.claude?",
                "how do other tools detect running sessions?"
  PRD         — "write a PRD for the insights tab", "spec out the permission inbox"
  PLAN        — "plan the codex collector", "design the worktree engine", "plan #42"
  IMPLEMENT   — "implement the plan", "execute .claude/archon/plans/collectors.plan.md",
                "build the feature from the plan", "code this up"
  REVIEW      — "review PR #123", "review my changes", "code review the diff"
  DEBUG       — "debug the failing test", "why is the snapshot stale?",
                "root cause analysis on the lsof timeout"
  COMMIT      — "commit these changes", "commit the collector work"
  PR          — "create a PR", "open a pull request for this branch"
  ISSUE       — "report this to gh", "create a gh issue", "log it in github",
                "file a bug for this", "create a feature request"

  This skill triggers on ANY development task: researching, investigating,
  planning, building, reviewing, debugging, committing, or shipping code.
  NOT for: Running Archon CLI workflows in worktrees (use /archon instead).
argument-hint: "[cookbook] [task description or issue number]"
---

# archon-dev

Development workflow — research, plan, build, review, ship.

## Current State

- **Branch**: !`git branch --show-current 2>/dev/null || echo "not in git repo"`
- **Artifacts**: !`ls .claude/archon/ 2>/dev/null || echo "none yet"`
- **Active plans**: !`ls .claude/archon/plans/*.plan.md 2>/dev/null | head -5 || echo "none"`

---

## Routing

**Read `$ARGUMENTS` and determine which cookbook to load.**

If the user explicitly names a cookbook (e.g., "plan", "implement"), use that.
Otherwise, match intent from keywords:

| Intent | Keywords | Cookbook |
|--------|----------|---------|
| Codebase questions, document what exists | "research", "how does", "what is", "where is", "trace", "find" | [cookbooks/research.md](cookbooks/research.md) |
| Strategic research, library eval, feasibility | "investigate", "should we", "can we", "compare", "evaluate", "feasibility", "best way to", "best approach" | [cookbooks/investigate.md](cookbooks/investigate.md) |
| Write product requirements | "prd", "requirements", "spec", "product requirement" | [cookbooks/prd.md](cookbooks/prd.md) |
| Create implementation plan | "plan", "design", "architect", "write a plan" | [cookbooks/plan.md](cookbooks/plan.md) |
| Execute an existing plan | "implement", "execute", "build", "code this", path to `.plan.md` | [cookbooks/implement.md](cookbooks/implement.md) |
| Review code or PR | "review", "review PR", "code review", "review changes" | [cookbooks/review.md](cookbooks/review.md) |
| Debug or root cause analysis | "debug", "rca", "root cause", "why is", "broken", "failing" | [cookbooks/debug.md](cookbooks/debug.md) |
| Commit changes | "commit", "save changes", "stage" | [cookbooks/commit.md](cookbooks/commit.md) |
| Create pull request | "pr", "pull request", "create pr", "open pr" | [cookbooks/pr.md](cookbooks/pr.md) |
| Report to GitHub | "issue", "report to gh", "log in github", "file a bug", "feature request", "create issue", "gh issue" | [cookbooks/issue.md](cookbooks/issue.md) |

**If ambiguous**: Ask the user which cookbook to use.

**After routing**: Read the matched cookbook file and follow its instructions exactly.

---

## Workflow Chains

Cookbooks feed into each other. After completing one, suggest the next:

```
research ──► investigate ──► prd ──► plan ──► implement ──► commit ──► pr
                              ▲                    │
             debug ───────────┘      review ◄──────┘
                 │
                 ▼
               issue ──► plan (if feature) or debug (if bug)
```

---

## Artifact Directory

All artifacts go to `.claude/archon/`. Create subdirectories as needed on first use.

```
.claude/archon/
├── prds/              # Product requirement documents
├── plans/             # Implementation plans
│   └── completed/     # Archived after implementation
├── reports/           # Implementation reports
├── issues/            # GitHub issue investigations
│   └── completed/
├── reviews/           # PR review reports
├── debug/             # Root cause analysis
└── research/          # Research findings
```

---

## Project commands

ai-manager is a **Rust (Cargo workspace) + Tauri (pnpm) monorepo**. Prefer the `make` targets:

- **Validate**: `make verify` (= lint + test + cli), or individually
  `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  `cargo test --workspace`, and `cd desktop && pnpm typecheck && pnpm test`.
- **Run**: `make dev` (desktop) · `make cli` (headless).
- **Bindings**: after changing a `#[ts]` model type, run `make gen-bindings`.
- **Conventions**: read `CLAUDE.md` — its rules override cookbook defaults.

---

## Rules

1. **Evidence-based**: Every claim about the codebase must reference `file:line`
2. **No speculation**: If uncertain, investigate first
3. **Fail fast**: Surface errors immediately, never swallow them
4. **Respect CLAUDE.md**: Project conventions override cookbook defaults
5. **AI attribution required**: commits end with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
