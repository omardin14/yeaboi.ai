"""Team-analysis engine — the headless pipeline behind the TUI Analysis mode.

# See README: "Architecture" — engines are UI-free pipelines; the TUI, CLI and
# MCP server are thin adapters over them (CLAUDE.md "REQUIRED: Surface Parity").

Design choice — standalone pipeline, not a LangGraph node (same rationale as
``standup/engine.py``): the analysis is a deterministic gather step
(``_fetch_*_history``) followed by the 4-worker parallel analysis in
``tools/team_learning.py`` (which already handles its own LLM calls with
regex fallbacks), so a compiled graph would add checkpointing overhead for
nothing.

Error contract:
- Missing tracker / no closed sprints / fetch failures **raise** — with no
  board there is nothing to analyse, and every caller (TUI worker, CLI, MCP
  ``run_engine``) has its own error surface for that.
- LLM failures never raise: the parsers inside ``_run_parallel_analysis`` fall
  back to regex extraction, and the optional insights/samples steps degrade to
  a ``warnings`` entry.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Friendly tracker labels for 'both'-mode output (mirrors reporting/engine.py's
# _source_names). Note analysis uses "azdevops" (not reporting's "azuredevops").
_SOURCE_NAMES = {"jira": "Jira", "azdevops": "Azure DevOps"}

# The three analysis components are decoupled — each runs over its OWN sub-sources,
# not the tracker. Delivery (the sprint/ticket pipeline → TeamProfile) runs PER
# tracker (velocity isn't comparable across trackers). Code (remote AI-usage scan)
# and Docs (doc-quality read) are each ONE global scan over their selected hosts.
# Note: the code Azure-Repos tag is "azdo", distinct from the delivery tracker key
# "azdevops" — they are different systems.
_COMPONENTS = ("delivery", "code", "docs")
_DELIVERY_SOURCES = ("jira", "azdevops")
_CODE_SOURCES = ("github", "azdo")
_DOC_SOURCES = ("confluence", "notion")
_COMPONENT_SOURCES: dict[str, tuple[str, ...]] = {
    "delivery": _DELIVERY_SOURCES,
    "code": _CODE_SOURCES,
    "docs": _DOC_SOURCES,
}


def _resolve_components(
    source: str,
    components: dict[str, list[str]] | None,
    include_ai_usage: bool,
    include_doc_quality: bool,
) -> dict[str, list[str]]:
    """Resolve the component → sub-source map that will actually run.

    An explicit ``components`` (keyed ``delivery``/``code``/``docs``) wins, filtered
    to each component's known sub-sources. Otherwise derive from ``source`` + the
    legacy booleans: delivery over the resolved tracker(s) (``source``/'both'/auto),
    code/docs over all their sub-sources when the booleans are set — reproducing
    today's behaviour, except code/docs now run **once** rather than per tracker.
    """
    if components is not None:

        def _pick(comp: str) -> list[str]:
            allowed = _COMPONENT_SOURCES[comp]
            return [v for v in (components.get(comp) or []) if v in allowed]

        return {"delivery": _pick("delivery"), "code": _pick("code"), "docs": _pick("docs")}

    if source == "both":
        delivery = _available_sources()
    elif source in _DELIVERY_SOURCES:
        delivery = [source]
    else:
        from yeaboi.tools.team_learning import _detect_source

        detected = _detect_source()
        delivery = [detected] if detected in _DELIVERY_SOURCES else []
    return {
        "delivery": delivery,
        "code": _available_code_sources() if include_ai_usage else [],
        "docs": _available_doc_sources() if include_doc_quality else [],
    }


def _resolve_source(source: str) -> str:
    from yeaboi.tools.team_learning import _detect_source

    resolved = source or _detect_source()
    if resolved not in ("jira", "azdevops"):
        raise ValueError(
            "No tracker configured for analysis — set JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN "
            "or AZURE_DEVOPS_ORG_URL/AZURE_DEVOPS_TOKEN (source: 'jira' or 'azdevops')."
        )
    return resolved


def _resolve_project(source: str, project_key: str, team_name: str) -> tuple[str, str]:
    if project_key:
        return project_key, team_name
    try:
        if source == "jira":
            from yeaboi.config import get_jira_project_key

            return get_jira_project_key() or "", team_name
        from yeaboi.config import get_azure_devops_project, get_azure_devops_team

        return get_azure_devops_project() or "", team_name or (get_azure_devops_team() or "")
    except Exception:
        return project_key, team_name


def _generate_samples(profile, examples: dict, warnings: list[str]) -> dict | None:
    """Auto-accepted sample tickets in the team's style (the TUI preview flow,
    minus the interactive accept/edit loop)."""
    try:
        from yeaboi.agent.nodes import _format_team_calibration
        from yeaboi.tools.team_learning import (
            generate_sample_epic,
            generate_sample_sprint,
            generate_sample_stories,
            generate_sample_tasks,
        )

        calibration = _format_team_calibration(profile, examples=examples)
        epic = generate_sample_epic(calibration, examples)
        stories = generate_sample_stories(calibration, epic, examples)
        tasks = generate_sample_tasks(calibration, stories, examples)
        sprint = generate_sample_sprint(calibration, stories, tasks, examples)
        return {"epic": epic, "stories": stories, "tasks": tasks, "sprint": sprint}
    except Exception as exc:  # LLM/parse trouble → warning, never a crash
        logger.warning("Sample-ticket generation failed: %s", exc)
        warnings.append(f"Sample-ticket generation failed: {exc}")
        return None


def _available_sources() -> list[str]:
    """Which trackers are configured (creds present). Ordered jira-first — the
    same precedence as ``_detect_source`` — so 'both' output is deterministic."""
    available: list[str] = []
    try:
        from yeaboi.config import get_jira_base_url, get_jira_token

        if get_jira_base_url() and get_jira_token():
            available.append("jira")
    except Exception:
        pass
    try:
        from yeaboi.config import get_azure_devops_org_url, get_azure_devops_token

        if get_azure_devops_org_url() and get_azure_devops_token():
            available.append("azdevops")
    except Exception:
        pass
    return available


def _available_code_sources() -> list[str]:
    """Which remote code hosts are configured (GitHub, Azure Repos). Used to build
    the picker's Code row and to default ``components=None``."""
    out: list[str] = []
    try:
        from yeaboi.config import get_github_token, get_standup_github_repo

        if get_standup_github_repo() and get_github_token():
            out.append("github")
    except Exception:
        pass
    try:
        from yeaboi.config import get_azure_devops_project, get_azure_devops_token

        if get_azure_devops_project() and get_azure_devops_token():
            out.append("azdo")
    except Exception:
        pass
    return out


