# .archon

Archon workflow definitions for yeaboi.ai — multi-step pipelines (plan → implement →
validate → PR → 5-agent review → fix).

**These require the separate [Archon](https://github.com/) CLI to run.** Without it this
directory is inert. The `archon-*` node `command:` references are Archon's *bundled* defaults
(installed with the CLI), not files in this repo.

- `config.yaml` — worktree base branch + assistant defaults.
- `workflows/aim-idea-to-pr.yaml` — full feature loop (Neon DB phases removed vs the
  GitHubIssueTriager original; validation is `make verify`).
- `workflows/aim-pr-review.yaml` — comprehensive 5-agent review of a PR.

No Archon CLI? Use the in-session equivalents instead:
- `/review-pr` — parallel reviewer fan-out (see `.claude/commands/review-pr.md`).
- `/cross-review` — layer Codex on top.
- the `archon-dev` skill — research / plan / implement / commit / pr cookbooks (standalone).
