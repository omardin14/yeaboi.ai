---
name: team-analysis
description: "Analyse a team's Jira/Azure DevOps history with yeaboi into a calibration profile: velocity, story-point calibration, estimation accuracy, writing style, and coaching insights. Use when the user asks how the team is performing, wants velocity/estimation analysis, coaching insights, or to calibrate planning to the team's real delivery data."
---

# Team analysis with yeaboi

1. **Check for an existing profile first.** Call `team_profile_get` — if a
   recent profile exists, present it and ask whether to re-analyse before
   running the heavy pipeline.

2. **Warn, then analyse.** `team_analyze` pages the tracker and makes several
   LLM calls — it takes minutes. Tell the user before calling it. Options:
   `source` ('jira'/'azdevops', auto-detected when blank), `sprint_count`
   (default 8 closed sprints), `include_insights` (start/stop/keep/try
   coaching), `generate_samples` (sample tickets in the team's style — extra
   LLM calls, only when asked).

3. **Present it in layers.** Lead with the headline stats (velocity ± stddev,
   estimation accuracy, sprint completion), then the coaching `insights` as
   start/stop/keep/try, then offer to go deeper into calibration or writing
   patterns from the profile. Surface any `warnings`.

4. **Close the loop.** The saved profile automatically calibrates future
   `plan_generate` runs. For "how did the last plan actually go?", call
   `team_compare_plan_to_actuals` on a planning session.

## Error handling

Every tool returns `{ok, llm_mode, warnings, data}`. If `ok` is false, relay
`error.message` and its `hint` (no tracker configured / credentials — `yeaboi
--setup`); don't retry blindly. `llm_mode: "fallback"` means no LLM was reachable
and the insights are deterministic skeletons — suggest `yeaboi --setup`.
