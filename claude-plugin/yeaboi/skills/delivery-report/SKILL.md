---
name: delivery-report
description: "Generate a business-friendly delivery report of the team's completed work with yeaboi. Use when the user asks what was delivered/shipped last sprint/month/quarter, needs a stakeholder update, or wants a delivery summary for management."
---

# Delivery Report with yeaboi

1. **Pick the period.** Ask (or infer from the request) which window:
   `last_sprint`, `last_month`, or `quarter`.

2. **Generate.** Call `report_delivery` with that `period`. It pulls completed
   tickets from the configured tracker (Jira/Azure DevOps) and produces an
   executive narrative, outcome themes, metrics, and highlights. Pass
   `solo: true` when the user is running their own delivery with no team —
   the narrative is written in the first person.

3. **Present it stakeholder-ready.** Lead with the executive summary, then the
   themes with their delivered items, then metrics and highlights. Keep the
   language business-friendly — outcomes, not ticket numbers. Surface any
   `warnings` (no tracker configured, truncated results) so the user knows the
   coverage.

4. **Exports.** yeaboi auto-saves Markdown/HTML/slide-deck versions under
   `~/.yeaboi/exports/reporting/` — mention this when the user wants something
   to circulate or present.

## Scoping what it reads

Every run tool takes three optional inputs: `context` — what this run may read from other
sessions (`"all"`, `"none"`, or a spec like `standup,retro:1@2sprints project=apollo tags=q3`:
sources, an optional window of `N sprints` / `month` / `quarter` / `year` / `YYYY-MM-DD..YYYY-MM-DD`,
project labels and tags; the JSON object of the same shape works too) — plus `project_label` (the
free-text project label recorded on the run) and `tags` (recorded beside the defaults every run gets,
such as `mode:reporting` and the month). When the user names a timeframe ("the last two sprints of
standups"), call `context_preview` with the spec first and show the counts before running. When the
user names a project, always pass `project_label` so later runs can filter by it.

## Error handling

Every tool returns `{ok, llm_mode, warnings, data}`. If `ok` is false, relay
`error.message` and its `hint` (usually credentials — `yeaboi --setup`); don't
retry blindly. `llm_mode: "fallback"` means no LLM was reachable and the report
is a deterministic count-based skeleton — suggest `yeaboi --setup`.
