---
description: Check all open PRs, surface CI failures, and spawn fix agents for red ones
---

Babysit the open pull requests so finished work doesn't pile up. Arguments (optional): $ARGUMENTS — `fix` to auto-spawn fix agents, otherwise report-only.

1. **Survey** — `gh pr list --state open` then `gh pr checks <number>` for each. Build a table: PR, branch, CI status (green/red/pending), review status, mergeable.

2. **Green PRs** — list them as ready to merge. Do NOT merge anything yourself unless the PR carries the `auto-merge` label (then `gh pr merge --auto --squash` is allowed).

3. **Red PRs** — for each failing PR, fetch the failing run's log (`gh run view <run-id> --log-failed`) and summarize the root cause in one line.
   - If `fix` was passed: for each red PR, spawn a background fix agent (Agent tool, worktree isolation) whose prompt contains the branch name, the failure summary, and the failing log excerpt. Instruct it to check out that branch, reproduce with `make test` / `make lint`, fix, and push to the same branch. Track the agents and report when they finish.
   - Otherwise: just report the failures with their causes.

4. **Stale PRs** — flag PRs behind `main` by many commits or inactive for days; suggest `/sync-main` on their worktree.

5. **Report** — end with a compact status table and the list of actions taken or recommended.
