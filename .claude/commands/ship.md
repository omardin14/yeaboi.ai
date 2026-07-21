---
description: Verify (independent review + full tests), commit, push, and open a PR for the current branch
---

Ship the current feature branch. Arguments (optional): $ARGUMENTS — may include `auto-merge` to enable auto-merge for low-risk changes (docs/chores/small fixes only).

Follow these steps **in order**. If any step fails, stop, report what failed, and fix it before continuing. Never skip the verification steps.

1. **Sanity check** — run `git branch --show-current`. If on `main`, stop: create a feature branch first.

2. **Independent verification (fresh context, no author bias)** — spawn the `code-reviewer` subagent (defined in `.claude/agents/code-reviewer.md`). Give it ONLY: (a) the output of `git diff main...HEAD`, (b) a one-paragraph description of what this branch was supposed to do — NOT this conversation's history. Its checklist (spec fit, skill-based conventions, correctness) lives in the agent definition. Resolve every finding it reports at `blocker` or `should-fix` severity before proceeding (fix it, or explain in the PR body why it's intentionally not addressed).

3. **Full test gate** — run `make test` and `make lint`. Both must pass (CLAUDE.md REQUIRED: Verification). `make test-fast` is not enough at ship time.

4. **Commit** — stage the relevant changes and commit using repo conventions: lowercase imperative message (e.g. "add streaming output"), ending with the Co-Authored-By trailer from CLAUDE.md's Git Conventions.

5. **Push + PR** — `git push -u origin <branch>`, then `gh pr create` against `main` with:
   - Title: same style as the commit message.
   - Body: a Summary section (what and why), a Test plan section (what was run), and the standard "🤖 Generated with Claude Code" footer.

6. **Auto-merge (only if `auto-merge` was passed)** — confirm the change is genuinely low-risk (docs, chore, small fix; no `src/yeaboi/agent/`, schema, or workflow changes), then run `gh pr merge --auto --squash`. If it is not low-risk, say so and skip this step.

7. **Report** — output the PR URL and a one-line status.
