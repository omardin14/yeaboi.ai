---
description: Fresh-context PR review — fans out parallel specialized subagents on the current PR diff.
argument-hint: [review-aspects]
allowed-tools: ["Bash", "Glob", "Grep", "Read", "Task"]
---

Independent review of the current PR in **fresh context** — the session that wrote the code should
not be the one that reviews it. Run the applicable reviewers **in parallel** and aggregate.

## 1. Identify the diff
```
gh pr view --json number,url,title,headRefName,body   # if a PR exists
git diff origin/main...HEAD                            # otherwise
```
Get the changed-file list and a one-paragraph statement of intent (from the PR body / linked issue).

## 2. Decide which reviewers apply (from the diff)
- **Always** → `code-reviewer` (general quality + `CLAUDE.md` compliance).
- **If error handling changed** (Rust `Result`/`?`/`catch_unwind`, or TS `try/catch`/`.catch`) →
  `silent-failure-hunter`.
- **If tests changed/added** (`#[test]`, `*.test.tsx`, `tests/`) → `pr-test-analyzer`.
- **After the above** → `code-simplifier` (polish pass, non-blocking).

## 3. Fan out in parallel
Launch all applicable subagents in a **single batch** (one message, multiple `Task` calls). Give each:
the changed-file list, the PR intent, "focus on the diff, not the whole repo," and "every finding
must cite `file:line`." Parallel is the default — sequential just gives the same signal slower.

## 4. Aggregate into one summary
```markdown
# PR Review — <pr-title>
## Critical (must fix before merge)
- [reviewer] <issue> — `path:line`
## Important (should fix)
- [reviewer] <issue> — `path:line`
## Suggestions
- [reviewer] <suggestion> — `path:line`
## Strengths
- <what the PR did well>
## Verdict
APPROVE / APPROVE_WITH_CHANGES / REQUEST_CHANGES
```

## 5. Do NOT apply fixes
This is review, not editing. Keep findings actionable: `file:line` + one sentence + suggested fix.
If the PR is trivial (docs-only, one-liner), return **APPROVE** with zero findings rather than
inventing issues.
