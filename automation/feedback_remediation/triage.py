# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk>=0.1.0"]
# ///
"""Feedback-remediation pilot — the Step-4 (AI-native) Agent-SDK pipeline.

Nightly, this triages new GitHub issues (especially the ones the in-TUI feedback
form files) and decides what to do with each:

    bug + actionable + confident  -> label `claude-implement` (capped per run)
                                     so claude.yml's implement job opens a fix PR
    feature                       -> label `feature-candidate` (human decides)
    question                      -> comment + `feedback:needs-info`
    noise                         -> `feedback:noise` (never auto-closed)

The SDK owns *triage + orchestration + rate-limiting*; fix *execution* is
delegated to the existing `claude-implement` label pathway, so every automated
fix flows through the same CI + advisory review + human-merge gate as human
code. Labeling `claude-implement` IS "Claude kicks off Claude", composed through
the proven workflow rather than duplicating checkout/push logic here.

Safety: this process has `issues: write` only — it structurally cannot touch PRs
or merge anything. It caps `claude-implement` labels per run, is idempotent via
the `triaged` label cursor, skips bot-authored issues, and supports `--dry-run`.

Run locally:  uv run automation/feedback_remediation/triage.py --dry-run
Auth:         ANTHROPIC_API_KEY (the Agent SDK) + GH_TOKEN (the gh CLI).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import logging
import re

import github_io as gh

try:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
except ImportError:  # keeps the module importable for tests / lint without the SDK
    ClaudeAgentOptions = ResultMessage = query = None  # type: ignore[assignment,misc]

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("feedback_remediation")

# --- policy constants -------------------------------------------------------

MAX_FIXES_PER_RUN = 3  # cap on claude-implement labels applied in one run

# Labels whose presence means "not fresh feedback" — skip these issues entirely.
SKIP_LABELS = frozenset({"triaged", "groomer-report", "flaky-test", "ci-sentinel", "ci-red-main"})
SKIP_AUTHORS = frozenset({"github-actions[bot]", "dependabot[bot]"})

# Feedback-form title prefixes → type label (a strong prior when labels were
# dropped, which happens when the form files without a token).
_TITLE_PREFIX = re.compile(r"^\[(bug|feature|improvement|other)\]", re.IGNORECASE)

_AREAS = ("analysis", "planning", "standup", "retro", "performance", "reporting", "usage", "settings", "general")


# --- pure helpers (unit-tested) --------------------------------------------


def should_process(issue: dict) -> bool:
    """True if the issue is fresh feedback worth triaging this run."""
    if issue.get("author", {}).get("login") in SKIP_AUTHORS:
        return False
    labels = {label_dict["name"] for label_dict in issue.get("labels", [])}
    return not (labels & SKIP_LABELS)


def type_label_from_title(title: str) -> str | None:
    """Infer a ``type:*`` label from the feedback-form title prefix, if present."""
    match = _TITLE_PREFIX.match(title.strip())
    if not match:
        return None
    kind = match.group(1).lower()
    return f"type:{kind}"


def parse_classification(text: str) -> dict:
    """Extract the classification JSON, tolerating markdown code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    data = json.loads(cleaned)
    return {
        "category": str(data.get("category", "")).lower(),
        "actionable": bool(data.get("actionable", False)),
        "confidence": str(data.get("confidence", "low")).lower(),
        "reason": str(data.get("reason", "")),
    }


# --- SDK calls --------------------------------------------------------------

_CLASSIFY_SYSTEM = (
    "You are a GitHub issue triager for a terminal AI Scrum Master app. You return ONLY a JSON object, no prose."
)


async def _ask(prompt: str, system: str, model: str) -> str:
    """One SDK round-trip with no tools; return the final assistant text."""
    if query is None:  # pragma: no cover - only when SDK missing
        raise RuntimeError("claude-agent-sdk is not installed")
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system,
        allowed_tools=[],
        max_turns=1,
        permission_mode="dontAsk",
    )
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            return message.result
    return ""


async def classify(title: str, body: str) -> dict:
    """Classify one issue with Haiku (cheap). Returns the parsed dict."""
    prompt = (
        f"Classify this issue.\n\nTitle: {title}\n\nBody:\n{body[:4000]}\n\n"
        'Return ONLY JSON: {"category": "bug"|"feature"|"question"|"noise", '
        '"actionable": true|false, "confidence": "high"|"medium"|"low", '
        '"reason": "<one short sentence>"}. '
        '"actionable" means a maintainer could act on it as-is without more info.'
    )
    raw = await _ask(prompt, _CLASSIFY_SYSTEM, model="haiku")
    return parse_classification(raw)


