---
name: standup
description: "Run a daily scrum standup with yeaboi: collect team activity from Jira/Azure DevOps/GitHub/git, score sprint confidence, and summarize per member. Use when the user asks for a standup, daily scrum, 'what did the team do', or sprint progress check."
---

# Daily Standup with yeaboi

1. **Run it.** Call `standup_run` (blank `session_id` targets the most recent
   planning session). Leave `deliver` false — you present the report; only set
   `deliver: true` if the user explicitly asks to send it to their configured
   channels (Slack/email/desktop).

2. **Present the report.** From `data`: lead with sprint day and the confidence
   score + rationale, then the team summary, then per-member updates (yesterday
   / today / blockers style). Surface any `warnings` (e.g. a tracker returned
   401) — they explain missing sections.

3. **History.** For trends or "how have standups been going", call
   `standup_history` and summarize confidence over time.

4. **Configuration.** To view or change the standup setup (time, weekdays,
   delivery channels, member aliases, user name), use `standup_config_get` /
   `standup_config_set`. Installing the OS schedule that fires it daily is done
   from the yeaboi TUI (it's machine-local).

If there are no sessions yet, suggest planning first (`/yeaboi:plan-sprint`) —
the standup needs a session for sprint dates and team context.

## Error handling

Every tool returns `{ok, llm_mode, warnings, data}`. If `ok` is false, relay
`error.message` and its `hint` (usually credentials — `yeaboi --setup`); don't
retry blindly. `llm_mode: "fallback"` means no LLM was reachable and the summary
is a deterministic skeleton — suggest `yeaboi --setup`.
