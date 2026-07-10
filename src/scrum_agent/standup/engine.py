"""Daily Standup engine — turns activity + sprint context into a delivered report.

This is a standalone pipeline (NOT a LangGraph node): the scheduled headless run
must be fast, cheap, and free of graph-checkpoint machinery, so it calls get_llm()
directly and follows the same parse → fallback → format convention the graph nodes
use (agent/nodes.py). Activity gathering and confidence are deterministic function
calls; the LLM is used only to synthesize prose, keeping a scheduled run to a
single cheap call.

Pipeline (run_standup):
  load session state + standup config
  → collect recent activity (collector)
  → gather sprint context + compute confidence (sprint_context, confidence)
  → per-member updates: self-reported verbatim, others inferred by one LLM call
  → assemble StandupReport → deliver → record run

# See README: "The ReAct Loop" — using the LLM outside the main graph
# See README: "Prompt Construction" — the standup summary prompt
# See README: "Daily Standup" — engine
"""

from __future__ import annotations

import json
import logging
from datetime import date

from langchain_core.messages import HumanMessage

from scrum_agent.agent.state import MemberUpdate, StandupReport
from scrum_agent.standup import collector, confidence, sprint_context
from scrum_agent.standup.store import StandupStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def _resolve_source_params(config: dict | None) -> dict:
    """Resolve collector source identifiers from config/env.

    Returns kwargs for collect_recent_activity: jira_project, azdo_project,
    github_repo, local_repo_path, confluence_space.
    """
    from scrum_agent.config import (
        get_azure_devops_project,
        get_confluence_space_key,
        get_jira_project_key,
    )

    params = {
        "jira_project": get_jira_project_key() or "",
        "azdo_project": get_azure_devops_project() or "",
        "confluence_space": get_confluence_space_key() or "",
        "github_repo": "",
        "local_repo_path": (config or {}).get("repo_path", "") or "",
    }
    # GitHub repo + optional overrides come from config getters added for standup.
    try:
        from scrum_agent.config import get_standup_github_repo

        params["github_repo"] = get_standup_github_repo() or ""
    except Exception:
        pass
    return params


# ---------------------------------------------------------------------------
# LLM summarization (parse → fallback → format)
# ---------------------------------------------------------------------------


