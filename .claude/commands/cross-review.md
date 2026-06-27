---
description: Cross-provider review — compares Codex's adversarial review against Claude's /review-pr to surface blind spots. Two-phase human-in-the-loop (the Codex plugin hides its review commands from model invocation by design).
argument-hint: [pr-number]
---

Layer **Codex (GPT)** on top of Claude's `/review-pr`. Claude and GPT were trained on different
distributions, so each catches things the other misses — anything **only Codex** flags is
disproportionately valuable.

## Phase 1 — no Codex review in the session yet
Codex's review commands are locked off from model invocation by the plugin
(`disable-model-invocation: true`), so hand off to the user:

> Run this yourself, then re-run `/cross-review $ARGUMENTS`:
>
> ```
> /codex:adversarial-review --scope branch --base main
> ```

Stop here until Codex's output is in the conversation.

## Phase 2 — Codex review IS present
1. Resolve the PR number if needed: `gh pr view --json number,url,title,headRefName`.
2. Confirm the codex plugin is enabled (`.claude/settings.json` → `enabledPlugins."codex@openai-codex"`).
3. Put Codex's findings next to Claude's `/review-pr` findings in one table:
   ```
   | Source | Severity | File:Line | Issue |
   ```
4. **Highlight Codex-only findings** — the blind spots Claude's reviewers missed. Note where the two
   providers **agree** (agreement is itself a strong signal).
5. For each cross-provider win, draft a candidate `CLAUDE.md` rule (or agent tweak) to prevent
   recurrence.

Keep it terse — surface blind spots, don't re-list everything both reviewers agreed on. Review only;
apply no fixes.
