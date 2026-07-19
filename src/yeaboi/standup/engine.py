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
  → per-member updates: one LLM call analyzes everyone's activity (alias-aware
    attribution); a typed self-report rides alongside as supporting context
  → assemble StandupReport → deliver → record run

# See README: "The ReAct Loop" — using the LLM outside the main graph
# See README: "Prompt Construction" — the standup summary prompt
# See README: "Daily Standup" — engine
"""

from __future__ import annotations

import json
import logging
from datetime import date

from yeaboi.agent.state import MemberUpdate, StandupReport
from yeaboi.standup import collector, confidence, sprint_context
from yeaboi.standup.store import StandupStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def _resolve_source_params(config: dict | None) -> dict:
    """Resolve collector source identifiers from config/env.

    Returns kwargs for collect_recent_activity: jira_project, azdo_project,
    github_repo, local_repo_path, confluence_space, notion_root.
    """
    from yeaboi.config import (
        get_azure_devops_project,
        get_confluence_space_key,
        get_jira_project_key,
        get_notion_root_page_id,
    )

    params = {
        "jira_project": get_jira_project_key() or "",
        "azdo_project": get_azure_devops_project() or "",
        "confluence_space": get_confluence_space_key() or "",
        # Notion's standup source is enabled by NOTION_ROOT_PAGE_ID — the same
        # "identifying parameter" gate Confluence uses with its space key.
        "notion_root": get_notion_root_page_id() or "",
        "github_repo": "",
        "local_repo_path": (config or {}).get("repo_path", "") or "",
    }
    # GitHub repo + optional overrides come from config getters added for standup.
    try:
        from yeaboi.config import get_standup_github_repo

        params["github_repo"] = get_standup_github_repo() or ""
    except Exception:
        logger.debug("standup: could not resolve GitHub repo config — skipping", exc_info=True)
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


def _normalize_author(s: str) -> set[str]:
    """Return the normalized alias strings for one raw author/name string.

    Lowercased + stripped; emails additionally yield their local part so
    "Omar@x.com" matches a member whose alias is just "omar". Deliberately
    conservative — exact normalized strings only, no fuzzy/substring matching
    (so "Sam" never absorbs "Samantha").
    """
    s = (s or "").strip().lower()
    if not s:
        return set()
    out = {s}
    if "@" in s:
        local = s.split("@", 1)[0].strip()
        if local:
            out.add(local)
    return out


def _detect_git_identity(repo_path: str) -> list[str]:
    """Best-effort git identity (user.name + user.email) for alias matching.

    Reads the configured local repo's git config when a repo path is set, plus
    the GLOBAL git config either way — so the standup user's commits attach to
    them with zero configuration. Never raises — skips whatever fails (no git,
    no repo, timeout).
    """
    import subprocess

    commands: list[list[str]] = []
    if (repo_path or "").strip():
        commands += [["git", "-C", repo_path, "config", key] for key in ("user.name", "user.email")]
    commands += [["git", "config", "--global", key] for key in ("user.name", "user.email")]

    identities: list[str] = []
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            value = (result.stdout or "").strip()
            if result.returncode == 0 and value and value not in identities:
                identities.append(value)
        except Exception:
            logger.debug("standup: git identity lookup failed (%s)", " ".join(cmd), exc_info=True)
    return identities


def _detect_tracker_identity() -> tuple[str, list[str]]:
    """Best-effort (display_name, identities) for the current user from configured trackers.

    Jira: the authenticated account's displayName + emailAddress (``myself()``).
    GitHub: the token's login (only when a token is configured — the lookup is a
    network call). Everything is guarded: unconfigured/failed sources contribute
    nothing and the standup proceeds. The display name lets the report present
    the user by their real name instead of the "Me" placeholder.
    """
    display = ""
    identities: list[str] = []
    try:
        from yeaboi.tools.jira import _make_jira_client

        client = _make_jira_client()
        if client is not None:
            me = client.myself()
            display = (me.get("displayName") or "").strip()
            for value in (display, (me.get("emailAddress") or "").strip()):
                if value:
                    identities.append(value)
    except Exception as e:
        logger.debug("standup: Jira identity lookup failed: %s", e, exc_info=True)
    try:
        from yeaboi.config import get_github_token

        if get_github_token():
            from yeaboi.tools.github import _get_github_client

            login = (_get_github_client().get_user().login or "").strip()
            if login:
                identities.append(login)
    except Exception as e:
        logger.debug("standup: GitHub identity lookup failed: %s", e, exc_info=True)
    return display, identities


def _build_alias_map(
    members: list[str],
    *,
    my_name: str = "",
    my_aliases: str = "",
    repo_path: str = "",
    extra_identities: tuple[str, ...] = (),
) -> dict[str, set[str]]:
    """Map each member to the set of normalized alias strings that identify them.

    Every member's own name is always an alias (so exact-name matching still
    works). The standup user (``my_name``) additionally gets their configured
    comma-separated ``my_aliases`` (GitHub handle, Jira display name, …), the
    auto-detected git identity, and any ``extra_identities`` (tracker-detected
    display name/email/login) — this is what lets the user's card claim
    activity authored under real tracker/VCS handles.
    """
    alias_map = {m: _normalize_author(m) for m in members}
    if my_name and my_name in alias_map:
        extras = [a.strip() for a in (my_aliases or "").split(",") if a.strip()]
        extras += _detect_git_identity(repo_path)
        extras += [x for x in extra_identities if x]
        for alias in extras:
            alias_map[my_name] |= _normalize_author(alias)
    return alias_map


def _enrich_aliases_from_items(alias_map: dict[str, set[str]], items: list[dict]) -> None:
    """Grow every member's alias set with emails observed on activity items.

    Sources attach ``author_email`` when the API exposes it (Jira/AzDO
    identities, git commit emails, Confluence editors). Whenever an item's
    author NAME already matches a member, that item's email (and its local
    part, via _normalize_author) becomes an alias of the member too — so a
    git commit authored as "omar.din@corp.com" attaches to the Jira member
    "Omar Din" once any tracker item exposed that email. Two passes reach the
    name → email → email-local-part closure. Strictly best-effort: emails are
    often hidden (GDPR) and their absence changes nothing.
    """
    # alias → emails seen alongside it on the same item.
    email_index: dict[str, set[str]] = {}
    for item in items:
        email = (item.get("author_email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        for alias in _normalize_author(item.get("author", "")):
            email_index.setdefault(alias, set()).add(email)
    if not email_index:
        return
    for _ in range(2):  # second pass closes name → email → local-part chains
        for member, aliases in alias_map.items():
            for alias in list(aliases):
                for email in email_index.get(alias, ()):
                    aliases |= _normalize_author(email)


def _group_activity_by_author(
    items: list[dict], members: list[str], alias_map: dict[str, set[str]] | None = None
) -> dict[str, list[dict]]:
    """Group activity items by author, matching via each member's alias set.

    Falls back to name-only aliases when no alias_map is given (the degenerate
    case is the old exact-match behavior, made case-insensitive).
    """
    alias_map = alias_map or {m: _normalize_author(m) for m in members}
    # Reverse index: normalized alias -> member (first member wins on collision).
    rev: dict[str, str] = {}
    for m in members:
        for alias in alias_map.get(m, _normalize_author(m)):
            rev.setdefault(alias, m)
    grouped: dict[str, list[dict]] = {m: [] for m in members}
    for item in items:
        author = (item.get("author") or "").strip()
        member = next((rev[a] for a in _normalize_author(author) if a in rev), None)
        if member is not None:
            grouped[member].append(
                {
                    "kind": item.get("kind", ""),
                    "title": item.get("title", ""),
                    "status": item.get("status", ""),
                    "source": item.get("source", ""),
                    "key": item.get("key", ""),
                    "url": item.get("url", ""),
                }
            )
    return grouped


def _member_links(acts: list[dict]) -> tuple[tuple[str, str], ...]:
    """Distinct (label, url) references from a member's grouped activity.

    Label is the item key (ticket id / PR number / sha) when present, else a
    truncated title. Deduped by URL preserving order, capped so a busy member's
    card stays readable.
    """
    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    for a in acts:
        url = (a.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        label = (a.get("key") or "").strip() or (a.get("title") or "")[:40]
        links.append((label, url))
        if len(links) >= 6:
            break
    return tuple(links)


def _member_source(has_self_report: bool, has_activity: bool) -> str:
    """Classify a MemberUpdate's provenance for rendering (✍ tags etc.)."""
    if has_self_report:
        return "combined" if has_activity else "self-reported"
    return "inferred"


