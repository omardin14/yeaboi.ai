# Feedback remediation pilot

A Claude **Agent SDK** pipeline that triages incoming GitHub issues nightly and
routes actionable bugs into the existing implementation flow. This is the
repo's Step-4 (AI-native) pilot — the first automation built on the Agent SDK
rather than the hosted `claude-code-action`.

## What it does

For every open issue that is *fresh feedback* (no `triaged` label, not
bot-authored, not an automation issue), it makes one cheap **Haiku**
classification call and acts:

| Classification | Action |
|---|---|
| bug · actionable · high-confidence | Sonnet double-checks it's specific enough, then labels `claude-implement` (capped at 3/run; overflow → `feedback:fix-queued`) |
| feature | labels `feature-candidate` (a human decides whether to implement) |
| question | comments asking for detail + labels `feedback:needs-info` |
| noise | labels `feedback:noise` (never auto-closed) |

Every triaged issue also gets the `triaged` cursor label (so it's processed
once) plus a `type:*` label inferred from the feedback-form title prefix.

## Why label `claude-implement` instead of fixing here

Fix *execution* is delegated to the existing `claude-implement` → `claude.yml`
pathway: labeling the issue opens a normal PR that flows through CI +
`claude-review.yml` + **human merge**. The SDK owns triage, orchestration, and
rate-limiting; it does not check out or push code. Labeling `claude-implement`
is the "Claude kicks off Claude" hand-off, composed through the proven pipeline.

## Safety

- Runs with **`issues: write` only** — it structurally cannot touch PRs or merge.
- Caps `claude-implement` labels per run (default 3).
- Idempotent via the `triaged` label cursor; skips bot-authored issues.
- `--dry-run` logs every intended action and changes nothing.

## Auth

Two credentials, both in the GitHub Actions secret store:

- **`ANTHROPIC_API_KEY`** — the Agent SDK authenticates with an API key, *not*
  the Claude GitHub App's `CLAUDE_CODE_OAUTH_TOKEN` (that token is only for
  `claude-code-action`). **This is a one-time setup step:** add an
  `ANTHROPIC_API_KEY` repo secret before enabling the nightly workflow.
- **`GH_TOKEN`** — the workflow's `github.token`, used by the `gh` CLI wrappers.

## Run locally

```bash
# Dry run against the live repo — prints intended actions, changes nothing:
GH_TOKEN=$(gh auth token) ANTHROPIC_API_KEY=sk-... \
  uv run automation/feedback_remediation/triage.py --dry-run

# Weekly digest (also upserts the "Feedback digest" issue):
uv run automation/feedback_remediation/triage.py --dry-run --digest
```

## Labels this uses (must pre-exist)

`triaged`, `feature-candidate`, `feedback:needs-info`, `feedback:noise`,
`feedback:fix-queued`, `feedback-digest`, plus the app's existing
`claude-implement` and `type:*` labels.

## Tests

```bash
uv run pytest automation/feedback_remediation/test_triage.py
```

The pure helpers (issue filtering, title-prefix inference, classification
parsing, digest rendering) are unit-tested without the SDK or network. The SDK
calls are exercised in production behind the `--dry-run` safety valve.
