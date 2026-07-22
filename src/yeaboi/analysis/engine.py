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

# The three analysis components, selectable per source. "delivery" is the sprint/
# ticket pipeline that produces the TeamProfile; "code" is the remote AI-usage scan;
# "docs" is the Notion/Confluence doc-quality read. Each is independent — a source may
# run any non-empty subset (e.g. docs-only, no velocity).
_COMPONENTS = ("delivery", "code", "docs")


def _resolve_components(
    src: str,
    components: dict[str, list[str]] | None,
    include_ai_usage: bool,
    include_doc_quality: bool,
) -> list[str]:
    """Resolve which components run for ``src``.

    An explicit non-empty ``components[src]`` wins (filtered to the known component
    names). Otherwise fall back to the legacy booleans — ``delivery`` always, plus
    ``code``/``docs`` per ``include_ai_usage``/``include_doc_quality`` — which
    reproduces today's behaviour exactly when no per-source selection is given.
    """
    if components and components.get(src):
        picked = [c for c in components[src] if c in _COMPONENTS]
        if picked:
            return picked
    out = ["delivery"]
    if include_ai_usage:
        out.append("code")
    if include_doc_quality:
        out.append("docs")
    return out


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


def _build_comparison(results: dict) -> list[tuple[str, str, str]]:
    """Side-by-side headline rows: (label, jira_value, azdevops_value). Kept
    deliberately separate (not aggregated) so each number names its tracker."""
    jira = results.get("jira", {}).get("profile")
    azdo = results.get("azdevops", {}).get("profile")
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
    """Analyse the team's board history into a TeamProfile and persist it.

    When ``source == 'both'`` this runs the single-source pipeline once per
    configured tracker (Jira then Azure DevOps) and returns a **combined** dict:
    ``{"source": "both", "results": {"jira": <single>, "azdevops": <single>},
    "comparison": [(label, jira_val, azdo_val), ...], "warnings": [...]}`` — the
    two profiles are kept clearly separate (never blended), since velocity/point
    scales are not comparable across trackers. If only one tracker is configured,
    'both' degrades to that single-source run (with a warning); ``project_key`` is
    ignored in 'both' mode (ambiguous for two boards) and auto-resolved per source.

    Otherwise the pipeline is: resolve source/project (auto-detected from config
    when blank) → fetch ``sprint_count`` closed sprints → ``_run_parallel_analysis``
    (velocity, calibration, writing style, DoD — 4 workers, LLM-enriched with
    deterministic fallbacks) → save via ``TeamProfileStore`` → write the analysis
    log → optional coaching insights and sample tickets.

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
        include_ai_usage: also scan the team's commits/PRs for AI-tool markers
            and attach an AI-adoption footprint + coaching to the profile. This
            makes best-effort GitHub/AzDO network calls; set False to skip them.
        include_doc_quality: also read the team's recent Notion/Confluence pages
            and attach a documentation clarity score + stylometric AI-likelihood
            estimate + coaching. Best-effort doc-platform network calls; set
            False to skip them.
        components: per-source component selection, e.g.
            ``{"jira": ["docs"], "azdevops": ["code"]}`` — each value a subset of
            ``{"delivery", "code", "docs"}``. A source missing/empty here falls back
            to the ``include_ai_usage``/``include_doc_quality`` booleans (today's
            behaviour). When ``delivery`` is absent for a source, that source returns
            a code/docs-only result with ``profile=None`` (no velocity, not persisted).
        members: per-source subset of assignee names, e.g.
            ``{"jira": ["Alice", "Bob"]}`` — re-scopes velocity/contributors/code to
            those people. Blank/missing = whole team. Discover names via
            ``get_team_roster``.
        progress: optional shared list the analysis workers append status
            strings to (the TUI reads it from its frame loop).
        db_path: sessions DB override (tests). Defaults to paths.get_db_path().

    Returns a dict with: source, project_key, sprint_names, duration_secs,
    profile (TeamProfile), examples (dict), headline_stats, insights, samples,
    log_path, warnings. Raises ValueError when no tracker is configured or the
    board has no closed sprints; tracker API errors propagate.
    """
    if source == "both":
        available = _available_sources()
        if not available:
            _resolve_source("")  # raises the canonical "no tracker configured" ValueError

        def _common_for(src: str) -> dict:
            return dict(
                sprint_count=sprint_count,
                generate_samples=generate_samples,
                include_insights=include_insights,
                components=_resolve_components(src, components, include_ai_usage, include_doc_quality),
                members=(members or {}).get(src),
                progress=progress,
                db_path=db_path,
            )

        # Only one tracker configured → 'both' gracefully degrades to that single
        # run (with a warning) so the surfaces render it exactly as a normal run.
        if len(available) == 1:
            only = available[0]
            logger.info("'both' requested but only %s configured — analysing %s only", only, only)
            single = _run_single_source(only, "", "", **_common_for(only))
            single["warnings"].append(
                f"Only {_SOURCE_NAMES[only]} is configured — analysed {_SOURCE_NAMES[only]} only."
            )
            return single
        logger.info("Team analysis starting for both trackers: %s", ", ".join(available))
        results: dict[str, dict] = {}
        both_warnings: list[str] = []
        for src in available:
            try:
                # project_key/team_name are intentionally auto-resolved per source
                # here — an explicit project is ambiguous across two boards.
                results[src] = _run_single_source(src, "", "", **_common_for(src))
                both_warnings.extend(results[src]["warnings"])
            except Exception as exc:  # a per-tracker failure degrades to a warning, not a crash
                logger.warning("Team analysis failed for %s: %s", src, exc)
                both_warnings.append(f"{_SOURCE_NAMES[src]} analysis failed: {exc}")
        if not results:
            raise ValueError("Both trackers failed to analyse — see warnings for the per-tracker errors.")
        logger.info("Team analysis completed for both trackers: %s", ", ".join(results))
        return {
            "source": "both",
            "results": results,
            "comparison": _build_comparison(results),
            "warnings": both_warnings,
        }

    # Single source — resolve it first so per-source components/members can be read.
    resolved = _resolve_source(source)
    return _run_single_source(
        resolved,
        project_key,
        team_name,
        sprint_count=sprint_count,
        generate_samples=generate_samples,
        include_insights=include_insights,
        components=_resolve_components(resolved, components, include_ai_usage, include_doc_quality),
        members=(members or {}).get(resolved),
        progress=progress,
        db_path=db_path,
    )