def _available_doc_sources() -> list[str]:
    """Which doc platforms are configured (Confluence, Notion). Used to build the
    picker's Docs row."""
    out: list[str] = []
    try:
        from yeaboi.config import get_confluence_base_url, get_confluence_token

        if get_confluence_token() and get_confluence_base_url():
            out.append("confluence")
    except Exception:
        pass
    try:
        from yeaboi.config import get_notion_token

        if get_notion_token():
            out.append("notion")
    except Exception:
        pass
    return out


# Headline rows shown in the 'both' side-by-side comparison. Each entry is
# (label, formatter) where formatter renders one profile's value; values are
# never blended across trackers — they sit in separate columns.
_COMPARISON_ROWS: tuple[tuple[str, callable], ...] = (
    ("Sprints analysed", lambda p: str(p.sample_sprints)),
    ("Stories analysed", lambda p: str(p.sample_stories)),
    ("Avg velocity", lambda p: f"{p.velocity_avg:.0f} ± {p.velocity_stddev:.0f}"),
    ("Completion rate", lambda p: f"{p.sprint_completion_rate:.0f}%"),
    ("Estimation accuracy", lambda p: f"{p.estimation_accuracy_pct:.0f}%"),
)


def _build_comparison(delivery: dict) -> list[tuple[str, str, str]]:
    """Side-by-side delivery headline rows: (label, jira_value, azdevops_value). Kept
    deliberately separate (not aggregated) so each number names its tracker."""
    jira = delivery.get("jira", {}).get("profile")
    azdo = delivery.get("azdevops", {}).get("profile")
    rows: list[tuple[str, str, str]] = []
    for label, fmt in _COMPARISON_ROWS:
        rows.append((label, fmt(jira) if jira else "—", fmt(azdo) if azdo else "—"))
    return rows


