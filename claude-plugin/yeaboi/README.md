# yeaboi — AI Scrum Master plugin for Claude Code

Sprint planning, daily standups, stakeholder delivery reports, and engineer
1:1 prep — without leaving your coding agent.

## What you get

- **MCP server** (started automatically via `uvx`): 16 tools — `plan_generate`,
  `plan_get`/`plan_export`, `intake_questions`, `sessions_list`/`session_get`,
  `standup_run`/`standup_history`, `report_delivery`, `perf_roster`,
  `perf_one_on_one_prep`/`perf_one_on_one_complete`/`perf_six_month_review`,
  `retro_history`, `team_profile_get`, `team_compare_plan_to_actuals`.
- **Skills**: `/yeaboi:plan-sprint` (guided conversational intake → full sprint
  plan), `/yeaboi:standup`, `/yeaboi:delivery-report`.

## Requirements

- `uv` installed (the server runs via `uvx --from 'yeaboi[mcp]' yeaboi-mcp`).
- **No API key needed in Claude Code** — generation runs through MCP sampling,
  i.e. the model you're already talking to. In clients without sampling
  support, yeaboi falls back to its own configured provider
  (`~/.yeaboi/.env`, set up with `yeaboi --setup`).
- Optional: Jira / Azure DevOps / GitHub credentials in `~/.yeaboi/.env` power
  the standup, delivery-report, and performance tools.

## Install

```bash
claude plugin marketplace add omardin14/yeaboi.ai
/plugin install yeaboi@yeaboi
```

Or for development: `claude --plugin-dir /path/to/repo/claude-plugin/yeaboi`

## Notes

- Every tool returns `{ok, llm_mode, warnings, data}`. `llm_mode: "fallback"`
  means no LLM was reachable and `data` is a deterministic skeleton.
- Plans generated here are saved as yeaboi sessions — resumable in the yeaboi
  TUI (`uvx yeaboi`) and shared with the standup/reporting/performance tools.
- Server logs: `~/.yeaboi/logs/mcp/mcp.log`.