def _run_single_source(
    source: str = "",
    project_key: str = "",
    team_name: str = "",
    sprint_count: int = 8,
    generate_samples: bool = False,
    include_insights: bool = True,
    components: list[str] | None = None,
    members: list[str] | None = None,
    *,
    progress: list | None = None,
    db_path=None,
) -> dict:
    """Analyse a single tracker's board history into a TeamProfile and persist it.

    The one-tracker pipeline behind ``run_team_analysis`` (which handles source
    resolution, per-source component/member selection, the 'both' fan-out, and
    degraded-run warnings). ``components`` is a resolved list (a subset of
    ``delivery``/``code``/``docs``); when ``delivery`` is absent no board is fetched,
    ``profile`` is ``None``, and the result is not persisted."""
    from yeaboi.tools.team_learning import compute_headline_stats

    started = time.monotonic()
    warnings: list[str] = []
    resolved_source = _resolve_source(source)
    resolved_project, resolved_team = _resolve_project(resolved_source, project_key, team_name)
    comps = list(components) if components else list(_COMPONENTS)
    run_delivery = "delivery" in comps
    run_code = "code" in comps
    run_docs = "docs" in comps
    logger.info(
        "Team analysis starting: source=%s project=%s sprints=%d components=%s members=%s",
        resolved_source,
        resolved_project,
        sprint_count,
        comps,
        members or "all",
    )

    # Delivery off — run just the code/docs components, no board fetch, no profile.
    if not run_delivery:
        from yeaboi.tools.team_learning import run_components_only

        examples = run_components_only(
            resolved_source,
            resolved_project or "unknown",
            run_code,
            run_docs,
            members,
            progress if progress is not None else [],
        )
        duration = time.monotonic() - started
        logger.info("Team analysis (components-only) completed in %.1fs: components=%s", duration, comps)
        return {
            "source": resolved_source,
            "project_key": resolved_project,
            "components": comps,
            "sprint_names": [],
            "duration_secs": round(duration, 1),
            "profile": None,
            "examples": examples,
            "headline_stats": None,
            "insights": None,
            "samples": None,
            "log_path": "",
            "warnings": warnings,
        }

    from yeaboi.paths import get_db_path
    from yeaboi.team_profile import TeamProfileStore
    from yeaboi.tools.team_learning import _fetch_azdevops_history, _fetch_jira_history, _run_parallel_analysis

    if resolved_source == "jira":
        sprint_data = _fetch_jira_history(resolved_project, sprint_count)
    else:
        sprint_data = _fetch_azdevops_history(resolved_project, sprint_count)
    if not sprint_data:
        raise ValueError("No closed sprints found on the board — nothing to analyse.")
    sprint_names = [sd.get("sprint_name", "") for sd in sprint_data]

    profile, examples = _run_parallel_analysis(
        resolved_source,
        resolved_project or "unknown",
        sprint_data,
        progress if progress is not None else [],
        include_ai_usage=run_code,
        include_doc_quality=run_docs,
        members=members,
        warnings=warnings,
    )
    if resolved_team and not profile.team_name:
        from dataclasses import replace

        profile = replace(profile, team_name=resolved_team)

    with TeamProfileStore(db_path or get_db_path()) as store:
        store.save(profile, examples=examples)

    duration = time.monotonic() - started
    log_path = ""
    try:
        from yeaboi.team_profile_exporter import write_analysis_log

        log_path = str(
            write_analysis_log(profile, examples=examples, sprint_names=sprint_names, duration_secs=duration)
        )
    except Exception as exc:  # best-effort artifact, same as the TUI
        logger.warning("Analysis log write failed: %s", exc)
        warnings.append(f"Analysis log not written: {exc}")

    insights = None
    if include_insights:
        from yeaboi.tools.team_learning import _generate_team_insights

        insights = _generate_team_insights(profile, examples)  # never raises — deterministic fallback inside

    samples = _generate_samples(profile, examples or {}, warnings) if generate_samples else None

    logger.info(
        "Team analysis completed in %.1fs: %d sprints, %d stories, vel=%.1f",
        duration,
        profile.sample_sprints,
        profile.sample_stories,
        profile.velocity_avg,
    )
    return {
        "source": resolved_source,
        "project_key": resolved_project,
        "components": comps,
        "sprint_names": sprint_names,
        "duration_secs": round(duration, 1),
        "profile": profile,
        "examples": examples,
        "headline_stats": compute_headline_stats(profile, examples),
        "insights": insights,
        "samples": samples,
        "log_path": log_path,
        "warnings": warnings,
    }