def get_team_roster(source: str = "", project_key: str = "", sprint_count: int = 8, db_path=None) -> list[str]:
    """Discover the team roster (assignee names) for a tracker — cheap, no LLM.

    Fetches ``sprint_count`` closed sprints (network only, via the same ``_fetch_*``
    helpers the full run uses) and returns the sorted, unique assignee display names.
    The expensive ``_run_parallel_analysis`` LLM step is skipped — this exists so the
    UI can present a member multi-select before committing to a full analysis.

    Raises the same ``ValueError`` as ``run_team_analysis`` when no tracker is
    configured; returns ``[]`` for a board with no closed sprints (the caller can then
    offer an unscoped run). ``db_path`` is accepted for signature parity (unused here).
    """
    from yeaboi.tools.team_learning import _fetch_azdevops_history, _fetch_jira_history

    resolved_source = _resolve_source(source)
    resolved_project, _ = _resolve_project(resolved_source, project_key, "")
    fetch = _fetch_jira_history if resolved_source == "jira" else _fetch_azdevops_history
    sprint_data = fetch(resolved_project, sprint_count)
    roster = sorted(
        {
            (s.get("assignee", "") or "").strip()
            for sd in sprint_data
            for s in sd.get("stories", [])
            if (s.get("assignee", "") or "").strip()
        }
    )
    logger.info("Roster for %s/%s: %d member(s)", resolved_source, resolved_project, len(roster))
    return roster


