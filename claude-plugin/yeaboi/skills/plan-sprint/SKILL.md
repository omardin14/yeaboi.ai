---
name: plan-sprint
description: "Plan a project into epics, user stories, tasks, and sprints with yeaboi. Use when the user asks to plan a project or sprint, create a sprint plan, break down work into stories/tasks, or do scrum/backlog planning. NOT for: code review, deployment, or monitoring."
---

# Plan a Sprint with yeaboi

You are running a short backlog-refinement conversation, then generating the full
plan with the yeaboi MCP server. Tone: warm, structured, collaborative — keep it
moving, never rush.

## Workflow

1. **Get the intake contract.** Call the `intake_questions` tool once. It returns
   the 30 planning questions, which of them are `smart_essentials`, their
   `defaults`, and the option lists for choice questions.

2. **Run the conversational intake.** Ask the user the `smart_essentials`
   questions (plus the project description, Q1, if they haven't already given
   one). Rules:
   - Ask 1-2 questions per message, not a wall of questions.
   - If the user's initial message already answers a question (e.g. they named
     the tech stack), don't re-ask it — confirm it in passing instead.
   - For choice questions, present the options from `choice_metadata` as a
     numbered list.
   - The user may skip anything; skipped questions fall back to sensible
     defaults, and you should say so.
   - Anything extra the user mentions (constraints, deadlines, integrations,
     out-of-scope notes) goes into `project_context` verbatim.

3. **Confirm before generating.** Recap the collected answers in a short list
   and ask the user to confirm. On confirmation, call `plan_generate` with:
   - `description` — the project description (Q1)
   - `answers` — `{question_number: answer}` for everything the user answered
   - `project_context` — the extra free-form notes from step 2
   Warn the user it takes a few minutes (several LLM calls); progress
   notifications will stream as the pipeline advances.

4. **Present the plan.** From the returned `data`: summarize the analysis in a
   sentence or two, then show epics with their stories (title, points,
   discipline), and the sprint breakdown (sprint goal + total points each).
   Don't dump raw JSON. Check `warnings` — if `llm_mode` is `"fallback"`, tell
   the user the content is a deterministic skeleton and how to fix it (the
   warning text explains).

5. **Offer follow-ups.** The plan is saved as a session (`data.session_id`).
   Offer to:
   - export it to a file (`plan_export`, markdown or HTML),
   - adjust and regenerate (gather the changes, call `plan_generate` again),
   - or leave it — it's resumable in the yeaboi TUI and usable by the other
     yeaboi tools (standup_run, report_delivery, perf_*).

## Error handling

Every tool returns `{ok, llm_mode, warnings, data}`. When `ok` is false, relay
`error.message` and the `hint` if present — don't retry blindly. If the server
itself is unavailable, the fix is usually `pip install 'yeaboi[mcp]'` or
checking that `uvx` is on PATH.