async def is_implementable(title: str, body: str) -> bool:
    """Second-stage Sonnet check: is a bug specific enough to auto-implement?"""
    prompt = (
        f"An automated triager flagged this bug as actionable. Before we start an "
        f"implementation run, confirm it is specific enough to fix WITHOUT asking "
        f"the reporter any questions (clear repro or unambiguous expected behaviour).\n\n"
        f"Title: {title}\n\nBody:\n{body[:4000]}\n\n"
        'Return ONLY JSON: {"implementable": true|false}.'
    )
    raw = await _ask(prompt, _CLASSIFY_SYSTEM, model="sonnet")
    try:
        return bool(parse_classification(raw.replace("implementable", "actionable")).get("actionable"))
    except (json.JSONDecodeError, ValueError):
        return False


# --- orchestration ----------------------------------------------------------


async def triage_issue(issue: dict, fixes_used: int, max_fixes: int) -> int:
    """Triage one issue and act. Returns the number of fixes consumed (0 or 1)."""
    number = issue["number"]
    title = issue["title"]
    body = issue.get("body") or ""
    consumed = 0

    cls = await classify(title, body)
    logger.info(
        "#%s [%s] actionable=%s conf=%s — %s",
        number,
        cls["category"],
        cls["actionable"],
        cls["confidence"],
        cls["reason"],
    )

    # Labels every triaged issue gets: the cursor + an inferred type label.
    to_add = ["triaged"]
    type_label = type_label_from_title(title)
    if type_label:
        to_add.append(type_label)

    if cls["category"] == "bug" and cls["actionable"] and cls["confidence"] == "high":
        if fixes_used < max_fixes and await is_implementable(title, body):
            to_add.append("claude-implement")
            consumed = 1
            logger.info("#%s -> claude-implement (fix %s/%s)", number, fixes_used + 1, max_fixes)
        else:
            to_add.append("feedback:fix-queued")
            logger.info("#%s -> fix queued (cap reached or not implementable)", number)
    elif cls["category"] == "feature":
        to_add.append("feature-candidate")
    elif cls["category"] == "question":
        to_add.append("feedback:needs-info")
        gh.comment(
            number,
            "Thanks for the report! Could you add a bit more detail (steps to reproduce, "
            "what you expected)? — automated triage",
        )
    elif cls["category"] == "noise":
        to_add.append("feedback:noise")

    gh.add_labels(number, to_add)
    return consumed


def build_digest(feature_candidates: list[dict], fixed: list[dict]) -> str:
    """Render the weekly digest body from this run's feature/fix outcomes."""
    lines = ["## Feedback digest", "", f"_Updated {_dt.date.today().isoformat()} by automated triage._", ""]
    lines.append("### Feature candidates (awaiting a human `claude-implement`)")
    lines += [f"- #{issue['number']} {issue['title']}" for issue in feature_candidates] or ["- _none this week_"]
    lines += ["", "### Bugs sent to implementation this week"]
    lines += [f"- #{issue['number']} {issue['title']}" for issue in fixed] or ["- _none this week_"]
    return "\n".join(lines)


async def run(dry_run: bool, do_digest: bool, max_fixes: int) -> None:
    gh.set_dry_run(dry_run)
    issues = [issue for issue in gh.list_open_issues() if should_process(issue)]
    logger.info("triaging %s fresh issue(s) (dry_run=%s)", len(issues), dry_run)

    fixes_used = 0
    feature_candidates: list[dict] = []
    fixed: list[dict] = []
    for issue in issues:
        consumed = await triage_issue(issue, fixes_used, max_fixes)
        fixes_used += consumed
        if consumed:
            fixed.append(issue)

    if do_digest:
        # Re-list to catch feature-candidate labels applied this run.
        for issue in issues:
            names = {label_dict["name"] for label_dict in issue.get("labels", [])}
            if "feature-candidate" in names or type_label_from_title(issue["title"]) == "type:feature":
                feature_candidates.append(issue)
        body = build_digest(feature_candidates, fixed)
        existing = gh.find_open_issue_by_label("feedback-digest")
        if existing:
            gh.update_issue_body(existing, body)
        else:
            gh.create_issue("Feedback digest", body, ["feedback-digest"])

    logger.info("done — %s issue(s) triaged, %s sent to implementation", len(issues), fixes_used)


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage GitHub feedback issues.")
    parser.add_argument("--dry-run", action="store_true", help="Log intended actions without changing anything.")
    parser.add_argument("--digest", action="store_true", help="Also create/update the weekly feedback digest issue.")
    parser.add_argument(
        "--max-fixes", type=int, default=MAX_FIXES_PER_RUN, help="Cap on claude-implement labels this run."
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, do_digest=args.digest, max_fixes=args.max_fixes))


if __name__ == "__main__":
    main()