def run_team_analysis(
    source: str = "",
    project_key: str = "",
    team_name: str = "",
    sprint_count: int = 8,
    generate_samples: bool = False,
    include_insights: bool = True,
    include_ai_usage: bool = True,
    include_doc_quality: bool = True,
    components: dict[str, list[str]] | None = None,
    members: dict[str, list[str]] | None = None,
    *,
    progress: list | None = None,
    db_path=None,
) -> dict:
    """Analyse the team into decoupled Delivery / Code / Docs components.

    The three components run independently over their **own** sub-sources:
    **Delivery** (velocity/calibration/contributors → a ``TeamProfile``) runs once
    per selected tracker (jira/azdevops; never blended). **Code** (remote AI-usage
    scan over github/azdo) and **Docs** (doc-quality over confluence/notion) are each
    a single **global** scan. Returns:
    ``{"delivery": {tracker: {profile, examples, ...}}, "code": {signal, examples}|None,
    "docs": {signal, examples}|None, "comparison": [...], "components": {...},
    "warnings": [...]}``. The global code/docs signals are also attached to every
    saved delivery profile (so the stored-profile browser keeps showing them).

    Args:
        source: 'jira', 'azdevops', or 'both'; blank auto-detects a single
            tracker from configured creds.
        project_key: tracker project; blank falls back to the configured one.
        team_name: AzDO team name attached to the profile (blank = configured).
        sprint_count: closed sprints to analyse (TUI uses 8).
        generate_samples: also generate auto-accepted sample tickets
            (epic/stories/tasks/sprint) in the team's style — extra LLM calls.
        include_insights: also generate the start/stop/keep/try coaching
            insights (one extra LLM call).
        include_ai_usage: legacy toggle folded into ``components`` when the latter is
            None — scan commits/PRs for AI-tool markers (Code component).
        include_doc_quality: legacy toggle folded into ``components`` when None — read
            recent Notion/Confluence pages (Docs component).
        components: component → sub-source map, e.g.
            ``{"delivery": ["jira"], "code": ["github", "azdo"], "docs": ["confluence"]}``.
            Each component runs over ONLY its listed sub-sources; an absent/empty
            component is skipped. ``None`` derives the default from ``source`` + the
            two booleans (delivery over source/both/auto; code/docs over all their
            sub-sources).
        members: per delivery-tracker subset of assignee names, e.g.
            ``{"jira": ["Alice", "Bob"]}`` — re-scopes that tracker's velocity/
            contributors. The single global code scan filters commit authors by the
            union of all selected members. Blank/missing = whole team.
        progress: optional shared list the analysis workers append status
            strings to (the TUI reads it from its frame loop).
        db_path: sessions DB override (tests). Defaults to paths.get_db_path().

    Raises ValueError when nothing at all can be analysed (no tracker/component
    configured); per-tracker board errors degrade to a ``warnings`` entry.
    """
    comps = _resolve_components(source, components, include_ai_usage, include_doc_quality)
    members = members or {}
    warnings: list[str] = []
    progress_list = progress if progress is not None else []
    logger.info(
        "Team analysis starting: delivery=%s code=%s docs=%s members=%s",
        comps["delivery"],
        comps["code"],
        comps["docs"],
        members or "all",
    )

    # Delivery — one TeamProfile per selected tracker (never blended).
    delivery: dict[str, dict] = {}
    single = len(comps["delivery"]) == 1
    for tracker in comps["delivery"]:
        try:
            delivery[tracker] = _run_delivery(
                tracker,
                project_key if single else "",
                team_name if single else "",
                members.get(tracker),
                sprint_count,
                generate_samples,
                include_insights,
                progress_list,
            )
        except Exception as exc:  # a per-tracker failure degrades to a warning, not a crash
            logger.warning("Delivery analysis failed for %s: %s", tracker, exc)
            warnings.append(f"{_SOURCE_NAMES.get(tracker, tracker)} delivery analysis failed: {exc}")

    # Code + Docs — one global scan each, over their selected sub-sources.
    union_members = sorted({m for names in members.values() for m in (names or [])}) or None
    code = None
    if comps["code"]:
        from yeaboi.tools.team_learning import _run_ai_usage_component

        signal, blob = _run_ai_usage_component("", "", [], [], union_members, progress_list, sub_sources=comps["code"])
        if signal is not None:
            code = {"signal": signal, "examples": blob}
    docs = None
    if comps["docs"]:
        from yeaboi.tools.team_learning import _run_doc_quality_component

        signal, blob = _run_doc_quality_component("", "", progress_list, sub_sources=comps["docs"])
        if signal is not None:
            docs = {"signal": signal, "examples": blob}

    # Attach the global code/docs signals to every delivery profile, then persist.
    if delivery:
        _persist_delivery(delivery, code, docs, db_path)
    for sub in delivery.values():
        warnings.extend(sub.get("warnings", []))

    if not delivery and code is None and docs is None:
        # Nothing produced a result. If literally nothing is selected/available,
        # raise the canonical "no tracker configured" error; else a softer message.
        if not comps["delivery"] and not comps["code"] and not comps["docs"]:
            _resolve_source("")  # raises
        raise ValueError("Nothing to analyse — no component produced a result (see warnings).")

    ran = [t for t in delivery if delivery[t].get("profile") is not None]
    return {
        "delivery": delivery,
        "code": code,
        "docs": docs,
        "comparison": _build_comparison(delivery) if len(ran) >= 2 else [],
        "components": comps,
        "warnings": warnings,
    }


