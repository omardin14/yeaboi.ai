---
name: team-analysis
description: "Analyse a team's Jira/Azure DevOps history with yeaboi into a calibration profile: velocity, story-point calibration, estimation accuracy, writing style, AI-tool adoption, documentation clarity + AI-usage, and coaching insights. Use when the user asks how the team is performing, wants velocity/estimation analysis, how the team uses AI, whether their docs are clear, coaching insights, or to calibrate planning to the team's real delivery data."
---

# Team analysis with yeaboi

1. **Check for an existing profile first.** Call `team_profile_get` — if a
   recent profile exists, present it and ask whether to re-analyse before
   running the heavy pipeline.

2. **Warn, then analyse.** `team_analyze` pages the tracker and makes several
   LLM calls — it takes minutes. Tell the user before calling it. Options:
   `source` ('jira'/'azdevops'/'both', auto-detects a single tracker when blank —
   use 'both' to analyse Jira **and** Azure DevOps in one run), `sprint_count`
   (default 8 closed sprints), `include_insights` (start/stop/keep/try
   coaching), `include_ai_usage` (scan the team's commits/PRs for AI-tool
   markers — on by default), `include_doc_quality` (read recent
   Notion/Confluence pages for clarity + AI-usage — on by default),
   `generate_samples` (sample tickets in the team's
   style — extra LLM calls, only when asked).

   **Decoupled components + member subset.** The analysis is three independent
   components, each over its OWN sub-sources — `components` is keyed by component,
   NOT by tracker:
   `{"delivery": ["jira","azdevops"], "code": ["github","azdo"], "docs": ["confluence","notion"]}`.
   **Delivery** (velocity/calibration/contributors) runs one profile PER selected
   tracker. **Code** (remote AI-usage) and **Docs** (Confluence/Notion clarity) are
   each a SINGLE global scan over their selected hosts — not per tracker. An
   absent/empty component is skipped (e.g. `{"docs": ["confluence"]}` = Confluence
   only, no velocity); `None` falls back to the `include_*` booleans. `members`
   scopes each delivery tracker's velocity/contributors (and code authors), e.g.
   `{"jira": ["Alice"]}` (blank = whole team); discover names with `team_roster`
   first. With a member subset, **velocity/calibration/estimation** reflect only
   those people, but **sprint completion rate stays board-level** — surfaced in
   `warnings`.

   Code scanning is **remote only** (GitHub + Azure Repos); there is no local-clone
   scan.

3. **Present it in layers.** Lead with the headline stats (velocity ± stddev,
   estimation accuracy, sprint completion), then the coaching `insights` as
   start/stop/keep/try, then the **AI adoption** footprint (`profile.ai_adoption`
   + `examples.ai_adoption`), then offer to go deeper into calibration or writing
   patterns from the profile. Surface any `warnings`.

   **AI adoption is a LOWER BOUND** — it only counts AI tools that leave a marker
   in commit messages or PR descriptions (Co-Authored-By: Claude, Copilot, Cursor,
   …). Inline IDE assist (Copilot ghost-text, Cursor Tab) leaves no trace, so real
   usage is at least the reported footprint. Never tell the user the team "doesn't
   use AI" from a low number — frame it as *detectable* usage and coach on making
   it broader and more visible.

   Then the **Documentation** read (`profile.doc_quality` + `examples.doc_quality`):
   an average clarity score (0–100), a clear/mixed/unclear split, and how AI shows
   up in the writing. Two different confidence levels — never conflate them:
   **clarity** is a readability score; **AI-likelihood** is a *stylometric estimate*,
   NOT a detection (prose carries no reliable AI marker — never assert a page "was
   written by AI"); **explicit AI markers** are a lower bound. Coach on clearer
   writing and effective AI use, not on policing.

   **Result shape:**
   `{delivery:{jira:{profile,...}, azdevops:{...}}, code:{signal,examples}|null, docs:{signal,examples}|null,
   comparison:[[label, jira, azdevops], ...], warnings}`. **Delivery** carries one entry per
   analysed tracker — present them **clearly separated** ("From Jira" / "From Azure DevOps"), never
   blend their velocity (scales aren't comparable), and lead with the `comparison` table when two
   trackers ran. **Code** and **Docs** are single global findings — present each ONCE, not per
   tracker (the same signal is also attached to each saved delivery profile so the stored-profile
   view keeps showing it). A code/docs-only run has `delivery: {}` (no velocity/calibration) —
   present the `code`/`docs` findings and don't offer it as planning calibration.

4. **Close the loop.** The saved profile automatically calibrates future
   `plan_generate` runs. For "how did the last plan actually go?", call
   `team_compare_plan_to_actuals` on a planning session.

## Error handling

Every tool returns `{ok, llm_mode, warnings, data}`. If `ok` is false, relay
`error.message` and its `hint` (no tracker configured / credentials — `yeaboi
--setup`); don't retry blindly. `llm_mode: "fallback"` means no LLM was reachable
and the insights are deterministic skeletons — suggest `yeaboi --setup`.