def _parse_standup_response(raw: str) -> dict:
    """Extract the summary JSON from an LLM response, tolerating markdown fences."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("standup: could not parse LLM JSON response")
        return {}


def _group_activity_by_author(items: list[dict], members: list[str]) -> dict[str, list[dict]]:
    """Group activity items by author, limited to the given member names."""
    grouped: dict[str, list[dict]] = {m: [] for m in members}
    for item in items:
        author = (item.get("author") or "").strip()
        if author in grouped:
            grouped[author].append(
                {
                    "kind": item.get("kind", ""),
                    "title": item.get("title", ""),
                    "status": item.get("status", ""),
                    "source": item.get("source", ""),
                }
            )
    return grouped


def _build_fallback_member_updates(grouped: dict[str, list[dict]], self_reported: dict[str, str]) -> list[MemberUpdate]:
    """Deterministic per-member updates when the LLM is unavailable.

    Self-reported updates are used verbatim; inferred members get a plain
    join of their activity titles.
    """
    updates: list[MemberUpdate] = []
    for name, text in self_reported.items():
        updates.append(MemberUpdate(name=name, summary=text, source="self-reported"))
    for name, acts in grouped.items():
        if name in self_reported:
            continue
        if acts:
            titles = "; ".join(a["title"] for a in acts if a.get("title"))[:400]
            summary = titles or "activity detected"
        else:
            summary = "No activity detected."
        updates.append(MemberUpdate(name=name, summary=summary, source="inferred"))
    return updates


def _build_fallback_team_summary(bundle: collector.ActivityBundle, progress: confidence.SprintProgress) -> str:
    """Deterministic team summary when the LLM is unavailable."""
    counts = ", ".join(f"{src}: {n}" for src, n in bundle.counts) or "no sources"
    return (
        f"{bundle.total()} activity item(s) detected ({counts}). "
        f"Sprint status: {progress.confidence_label}. {progress.confidence_rationale}"
    ).strip()


def _summarize_members(
    *,
    bundle: collector.ActivityBundle,
    progress: confidence.SprintProgress,
    members: list[str],
    self_reported: dict[str, str],
    sprint_name: str,
) -> tuple[list[MemberUpdate], str, list[str]]:
    """Produce (member_updates, team_summary, warnings) via one LLM call + deterministic fallback.

    Unlike before, an LLM auth/billing failure is NOT re-raised — it's turned into
    a user-facing *warning* and the deterministic fallback is used, so the standup
    still renders with a clear reason instead of crashing or looking empty.
    Self-reported updates are always passed through verbatim regardless of the LLM.
    """
    grouped = _group_activity_by_author(bundle.items, members)
    inferred_names = [m for m in members if m not in self_reported]
    inferred_payload = [{"name": name, "activity": grouped.get(name, [])} for name in inferred_names]

    def _fallback(extra_warnings: list[str]) -> tuple[list[MemberUpdate], str, list[str]]:
        return (
            _build_fallback_member_updates(grouped, self_reported),
            _build_fallback_team_summary(bundle, progress),
            extra_warnings,
        )

    # Nothing to infer and no self-reports → deterministic team summary only.
    if not inferred_payload and not self_reported:
        return _fallback([])

    # No LLM credentials → don't attempt the call; say so plainly.
    from scrum_agent.config import is_llm_configured

    configured, why = is_llm_configured()
    if not configured:
        logger.warning("standup: LLM not configured (%s) — using deterministic fallback", why)
        return _fallback([f"AI summary unavailable — {why}."])

    from scrum_agent.agent.llm import get_llm, track_usage
    from scrum_agent.agent.nodes import _is_llm_auth_or_billing_error
    from scrum_agent.prompts.standup import get_standup_summary_prompt

    prompt = get_standup_summary_prompt(
        sprint_name=sprint_name,
        sprint_day=progress.sprint_day,
        sprint_total_days=progress.sprint_total_days,
        confidence_label=progress.confidence_label,
        confidence_rationale=progress.confidence_rationale,
        inferred_members=inferred_payload,
        self_reported=self_reported,
        activity_counts=bundle.counts,
    )

    try:
        logger.info("standup: invoking LLM to summarize %d inferred member(s)", len(inferred_payload))
        response = get_llm(temperature=0.0).invoke([HumanMessage(content=prompt)])
        track_usage(response)
        parsed = _parse_standup_response(response.content)
    except Exception as exc:
        if _is_llm_auth_or_billing_error(exc):
            logger.warning("standup: LLM auth/billing error — surfacing as warning: %s", exc)
            return _fallback(["AI summary unavailable — API key invalid or billing issue."])
        logger.warning("standup: LLM summarization failed, using fallback: %s", exc)
        return _fallback(["AI summary unavailable — LLM request failed (see logs)."])

    # Assemble: self-reported verbatim first, then LLM-inferred members.
    updates: list[MemberUpdate] = [
        MemberUpdate(name=name, summary=text, source="self-reported") for name, text in self_reported.items()
    ]
    llm_members = {m.get("name", ""): m for m in parsed.get("members", []) if isinstance(m, dict)}
    for name in inferred_names:
        m = llm_members.get(name, {})
        summary = (m.get("summary") or "").strip()
        if not summary:
            # LLM omitted this member — fall back to their activity titles.
            acts = grouped.get(name, [])
            summary = "; ".join(a["title"] for a in acts if a.get("title"))[:400] or "No activity detected."
        updates.append(MemberUpdate(name=name, summary=summary, blockers=(m.get("blockers") or "").strip()))

    team_summary = (parsed.get("team_summary") or "").strip() or _build_fallback_team_summary(bundle, progress)
    return updates, team_summary, []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_standup(
    session_id: str,
    *,
    channels: list[str] | None = None,
    days: int = 1,
    deliver: bool = True,
    dry_run: bool = False,
    db_path=None,
    today: date | None = None,
) -> StandupReport:
    """Run a full standup for ``session_id`` and return the StandupReport.

    Args:
        channels: delivery channels override; falls back to saved config, then ["terminal"].
        days: activity look-back window in days.
        deliver: when True, fan out to delivery channels (skipped if dry_run).
        dry_run: build the report but do not deliver (used by the TUI "Generate" preview).
        db_path: override sessions.db path (tests); defaults to paths.get_db_path().
        today: override for the current date (tests).
    """
    from scrum_agent.paths import get_db_path
    from scrum_agent.sessions import SessionStore

    today = today or date.today()
    date_str = today.isoformat()
    db_path = db_path or get_db_path()
    logger.info("run_standup: session=%s date=%s days=%d dry_run=%s", session_id, date_str, days, dry_run)

    # 1. Load session state + standup config.
    with SessionStore(db_path) as sessions:
        state = sessions.load_state(session_id) or {}
    with StandupStore(db_path) as store:
        config = store.load_config(session_id)
        self_reported = store.get_my_updates(session_id, date_str)

    resolved_channels = channels or (config or {}).get("delivery_channels") or ["terminal"]
    source_params = _resolve_source_params(config)

    # 2. Collect recent activity across all resolved sources.
    bundle = collector.collect_recent_activity(days=days, **source_params)

    # 3. Sprint context + deterministic confidence.
    ctx = sprint_context.gather(
        state,
        jira_project=source_params["jira_project"],
        azdo_project=source_params["azdo_project"],
    )
    progress = confidence.compute(
        sprint_name=ctx.sprint_name,
        start_date=ctx.start_date,
        sprint_length_weeks=ctx.sprint_length_weeks,
        capacity_points=ctx.capacity_points if ctx.have_burn else 0.0,
        completed_points=ctx.completed_points,
        activity_count=bundle.total(),
        today=today,
    )

    # 4. Team members: prefer the plan's selected members, else distinct authors seen.
    members = list(state.get("selected_team_members") or ()) or bundle.authors()
    # Ensure anyone who self-reported is included even if not in the roster.
    for name in self_reported:
        if name not in members:
            members.append(name)

    # 5. Per-member + team summary (one LLM call, deterministic fallback).
    member_updates, team_summary, llm_warnings = _summarize_members(
        bundle=bundle,
        progress=progress,
        members=members,
        self_reported=self_reported,
        sprint_name=ctx.sprint_name,
    )

    # Warnings the user must see: source auth failures (from the collector) first,
    # then any LLM/config issue. These render as a "Notices" section, never silent.
    warnings = [f"{src.replace('_', ' ').title()}: {msg}" for src, msg in bundle.errors] + llm_warnings

    report = StandupReport(
        date=date_str,
        session_id=session_id,
        sprint_name=ctx.sprint_name,
        sprint_day=progress.sprint_day,
        sprint_total_days=progress.sprint_total_days,
        confidence_pct=progress.confidence_pct,
        confidence_label=progress.confidence_label,
        confidence_rationale=progress.confidence_rationale,
        team_summary=team_summary,
        member_updates=tuple(member_updates),
        activity_counts=tuple(bundle.counts),
        warnings=tuple(warnings),
    )

    # 6. Deliver, then record the run (so delivery status is captured).
    delivery_status: dict[str, bool] = {}
    status = "success"
    if deliver and not dry_run:
        try:
            from scrum_agent.standup import delivery

            delivery_status = delivery.deliver(report, resolved_channels)
            if delivery_status and not all(delivery_status.values()):
                status = "partial"
        except Exception as e:
            logger.error("standup delivery raised: %s", e)
            status = "partial"

    with StandupStore(db_path) as store:
        store.record_run(report, delivery_status=delivery_status, status=status)

    logger.info(
        "run_standup complete: session=%s day=%d/%d confidence=%d%% status=%s",
        session_id,
        report.sprint_day,
        report.sprint_total_days,
        report.confidence_pct,
        status,
    )
    return report