def _run_delivery(
    tracker: str,
    project_key: str,
    team_name: str,
    members: list[str] | None,
    sprint_count: int,
    generate_samples: bool,
    include_insights: bool,
    progress: list,
) -> dict:
    """Run the Delivery component for one tracker → a per-tracker result sub-dict.

    Fetches the board and runs the 4-worker parallel analysis (code/docs are NOT run
    here — they are separate global scans). Does NOT save; ``_persist_delivery``
    attaches the global code/docs signals and persists afterwards."""
    from yeaboi.tools.team_learning import (
        _fetch_azdevops_history,
        _fetch_jira_history,
        _run_parallel_analysis,
        compute_headline_stats,
    )

    started = time.monotonic()
    warnings: list[str] = []
    resolved_source = _resolve_source(tracker)
    resolved_project, resolved_team = _resolve_project(resolved_source, project_key, team_name)
    logger.info(
        "Delivery analysis: source=%s project=%s sprints=%d members=%s",
        resolved_source,
        resolved_project,
        sprint_count,
        members or "all",
    )
    fetch = _fetch_jira_history if resolved_source == "jira" else _fetch_azdevops_history
    sprint_data = fetch(resolved_project, sprint_count)
    if not sprint_data:
        raise ValueError("No closed sprints found on the board — nothing to analyse.")
    sprint_names = [sd.get("sprint_name", "") for sd in sprint_data]

    profile, examples = _run_parallel_analysis(
        resolved_source,
        resolved_project or "unknown",
        sprint_data,
        progress,
        include_ai_usage=False,
        include_doc_quality=False,
        members=members,
        warnings=warnings,
    )
    if resolved_team and not profile.team_name:
        from dataclasses import replace

        profile = replace(profile, team_name=resolved_team)

    duration = time.monotonic() - started
    insights = _generate_team_insights_safe(profile, examples) if include_insights else None
    samples = _generate_samples(profile, examples or {}, warnings) if generate_samples else None
    return {
        "source": resolved_source,
        "project_key": resolved_project,
        "sprint_names": sprint_names,
        "duration_secs": round(duration, 1),
        "profile": profile,
        "examples": examples,
        "headline_stats": compute_headline_stats(profile, examples),
        "insights": insights,
        "samples": samples,
        "log_path": "",
        "warnings": warnings,
    }


def _generate_team_insights_safe(profile, examples):
    from yeaboi.tools.team_learning import _generate_team_insights

    return _generate_team_insights(profile, examples)  # never raises — deterministic fallback inside


def _persist_delivery(delivery: dict, code: dict | None, docs: dict | None, db_path) -> None:
    """Attach the global code/docs signals to each delivery profile, save it, and
    write the analysis log. Scanning happens once; the same signal is written onto
    every tracker's profile so the stored-profile browser keeps rendering them."""
    from dataclasses import replace

    from yeaboi.paths import get_db_path
    from yeaboi.team_profile import TeamProfileStore
    from yeaboi.team_profile_exporter import write_analysis_log

    code_sig = code["signal"] if code else None
    docs_sig = docs["signal"] if docs else None
    with TeamProfileStore(db_path or get_db_path()) as store:
        for sub in delivery.values():
            profile = sub["profile"]
            examples = sub["examples"]
            if code_sig is not None:
                profile = replace(profile, ai_adoption=code_sig)
                examples["ai_adoption"] = code["examples"]
            if docs_sig is not None:
                profile = replace(profile, doc_quality=docs_sig)
                examples["doc_quality"] = docs["examples"]
            sub["profile"] = profile
            store.save(profile, examples=examples)
            try:
                sub["log_path"] = str(
                    write_analysis_log(
                        profile,
                        examples=examples,
                        sprint_names=sub["sprint_names"],
                        duration_secs=sub["duration_secs"],
                    )
                )
            except Exception as exc:  # best-effort artifact
                logger.warning("Analysis log write failed: %s", exc)
                sub["warnings"].append(f"Analysis log not written: {exc}")