def _fallback_summary(acts: list[dict]) -> str:
    """Deterministic summary from grouped items: fresh activity first, then WIP.

    A member whose only signal is in-progress tickets (kind="wip") reads
    "Continuing work on: …" — being quiet in the window is not "no activity"
    when they have assigned in-flight work.
    """
    fresh = "; ".join(a["title"] for a in acts if a.get("title") and a.get("kind") != "wip")[:400]
    if fresh:
        return fresh
    wip = "; ".join(a["title"] for a in acts if a.get("title") and a.get("kind") == "wip")[:400]
    if wip:
        return f"Continuing work on: {wip}"[:400]
    return "No activity detected."


def _build_fallback_member_updates(grouped: dict[str, list[dict]], self_reported: dict[str, str]) -> list[MemberUpdate]:
    """Deterministic per-member updates when the LLM is unavailable.

    Every member gets an activity-derived summary (a plain join of their
    activity titles); a self-report is carried alongside as supporting context,
    never replacing the activity view.
    """
    updates: list[MemberUpdate] = []
    for name, acts in grouped.items():
        summary = _fallback_summary(acts)
        updates.append(
            MemberUpdate(
                name=name,
                summary=summary,
                self_report=self_reported.get(name, ""),
                source=_member_source(name in self_reported, bool(acts)),
                links=_member_links(acts),
                activity_count=len(acts),
            )
        )
    # Self-reporters missing from the grouping (shouldn't happen — run_standup
    # adds them to the roster) still surface rather than silently dropping.
    for name, text in self_reported.items():
        if name not in grouped:
            updates.append(
                MemberUpdate(name=name, summary="No activity detected.", self_report=text, source="self-reported")
            )
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
    self_reported_images: dict[str, list[str]] | None = None,
    alias_map: dict[str, set[str]] | None = None,
) -> tuple[list[MemberUpdate], str, list[str]]:
    """Produce (member_updates, team_summary, warnings) via one LLM call + deterministic fallback.

    An LLM auth/billing failure is NOT re-raised — it's turned into a
    user-facing *warning* and the deterministic fallback is used, so the standup
    still renders with a clear reason instead of crashing or looking empty.

    Every member — including those who typed their own update — gets an
    activity-derived summary; a self-report is passed to the LLM as supporting
    context and carried verbatim on ``MemberUpdate.self_report``, so typing an
    update never suppresses the analysis of what you actually did.

    self_reported_images: per-member screenshot paths pasted (Ctrl+V) into "My
        Update" — attached to the summary LLM call as multimodal image blocks so
        the model can fold what they show into the team summary.
    """
    grouped = _group_activity_by_author(bundle.items, members, alias_map)

    def _for_llm(acts: list[dict]) -> list[dict]:
        # URLs (and the keys they duplicate — titles already carry ticket ids)
        # are for rendering links, not reasoning; strip them to keep the prompt lean.
        return [{k: v for k, v in a.items() if k not in ("url", "key")} for a in acts]

    # WIP (assigned in-progress tickets, possibly untouched in the window) is a
    # separate payload list so the LLM can distinguish "did" from "is doing".
    member_payload = [
        {
            "name": name,
            "activity": _for_llm([a for a in grouped.get(name, []) if a.get("kind") != "wip"]),
            "in_progress": _for_llm([a for a in grouped.get(name, []) if a.get("kind") == "wip"]),
            "self_report": self_reported.get(name, ""),
        }
        for name in members
    ]

    def _fallback(extra_warnings: list[str]) -> tuple[list[MemberUpdate], str, list[str]]:
        return (
            _build_fallback_member_updates(grouped, self_reported),
            _build_fallback_team_summary(bundle, progress),
            extra_warnings,
        )

    # Nothing to reason over (no activity anywhere and no self-reports) →
    # deterministic fallback only; don't spend an LLM call saying "no activity".
    if (not member_payload or not bundle.items) and not self_reported:
        return _fallback([])

    # No LLM credentials → don't attempt the call; say so plainly.
    from yeaboi.config import is_llm_configured

    configured, why = is_llm_configured()
    if not configured:
        logger.warning("standup: LLM not configured (%s) — using deterministic fallback", why)
        return _fallback([f"AI summary unavailable — {why}."])

    from yeaboi.agent.llm import get_llm, invoke_with_images, track_usage
    from yeaboi.agent.nodes import _is_llm_auth_or_billing_error
    from yeaboi.prompts.standup import get_standup_summary_prompt

    prompt = get_standup_summary_prompt(
        sprint_name=sprint_name,
        sprint_day=progress.sprint_day,
        sprint_total_days=progress.sprint_total_days,
        confidence_label=progress.confidence_label,
        confidence_rationale=progress.confidence_rationale,
        members=member_payload,
        activity_counts=bundle.counts,
    )

    # Screenshots pasted into "My Update" — flattened across members and attached
    # as multimodal image blocks (see agent/llm.py; degrades text-only on failure).
    images = [p for paths in (self_reported_images or {}).values() for p in paths]

    try:
        logger.info(
            "standup: invoking LLM to summarize %d member(s) (%d pasted image(s))",
            len(member_payload),
            len(images),
        )
        response = invoke_with_images(get_llm(temperature=0.0), prompt, images)
        track_usage(response)
        parsed = _parse_standup_response(response.content)
    except Exception as exc:
        if _is_llm_auth_or_billing_error(exc):
            logger.warning("standup: LLM auth/billing error — surfacing as warning: %s", exc)
            return _fallback(["AI summary unavailable — API key invalid or billing issue."])
        logger.warning("standup: LLM summarization failed, using fallback: %s", exc)
        return _fallback(["AI summary unavailable — LLM request failed (see logs)."])

    # Assemble: every member gets an activity-derived summary; self-reports ride
    # alongside on self_report (shown as "their words" by the renderers).
    updates: list[MemberUpdate] = []
    llm_members = {m.get("name", ""): m for m in parsed.get("members", []) if isinstance(m, dict)}
    for name in members:
        m = llm_members.get(name, {})
        summary = (m.get("summary") or "").strip()
        acts = grouped.get(name, [])
        if not summary:
            # LLM omitted this member — fall back to their activity/WIP titles.
            summary = _fallback_summary(acts)
        updates.append(
            MemberUpdate(
                name=name,
                summary=summary,
                blockers=(m.get("blockers") or "").strip(),
                self_report=self_reported.get(name, ""),
                source=_member_source(name in self_reported, bool(acts)),
                links=_member_links(acts),
                activity_count=len(acts),
            )
        )

    team_summary = (parsed.get("team_summary") or "").strip() or _build_fallback_team_summary(bundle, progress)
    return updates, team_summary, []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_standup(
    session_id: str,
    *,
    channels: list[str] | None = None,
    days: int | None = None,
    deliver: bool = True,
    dry_run: bool = False,
    db_path=None,
    today: date | None = None,
    on_progress=None,
) -> StandupReport:
    """Run a full standup for ``session_id`` and return the StandupReport.

    Args:
        channels: delivery channels override; falls back to saved config, then ["terminal"].
        days: explicit look-back window in days (now − N). Default None uses the
            working-day window instead: previous working day 00:00 → now, so a
            weekend/Monday run still captures Friday and a midweek run covers
            the FULL previous day plus today so far.
        deliver: when True, fan out to delivery channels (skipped if dry_run).
        dry_run: build the report but do not deliver (used by the TUI "Generate" preview).
        db_path: override sessions.db path (tests); defaults to paths.get_db_path().
        today: override for the current date (tests).
        on_progress: optional ``callable(str)`` invoked (best-effort) as each
            pipeline phase starts — lets the TUI show live progress while the
            network + LLM calls run on a worker thread.
    """
    from yeaboi.paths import get_db_path
    from yeaboi.sessions import SessionStore

    def _notify(phase: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(phase)
        except Exception:  # progress display must never break the run
            logger.debug("standup: on_progress callback failed", exc_info=True)

    today = today or date.today()
    date_str = today.isoformat()
    db_path = db_path or get_db_path()
    logger.info("run_standup: session=%s date=%s days=%s dry_run=%s", session_id, date_str, days, dry_run)

    # 1. Load session state + standup config.
    with SessionStore(db_path) as sessions:
        state = sessions.load_state(session_id) or {}
    with StandupStore(db_path) as store:
        config = store.load_config(session_id)
        self_reported = store.get_my_updates(session_id, date_str)
        self_reported_images = store.get_my_update_images(session_id, date_str)

    resolved_channels = channels or (config or {}).get("delivery_channels") or ["terminal"]
    source_params = _resolve_source_params(config)

    # 2. Collect recent activity across all resolved sources. Window: start of
    #    the previous working day → now (or an explicit now − days override).
    _notify("Collecting recent activity")
    if days is None:
        since = collector.previous_working_day_start(today)
        activity_window = f"{since:%a %Y-%m-%d} 00:00 → now"
        bundle = collector.collect_recent_activity(since=since, **source_params)
    else:
        activity_window = f"last {days} day(s)"
        bundle = collector.collect_recent_activity(days=days, **source_params)

    # 3. Sprint context + deterministic confidence.
    _notify("Reading sprint progress")
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
        # WIP items are standing state (tickets that exist regardless of the
        # window) — they must not defeat the silence penalty for a quiet day.
        activity_count=bundle.total(exclude_kinds=("wip",)),
        today=today,
    )

    # 4. Team members & identity.
    #    Roster: the plan's selected members, or — when the plan has none — the
    #    tracker roster (assignees who did work in the last ~30 days, reusing
    #    performance/roster.fetch_roster), so teammates found in Jira/AzDO
    #    appear even when they have no activity in today's window. Anyone who
    #    self-reported and any unmatched activity author is added too — nobody's
    #    work is silently dropped.
    #    Identity: the standup user's tracker identity is auto-detected (Jira
    #    displayName/email, GitHub login) and merged with configured my_aliases
    #    + git identity, so their activity attaches to THEIR card instead of
    #    appearing as a separate person; with the default "Me" name, the
    #    detected display name replaces the placeholder entirely.
    from yeaboi.config import get_standup_user_name

    _notify("Resolving team & identities")
    my_name = get_standup_user_name()
    display_name, tracker_identities = _detect_tracker_identity()
    if my_name == "Me" and display_name:
        # Default placeholder + a real detected identity → present the user by
        # name. Re-key any "Me" self-report so it stays theirs.
        for mapping in (self_reported, self_reported_images):
            if "Me" in mapping:
                mapping[display_name] = mapping.pop("Me")
        my_name = display_name
        logger.info("standup: resolved standup user to %r via tracker identity", my_name)

    plan_members = list(state.get("selected_team_members") or ())
    roster_members: list[str] = []
    if not plan_members:
        try:
            from yeaboi.performance.roster import fetch_roster

            roster_members = [
                ref.name
                for ref in fetch_roster(
                    jira_project=source_params["jira_project"],
                    azdo_project=source_params["azdo_project"],
                )
            ]
        except Exception as e:  # roster is best-effort — never blocks the standup
            logger.warning("standup: tracker roster lookup failed: %s", e)

    # The user's card first, then the rest of the team.
    members = [my_name] + [m for m in (plan_members or roster_members) if m != my_name]
    for name in self_reported:
        if name not in members:
            members.append(name)
    alias_map = _build_alias_map(
        members,
        my_name=my_name,
        my_aliases=(config or {}).get("my_aliases", ""),
        repo_path=(config or {}).get("repo_path", ""),
        # "Me" stays an alias so legacy self-reports/config still match.
        extra_identities=(*tracker_identities, "Me"),
    )
    # Every member (not just the user) learns the emails the sources exposed for
    # them, so cross-source work (git commits vs tracker display names) attaches
    # to the right card instead of spawning a phantom member below.
    _enrich_aliases_from_items(alias_map, bundle.items)
    # Drop roster/plan entries that are actually the standup user under another
    # name (e.g. their Jira displayName) — one person, one card.
    my_alias_set = alias_map.get(my_name, set())
    for dupe in [m for m in members if m != my_name and _normalize_author(m) & my_alias_set]:
        members.remove(dupe)
        alias_map.pop(dupe, None)
        logger.info("standup: merged roster entry %r into the standup user's card", dupe)
    known_aliases: set[str] = set().union(*alias_map.values()) if alias_map else set()
    for author in bundle.authors():
        author_aliases = _normalize_author(author)
        if author_aliases & known_aliases:
            continue  # already attributed to a member
        members.append(author)
        alias_map[author] = author_aliases
        known_aliases |= author_aliases

    # 5. Per-member + team summary (one LLM call, deterministic fallback).
    _notify("Writing summaries with AI")
    member_updates, team_summary, llm_warnings = _summarize_members(
        bundle=bundle,
        progress=progress,
        members=members,
        self_reported=self_reported,
        sprint_name=ctx.sprint_name,
        self_reported_images=self_reported_images,
        alias_map=alias_map,
    )

    # Warnings the user must see: source auth failures (from the collector) first,
    # then any LLM/config issue. These render as a "Notices" section, never silent.
    warnings = [f"{src.replace('_', ' ').title()}: {msg}" for src, msg in bundle.errors] + llm_warnings
    if not bundle.counts and not bundle.errors:
        warnings.insert(
            0,
            "No activity sources configured — set a local repo path via Configure, or connect "
            "GitHub/Jira/Azure DevOps/Confluence/Notion in .env, so updates can be inferred from real activity.",
        )
    elif bundle.skipped:
        # Partial coverage is advised, not silent: one combined line (last — auth/LLM
        # problems above are more urgent) naming each unscanned source and its fix.
        skipped = ", ".join(f"{src.replace('_', ' ').title()} ({reason})" for src, reason in bundle.skipped)
        warnings.append(f"Not scanned: {skipped} — connect these in .env to include their activity in the standup.")

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
        activity_window=activity_window,
        skipped_sources=tuple(bundle.skipped),
        my_name=my_name,
        warnings=tuple(warnings),
    )

    # 6. Deliver, then record the run (so delivery status is captured).
    _notify("Saving & exporting")
    delivery_status: dict[str, bool] = {}
    status = "success"
    if deliver and not dry_run:
        try:
            from yeaboi.standup import delivery

            delivery_status = delivery.deliver(report, resolved_channels)
            if delivery_status and not all(delivery_status.values()):
                status = "partial"
        except Exception as e:
            logger.error("standup delivery raised: %s", e)
            status = "partial"

    with StandupStore(db_path) as store:
        store.record_run(report, delivery_status=delivery_status, status=status)

    # Persist readable output (Markdown + HTML) alongside the logs, so a standup's
    # result is a shareable document — not something you can only reconstruct from
    # a log file. Best-effort: never fail the run over an export I/O error.
    try:
        from yeaboi.standup.export import export_standup

        export_standup(report, project_name=state.get("project_name", "") or session_id)
    except Exception as e:
        logger.warning("standup export failed: %s", e)

    logger.info(
        "run_standup complete: session=%s day=%d/%d confidence=%d%% status=%s",
        session_id,
        report.sprint_day,
        report.sprint_total_days,
        report.confidence_pct,
        status,
    )
    return report
