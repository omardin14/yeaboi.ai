---
description: Rebase the current worktree branch on latest main and re-verify
---

Bring the current feature branch up to date with `main`.

1. Run `git branch --show-current`. If on `main`, just run `git pull --ff-only` and stop.
2. `git fetch origin main`.
3. If the working tree is dirty, stash first (`git stash push -u -m "sync-main autostash"`) and remember to pop at the end.
4. `git rebase origin/main`. If conflicts arise, resolve them: prefer `main`'s version for files this branch didn't intentionally change; for genuine overlaps, merge both intents and explain what you did.
5. Pop the stash if one was created (resolve any conflicts the same way).
6. Run `make test-fast` and `make lint` to confirm the branch still works on top of the new base. If either fails, fix before finishing.
7. Report: how many commits the branch was behind, any conflicts resolved, and the verification result.
