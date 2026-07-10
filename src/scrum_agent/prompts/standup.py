"""Prompt construction for the Daily Standup summary.

One LLM call turns raw activity + sprint context into (a) a concise per-member
update for each person whose work must be *inferred* from activity, and (b) a
team-level narrative. Members who typed their own update are handled verbatim by
the engine and are NOT re-summarized here — we only pass their text in as
context so the team narrative can reference it.

Uses the ARC framework (Ask · Requirements · Context) like every other prompt in
this package.

# See README: "Prompt Construction" — ARC framework, chain-of-thought, JSON output
"""

from __future__ import annotations

import json


def get_standup_summary_prompt(
    *,
    sprint_name: str,
    sprint_day: int,
    sprint_total_days: int,
    confidence_label: str,
    confidence_rationale: str,
    inferred_members: list[dict],
    self_reported: dict[str, str],
    activity_counts: list[tuple[str, int]],
) -> str:
    """Build the standup-summary prompt.

    Args:
        inferred_members: [{"name": str, "activity": [ {kind,title,status,source}, ... ]}]
            — one entry per person whose update must be inferred from activity.
        self_reported: {member_name: typed_update} — passed as context only.
        activity_counts: (source, count) pairs for the "what we looked at" line.
    """
    # --- Context block: everything the model needs to reason over ------------
    counts_str = ", ".join(f"{src}: {n}" for src, n in activity_counts) or "no activity sources reported"
    inferred_json = json.dumps(inferred_members, ensure_ascii=False, indent=2)
    self_json = json.dumps(self_reported, ensure_ascii=False, indent=2)

    # ARC: Ask
    ask = (
        "You are an experienced Scrum Master writing the notes for today's daily standup. "
        "Summarize what each team member did since the last standup, and write a short "
        "team-level progress narrative."
    )

    # ARC: Requirements
    requirements = (
        "Requirements:\n"
        "- For EACH person in INFERRED_MEMBERS, write a one- to two-sentence 'summary' of what they "
        "worked on, derived ONLY from their listed activity. Do not invent work that isn't in the data.\n"
        "- If their activity suggests a blocker (e.g. a PR stuck in review, a ticket flipped back to "
        "'Blocked'), note it in 'blockers'; otherwise use an empty string.\n"
        "- Write 'team_summary' as 2-4 sentences: overall momentum, notable progress, and any risks. "
        f"Factor in the sprint status (currently '{confidence_label}': {confidence_rationale}).\n"
        "- People in SELF_REPORTED already wrote their own update — do NOT produce summaries for them, "
        "but DO consider their updates when writing team_summary.\n"
        "- Be concrete and concise. No filler, no preamble.\n"
        "- Return ONLY a JSON object, no markdown fences, of the exact shape:\n"
        '  {"members": [{"name": "...", "summary": "...", "blockers": "..."}], "team_summary": "..."}'
    )

    # ARC: Context
    context = (
        "Context:\n"
        f"- Sprint: {sprint_name or 'unknown'} — day {sprint_day} of {sprint_total_days}.\n"
        f"- Activity sources examined ({counts_str}).\n"
        f"- INFERRED_MEMBERS (summarize these):\n{inferred_json}\n"
        f"- SELF_REPORTED (context only, do not summarize):\n{self_json}"
    )

    return f"{ask}\n\n{requirements}\n\n{context}"
