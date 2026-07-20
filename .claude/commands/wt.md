---
description: Manage git worktrees for parallel development (new/list/rm/headless)
---

Worktree operations for parallel feature development. Arguments: $ARGUMENTS

Parse the arguments and run the matching operation via the existing tooling (never reimplement it):

- `list` (or no arguments) — run `bash scripts/wt-list.sh` and, for each worktree, also check `gh pr list --head <branch>` to note whether it has an open PR. Present a compact table: name, branch, clean/dirty, PR status.
- `new <name>` — run `bash scripts/wt.sh <name> open` (creates `.claude/worktrees/<name>` with branch, `.env`, venv, pre-commit hooks, then opens VS Code with a claude session).
- `headless <name>` — run `bash scripts/wt.sh <name> headless` (same provisioning, no VS Code window; prints the path). Use this when the feature will be driven by a background agent from this session instead of a human-attended window.
- `rm <name>` — first check the worktree is clean (`git -C .claude/worktrees/<name> status --porcelain` from the main checkout) and has no unmerged work; warn and ask before removing anything dirty. Then run `bash scripts/wt.sh <name> rm`.

Worktrees live under `<main checkout>/.claude/worktrees/`. If the current directory is itself a worktree, the scripts already resolve the main checkout — just run them from here.
